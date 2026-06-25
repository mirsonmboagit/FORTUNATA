import builtins
import os
import sqlite3
import sys
from datetime import datetime, timedelta, date
from time import perf_counter
import bcrypt

from database.automation import DatabaseAutomationMixin
from utils.perf_utils import perf_log, should_log_debug
from utils.paths import DB_BACKUP_DIR, resolve_path
from utils.vat import (
    DEFAULT_VAT_RULE_CODE,
    VAT_RULES,
    compute_vat_breakdown,
    normalize_reference_date,
)

NEAR_EXPIRY_DAYS = 15
LOSS_QTY_LIMIT_UN = 10
LOSS_QTY_LIMIT_KG = 5.0
LOSS_VALUE_LIMIT_MZN = 5000
LOSS_TYPES = {"DAMAGE", "EXPIRED", "THEFT", "ADJUSTMENT"}


def _safe_print(*args, **kwargs):
    # Evita quebra no terminal quando aparecer texto com encoding diferente.
    try:
        builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        stream = kwargs.get("file") or sys.stdout
        encoding = getattr(stream, "encoding", None) or "ascii"
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        flush = kwargs.get("flush", False)
        text = sep.join(str(arg) for arg in args)
        sanitized = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        builtins.print(sanitized, end=end, file=stream, flush=flush)


print = _safe_print

def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def _parse_datetime_value(value, end_of_day=False):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt_value = value
    else:
        text = str(value).strip()
        if not text:
            return None
        dt_value = None
        try:
            dt_value = datetime.fromisoformat(text)
        except Exception:
            pass
        if dt_value is None:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y",
            ):
                try:
                    dt_value = datetime.strptime(text, fmt)
                    break
                except Exception:
                    continue
        if dt_value is None:
            return None
    if end_of_day and dt_value.hour == 0 and dt_value.minute == 0 and dt_value.second == 0:
        dt_value = dt_value.replace(hour=23, minute=59, second=59)
    return dt_value.replace(microsecond=0)


def _fetch_sales_velocity(db, days=14):
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    owner = db._active_owner() if hasattr(db, "_active_owner") else None
    db.cursor.execute(
        "SELECT product_id, COALESCE(SUM(quantity), 0) "
        "FROM sales WHERE DATE(sale_date) >= ? "
        + ("AND COALESCE(owner_username, '') = ? " if owner else "")
        + "GROUP BY product_id",
        (start_date, owner) if owner else (start_date,),
    )
    totals = {row[0]: _safe_float(row[1], 0.0) for row in db.cursor.fetchall()}
    velocity = {}
    for product_id, total_qty in totals.items():
        velocity[product_id] = total_qty / max(days, 1)
    return velocity


def _get_product_daily_sales(db, product_id, days=14):
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    owner = db._active_owner() if hasattr(db, "_active_owner") else None
    db.cursor.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM sales "
        "WHERE product_id = ? AND DATE(sale_date) >= ? "
        + ("AND COALESCE(owner_username, '') = ?" if owner else ""),
        (product_id, start_date, owner) if owner else (product_id, start_date),
    )
    total = _safe_float(db.cursor.fetchone()[0], 0.0)
    return total / max(days, 1)


def _build_forecasts(db, days=14, limit=10):
    # Calcula previsao simples de reposicao e risco de validade.
    velocity = _fetch_sales_velocity(db, days=days)
    scope_sql, scope_params = db._owner_filter() if hasattr(db, "_owner_filter") else ("", [])
    db.cursor.execute(
        "SELECT id, description, existing_stock, is_sold_by_weight, expiry_date, "
        "sale_price, unit_purchase_price "
        "FROM products WHERE 1=1 " + scope_sql,
        tuple(scope_params),
    )
    forecasts = []
    expiry_risk = []
    today_date = datetime.now().date()

    for prod_id, name, stock, by_weight, expiry_date, sale_price, unit_purchase_price in db.cursor.fetchall():
        avg_daily = _safe_float(velocity.get(prod_id, 0.0), 0.0)
        stock_value = _safe_float(stock, 0.0)
        days_left = None
        recommended_qty = 0.0

        if avg_daily > 0:
            days_left = stock_value / avg_daily
            recommended_qty = max(0.0, (avg_daily * days) - stock_value)

        unit = "kg" if by_weight else "un"
        forecasts.append({
            "product_id": prod_id,
            "name": name,
            "stock": stock_value,
            "unit": unit,
            "avg_daily": avg_daily,
            "days_left": days_left,
            "recommended_qty": recommended_qty,
        })

        exp_date = _parse_date(expiry_date)
        if exp_date and avg_daily > 0:
            days_to_expiry = (exp_date - today_date).days
            if days_to_expiry >= 0:
                days_to_sell = stock_value / avg_daily
                if days_to_sell > days_to_expiry:
                    unsold_qty = max(0.0, stock_value - (avg_daily * days_to_expiry))
                    loss_revenue = unsold_qty * _safe_float(sale_price, 0.0)
                    loss_profit = unsold_qty * (
                        _safe_float(sale_price, 0.0)
                        - _safe_float(unit_purchase_price, 0.0)
                    )
                    expiry_risk.append({
                        "name": name,
                        "days_to_expiry": days_to_expiry,
                        "days_to_sell": days_to_sell,
                        "stock": stock_value,
                        "unit": unit,
                        "unsold_qty": unsold_qty,
                        "loss_revenue": loss_revenue,
                        "loss_profit": loss_profit,
                    })

    forecasts.sort(key=lambda x: (x["days_left"] is None, x["days_left"] or 9999))
    expiry_risk.sort(key=lambda x: x["days_to_expiry"])
    return forecasts[:limit], expiry_risk[:limit]

class Database(DatabaseAutomationMixin):
    # Camada principal de acesso ao SQLite.
    SKU_PREFIX_DEFAULT = "LOJA"
    BACKUP_RETENTION_DAYS = 30
    BACKUP_INTERVAL_HOURS = 24
    RECONCILE_INTERVAL_MINUTES = 60
    RECONCILE_DIFF_TOLERANCE = 0.0001

    def __init__(self, db_name="inventory.db", db_path=None, db_folder="database"):
        # Guardamos o nome simples
        self.db_name = db_name

        # Definimos a pasta/base do banco
        if db_path:
            resolved_db_path = resolve_path(db_path)
            self.db_path = str(resolved_db_path)
            self.db_folder = os.path.dirname(self.db_path) or "."
            self.db_name = os.path.basename(self.db_path)
        else:
            self.db_folder = str(resolve_path(db_folder))
            self.db_path = os.path.join(self.db_folder, self.db_name)

        # Criamos a pasta se nÃƒÆ’Ã‚Â£o existir
        if self.db_folder and not os.path.exists(self.db_folder):
            os.makedirs(self.db_folder)
            print(f"Pasta '{self.db_folder}' criada!")

        self.conn = None
        self.cursor = None
        self.backup_root = str(DB_BACKUP_DIR)
        self.current_user = None
        self.current_role = None
        self.current_data_owner = None
        self.sku_prefix = self._sanitize_sku_token(
            os.getenv("SKU_PREFIX", self.SKU_PREFIX_DEFAULT),
            fallback=self.SKU_PREFIX_DEFAULT,
            max_len=8,
        )
        self.connect()
        self.setup()
    
    def connect(self):
        """Conectar ao banco de dados"""
        try:
            # IMPORTANTE: Usamos o self.db_path aqui
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
            self.cursor = self.conn.cursor()
            self.cursor.execute("PRAGMA busy_timeout = 30000")
            self.cursor.execute("PRAGMA foreign_keys = ON")
            try:
                self.cursor.execute("PRAGMA journal_mode = WAL")
            except sqlite3.Error:
                pass
            print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Conectado com sucesso em: {self.db_path}")
        except (sqlite3.Error, ValueError) as e:
            if self.conn:
                self.conn.rollback()
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao conectar: {e}")
    
    def close(self):
        """Fechar a conexÃƒÆ’Ã‚Â£o com o banco de dados"""
        if self.conn:
            self.conn.close()

    @staticmethod
    def _sanitize_sku_token(value, fallback="SKU", max_len=8):
        # Mantem o SKU apenas com letras e numeros.
        token = "".join(ch for ch in str(value or "") if ch.isalnum()).upper()
        if not token:
            token = fallback
        return token[:max_len]

    def _sku_manual_token(self, description):
        return self._sanitize_sku_token(description, fallback="PROD", max_len=3)

    def _build_sku(self, product_id, description):
        manual = self._sku_manual_token(description)
        return f"{manual}-{self.sku_prefix}-{int(product_id):06d}"

    def set_active_user(self, username=None, role=None):
        """Define o espaco de dados visivel na sessao atual."""
        self.current_user = username
        self.current_role = role
        self.current_data_owner = self.get_user_data_owner(username) if username else None

    # Filtros de dono mantem cada utilizador no seu escopo de dados.
    def _active_owner(self):
        return (self.current_data_owner or self.current_user or "").strip() or None

    def _owner_value(self, username=None):
        owner = self.get_user_data_owner(username) if username else None
        return owner or self._active_owner() or username or "SYSTEM"

    def _owner_filter(self, alias=None):
        owner = self._active_owner()
        if not owner:
            return "", []
        prefix = f"{alias}." if alias else ""
        return f" AND COALESCE({prefix}owner_username, '') = ?", [owner]

    def _rebuild_all_skus(self):
        """Regera SKUs no formato MANUAL-PREFIXO-000001 para produtos e arquivo."""
        self.cursor.execute("SELECT id, description FROM products")
        for product_id, description in self.cursor.fetchall():
            sku = self._build_sku(product_id, description)
            self.cursor.execute(
                "UPDATE products SET sku = ? WHERE id = ?",
                (sku, product_id),
            )

        self.cursor.execute("SELECT id, description FROM products_archive")
        for product_id, description in self.cursor.fetchall():
            sku = self._build_sku(product_id, description)
            self.cursor.execute(
                "UPDATE products_archive SET sku = ? WHERE id = ?",
                (sku, product_id),
            )

    @staticmethod
    def _normalize_vat_rule_code(vat_rule_code):
        code = str(vat_rule_code or DEFAULT_VAT_RULE_CODE).strip().upper()
        if not code:
            code = DEFAULT_VAT_RULE_CODE
        return code

    # Regras de IVA usadas nos produtos e relatorios.
    def _seed_vat_rules(self):
        for rule in VAT_RULES:
            self.cursor.execute(
                """
                INSERT OR IGNORE INTO vat_rules (
                    code,
                    label,
                    short_label,
                    rate_percent,
                    taxable_ratio,
                    effective_from,
                    effective_to,
                    legal_reference,
                    description,
                    price_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule["code"],
                    rule.get("label"),
                    rule.get("short_label"),
                    float(rule.get("rate_percent") or 0.0),
                    float(rule.get("taxable_ratio") or 0.0),
                    rule.get("effective_from"),
                    rule.get("effective_to"),
                    rule.get("legal_reference"),
                    rule.get("description"),
                    rule.get("price_mode"),
                ),
            )

    def get_vat_rules(self):
        try:
            self.cursor.execute(
                """
                SELECT
                    code,
                    label,
                    short_label,
                    rate_percent,
                    taxable_ratio,
                    effective_from,
                    effective_to,
                    legal_reference,
                    description,
                    price_mode
                FROM vat_rules
                ORDER BY code ASC, effective_from DESC
                """
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter regras de IVA: {e}")
            return []

    def replace_vat_rules(self, rules):
        try:
            normalized_rows = []
            for raw_rule in list(rules or []):
                code = self._normalize_vat_rule_code(raw_rule.get("code"))
                label = str(raw_rule.get("label") or code).strip()
                short_label = str(raw_rule.get("short_label") or label).strip()
                rate_percent = float(raw_rule.get("rate_percent") or 0.0)
                effective_from = normalize_reference_date(raw_rule.get("effective_from")).isoformat()
                effective_to_raw = str(raw_rule.get("effective_to") or "").strip()
                effective_to = normalize_reference_date(effective_to_raw).isoformat() if effective_to_raw else None
                if effective_to and effective_to < effective_from:
                    raise ValueError(f"Vigencia invalida para {code}: fim antes do inicio")
                price_mode = str(raw_rule.get("price_mode") or "INCLUSIVE").strip().upper()
                if price_mode not in {"INCLUSIVE", "EXCLUSIVE"}:
                    price_mode = "INCLUSIVE"
                taxable_ratio = raw_rule.get("taxable_ratio")
                if taxable_ratio in (None, ""):
                    taxable_ratio = 0.0 if rate_percent <= 0 else 1.0
                taxable_ratio = float(taxable_ratio)
                legal_reference = str(raw_rule.get("legal_reference") or "").strip() or None
                description = str(raw_rule.get("description") or "").strip() or None
                normalized_rows.append(
                    (
                        code,
                        label,
                        short_label,
                        rate_percent,
                        taxable_ratio,
                        effective_from,
                        effective_to,
                        legal_reference,
                        description,
                        price_mode,
                    )
                )

            if not normalized_rows:
                raise ValueError("Informe pelo menos uma regra de IVA")

            unique_keys = {(row[0], row[5]) for row in normalized_rows}
            if len(unique_keys) != len(normalized_rows):
                raise ValueError("Existem regras duplicadas com o mesmo criterio e data inicial")

            self.cursor.execute("DELETE FROM vat_rules")
            self.cursor.executemany(
                """
                INSERT INTO vat_rules (
                    code,
                    label,
                    short_label,
                    rate_percent,
                    taxable_ratio,
                    effective_from,
                    effective_to,
                    legal_reference,
                    description,
                    price_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                normalized_rows,
            )
            self.conn.commit()
            return True
        except (sqlite3.Error, ValueError) as e:
            print(f"Erro ao substituir regras de IVA: {e}")
            self.conn.rollback()
            raise
            return False

    def reset_vat_rules(self):
        try:
            self.cursor.execute("DELETE FROM vat_rules")
            self._seed_vat_rules()
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao restaurar regras de IVA: {e}")
            self.conn.rollback()
            return False

    def calculate_vat_breakdown(self, unit_price, quantity=1.0, vat_rule_code=None, reference_date=None):
        rules = self.get_vat_rules()
        return compute_vat_breakdown(
            unit_price,
            quantity=quantity,
            rule_code=self._normalize_vat_rule_code(vat_rule_code),
            reference_date=reference_date,
            rules=rules,
        )
    
    def setup(self):
        """Configurar tabelas do banco de dados"""
        try:
            # Tabelas principais do sistema.
            # Tabela de usuÃƒÆ’Ã‚Â¡rios (administrador e gerente)
            self.cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                data_owner TEXT
            )''')
            # Garantir colunas de contacto para recuperacao (email/telefone)
            try:
                self.cursor.execute("PRAGMA table_info(users)")
                cols = [row[1] for row in self.cursor.fetchall()]
                if "email" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
                if "phone" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")
                if "data_owner" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN data_owner TEXT")
            except sqlite3.Error as e:
                print(f"Erro ao adicionar colunas de contacto: {e}")

            # Tabela de recuperacao de senha por SMS
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                code_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                last_sent_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users(username)
            )''')
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_password_resets_username ON password_resets(username)"
            )
            # Tabela de perguntas de seguranca
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_security_questions (
                username TEXT PRIMARY KEY,
                q1_hash BLOB NOT NULL,
                q2_hash BLOB NOT NULL,
                q3_hash BLOB NOT NULL,
                q4_hash BLOB NOT NULL,
                attempts INTEGER DEFAULT 0,
                lock_until TEXT,
                updated_at TEXT,
                FOREIGN KEY (username) REFERENCES users(username)
            )''')
            self.cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS vat_rules (
                    code TEXT NOT NULL,
                    label TEXT NOT NULL,
                    short_label TEXT,
                    rate_percent REAL NOT NULL DEFAULT 0,
                    taxable_ratio REAL NOT NULL DEFAULT 1,
                    effective_from TEXT NOT NULL,
                    effective_to TEXT,
                    legal_reference TEXT,
                    description TEXT,
                    price_mode TEXT DEFAULT 'INCLUSIVE',
                    PRIMARY KEY (code, effective_from)
                )
                '''
            )
            self._seed_vat_rules()
            # Nao criar usuario padrao automaticamente
            # Tabela de produtos (atualizada com barcode, expiry_date, status e is_sold_by_weight)
            self.cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                category TEXT,
                existing_stock REAL NOT NULL,
                sold_stock REAL DEFAULT 0,
                sale_price REAL NOT NULL,
                total_purchase_price REAL NOT NULL,
                unit_purchase_price REAL NOT NULL,
                profit_per_unit REAL NOT NULL,
                barcode TEXT,
                expiry_date TEXT,
                date_added TEXT NOT NULL,
                is_sold_by_weight INTEGER DEFAULT 0,
                package_quantity TEXT,
                status TEXT DEFAULT 'ATIVO',
                status_source TEXT DEFAULT 'MANUAL',
                status_reason TEXT,
                status_updated_at TEXT,
                status_updated_by TEXT,
                sku TEXT,
                units_per_package INTEGER,
                allow_pack_sale INTEGER DEFAULT 0,
                vat_rule_code TEXT DEFAULT 'STANDARD',
                owner_username TEXT
            )''')

            # Tabela de produtos arquivados (excluÃƒÆ’Ã‚Â­dos)
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products_archive (
                id INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                category TEXT,
                existing_stock REAL NOT NULL,
                sold_stock REAL DEFAULT 0,
                sale_price REAL NOT NULL,
                total_purchase_price REAL NOT NULL,
                unit_purchase_price REAL NOT NULL,
                profit_per_unit REAL NOT NULL,
                barcode TEXT,
                expiry_date TEXT,
                date_added TEXT NOT NULL,
                is_sold_by_weight INTEGER DEFAULT 0,
                package_quantity TEXT,
                status TEXT,
                status_source TEXT,
                status_reason TEXT,
                status_updated_at TEXT,
                status_updated_by TEXT,
                sku TEXT,
                units_per_package INTEGER,
                allow_pack_sale INTEGER DEFAULT 0,
                vat_rule_code TEXT DEFAULT 'STANDARD',
                deleted_at TEXT,
                deleted_by TEXT,
                owner_username TEXT
            )''')

            # Tabela de logs do sistema
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                role TEXT,
                action TEXT NOT NULL,
                details TEXT,
                timestamp TEXT NOT NULL,
                owner_username TEXT
            )''')
            
            # ===== VERIFICAR E ADICIONAR COLUNAS NECESSÃƒÆ’Ã‚ÂRIAS =====
            self.cursor.execute("PRAGMA table_info(products)")
            columns = [column[1] for column in self.cursor.fetchall()]
            # Nao criar usuario padrao automaticamente
            if 'is_sold_by_weight' not in columns:
                print("ÃƒÂ¢Ã…Â¡Ã¢â€žÂ¢ÃƒÂ¯Ã‚Â¸Ã‚Â Adicionando coluna 'is_sold_by_weight' ÃƒÆ’Ã‚Â  tabela products...")
                self.cursor.execute("ALTER TABLE products ADD COLUMN is_sold_by_weight INTEGER DEFAULT 0")
                print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Coluna 'is_sold_by_weight' adicionada com sucesso!")
            
            # ===== ADICIONAR COLUNAS DE STATUS (se necessÃƒÆ’Ã‚Â¡rio) =====
            def ensure_column(table, column, col_def):
                self.cursor.execute(f"PRAGMA table_info({table})")
                cols = [c[1] for c in self.cursor.fetchall()]
                if column not in cols:
                    self.cursor.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
                    )

            ensure_column("user_logs", "owner_username", "TEXT")
            ensure_column("products", "status", "TEXT DEFAULT 'ATIVO'")
            ensure_column("products", "status_source", "TEXT DEFAULT 'MANUAL'")
            ensure_column("products", "status_reason", "TEXT")
            ensure_column("products", "status_updated_at", "TEXT")
            ensure_column("products", "status_updated_by", "TEXT")
            ensure_column("products", "package_quantity", "TEXT")
            ensure_column("products", "sku", "TEXT")
            ensure_column("products", "units_per_package", "INTEGER")
            ensure_column("products", "allow_pack_sale", "INTEGER DEFAULT 0")
            ensure_column("products", "vat_rule_code", "TEXT DEFAULT 'STANDARD'")
            ensure_column("products", "owner_username", "TEXT")
            ensure_column("products_archive", "package_quantity", "TEXT")
            ensure_column("products_archive", "status", "TEXT")
            ensure_column("products_archive", "status_source", "TEXT")
            ensure_column("products_archive", "status_reason", "TEXT")
            ensure_column("products_archive", "status_updated_at", "TEXT")
            ensure_column("products_archive", "status_updated_by", "TEXT")
            ensure_column("products_archive", "sku", "TEXT")
            ensure_column("products_archive", "units_per_package", "INTEGER")
            ensure_column("products_archive", "allow_pack_sale", "INTEGER DEFAULT 0")
            ensure_column("products_archive", "vat_rule_code", "TEXT DEFAULT 'STANDARD'")
            ensure_column("products_archive", "deleted_at", "TEXT")
            ensure_column("products_archive", "deleted_by", "TEXT")
            ensure_column("products_archive", "owner_username", "TEXT")

            # ===== ALTERAR TIPO DE DADOS PARA SUPORTAR DECIMAIS (KG) =====
            # Verificar se as colunas de estoque jÃƒÆ’Ã‚Â¡ sÃƒÆ’Ã‚Â£o REAL (suportam decimais)
            self.cursor.execute("PRAGMA table_info(products)")
            columns_info = self.cursor.fetchall()
            
            existing_stock_type = None
            sold_stock_type = None
            
            for col in columns_info:
                if col[1] == 'existing_stock':
                    existing_stock_type = col[2]
                elif col[1] == 'sold_stock':
                    sold_stock_type = col[2]
            
            # Se as colunas forem INTEGER, precisamos recriÃƒÆ’Ã‚Â¡-las como REAL
            if existing_stock_type == 'INTEGER' or sold_stock_type == 'INTEGER':
                print("ÃƒÂ¢Ã…Â¡Ã¢â€žÂ¢ÃƒÂ¯Ã‚Â¸Ã‚Â Convertendo colunas de estoque para suportar valores decimais (KG)...")
                
                # Criar tabela temporÃƒÆ’Ã‚Â¡ria com tipos corretos
                self.cursor.execute(''' 
                CREATE TABLE IF NOT EXISTS products_temp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    category TEXT,
                    existing_stock REAL NOT NULL,
                    sold_stock REAL DEFAULT 0,
                    sale_price REAL NOT NULL,
                    total_purchase_price REAL NOT NULL,
                    unit_purchase_price REAL NOT NULL,
                    profit_per_unit REAL NOT NULL,
                    barcode TEXT,
                    expiry_date TEXT,
                    date_added TEXT NOT NULL,
                    is_sold_by_weight INTEGER DEFAULT 0,
                    package_quantity TEXT,
                    status TEXT DEFAULT 'ATIVO',
                    status_source TEXT DEFAULT 'MANUAL',
                    status_reason TEXT,
                    status_updated_at TEXT,
                    status_updated_by TEXT,
                    sku TEXT,
                    units_per_package INTEGER,
                    allow_pack_sale INTEGER DEFAULT 0,
                    vat_rule_code TEXT DEFAULT 'STANDARD',
                    owner_username TEXT
                )''')
                
                # Copiar dados para tabela temporÃƒÆ’Ã‚Â¡ria
                self.cursor.execute('''
                INSERT INTO products_temp 
                SELECT id, description, category, CAST(existing_stock AS REAL), 
                       CAST(sold_stock AS REAL), sale_price, total_purchase_price, 
                       unit_purchase_price, profit_per_unit, barcode, expiry_date, 
                       date_added, is_sold_by_weight,
                       package_quantity,
                       status, status_source, status_reason, status_updated_at, status_updated_by,
                       sku, units_per_package, allow_pack_sale, vat_rule_code, owner_username
                FROM products
                ''')
                
                # Remover tabela antiga
                self.cursor.execute('DROP TABLE products')
                
                # Renomear tabela temporÃƒÆ’Ã‚Â¡ria
                self.cursor.execute('ALTER TABLE products_temp RENAME TO products')
                
                print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Colunas convertidas para REAL (suportam decimais)!")
            
            # Tabela de vendas (atualizada para aceitar quantidades decimais - KG)
            self.cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                sale_price REAL NOT NULL,
                total_price REAL NOT NULL,
                is_promotional INTEGER DEFAULT 0,
                sale_date TEXT NOT NULL,
                created_by TEXT,
                created_role TEXT,
                terminal_id TEXT,
                vat_rule_code TEXT DEFAULT 'STANDARD',
                vat_label TEXT,
                vat_rate_percent REAL DEFAULT 0,
                vat_taxable_ratio REAL DEFAULT 0,
                net_total REAL DEFAULT 0,
                vat_amount REAL DEFAULT 0,
                gross_total REAL DEFAULT 0,
                owner_username TEXT,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )''')

            # Garantir novas colunas na tabela sales (bases antigas)
            ensure_column("sales", "created_by", "TEXT")
            ensure_column("sales", "created_role", "TEXT")
            ensure_column("sales", "terminal_id", "TEXT")
            ensure_column("sales", "is_promotional", "INTEGER DEFAULT 0")
            ensure_column("sales", "vat_rule_code", "TEXT DEFAULT 'STANDARD'")
            ensure_column("sales", "vat_label", "TEXT")
            ensure_column("sales", "vat_rate_percent", "REAL DEFAULT 0")
            ensure_column("sales", "vat_taxable_ratio", "REAL DEFAULT 0")
            ensure_column("sales", "net_total", "REAL DEFAULT 0")
            ensure_column("sales", "vat_amount", "REAL DEFAULT 0")
            ensure_column("sales", "gross_total", "REAL DEFAULT 0")
            ensure_column("sales", "owner_username", "TEXT")

            # Tabela de devolucoes/estornos de venda
            self.cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS sales_returns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    returned_qty REAL NOT NULL,
                    sale_price REAL NOT NULL,
                    total_refund REAL NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    created_role TEXT,
                    terminal_id TEXT,
                    stock_movement_id INTEGER,
                    owner_username TEXT,
                    FOREIGN KEY (sale_id) REFERENCES sales (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (stock_movement_id) REFERENCES stock_movements (id)
                )
                '''
            )
            ensure_column("sales_returns", "owner_username", "TEXT")

            # Atualizar status default para registros antigos
            self.cursor.execute(
                "UPDATE products SET status = 'ATIVO' "
                "WHERE status IS NULL OR status = ''"
            )
            self.cursor.execute(
                "UPDATE products SET status_source = 'MANUAL' "
                "WHERE status_source IS NULL OR status_source = ''"
            )
            self.cursor.execute(
                "UPDATE products SET vat_rule_code = ? "
                "WHERE vat_rule_code IS NULL OR TRIM(vat_rule_code) = ''",
                (DEFAULT_VAT_RULE_CODE,),
            )
            self.cursor.execute(
                "UPDATE products_archive SET vat_rule_code = ? "
                "WHERE vat_rule_code IS NULL OR TRIM(vat_rule_code) = ''",
                (DEFAULT_VAT_RULE_CODE,),
            )
            self.cursor.execute(
                "UPDATE sales SET gross_total = COALESCE(NULLIF(gross_total, 0), total_price) "
                "WHERE gross_total IS NULL OR gross_total = 0"
            )
            self.cursor.execute(
                "UPDATE sales SET net_total = COALESCE(NULLIF(net_total, 0), total_price - COALESCE(vat_amount, 0)) "
                "WHERE net_total IS NULL OR net_total = 0"
            )
            self.cursor.execute(
                "UPDATE sales SET vat_rule_code = ? "
                "WHERE vat_rule_code IS NULL OR TRIM(vat_rule_code) = ''",
                (DEFAULT_VAT_RULE_CODE,),
            )
            # Regerar SKU no formato MANUAL-PREFIXO-000001
            self._rebuild_all_skus()
            self.cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku "
                "ON products (sku)"
            )

            # Tabela de movimentos de stock (livro-razÃƒÆ’Ã‚Â£o)
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                qty REAL NOT NULL,
                unit TEXT NOT NULL,
                unit_cost REAL NOT NULL,
                unit_price REAL NOT NULL,
                total_cost REAL NOT NULL,
                total_price REAL NOT NULL,
                stock_before REAL,
                stock_after REAL,
                reason TEXT,
                note TEXT,
                supplier_name TEXT,
                invoice_number TEXT,
                evidence_path TEXT,
                reference_table TEXT,
                reference_id INTEGER,
                created_at TEXT NOT NULL,
                created_by TEXT,
                created_role TEXT,
                terminal_id TEXT,
                approval_status TEXT DEFAULT 'APPROVED',
                approved_by TEXT,
                approved_at TEXT,
                applied INTEGER DEFAULT 1,
                owner_username TEXT,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )''')
            ensure_column("stock_movements", "supplier_name", "TEXT")
            ensure_column("stock_movements", "invoice_number", "TEXT")
            ensure_column("stock_movements", "owner_username", "TEXT")

            # Historico de status do produto
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS product_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                old_status TEXT,
                new_status TEXT,
                reason TEXT,
                source TEXT,
                changed_at TEXT,
                changed_by TEXT,
                owner_username TEXT,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )''')
            ensure_column("product_status_history", "owner_username", "TEXT")

            # ===== NOVA: Tabela de alertas de fraude =====
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS fraud_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                severity INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                related_user TEXT,
                related_product_id INTEGER,
                related_movement_id INTEGER,
                data_json TEXT,
                status TEXT DEFAULT 'OPEN',
                created_at TEXT NOT NULL,
                reviewed_by TEXT,
                reviewed_at TEXT,
                resolution_note TEXT,
                owner_username TEXT,
                FOREIGN KEY (related_product_id) REFERENCES products (id),
                FOREIGN KEY (related_movement_id) REFERENCES stock_movements (id)
            )''')
            ensure_column("fraud_alerts", "owner_username", "TEXT")

            # Estado de tarefas automÃƒÂ¡ticas (backup/reconciliaÃƒÂ§ÃƒÂ£o)
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS automation_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT,
                updated_at TEXT NOT NULL
            )''')

            # Registo de inconsistÃƒÂªncias encontradas na reconciliaÃƒÂ§ÃƒÂ£o de stock
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_reconciliation_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_run_at TEXT NOT NULL,
                product_id INTEGER,
                issue_type TEXT NOT NULL,
                movement_id INTEGER,
                stock_before REAL,
                stock_after REAL,
                expected_stock_after REAL,
                current_stock REAL,
                diff_qty REAL,
                details TEXT,
                owner_username TEXT,
                FOREIGN KEY (product_id) REFERENCES products (id),
                FOREIGN KEY (movement_id) REFERENCES stock_movements (id)
            )''')
            ensure_column("stock_reconciliation_issues", "owner_username", "TEXT")

            self.cursor.execute(
                "SELECT username FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1"
            )
            legacy_owner_row = self.cursor.fetchone()
            legacy_owner = legacy_owner_row[0] if legacy_owner_row else None
            if legacy_owner:
                self.cursor.execute(
                    "UPDATE users SET data_owner = ? WHERE data_owner IS NULL OR TRIM(data_owner) = ''",
                    (legacy_owner,),
                )
                for table in (
                    "products",
                    "products_archive",
                    "sales",
                    "sales_returns",
                    "stock_movements",
                    "product_status_history",
                    "fraud_alerts",
                    "stock_reconciliation_issues",
                    "user_logs",
                ):
                    self.cursor.execute(
                        f"UPDATE {table} SET owner_username = ? "
                        "WHERE owner_username IS NULL OR TRIM(owner_username) = ''",
                        (legacy_owner,),
                    )

            # Indices para performance
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_movements_product_date "
                "ON stock_movements (product_id, created_at)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_movements_type_date "
                "ON stock_movements (movement_type, created_at)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_movements_owner_applied_date "
                "ON stock_movements (owner_username, applied, created_at DESC)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_returns_sale "
                "ON sales_returns (sale_id, created_at)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_status "
                "ON products (status)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_fraud_status "
                "ON fraud_alerts (status, severity)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_reconcile_product_date "
                "ON stock_reconciliation_issues (product_id, check_run_at)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_barcode "
                "ON products (barcode)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_description "
                "ON products (description)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_category "
                "ON products (category)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_date_added "
                "ON products (date_added)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_sale_filter "
                "ON products (status, expiry_date, existing_stock)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_sale_date "
                "ON sales (sale_date)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_product_date "
                "ON sales (product_id, sale_date)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_terminal_date "
                "ON sales (terminal_id, sale_date)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_logs_timestamp "
                "ON user_logs (timestamp)"
            )
            
            self.conn.commit()
            print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Banco de dados configurado com suporte completo a vendas por KG e sistema de perdas!")
            
        except (sqlite3.Error, ValueError) as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao configurar o banco de dados: {e}")
            try:
                if self.conn:
                    self.conn.rollback()
            except Exception:
                pass
    
    # Autenticacao e recuperacao de acesso.
    def validate_user(self, username, password):
        """Validar credenciais do usuÃƒÆ’Ã‚Â¡rio usando hashing"""
        try:
            self.cursor.execute(
                "SELECT password, role FROM users WHERE username = ?", (username,)
            )
            result = self.cursor.fetchone()
            if result and bcrypt.checkpw(password.encode('utf-8'), result[0]):
                return result[1]  # Retorna a role do usuÃƒÆ’Ã‚Â¡rio
            return None
        except (sqlite3.Error, ValueError) as e:
            print(f"Erro ao validar usuÃƒÆ’Ã‚Â¡rio: {e}")
            return None


    def has_admin(self):
        """Verificar se existe algum admin cadastrado"""
        try:
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            return self.cursor.fetchone()[0] > 0
        except (sqlite3.Error, ValueError) as e:
            print(f"Erro ao verificar admin: {e}")
            return False

    def create_admin(self, username, password):
        """Criar admin inicial"""
        try:
            self.cursor.execute("SELECT COUNT(*) FROM users")
            had_users = int(self.cursor.fetchone()[0] or 0) > 0
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            self.cursor.execute(
                "INSERT INTO users (username, password, role, data_owner) VALUES (?, ?, ?, ?)",
                (username, hashed_password, 'admin', username),
            )
            if not had_users:
                for table in (
                    "products",
                    "products_archive",
                    "sales",
                    "sales_returns",
                    "stock_movements",
                    "product_status_history",
                    "fraud_alerts",
                    "stock_reconciliation_issues",
                    "user_logs",
                ):
                    self.cursor.execute(
                        f"UPDATE {table} SET owner_username = ? "
                        "WHERE owner_username IS NULL OR TRIM(owner_username) = ''",
                        (username,),
                    )
            self.conn.commit()
            self.log_action(username, 'admin', 'CREATE_USER', f"Admin criado: {username}")
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False
        except (sqlite3.Error, ValueError) as e:
            print(f"Erro ao criar admin: {e}")
            self.conn.rollback()
            return False

    def is_user_password_default(self, username, defaults=None):
        """Verificar se a senha do usuario e uma senha padrao"""
        defaults = defaults or ['123', '123456']
        try:
            self.cursor.execute(
                "SELECT password FROM users WHERE username = ? AND role = 'admin'",
                (username,),
            )
            row = self.cursor.fetchone()
            if not row:
                return False
            stored = row[0]
            for pwd in defaults:
                if bcrypt.checkpw(pwd.encode('utf-8'), stored):
                    return True
            return False
        except sqlite3.Error as e:
            print(f"Erro ao verificar senha padrao: {e}")
            return False

    def update_user_password(self, username, new_password, role=None):
        """Atualizar senha do usuario"""
        try:
            hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
            if role:
                self.cursor.execute(
                    "UPDATE users SET password = ? WHERE username = ? AND role = ?",
                    (hashed_password, username, role),
                )
            else:
                self.cursor.execute(
                    "UPDATE users SET password = ? WHERE username = ?",
                    (hashed_password, username),
                )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao atualizar senha: {e}")
            self.conn.rollback()
            return False

    def get_admin_usernames(self):
        """Obter lista de admins cadastrados"""
        try:
            self.cursor.execute("SELECT username FROM users WHERE role = 'admin'")
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Erro ao obter admins: {e}")
            return []

    def is_admin_default(self, username, defaults=None):
        """Verificar se o admin usa senha padrao"""
        if not username:
            return False
        return self.is_user_password_default(username, defaults)

    def update_admin_credentials(self, old_username, new_username, new_password):
        """Atualizar username e senha do admin padrao"""
        try:
            if not new_username:
                return False
            self.cursor.execute(
                "SELECT COUNT(*) FROM users WHERE username = ? AND username != ?",
                (new_username, old_username),
            )
            if self.cursor.fetchone()[0] > 0:
                return False

            hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
            self.cursor.execute(
                "UPDATE users SET username = ?, password = ? WHERE username = ? AND role = 'admin'",
                (new_username, hashed_password, old_username),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return False
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao atualizar admin: {e}")
            self.conn.rollback()
            return False

    def user_exists(self, username, exclude_username=None):
        """Verificar se um usuario existe"""
        try:
            if exclude_username:
                self.cursor.execute(
                    "SELECT COUNT(*) FROM users WHERE username = ? AND username != ?",
                    (username, exclude_username),
                )
            else:
                self.cursor.execute(
                    "SELECT COUNT(*) FROM users WHERE username = ?",
                    (username,),
                )
            return self.cursor.fetchone()[0] > 0
        except sqlite3.Error as e:
            print(f"Erro ao verificar usuario: {e}")
            return False

    def get_user_role(self, username):
        """Obter role de um usuario"""
        try:
            self.cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
            row = self.cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            print(f"Erro ao obter role: {e}")
            return None

    def get_user(self, username):
        """Obter dados completos de um usuario"""
        try:
            self.cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"Erro ao obter usuario: {e}")
            return None

    def get_user_data_owner(self, username):
        """Obter o espaco de dados associado ao usuario."""
        if not username:
            return None
        try:
            self.cursor.execute(
                "SELECT COALESCE(NULLIF(TRIM(data_owner), ''), username) FROM users WHERE username = ?",
                (username,),
            )
            row = self.cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            print(f"Erro ao obter dono dos dados: {e}")
            return username

    def create_user(self, username, password, role, email=None, phone=None, data_owner=None):
        """Criar usuario (admin ou manager)"""
        try:
            username = str(username or "").strip()
            role = str(role or "").strip().lower()
            if not username or not password or role not in ("admin", "manager"):
                return False
            email = str(email).strip() if email else None
            phone = str(phone).strip() if phone else None
            owner = str(data_owner or username or "").strip() or username
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            self.cursor.execute(
                "INSERT INTO users (username, password, role, email, phone, data_owner) VALUES (?, ?, ?, ?, ?, ?)",
                (username, hashed_password, role, email, phone, owner),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False
        except sqlite3.Error as e:
            print(f"Erro ao criar usuario: {e}")
            self.conn.rollback()
            return False

    def update_admin_profile(self, current_username, new_username=None, new_password=None):
        """Atualizar username e/ou senha do admin"""
        if not new_username and not new_password:
            return False
        try:
            if new_username and self.user_exists(new_username, exclude_username=current_username):
                return False
            update_parts = []
            params = []
            if new_username:
                update_parts.append("username = ?")
                params.append(new_username)
            if new_password:
                hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
                update_parts.append("password = ?")
                params.append(hashed_password)
            params.append(current_username)
            self.cursor.execute(
                f"UPDATE users SET {', '.join(update_parts)} WHERE username = ? AND role = 'admin'",
                params,
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return False
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao atualizar admin: {e}")
            self.conn.rollback()
            return False

    def set_security_questions(self, username, answers):
        """Configurar perguntas de seguranca para um usuario"""
        try:
            from utils.security_questions import REQUIRED_QUESTION_COUNT, hash_answer
            normalized_answers = [str(answer or "").strip() for answer in list(answers or [])]
            if len(normalized_answers) < REQUIRED_QUESTION_COUNT or len(normalized_answers) > 4:
                return False
            if any(not answer for answer in normalized_answers):
                return False

            hashes = [hash_answer(ans) for ans in normalized_answers]
            placeholder = hash_answer("__unused__")
            while len(hashes) < 4:
                hashes.append(placeholder)
            now = datetime.now().isoformat()
            self.cursor.execute(
                'INSERT OR REPLACE INTO user_security_questions '
                '(username, q1_hash, q2_hash, q3_hash, q4_hash, attempts, lock_until, updated_at) '
                'VALUES (?, ?, ?, ?, ?, 0, NULL, ?)',
                (username, hashes[0], hashes[1], hashes[2], hashes[3], now),
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro ao salvar perguntas: {e}")
            self.conn.rollback()
            return False

    def get_security_record(self, username):
        """Obter registro de perguntas de seguranca"""
        try:
            self.cursor.execute(
                'SELECT q1_hash, q2_hash, q3_hash, q4_hash, attempts, lock_until '
                'FROM user_security_questions WHERE username = ?',
                (username,),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            q1, q2, q3, q4, attempts, lock_until = row
            lock_value = None
            if lock_until:
                try:
                    lock_value = datetime.fromisoformat(lock_until).isoformat()
                except Exception:
                    lock_value = lock_until
            return {
                "hashes": [q1, q2, q3, q4],
                "attempts": attempts or 0,
                "lock_until": lock_value,
            }
        except sqlite3.Error as e:
            print(f"Erro ao obter registro de seguranca: {e}")
            return None

    def update_security_state(self, username, attempts, lock_until):
        """Atualizar estado de seguranca (tentativas e bloqueio)"""
        try:
            if isinstance(lock_until, str):
                lock_value = lock_until
            else:
                lock_value = lock_until.isoformat() if lock_until else None
            self.cursor.execute(
                'UPDATE user_security_questions SET attempts = ?, lock_until = ? WHERE username = ?',
                (attempts, lock_value, username),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao atualizar seguranca: {e}")
            self.conn.rollback()
            return False

    def verify_security_answers(self, username, answers, max_attempts=5, lock_minutes=15):
        """Verifica respostas de seguranca e gerencia tentativas/lock"""
        try:
            from utils.security_questions import REQUIRED_QUESTION_COUNT, check_answer
            normalized_answers = [str(answer or "").strip() for answer in list(answers or [])]
            if len(normalized_answers) < REQUIRED_QUESTION_COUNT or len(normalized_answers) > 4:
                return {"ok": False, "reason": "not_configured"}
            if any(not answer for answer in normalized_answers):
                return {"ok": False, "reason": "not_configured"}
            record = self.get_security_record(username)
            if not record:
                return {"ok": False, "reason": "not_configured"}

            now = datetime.now()
            lock_until_raw = record.get("lock_until")
            lock_until = None
            if lock_until_raw:
                try:
                    lock_until = datetime.fromisoformat(lock_until_raw)
                except Exception:
                    lock_until = None
            if lock_until and now < lock_until:
                remaining = int((lock_until - now).total_seconds() / 60) + 1
                return {
                    "ok": False,
                    "reason": "locked",
                    "lock_until": lock_until.isoformat(),
                    "remaining_minutes": remaining,
                }
            if lock_until and now >= lock_until:
                self.update_security_state(username, 0, None)
                record["attempts"] = 0
                record["lock_until"] = None

            hashes = list(record.get("hashes", []) or [])[: len(normalized_answers)]
            if len(hashes) < len(normalized_answers):
                return {"ok": False, "reason": "not_configured"}

            all_ok = True
            for ans, hashed in zip(normalized_answers, hashes):
                if not check_answer(ans, hashed):
                    all_ok = False
                    break

            if not all_ok:
                attempts = (record.get("attempts") or 0) + 1
                if attempts >= max_attempts:
                    lock_until = now + timedelta(minutes=lock_minutes)
                    self.update_security_state(username, attempts, lock_until)
                    return {
                        "ok": False,
                        "reason": "locked",
                        "lock_until": lock_until.isoformat(),
                        "remaining_minutes": lock_minutes,
                    }
                self.update_security_state(username, attempts, None)
                return {
                    "ok": False,
                    "reason": "invalid",
                    "remaining": max_attempts - attempts,
                    "attempts": attempts,
                }

            self.update_security_state(username, 0, None)
            return {"ok": True}
        except Exception as e:
            print(f"Erro ao verificar respostas: {e}")
            return {"ok": False, "reason": "error"}

    def log_action(self, username, role, action, details=""):
        """Registrar aÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o do usuÃƒÆ’Ã‚Â¡rio no log do sistema"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.cursor.execute(
                """
                INSERT INTO user_logs (username, role, action, details, timestamp, owner_username)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, role, action, details, timestamp, self._owner_value(username)),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Erro ao registrar log: {e}")
            self.conn.rollback()
    
    # Metodos para produtos, lotes e movimentos de stock.
    
    def _now_str(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _parse_expiry_date(self, text):
        if not text:
            return None
        try:
            return datetime.strptime(str(text), "%Y-%m-%d").date()
        except Exception:
            return None

    @staticmethod
    def _normalize_barcode_value(barcode):
        text = str(barcode or "").strip()
        return text or None

    def _normalize_expiry_value(self, expiry_date):
        if expiry_date in (None, ""):
            return None
        parsed = _parse_date(expiry_date)
        if not parsed:
            raise ValueError("Data de validade invalida.")
        return parsed.isoformat()

    @staticmethod
    def _expiry_order_clause(prefix=""):
        column = f"{prefix}expiry_date" if prefix else "expiry_date"
        id_column = f"{prefix}id" if prefix else "id"
        return (
            f"CASE WHEN {column} IS NULL OR TRIM({column}) = '' THEN 1 ELSE 0 END, "
            f"DATE({column}) ASC, {id_column} ASC"
        )

    @staticmethod
    def _catalog_identity_sql(prefix=""):
        barcode_column = f"{prefix}barcode" if prefix else "barcode"
        id_column = f"{prefix}id" if prefix else "id"
        return (
            "CASE "
            f"WHEN {barcode_column} IS NOT NULL AND TRIM({barcode_column}) != '' "
            f"THEN LOWER(TRIM({barcode_column})) "
            f"ELSE 'id:' || CAST({id_column} AS TEXT) "
            "END"
        )

    def _find_existing_batch(self, barcode, expiry_date, exclude_id=None):
        barcode_clean = self._normalize_barcode_value(barcode)
        if not barcode_clean:
            return None

        normalized_expiry = self._normalize_expiry_value(expiry_date)
        query = """
            SELECT id, existing_stock, sold_stock, unit_purchase_price
            FROM products
            WHERE LOWER(TRIM(barcode)) = LOWER(TRIM(?))
        """
        params = [barcode_clean]

        if normalized_expiry is None:
            query += " AND (expiry_date IS NULL OR TRIM(expiry_date) = '')"
        else:
            query += " AND TRIM(COALESCE(expiry_date, '')) = ?"
            params.append(normalized_expiry)

        if exclude_id is not None:
            query += " AND id != ?"
            params.append(int(exclude_id))

        scope_sql, scope_params = self._owner_filter()
        query += scope_sql
        params.extend(scope_params)

        query += " LIMIT 1"
        self.cursor.execute(query, tuple(params))
        return self.cursor.fetchone()

    def _to_dt_str(self, value, end=False):
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, date):
            t = datetime.combine(
                value,
                datetime.max.time() if end else datetime.min.time()
            ).replace(microsecond=0)
            return t.strftime("%Y-%m-%d %H:%M:%S")
        return value

    # ==================== STATUS E EXPIRACAO ====================
    def set_product_status(self, product_id, new_status, reason, username, source="MANUAL"):
        """Atualiza status do produto e grava historico."""
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                f"SELECT status FROM products WHERE id = ?{scope_sql}",
                (product_id, *scope_params),
            )
            row = self.cursor.fetchone()
            if not row:
                return False

            old_status = row[0]
            now = self._now_str()
            user = username or "SYSTEM"

            self.cursor.execute(
                """
                UPDATE products
                SET status = ?, status_source = ?, status_reason = ?,
                    status_updated_at = ?, status_updated_by = ?
                WHERE id = ?
                """,
                (new_status, source, reason, now, user, product_id),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return False
            self.cursor.execute(
                """
                INSERT INTO product_status_history
                (product_id, old_status, new_status, reason, source, changed_at, changed_by, owner_username)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, old_status, new_status, reason, source, now, user, self._owner_value(user)),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao atualizar status: {e}")
            self.conn.rollback()
            return False

    def refresh_auto_statuses(self, now=None):
        """Atualiza automaticamente status baseado em validade."""
        try:
            today = now.date() if isinstance(now, datetime) else (
                now if isinstance(now, date) else datetime.now().date()
            )
            near_date = today + timedelta(days=NEAR_EXPIRY_DAYS)
            changes = []

            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                f"SELECT id, status, status_source, expiry_date FROM products WHERE 1=1{scope_sql}",
                tuple(scope_params),
            )
            rows = self.cursor.fetchall()

            for product_id, status, status_source, expiry_date in rows:
                exp_date = self._parse_expiry_date(expiry_date)
                new_status = None
                reason = None

                if not exp_date:
                    if status_source == "AUTO" and status in ("EXPIRADO", "PERTO_DO_PRAZO"):
                        new_status = "ATIVO"
                        reason = "Validade removida ou corrigida"
                else:
                    if exp_date < today:
                        if status in ("ATIVO", "PERTO_DO_PRAZO"):
                            new_status = "EXPIRADO"
                            reason = "Expirado automaticamente"
                    elif exp_date <= near_date:
                        if status == "ATIVO":
                            new_status = "PERTO_DO_PRAZO"
                            reason = "Perto do prazo"
                    else:
                        if status_source == "AUTO" and status in ("EXPIRADO", "PERTO_DO_PRAZO"):
                            new_status = "ATIVO"
                            reason = "Validade corrigida"

                if new_status and new_status != status:
                    changes.append((product_id, status, new_status, reason))

            if not changes:
                return 0

            now_str = self._now_str()
            for product_id, old_status, new_status, reason in changes:
                self.cursor.execute(
                    """
                    UPDATE products
                    SET status = ?, status_source = 'AUTO', status_reason = ?,
                        status_updated_at = ?, status_updated_by = ?
                    WHERE id = ?
                    """,
                    (new_status, reason, now_str, "SYSTEM", product_id),
                )
                self.cursor.execute(
                    """
                    INSERT INTO product_status_history
                    (product_id, old_status, new_status, reason, source, changed_at, changed_by)
                    VALUES (?, ?, ?, ?, 'AUTO', ?, ?)
                    """,
                    (product_id, old_status, new_status, reason, now_str, "SYSTEM"),
                )

            self.conn.commit()
            return len(changes)
        except sqlite3.Error as e:
            print(f"Erro ao atualizar status automatico: {e}")
            self.conn.rollback()
            return 0

    # ==================== MOVIMENTOS DE STOCK ====================
    def _record_stock_movement_tx(
        self,
        cursor,
        product_id,
        movement_type,
        qty,
        direction,
        reason="",
        note="",
        evidence_path=None,
        reference_table=None,
        reference_id=None,
        created_by=None,
        created_role=None,
        terminal_id=None,
        unit_cost=None,
        unit_price=None,
        supplier_name=None,
        invoice_number=None,
        approval_status="APPROVED",
        approved_by=None,
        approved_at=None,
        apply_stock=True,
    ):
        scope_sql, scope_params = self._owner_filter()
        cursor.execute(
            f"""
            SELECT existing_stock, sold_stock, unit_purchase_price,
                   sale_price, is_sold_by_weight
            FROM products WHERE id = ?
            {scope_sql}
            """,
            (product_id, *scope_params),
        )
        product = cursor.fetchone()
        if not product:
            return None

        stock_before = float(product[0])
        is_by_weight = bool(product[4])
        qty = float(qty)
        if qty <= 0:
            return None

        if unit_cost is None:
            unit_cost = float(product[2] or 0)
        if unit_price is None:
            unit_price = float(product[3] or 0)

        total_cost = qty * float(unit_cost)
        total_price = qty * float(unit_price)

        if direction not in ("IN", "OUT"):
            return None

        if apply_stock:
            if direction == "OUT":
                if stock_before < qty:
                    return None
                stock_after = stock_before - qty
                if movement_type == "SALE":
                    cursor.execute(
                        """
                        UPDATE products
                        SET existing_stock = existing_stock - ?,
                            sold_stock = sold_stock + ?
                        WHERE id = ?
                        """,
                        (qty, qty, product_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE products SET existing_stock = existing_stock - ? WHERE id = ?",
                        (qty, product_id),
                    )
            else:
                stock_after = stock_before + qty
                if movement_type == "RETURN":
                    cursor.execute(
                        """
                        UPDATE products
                        SET existing_stock = existing_stock + ?,
                            sold_stock = CASE
                                WHEN sold_stock >= ? THEN sold_stock - ?
                                ELSE 0
                            END
                        WHERE id = ?
                        """,
                        (qty, qty, qty, product_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE products SET existing_stock = existing_stock + ? WHERE id = ?",
                        (qty, product_id),
                    )
        else:
            stock_after = stock_before

        unit = "KG" if is_by_weight else "UN"
        now_str = self._now_str()
        approved_at = approved_at or (now_str if approval_status == "APPROVED" else None)
        approved_by = approved_by or (created_by if approval_status == "APPROVED" else None)
        applied = 1 if apply_stock else 0

        cursor.execute(
            """
            INSERT INTO stock_movements (
                product_id, movement_type, direction, qty, unit,
                unit_cost, unit_price, total_cost, total_price,
                stock_before, stock_after, reason, note, supplier_name, invoice_number, evidence_path,
                reference_table, reference_id, created_at, created_by,
                created_role, terminal_id, approval_status, approved_by,
                approved_at, applied, owner_username
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id, movement_type, direction, qty, unit,
                unit_cost, unit_price, total_cost, total_price,
                stock_before, stock_after, reason, note, supplier_name, invoice_number, evidence_path,
                reference_table, reference_id, now_str, created_by,
                created_role, terminal_id, approval_status, approved_by,
                approved_at, applied, self._owner_value(created_by)
            ),
        )
        return cursor.lastrowid

    def record_stock_movement(
        self,
        product_id,
        movement_type,
        qty,
        direction,
        reason="",
        note="",
        evidence_path=None,
        reference_table=None,
        reference_id=None,
        created_by=None,
        created_role=None,
        terminal_id=None,
        unit_cost=None,
        unit_price=None,
        supplier_name=None,
        invoice_number=None,
    ):
        """Registra movimento e aplica no stock imediatamente."""
        try:
            movement_id = self._record_stock_movement_tx(
                self.cursor,
                product_id,
                movement_type,
                qty,
                direction,
                reason=reason,
                note=note,
                evidence_path=evidence_path,
                reference_table=reference_table,
                reference_id=reference_id,
                created_by=created_by,
                created_role=created_role,
                terminal_id=terminal_id,
                unit_cost=unit_cost,
                unit_price=unit_price,
                supplier_name=supplier_name,
                invoice_number=invoice_number,
                approval_status="APPROVED",
                approved_by=created_by,
                approved_at=self._now_str(),
                apply_stock=True,
            )
            if not movement_id:
                self.conn.rollback()
                return None
            self.conn.commit()
            return movement_id
        except sqlite3.Error as e:
            print(f"Erro ao registrar movimento: {e}")
            self.conn.rollback()
            return None

    def request_stock_movement(
        self,
        product_id,
        movement_type,
        qty,
        reason,
        created_by,
        created_role,
        terminal_id=None,
        note="",
        evidence_path=None,
        reference_table=None,
        reference_id=None,
        unit_cost=None,
        unit_price=None,
        direction=None,
    ):
        """Registra movimento e decide se precisa aprovacao."""
        try:
            self.cursor.execute(
                """
                SELECT existing_stock, unit_purchase_price, sale_price, is_sold_by_weight
                FROM products WHERE id = ?
                """,
                (product_id,),
            )
            product = self.cursor.fetchone()
            if not product:
                return None

            stock_before = float(product[0])
            unit_cost = float(unit_cost) if unit_cost is not None else float(product[1] or 0)
            unit_price = float(unit_price) if unit_price is not None else float(product[2] or 0)
            is_by_weight = bool(product[3])

            qty = float(qty)
            if qty <= 0:
                return None

            if direction is None:
                if movement_type in LOSS_TYPES or movement_type == "SALE":
                    direction = "OUT"
                elif movement_type == "RETURN":
                    direction = "IN"

            if direction == "OUT" and stock_before < qty:
                return None

            needs_approval = False
            if movement_type in LOSS_TYPES:
                qty_limit = LOSS_QTY_LIMIT_KG if is_by_weight else LOSS_QTY_LIMIT_UN
                if qty > qty_limit or (qty * unit_cost) > LOSS_VALUE_LIMIT_MZN:
                    needs_approval = True

            if needs_approval:
                movement_id = self._record_stock_movement_tx(
                    self.cursor,
                    product_id,
                    movement_type,
                    qty,
                    direction,
                    reason=reason,
                    note=note,
                    evidence_path=evidence_path,
                    reference_table=reference_table,
                    reference_id=reference_id,
                    created_by=created_by,
                    created_role=created_role,
                    terminal_id=terminal_id,
                    unit_cost=unit_cost,
                    unit_price=unit_price,
                    approval_status="PENDING",
                    approved_by=None,
                    approved_at=None,
                    apply_stock=False,
                )
                if not movement_id:
                    self.conn.rollback()
                    return None
                self.conn.commit()
                return movement_id

            return self.record_stock_movement(
                product_id,
                movement_type,
                qty,
                direction,
                reason=reason,
                note=note,
                evidence_path=evidence_path,
                reference_table=reference_table,
                reference_id=reference_id,
                created_by=created_by,
                created_role=created_role,
                terminal_id=terminal_id,
                unit_cost=unit_cost,
                unit_price=unit_price,
            )
        except sqlite3.Error as e:
            print(f"Erro ao solicitar movimento: {e}")
            self.conn.rollback()
            return None

    def approve_stock_movement(self, movement_id, approved_by):
        """Aprova movimento pendente e aplica no stock."""
        try:
            self.cursor.execute(
                """
                SELECT product_id, movement_type, direction, qty, approval_status, applied
                FROM stock_movements WHERE id = ?
                """,
                (movement_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                return False

            product_id, movement_type, direction, qty, approval_status, applied = row
            if approval_status != "PENDING" or applied:
                return False

            self.cursor.execute(
                "SELECT existing_stock, sold_stock FROM products WHERE id = ?",
                (product_id,),
            )
            product = self.cursor.fetchone()
            if not product:
                return False

            stock_before = float(product[0])
            qty = float(qty)
            if direction == "OUT":
                if stock_before < qty:
                    return False
                stock_after = stock_before - qty
                if movement_type == "SALE":
                    self.cursor.execute(
                        """
                        UPDATE products
                        SET existing_stock = existing_stock - ?,
                            sold_stock = sold_stock + ?
                        WHERE id = ?
                        """,
                        (qty, qty, product_id),
                    )
                else:
                    self.cursor.execute(
                        "UPDATE products SET existing_stock = existing_stock - ? WHERE id = ?",
                        (qty, product_id),
                    )
            else:
                stock_after = stock_before + qty
                if movement_type == "RETURN":
                    self.cursor.execute(
                        """
                        UPDATE products
                        SET existing_stock = existing_stock + ?,
                            sold_stock = CASE
                                WHEN sold_stock >= ? THEN sold_stock - ?
                                ELSE 0
                            END
                        WHERE id = ?
                        """,
                        (qty, qty, qty, product_id),
                    )
                else:
                    self.cursor.execute(
                        "UPDATE products SET existing_stock = existing_stock + ? WHERE id = ?",
                        (qty, product_id),
                    )

            now_str = self._now_str()
            self.cursor.execute(
                """
                UPDATE stock_movements
                SET approval_status = 'APPROVED',
                    approved_by = ?,
                    approved_at = ?,
                    applied = 1,
                    stock_before = ?,
                    stock_after = ?
                WHERE id = ?
                """,
                (approved_by, now_str, stock_before, stock_after, movement_id),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao aprovar movimento: {e}")
            self.conn.rollback()
            return False

    def delete_stock_movement(self, movement_id, deleted_by=None):
        """Remove um movimento do historico visivel sem recalcular o stock atual."""
        try:
            movement_id = int(movement_id)
        except (TypeError, ValueError):
            return False

        try:
            where = ["id = ?", "applied = 1"]
            params = [movement_id]
            owner = self._active_owner()
            if owner:
                where.append("COALESCE(owner_username, '') = ?")
                params.append(owner)

            self.cursor.execute(
                f"""
                UPDATE stock_movements
                SET applied = 0,
                    approval_status = 'DELETED',
                    note = CASE
                        WHEN COALESCE(note, '') = '' THEN ?
                        ELSE note || ' | ' || ?
                    END
                WHERE {" AND ".join(where)}
                """,
                (
                    f"Movimento eliminado por {deleted_by or 'admin'} em {self._now_str()}",
                    f"Movimento eliminado por {deleted_by or 'admin'} em {self._now_str()}",
                    *params,
                ),
            )
            changed = self.cursor.rowcount > 0
            self.conn.commit()
            return changed
        except sqlite3.Error as e:
            print(f"Erro ao eliminar movimento de stock: {e}")
            self.conn.rollback()
            return False

    # ==================== PERDAS ====================
    def get_loss_summary(self, start_dt, end_dt):
        """Resumo de perdas por periodo."""
        start = self._to_dt_str(start_dt, end=False)
        end = self._to_dt_str(end_dt, end=True)
        try:
            loss_types = list(LOSS_TYPES)
            placeholders = ",".join(["?"] * len(loss_types))
            self.cursor.execute(
                f"""
                SELECT COALESCE(SUM(total_cost), 0),
                       COALESCE(SUM(total_price), 0)
                FROM stock_movements
                WHERE applied = 1
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                """,
                (*loss_types, start, end),
            )
            loss_cost, loss_revenue = self.cursor.fetchone()

            self.cursor.execute(
                """
                SELECT COALESCE(SUM(total_price), 0)
                FROM sales
                WHERE sale_date BETWEEN ? AND ?
                """,
                (start, end),
            )
            total_sales = self.cursor.fetchone()[0]

            loss_pct_sales = 0
            if total_sales and total_sales > 0:
                loss_pct_sales = (loss_cost / total_sales) * 100

            return {
                "loss_cost_total": loss_cost,
                "loss_revenue_total": loss_revenue,
                "loss_pct_sales": loss_pct_sales,
                "total_sales": total_sales,
            }
        except sqlite3.Error as e:
            print(f"Erro ao obter resumo de perdas: {e}")
            return None

    def get_loss_by_user(self, start_dt, end_dt):
        """Perdas agrupadas por utilizador."""
        start = self._to_dt_str(start_dt, end=False)
        end = self._to_dt_str(end_dt, end=True)
        try:
            loss_types = list(LOSS_TYPES)
            placeholders = ",".join(["?"] * len(loss_types))
            self.cursor.execute(
                f"""
                SELECT created_by,
                       COALESCE(SUM(total_cost), 0) as loss_cost,
                       COALESCE(SUM(total_price), 0) as loss_revenue,
                       COUNT(*) as events
                FROM stock_movements
                WHERE applied = 1
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                GROUP BY created_by
                ORDER BY loss_cost DESC
                """,
                (*loss_types, start, end),
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter perdas por utilizador: {e}")
            return []

    def restock_product(
        self,
        product_id,
        qty,
        unit_cost,
        expiry_date=None,
        reason="ReposiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de stock",
        note="",
        evidence_path=None,
        created_by=None,
        created_role=None,
        terminal_id=None,
        supplier_name=None,
        invoice_number=None,
    ):
        """Registra reposiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de stock e atualiza custo mÃƒÆ’Ã‚Â©dio."""
        try:
            qty = float(qty)
            unit_cost = float(unit_cost)
            if qty <= 0 or unit_cost <= 0:
                return None

            self.cursor.execute(
                """
                SELECT description, category, existing_stock, unit_purchase_price, sale_price,
                       barcode, is_sold_by_weight, expiry_date, package_quantity,
                       units_per_package, allow_pack_sale, vat_rule_code
                FROM products WHERE id = ?
                """,
                (product_id,),
            )
            product = self.cursor.fetchone()
            if not product:
                return None

            (
                description,
                category,
                _base_stock,
                _base_cost,
                base_sale_price,
                barcode,
                is_sold_by_weight,
                base_expiry,
                package_quantity,
                units_per_package,
                allow_pack_sale,
                vat_rule_code,
            ) = product

            normalized_barcode = self._normalize_barcode_value(barcode)
            normalized_base_expiry = self._normalize_expiry_value(base_expiry)
            target_expiry = (
                self._normalize_expiry_value(expiry_date)
                if expiry_date not in (None, "")
                else normalized_base_expiry
            )

            target_product_id = int(product_id)
            if normalized_barcode and target_expiry != normalized_base_expiry:
                sibling = self._find_existing_batch(normalized_barcode, target_expiry)
                if sibling:
                    target_product_id = int(sibling[0])
                else:
                    cloned_profit = float(base_sale_price or 0) - unit_cost
                    target_product_id = self._insert_product_row(
                        description=description,
                        category=category,
                        existing_stock=0.0,
                        sold_stock=0.0,
                        sale_price=float(base_sale_price or 0),
                        total_purchase_price=0.0,
                        unit_purchase_price=unit_cost,
                        profit_per_unit=cloned_profit,
                        barcode=normalized_barcode,
                        expiry_date=target_expiry,
                        is_sold_by_weight=bool(is_sold_by_weight),
                        package_quantity=package_quantity,
                        units_per_package=units_per_package,
                        allow_pack_sale=allow_pack_sale,
                        vat_rule_code=self._normalize_vat_rule_code(vat_rule_code),
                    )

            self.cursor.execute(
                """
                SELECT existing_stock, unit_purchase_price, sale_price
                FROM products WHERE id = ?
                """,
                (target_product_id,),
            )
            target_product = self.cursor.fetchone()
            if not target_product:
                self.conn.rollback()
                return None

            stock_before = float(target_product[0] or 0.0)
            old_cost = float(target_product[1] or 0.0)
            sale_price = float(target_product[2] or 0.0)

            movement_id = self._record_stock_movement_tx(
                self.cursor,
                target_product_id,
                "RESTOCK",
                qty,
                "IN",
                reason=reason,
                note=note,
                evidence_path=evidence_path,
                created_by=created_by,
                created_role=created_role,
                terminal_id=terminal_id,
                unit_cost=unit_cost,
                unit_price=sale_price,
                supplier_name=supplier_name,
                invoice_number=invoice_number,
                approval_status="APPROVED",
                approved_by=created_by,
                approved_at=self._now_str(),
                apply_stock=True,
            )
            if not movement_id:
                self.conn.rollback()
                return None

            total_qty = stock_before + qty
            if total_qty <= 0:
                new_unit_cost = unit_cost
            else:
                new_unit_cost = ((stock_before * old_cost) + (qty * unit_cost)) / total_qty

            new_total_purchase = new_unit_cost * total_qty
            profit_per_unit = sale_price - new_unit_cost

            self.cursor.execute(
                """
                UPDATE products
                SET unit_purchase_price = ?,
                    total_purchase_price = ?,
                    profit_per_unit = ?
                WHERE id = ?
                """,
                (new_unit_cost, new_total_purchase, profit_per_unit, target_product_id),
            )

            self.conn.commit()
            return movement_id
        except sqlite3.Error as e:
            print(f"Erro ao repor stock: {e}")
            self.conn.rollback()
            return None

    def get_loss_records(self, start_dt, end_dt, limit=200):
        """Lista detalhada de perdas no perÃƒÆ’Ã‚Â­odo."""
        start = self._to_dt_str(start_dt, end=False)
        end = self._to_dt_str(end_dt, end=True)
        try:
            loss_types = list(LOSS_TYPES)
            placeholders = ",".join(["?"] * len(loss_types))
            limit_clause = "LIMIT ?" if limit else ""
            params = [*loss_types, start, end]
            if limit:
                params.append(int(limit))
            self.cursor.execute(
                f"""
                SELECT sm.created_at,
                       COALESCE(p.description, pa.description) as product_name,
                       sm.movement_type,
                       sm.qty,
                       sm.unit,
                       sm.total_cost,
                       sm.total_price,
                       sm.reason,
                       sm.created_by
                FROM stock_movements sm
                LEFT JOIN products p ON sm.product_id = p.id
                LEFT JOIN products_archive pa ON sm.product_id = pa.id
                WHERE sm.applied = 1
                  AND sm.direction = 'OUT'
                  AND sm.movement_type IN ({placeholders})
                  AND sm.created_at BETWEEN ? AND ?
                ORDER BY sm.created_at DESC
                {limit_clause}
                """,
                tuple(params),
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter registros de perdas: {e}")
            return []

    # ==================== NOVO: MÃƒÆ’Ã¢â‚¬Â°TODOS DE CÃƒÆ’Ã‚ÂLCULO DE PERDAS ====================
    
    def get_restock_records(self, start_dt, end_dt, limit=300):
        """Lista detalhada de reposiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes no perÃƒÆ’Ã‚Â­odo."""
        start = self._to_dt_str(start_dt, end=False)
        end = self._to_dt_str(end_dt, end=True)
        try:
            limit_clause = "LIMIT ?" if limit else ""
            params = [start, end]
            if limit:
                params.append(int(limit))
            self.cursor.execute(
                f"""
                SELECT sm.created_at,
                       COALESCE(p.description, pa.description) as product_name,
                       sm.qty,
                       sm.unit,
                       sm.unit_cost,
                       sm.total_cost,
                       sm.created_by,
                       sm.note
                FROM stock_movements sm
                LEFT JOIN products p ON sm.product_id = p.id
                LEFT JOIN products_archive pa ON sm.product_id = pa.id
                WHERE sm.applied = 1
                  AND sm.direction = 'IN'
                  AND sm.movement_type = 'RESTOCK'
                  AND sm.created_at BETWEEN ? AND ?
                ORDER BY sm.created_at DESC
                {limit_clause}
                """,
                tuple(params),
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter reposiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes: {e}")
            return []

    def calculate_loss_metrics(self, start_dt, end_dt):
        """
        Calcula todas as mÃƒÆ’Ã‚Â©tricas de perdas para um perÃƒÆ’Ã‚Â­odo
        
        Returns:
            Dict com todas as mÃƒÆ’Ã‚Â©tricas ou None em caso de erro
        """
        start = self._to_dt_str(start_dt, end=False)
        end = self._to_dt_str(end_dt, end=True)
        
        try:
            loss_types = list(LOSS_TYPES)
            placeholders = ",".join(["?"] * len(loss_types))
            
            # 1. Totais gerais
            self.cursor.execute(
                f"""
                SELECT 
                    COUNT(*) as loss_count,
                    COALESCE(SUM(total_cost), 0) as total_cost,
                    COALESCE(SUM(total_price), 0) as total_revenue_lost
                FROM stock_movements
                WHERE applied = 1
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                """,
                (*loss_types, start, end),
            )
            
            row = self.cursor.fetchone()
            loss_count = row[0]
            total_cost = float(row[1] or 0)
            total_revenue_lost = float(row[2] or 0)
            total_profit_lost = total_revenue_lost - total_cost
            avg_loss_value = total_cost / loss_count if loss_count > 0 else 0
            
            # 2. Total de vendas
            self.cursor.execute(
                """
                SELECT COALESCE(SUM(total_price), 0)
                FROM sales
                WHERE sale_date BETWEEN ? AND ?
                """,
                (start, end),
            )
            total_sales = float(self.cursor.fetchone()[0] or 0)
            
            # 3. Percentagem
            loss_percentage = (total_cost / total_sales * 100) if total_sales > 0 else 0
            
            # 4. Por tipo
            by_type = {}
            self.cursor.execute(
                f"""
                SELECT 
                    movement_type,
                    COUNT(*) as count,
                    COALESCE(SUM(total_cost), 0) as total_cost,
                    COALESCE(SUM(total_price), 0) as total_revenue_lost
                FROM stock_movements
                WHERE applied = 1
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                GROUP BY movement_type
                ORDER BY total_cost DESC
                """,
                (*loss_types, start, end),
            )
            
            for row in self.cursor.fetchall():
                movement_type = row[0]
                by_type[movement_type] = {
                    'count': row[1],
                    'total_cost': float(row[2]),
                    'total_revenue_lost': float(row[3]),
                    'total_profit_lost': float(row[3]) - float(row[2])
                }
            
            # 5. Por utilizador
            by_user = self.get_loss_by_user(start_dt, end_dt)
            
            # 6. Por produto (top 10)
            self.cursor.execute(
                f"""
                SELECT 
                    sm.product_id,
                    COALESCE(p.description, pa.description),
                    COUNT(*) as loss_count,
                    COALESCE(SUM(sm.total_cost), 0) as total_cost
                FROM stock_movements sm
                LEFT JOIN products p ON sm.product_id = p.id
                LEFT JOIN products_archive pa ON sm.product_id = pa.id
                WHERE sm.applied = 1
                  AND sm.direction = 'OUT'
                  AND sm.movement_type IN ({placeholders})
                  AND sm.created_at BETWEEN ? AND ?
                GROUP BY sm.product_id
                ORDER BY total_cost DESC
                LIMIT 10
                """,
                (*loss_types, start, end),
            )
            by_product = self.cursor.fetchall()
            
            return {
                'total_cost': total_cost,
                'total_revenue_lost': total_revenue_lost,
                'total_profit_lost': total_profit_lost,
                'loss_percentage': loss_percentage,
                'total_sales': total_sales,
                'loss_count': loss_count,
                'avg_loss_value': avg_loss_value,
                'by_type': by_type,
                'by_user': by_user,
                'by_product': by_product
            }
            
        except sqlite3.Error as e:
            print(f"Erro ao calcular mÃƒÆ’Ã‚Â©tricas de perdas: {e}")
            return None

    # ==================== NOVO: DETECÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O DE FRAUDE ====================
    
    def detect_fraud_patterns(self, days_lookback=30):
        """
        Detecta padrÃƒÆ’Ã‚Âµes suspeitos nos ÃƒÆ’Ã‚Âºltimos X dias
        
        Returns:
            Lista de alertas ordenados por severidade
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_lookback)
        
        alerts = []
        
        # 1. Utilizadores com perdas acima da mÃƒÆ’Ã‚Â©dia
        try:
            start = self._to_dt_str(start_date, end=False)
            end = self._to_dt_str(end_date, end=True)
            loss_types = list(LOSS_TYPES)
            placeholders = ",".join(["?"] * len(loss_types))
            
            self.cursor.execute(
                f"""
                SELECT 
                    created_by,
                    COUNT(*) as loss_count,
                    COALESCE(SUM(total_cost), 0) as total_cost
                FROM stock_movements
                WHERE applied = 1
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                  AND created_by IS NOT NULL
                GROUP BY created_by
                """,
                (*loss_types, start, end),
            )
            
            users_data = self.cursor.fetchall()
            
            if len(users_data) >= 2:
                costs = [row[2] for row in users_data]
                avg_cost = sum(costs) / len(costs)
                threshold = avg_cost * 1.5
                
                for user, count, cost in users_data:
                    if cost > threshold:
                        percentage_above = ((cost - avg_cost) / avg_cost) * 100
                        severity = 3 if percentage_above > 100 else (2 if percentage_above > 50 else 1)
                        
                        alerts.append({
                            'alert_type': 'HIGH_LOSS_USER',
                            'severity': severity,
                            'title': f'Utilizador com perdas elevadas: {user}',
                            'description': f'{user} registou perdas de {cost:.2f} MZN ({percentage_above:.1f}% acima da mÃƒÆ’Ã‚Â©dia)',
                            'related_user': user,
                            'related_product_id': None,
                            'data': {
                                'user': user,
                                'loss_count': count,
                                'total_cost': cost,
                                'average_cost': avg_cost,
                                'percentage_above': percentage_above
                            }
                        })
        except Exception as e:
            print(f"Erro ao detectar utilizadores com perdas elevadas: {e}")
        
        # 2. Produtos com perdas repetidas
        try:
            self.cursor.execute(
                f"""
                SELECT 
                    sm.product_id,
                    COALESCE(p.description, pa.description),
                    COUNT(*) as loss_count,
                    COALESCE(SUM(sm.total_cost), 0) as total_cost
                FROM stock_movements sm
                LEFT JOIN products p ON sm.product_id = p.id
                LEFT JOIN products_archive pa ON sm.product_id = pa.id
                WHERE sm.applied = 1
                  AND sm.direction = 'OUT'
                  AND sm.movement_type IN ({placeholders})
                  AND sm.created_at BETWEEN ? AND ?
                GROUP BY sm.product_id
                HAVING loss_count >= 3
                ORDER BY loss_count DESC
                """,
                (*loss_types, start, end),
            )
            
            for product_id, description, count, cost in self.cursor.fetchall():
                severity = 3 if count >= 10 else (2 if count >= 6 else 1)
                
                alerts.append({
                    'alert_type': 'REPEATED_PRODUCT_LOSS',
                    'severity': severity,
                    'title': f'Produto com perdas repetidas: {description}',
                    'description': f'{description} teve {count} registos de perda totalizando {cost:.2f} MZN',
                    'related_user': None,
                    'related_product_id': product_id,
                    'data': {
                        'product_id': product_id,
                        'product_name': description,
                        'loss_count': count,
                        'total_cost': cost
                    }
                })
        except Exception as e:
            print(f"Erro ao detectar produtos com perdas repetidas: {e}")
        
        # 3. Perdas fora do horÃƒÆ’Ã‚Â¡rio (22h-6h)
        try:
            self.cursor.execute(
                f"""
                SELECT 
                    id,
                    product_id,
                    created_by,
                    created_at,
                    movement_type,
                    total_cost
                FROM stock_movements
                WHERE applied = 1
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                  AND (
                      CAST(strftime('%H', created_at) AS INTEGER) >= 22
                      OR CAST(strftime('%H', created_at) AS INTEGER) < 6
                  )
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (*loss_types, start, end),
            )
            
            for row in self.cursor.fetchall():
                movement_id, product_id, user, created_at, movement_type, cost = row
                time_str = created_at.split()[1] if ' ' in created_at else 'N/A'
                
                alerts.append({
                    'alert_type': 'OFF_HOURS_LOSS',
                    'severity': 2,
                    'title': f'Perda fora do horÃƒÆ’Ã‚Â¡rio: {user}',
                    'description': f'Perda registada ÃƒÆ’Ã‚Â s {time_str} por {user} ({movement_type}, {cost:.2f} MZN)',
                    'related_user': user,
                    'related_product_id': product_id,
                    'data': {
                        'movement_id': movement_id,
                        'user': user,
                        'time': time_str,
                        'movement_type': movement_type,
                        'cost': cost
                    }
                })
        except Exception as e:
            print(f"Erro ao detectar perdas fora do horÃƒÆ’Ã‚Â¡rio: {e}")
        
        # 4. Perdas sem evidÃƒÆ’Ã‚Âªncia (acima de 50% do limite)
        try:
            high_value_threshold = LOSS_VALUE_LIMIT_MZN * 0.5
            
            self.cursor.execute(
                f"""
                SELECT 
                    id,
                    product_id,
                    created_by,
                    movement_type,
                    total_cost
                FROM stock_movements
                WHERE applied = 1
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                  AND total_cost >= ?
                  AND (evidence_path IS NULL OR evidence_path = '')
                ORDER BY total_cost DESC
                LIMIT 10
                """,
                (*loss_types, start, end, high_value_threshold),
            )
            
            for row in self.cursor.fetchall():
                movement_id, product_id, user, movement_type, cost = row
                
                alerts.append({
                    'alert_type': 'NO_EVIDENCE',
                    'severity': 2,
                    'title': f'Perda sem evidÃƒÆ’Ã‚Âªncia: {cost:.2f} MZN',
                    'description': f'{user} registou {movement_type} de {cost:.2f} MZN sem foto/comprovativo',
                    'related_user': user,
                    'related_product_id': product_id,
                    'data': {
                        'movement_id': movement_id,
                        'user': user,
                        'movement_type': movement_type,
                        'cost': cost
                    }
                })
        except Exception as e:
            print(f"Erro ao detectar perdas sem evidÃƒÆ’Ã‚Âªncia: {e}")
        
        return sorted(alerts, key=lambda x: x['severity'], reverse=True)

    # ==================== NOVO: APROVAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã¢â‚¬Â¢ES PENDENTES ====================
    
    def get_pending_approvals(self):
        """Obter todas as perdas pendentes de aprovaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"""
        try:
            loss_types = list(LOSS_TYPES)
            placeholders = ",".join(["?"] * len(loss_types))
            
            self.cursor.execute(
                f"""
                SELECT
                    sm.id,
                    sm.product_id,
                    COALESCE(p.description, pa.description),
                    sm.movement_type,
                    sm.qty,
                    sm.unit,
                    sm.total_cost,
                    sm.total_price,
                    sm.reason,
                    sm.note,
                    sm.evidence_path,
                    sm.created_at,
                    sm.created_by,
                    sm.created_role
                FROM stock_movements sm
                LEFT JOIN products p ON sm.product_id = p.id
                LEFT JOIN products_archive pa ON sm.product_id = pa.id
                WHERE sm.approval_status = 'PENDING'
                  AND sm.direction = 'OUT'
                  AND sm.movement_type IN ({placeholders})
                ORDER BY sm.created_at DESC
                """,
                tuple(loss_types),
            )
            
            return self.cursor.fetchall()
            
        except sqlite3.Error as e:
            print(f"Erro ao obter aprovaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes pendentes: {e}")
            return []

    @staticmethod
    def _normalize_pack_sale_fields(is_sold_by_weight, units_per_package, allow_pack_sale):
        """Normaliza e valida configuracao de venda por embalagem."""
        if is_sold_by_weight:
            return None, 0

        allow_flag = 1 if bool(allow_pack_sale) else 0
        if not allow_flag:
            return None, 0

        if units_per_package in (None, ""):
            raise ValueError("units_per_package must be >= 2 when allow_pack_sale is enabled")

        try:
            units = int(float(units_per_package))
        except (TypeError, ValueError):
            raise ValueError("units_per_package must be an integer value")

        if units < 2:
            raise ValueError("units_per_package must be >= 2 when allow_pack_sale is enabled")

        return units, 1

    def _insert_product_row(
        self,
        description,
        category,
        existing_stock,
        sold_stock,
        sale_price,
        total_purchase_price,
        unit_purchase_price,
        profit_per_unit,
        barcode,
        expiry_date,
        is_sold_by_weight,
        package_quantity,
        units_per_package,
        allow_pack_sale,
        vat_rule_code,
        date_added=None,
    ):
        self.cursor.execute(
            """
            INSERT INTO products (
                description, category, existing_stock, sold_stock, sale_price,
                total_purchase_price, unit_purchase_price, profit_per_unit, barcode,
                expiry_date, date_added, is_sold_by_weight, package_quantity,
                units_per_package, allow_pack_sale, vat_rule_code, owner_username
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                description,
                category,
                float(existing_stock),
                float(sold_stock),
                float(sale_price),
                float(total_purchase_price),
                float(unit_purchase_price),
                float(profit_per_unit),
                barcode,
                expiry_date,
                date_added or self._now_str(),
                1 if is_sold_by_weight else 0,
                package_quantity,
                units_per_package,
                allow_pack_sale,
                vat_rule_code,
                self._owner_value(),
            ),
        )
        product_id = self.cursor.lastrowid
        sku = self._build_sku(product_id, description)
        self.cursor.execute(
            "UPDATE products SET sku = ? WHERE id = ?",
            (sku, product_id),
        )
        return product_id

    def add_product(
        self,
        description,
        category,
        existing_stock,
        sold_stock,
        sale_price,
        total_purchase_price,
        unit_purchase_price,
        barcode=None,
        expiry_date=None,
        is_sold_by_weight=False,
        package_quantity=None,
        units_per_package=None,
        allow_pack_sale=False,
        vat_rule_code=DEFAULT_VAT_RULE_CODE,
    ):
        """Adicionar um novo produto ao banco de dados"""
        try:
            incoming_stock = float(existing_stock)
            sale_price = float(sale_price)
            total_purchase_price = float(total_purchase_price)
            unit_purchase_price = float(unit_purchase_price)
            profit_per_unit = sale_price - unit_purchase_price
            date_added = self._now_str()
            normalized_barcode = self._normalize_barcode_value(barcode)
            normalized_expiry = self._normalize_expiry_value(expiry_date)
            normalized_vat_rule = self._normalize_vat_rule_code(vat_rule_code)
            normalized_units, normalized_allow = self._normalize_pack_sale_fields(
                is_sold_by_weight,
                units_per_package,
                allow_pack_sale,
            )

            existing_batch = self._find_existing_batch(normalized_barcode, normalized_expiry)
            if existing_batch:
                product_id, current_stock, current_sold_stock, current_unit_cost = existing_batch
                current_stock = float(current_stock or 0.0)
                current_sold_stock = float(current_sold_stock or 0.0)
                current_unit_cost = float(current_unit_cost or 0.0)
                merged_stock = current_stock + incoming_stock

                if merged_stock <= 0 or current_stock <= 0:
                    merged_unit_cost = unit_purchase_price
                else:
                    merged_unit_cost = (
                        (current_stock * current_unit_cost) + (incoming_stock * unit_purchase_price)
                    ) / merged_stock

                merged_total_purchase = merged_unit_cost * merged_stock
                merged_profit_per_unit = sale_price - merged_unit_cost

                self.cursor.execute(
                    """
                    UPDATE products
                    SET description = ?,
                        category = ?,
                        existing_stock = ?,
                        sold_stock = ?,
                        sale_price = ?,
                        total_purchase_price = ?,
                        unit_purchase_price = ?,
                        profit_per_unit = ?,
                        barcode = ?,
                        expiry_date = ?,
                        is_sold_by_weight = ?,
                        package_quantity = ?,
                        units_per_package = ?,
                        allow_pack_sale = ?,
                        vat_rule_code = ?
                    WHERE id = ?
                    """,
                    (
                        description,
                        category,
                        merged_stock,
                        current_sold_stock,
                        sale_price,
                        merged_total_purchase,
                        merged_unit_cost,
                        merged_profit_per_unit,
                        normalized_barcode,
                        normalized_expiry,
                        1 if is_sold_by_weight else 0,
                        package_quantity,
                        normalized_units,
                        normalized_allow,
                        normalized_vat_rule,
                        product_id,
                    ),
                )
                self.conn.commit()
                tipo = "KG" if is_sold_by_weight else "UNIDADE"
                print(f"Lote existente fundido com sucesso! ID: {product_id} | Tipo: {tipo}")
                return product_id

            product_id = self._insert_product_row(
                description=description,
                category=category,
                existing_stock=incoming_stock,
                sold_stock=float(sold_stock),
                sale_price=sale_price,
                total_purchase_price=total_purchase_price,
                unit_purchase_price=unit_purchase_price,
                profit_per_unit=profit_per_unit,
                barcode=normalized_barcode,
                expiry_date=normalized_expiry,
                is_sold_by_weight=is_sold_by_weight,
                package_quantity=package_quantity,
                units_per_package=normalized_units,
                allow_pack_sale=normalized_allow,
                vat_rule_code=normalized_vat_rule,
                date_added=date_added,
            )
            self.conn.commit()
            tipo = "KG" if is_sold_by_weight else "UNIDADE"
            print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Produto adicionado com sucesso! ID: {product_id} | Tipo: {tipo}")
            
            return product_id
            
        except (sqlite3.Error, ValueError) as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao adicionar produto: {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
            return None
    
    def update_product(
        self,
        id,
        description,
        category,
        existing_stock,
        sold_stock,
        sale_price,
        total_purchase_price,
        unit_purchase_price,
        barcode=None,
        expiry_date=None,
        is_sold_by_weight=False,
        package_quantity=None,
        units_per_package=None,
        allow_pack_sale=False,
        vat_rule_code=DEFAULT_VAT_RULE_CODE,
    ):
        """Atualizar produto existente"""
        return self._update_product_impl(
            id=id,
            description=description,
            category=category,
            existing_stock=existing_stock,
            sold_stock=sold_stock,
            sale_price=sale_price,
            total_purchase_price=total_purchase_price,
            unit_purchase_price=unit_purchase_price,
            barcode=barcode,
            expiry_date=expiry_date,
            is_sold_by_weight=is_sold_by_weight,
            package_quantity=package_quantity,
            units_per_package=units_per_package,
            allow_pack_sale=allow_pack_sale,
            vat_rule_code=vat_rule_code,
        )
        try:
            sale_price = float(sale_price)
            total_purchase_price = float(total_purchase_price)
            unit_purchase_price = float(unit_purchase_price)
            profit_per_unit = sale_price - unit_purchase_price
            normalized_barcode = self._normalize_barcode_value(barcode)
            normalized_expiry = self._normalize_expiry_value(expiry_date)
            normalized_vat_rule = self._normalize_vat_rule_code(vat_rule_code)
            normalized_units, normalized_allow = self._normalize_pack_sale_fields(
                is_sold_by_weight,
                units_per_package,
                allow_pack_sale,
            )
            if self._find_existing_batch(normalized_barcode, normalized_expiry, exclude_id=id):
                raise ValueError(
                    "Ja existe um lote com este codigo de barras e validade. Use a reposicao "
                    "para somar stock ou informe uma validade diferente."
                )
            self.cursor.execute(
                """UPDATE products SET 
                   description = ?, category = ?, existing_stock = ?, sold_stock = ?, 
                   sale_price = ?, total_purchase_price = ?, unit_purchase_price = ?, 
                   profit_per_unit = ?, barcode = ?, expiry_date = ?, is_sold_by_weight = ?, package_quantity = ?,
                   units_per_package = ?, allow_pack_sale = ?, vat_rule_code = ?
                   WHERE id = ?""", 
                (description, category, float(existing_stock), float(sold_stock), sale_price, 
                 total_purchase_price, unit_purchase_price, profit_per_unit, normalized_barcode, normalized_expiry,
                 1 if is_sold_by_weight else 0, package_quantity, normalized_units, normalized_allow, normalized_vat_rule, id)
            )
            self.conn.commit()
            
            tipo = "KG" if is_sold_by_weight else "UNIDADE"
            print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Produto {id} atualizado com sucesso! | Tipo: {tipo}")
            
        except (sqlite3.Error, ValueError) as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao atualizar produto: {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
    
    def delete_product(self, id, username=None):
        """Excluir produto (hard delete) e arquivar histÃƒÆ’Ã‚Â³rico"""
        try:
            user = username or "SYSTEM"
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                f"""
                SELECT id, description, category, existing_stock, sold_stock, sale_price,
                       total_purchase_price, unit_purchase_price, profit_per_unit, barcode,
                       expiry_date, date_added, is_sold_by_weight, package_quantity,
                       status, status_source, status_reason, status_updated_at, status_updated_by,
                       sku, units_per_package, allow_pack_sale, vat_rule_code, owner_username
                FROM products WHERE id = ?
                {scope_sql}
                """,
                (id, *scope_params),
            )
            row = self.cursor.fetchone()
            if not row:
                return False

            deleted_at = self._now_str()
            self.cursor.execute(
                """
                INSERT OR REPLACE INTO products_archive (
                    id, description, category, existing_stock, sold_stock, sale_price,
                    total_purchase_price, unit_purchase_price, profit_per_unit, barcode,
                    expiry_date, date_added, is_sold_by_weight, package_quantity,
                    status, status_source, status_reason, status_updated_at, status_updated_by,
                    sku, units_per_package, allow_pack_sale, vat_rule_code, owner_username,
                    deleted_at, deleted_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*row, deleted_at, user),
            )

            self.cursor.execute("DELETE FROM products WHERE id = ?", (id,))
            self.conn.commit()
            print(f"Produto {id} eliminado e arquivado com sucesso!")
            return True
        except sqlite3.Error as e:
            print(f"Erro ao eliminar produto: {e}")
            self.conn.rollback()
            return False

    def get_all_products(self):
        """Obter todos os produtos - COM SUPORTE A KG"""
        return self.get_all_products_page(limit=None, offset=0)

    def _readonly_fetchall(self, query, params=()):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, tuple(params))
            return cur.fetchall()

    def get_all_products_page(
        self,
        search_text="",
        category=None,
        sold_by_weight=None,
        limit=120,
        offset=0,
    ):
        """Lista paginada de produtos para a tela admin."""
        started_at = perf_counter()
        try:
            query = """
                SELECT
                    p.id,
                    p.description,
                    p.existing_stock,
                    p.sold_stock,
                    p.sale_price,
                    p.total_purchase_price,
                    p.unit_purchase_price,
                    p.profit_per_unit,
                    (p.profit_per_unit * p.sold_stock) as total_profit,
                    CASE
                        WHEN p.sold_stock > 0 THEN (p.profit_per_unit * p.sold_stock * 100) / (p.unit_purchase_price * p.sold_stock)
                        ELSE 0
                    END as profit_percentage,
                    (p.sale_price - p.unit_purchase_price) / p.unit_purchase_price * 100 as price_percentage,
                    p.category,
                    p.barcode,
                    p.expiry_date,
                    p.date_added,
                    p.is_sold_by_weight,
                    p.status,
                    p.status_source,
                    p.status_reason,
                    p.status_updated_at,
                    p.status_updated_by,
                    p.package_quantity,
                    p.sku,
                    p.units_per_package,
                    p.allow_pack_sale,
                    p.vat_rule_code
                FROM products p
                WHERE 1=1
            """
            params = []
            scope_sql, scope_params = self._owner_filter("p")
            query += scope_sql
            params.extend(scope_params)
            search = (search_text or "").strip().lower()
            if search:
                query += """
                    AND (
                        CAST(p.id AS TEXT) LIKE ?
                        OR LOWER(COALESCE(p.description, '')) LIKE ?
                        OR LOWER(COALESCE(p.category, '')) LIKE ?
                        OR LOWER(COALESCE(p.barcode, '')) LIKE ?
                        OR LOWER(COALESCE(p.sku, '')) LIKE ?
                    )
                """
                like = f"%{search}%"
                params.extend([like, like, like, like, like])

            if category and category not in ("Todas", "Todas as Categorias"):
                query += " AND p.category = ?"
                params.append(category)

            if sold_by_weight is not None:
                query += " AND p.is_sold_by_weight = ?"
                params.append(1 if bool(sold_by_weight) else 0)

            query += " ORDER BY p.id DESC"
            if limit:
                query += " LIMIT ? OFFSET ?"
                params.extend([int(limit), max(0, int(offset or 0))])

            rows = self._readonly_fetchall(query, params)
            perf_log(
                "db.get_all_products_page",
                started_at,
                f"rows={len(rows)} limit={limit} offset={offset}",
            )
            return rows
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos paginados: {e}")
            return []

    def get_product(self, id):
        """Obter um produto especÃƒÆ’Ã‚Â­fico"""
        try:
            scope_sql, scope_params = self._owner_filter("p")
            self.cursor.execute(""" 
                SELECT 
                    p.id, p.description, p.existing_stock, p.sold_stock, 
                    p.sale_price, p.total_purchase_price, p.unit_purchase_price, 
                    p.profit_per_unit,
                    (p.profit_per_unit * p.sold_stock) as total_profit,
                    CASE 
                        WHEN p.sold_stock > 0 THEN (p.profit_per_unit * p.sold_stock * 100) / (p.unit_purchase_price * p.sold_stock)
                        ELSE 0 
                    END as profit_percentage,
                    (p.sale_price - p.unit_purchase_price) / p.unit_purchase_price * 100 as price_percentage,
                    p.category,
                    p.barcode,
                    p.expiry_date,
                    p.date_added,
                    p.is_sold_by_weight,
                    p.status,
                    p.status_source,
                    p.status_reason,
                    p.status_updated_at,
                    p.status_updated_by,
                    p.package_quantity,
                    p.sku,
                    p.units_per_package,
                    p.allow_pack_sale,
                    p.vat_rule_code
                FROM products p
                WHERE p.id = ?""" + scope_sql, (id, *scope_params))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao obter produto: {e}")
            return None
    
    @classmethod
    def _group_products_for_sale_catalog(cls, rows):
        grouped = {}
        ordered_keys = []
        for row in rows or []:
            if not row:
                continue
            catalog_key = cls._catalog_identity_from_sale_row(row)
            stock_value = float(row[2] or 0.0)
            current = grouped.get(catalog_key)
            if current is None:
                grouped[catalog_key] = {
                    "id": row[0],
                    "description": row[1],
                    "stock": stock_value,
                    "sale_price": row[3],
                    "barcode": row[4] if len(row) > 4 else None,
                    "is_sold_by_weight": bool(row[5]) if len(row) > 5 else False,
                    "expiry_date": row[6] if len(row) > 6 else None,
                    "status": row[7] if len(row) > 7 else None,
                    "units_per_package": row[8] if len(row) > 8 else None,
                    "allow_pack_sale": bool(row[9]) if len(row) > 9 else False,
                    "vat_rule_code": row[10] if len(row) > 10 else DEFAULT_VAT_RULE_CODE,
                    "catalog_key": catalog_key,
                    "lot_count": 1,
                }
                ordered_keys.append(catalog_key)
                continue

            current["stock"] += stock_value
            current["lot_count"] += 1

        result = []
        for key in ordered_keys:
            item = grouped[key]
            result.append(
                (
                    item["id"],
                    item["description"],
                    item["stock"],
                    item["sale_price"],
                    item["barcode"],
                    1 if item["is_sold_by_weight"] else 0,
                    item["expiry_date"],
                    item["status"],
                    item["units_per_package"],
                    1 if item["allow_pack_sale"] else 0,
                    item["vat_rule_code"],
                    item["catalog_key"],
                    item["lot_count"],
                )
            )
        return result

    @staticmethod
    def _catalog_identity_from_sale_row(row):
        barcode = str(row[4] if len(row) > 4 and row[4] is not None else "").strip().lower()
        if barcode:
            return f"bc:{barcode}"
        description = " ".join(str(row[1] if len(row) > 1 and row[1] is not None else "").split()).lower()
        if description:
            sale_price = round(float(row[3] or 0.0), 4)
            is_weight = 1 if (len(row) > 5 and bool(row[5])) else 0
            units_per_package = (
                int(float(row[8] or 0))
                if len(row) > 8 and row[8] not in (None, "")
                else 0
            )
            allow_pack_sale = 1 if (len(row) > 9 and bool(row[9])) else 0
            vat_rule = (
                str(row[10] or DEFAULT_VAT_RULE_CODE).strip().upper()
                if len(row) > 10
                else DEFAULT_VAT_RULE_CODE
            )
            return (
                f"desc:{description}|w:{is_weight}|p:{sale_price:.4f}|"
                f"u:{units_per_package}|a:{allow_pack_sale}|v:{vat_rule}"
            )
        return f"id:{int(row[0])}"

    def get_products_for_sale(self):
        """Obter produtos disponiveis para venda."""
        return self.get_products_for_sale_page(limit=None, offset=0, refresh_statuses=True)

    def get_products_for_sale_page(
        self,
        search_text="",
        limit=200,
        offset=0,
        refresh_statuses=False,
    ):
        """Lista paginada para tela de vendas."""
        started_at = perf_counter()
        try:
            if refresh_statuses:
                self.refresh_auto_statuses()

            query = """
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight,
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code
                FROM products
                WHERE existing_stock > 0
                  AND status IN ('ATIVO', 'PERTO_DO_PRAZO')
                  AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))
            """
            params = []
            scope_sql, scope_params = self._owner_filter()
            query += scope_sql
            params.extend(scope_params)
            search = (search_text or "").strip().lower()
            if search:
                query += """
                  AND (
                    CAST(id AS TEXT) LIKE ?
                    OR LOWER(COALESCE(description, '')) LIKE ?
                    OR LOWER(COALESCE(barcode, '')) LIKE ?
                  )
                """
                like = f"%{search}%"
                params.extend([like, like, like])

            query += (
                f" ORDER BY LOWER(COALESCE(description, '')) ASC, {self._expiry_order_clause()}"
            )
            if limit:
                query += " LIMIT ? OFFSET ?"
                params.extend([int(limit), max(0, int(offset or 0))])

            rows = self._readonly_fetchall(query, params)
            perf_log(
                "db.get_products_for_sale_page",
                started_at,
                f"rows={len(rows)} limit={limit} offset={offset}",
            )
            return rows
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos para venda: {e}")
            return []

    def get_products_for_sale_catalog_page(
        self,
        search_text="",
        limit=200,
        offset=0,
        refresh_statuses=False,
    ):
        """Lista paginada agregando lotes irmaos para a tela de vendas."""
        started_at = perf_counter()
        try:
            rows = self.get_products_for_sale_page(
                search_text=search_text,
                limit=None,
                offset=0,
                refresh_statuses=refresh_statuses,
            ) or []
            grouped_rows = self._group_products_for_sale_catalog(rows)
            off = max(0, int(offset or 0))
            if limit:
                paged_rows = grouped_rows[off:off + int(limit)]
            else:
                paged_rows = grouped_rows[off:]
            perf_log(
                "db.get_products_for_sale_catalog_page",
                started_at,
                f"rows={len(paged_rows)} total={len(grouped_rows)} limit={limit} offset={offset}",
            )
            return paged_rows
        except sqlite3.Error as e:
            print(f"Erro ao obter catalogo de produtos para venda: {e}")
            return []
        except Exception as e:
            print(f"Erro geral ao obter catalogo de produtos para venda: {e}")
            return []

    def get_products_for_sale_ids(self, product_ids):
        """Obtem snapshot de produtos por IDs para validacao de stock."""
        try:
            ids = [int(pid) for pid in (product_ids or []) if pid is not None]
            if not ids:
                return []
            placeholders = ",".join(["?"] * len(ids))
            query = f"""
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight,
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code
                FROM products
                WHERE id IN ({placeholders})
            """
            scope_sql, scope_params = self._owner_filter()
            query += scope_sql
            return self._readonly_fetchall(query, [*ids, *scope_params])
        except Exception as e:
            print(f"Erro ao obter produtos por IDs: {e}")
            return []

    def get_products_by_weight(self):
        """Obter apenas produtos vendidos por peso (kg)"""
        try:
            scope_sql, scope_params = self._owner_filter("p")
            self.cursor.execute(f""" 
                SELECT 
                    p.id, p.description, p.existing_stock, p.sold_stock, 
                    p.sale_price, p.total_purchase_price, p.unit_purchase_price, 
                    p.profit_per_unit,
                    (p.profit_per_unit * p.sold_stock) as total_profit,
                    CASE 
                        WHEN p.sold_stock > 0 THEN (p.profit_per_unit * p.sold_stock * 100) / (p.unit_purchase_price * p.sold_stock)
                        ELSE 0 
                    END as profit_percentage,
                    (p.sale_price - p.unit_purchase_price) / p.unit_purchase_price * 100 as price_percentage,
                    p.category,
                    p.barcode,
                    p.expiry_date,
                    p.date_added,
                    p.is_sold_by_weight,
                    p.status,
                    p.status_source,
                    p.status_reason,
                    p.status_updated_at,
                    p.status_updated_by,
                    p.package_quantity,
                    p.sku,
                    p.units_per_package,
                    p.allow_pack_sale,
                    p.vat_rule_code
                FROM products p
                WHERE p.is_sold_by_weight = 1
                {scope_sql}
                ORDER BY p.description ASC
            """, tuple(scope_params))
            results = self.cursor.fetchall()
            print(f"ÃƒÂ¢Ã…Â¡Ã¢â‚¬â€œÃƒÂ¯Ã‚Â¸Ã‚Â Produtos vendidos por KG: {len(results)}")
            return results
            
        except sqlite3.Error as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao obter produtos por peso: {e}")
            return []
    
    def get_product_by_barcode(self, barcode):
        """Buscar produto pelo cÃƒÆ’Ã‚Â³digo de barras - VERSÃƒÆ’Ã†â€™O ROBUSTA COM SUPORTE A KG"""
        try:
            self.refresh_auto_statuses()
            barcode_clean = self._normalize_barcode_value(barcode)
            
            print(f"\nÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â DB: Buscando cÃƒÆ’Ã‚Â³digo de barras...")
            print(f"   CÃƒÆ’Ã‚Â³digo recebido: '{barcode}'")
            print(f"   CÃƒÆ’Ã‚Â³digo limpo: '{barcode_clean or ''}'")
            
            if not barcode_clean:
                print(f"   ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â CÃƒÆ’Ã‚Â³digo vazio apÃƒÆ’Ã‚Â³s limpeza!")
                return None

            self.cursor.execute(
                f"""
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight,
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code
                FROM products
                WHERE barcode IS NOT NULL
                  AND TRIM(barcode) != ''
                  AND LOWER(TRIM(barcode)) = LOWER(TRIM(?))
                  AND existing_stock > 0
                  AND status IN ('ATIVO', 'PERTO_DO_PRAZO')
                  AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))
                  {self._owner_filter()[0]}
                ORDER BY {self._expiry_order_clause()}
                LIMIT 1
                """,
                (barcode_clean, *self._owner_filter()[1]),
            )
            result = self.cursor.fetchone()

            if result:
                tipo = "ÃƒÂ¢Ã…Â¡Ã¢â‚¬â€œÃƒÂ¯Ã‚Â¸Ã‚Â KG" if result[5] else "ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‚Â¦ UNIDADE"
                print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Encontrado com FEFO!")
                print(f"   ID: {result[0]} | Nome: {result[1]} | Tipo: {tipo}")
                return result
            
            print(f"\nÃƒÂ¢Ã‚ÂÃ…â€™ CÃƒÆ’Ã‚Â³digo '{barcode_clean}' NÃƒÆ’Ã†â€™O ENCONTRADO no banco de dados")
            
            # Listar cÃƒÆ’Ã‚Â³digos disponÃƒÆ’Ã‚Â­veis para debug
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                "SELECT barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''" + scope_sql,
                tuple(scope_params),
            )
            available_barcodes = self.cursor.fetchall()
            if available_barcodes:
                print(f"\nÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹ CÃƒÆ’Ã‚Â³digos disponÃƒÆ’Ã‚Â­veis no banco ({len(available_barcodes)}):")
                for bc in available_barcodes[:5]:  # Mostrar apenas 5 primeiros
                    print(f"   - '{bc[0]}'")
            
            return None
            
        except sqlite3.Error as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro SQL ao buscar cÃƒÆ’Ã‚Â³digo de barras: {e}")
            import traceback
            traceback.print_exc()
            return None
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro geral ao buscar cÃƒÆ’Ã‚Â³digo de barras: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_products_by_barcode(self, barcode, include_expired=False, include_zero_stock=False):
        """Lista lotes irmaos pelo barcode em ordem FEFO."""
        try:
            barcode_clean = self._normalize_barcode_value(barcode)
            if not barcode_clean:
                return []

            query = f"""
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight,
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code
                FROM products
                WHERE barcode IS NOT NULL
                  AND TRIM(barcode) != ''
                  AND LOWER(TRIM(barcode)) = LOWER(TRIM(?))
            """
            params = [barcode_clean]
            scope_sql, scope_params = self._owner_filter()
            query += scope_sql
            params.extend(scope_params)

            if not include_zero_stock:
                query += " AND existing_stock > 0"

            if not include_expired:
                query += " AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))"

            query += f" ORDER BY {self._expiry_order_clause()}"
            self.cursor.execute(query, tuple(params))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao listar produtos por codigo de barras: {e}")
            return []

    # ==================== MÃƒÆ’Ã¢â‚¬Â°TODOS PARA VENDAS ====================
    
    def find_product_by_barcode_fast(self, barcode):
        """Consulta read-only otimizada para leituras frequentes na tela de vendas."""
        try:
            barcode_clean = self._normalize_barcode_value(barcode)
            if not barcode_clean:
                return None

            rows = self._readonly_fetchall(
                f"""
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight,
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code
                FROM products
                WHERE barcode IS NOT NULL
                  AND TRIM(barcode) != ''
                  AND existing_stock > 0
                  AND status IN ('ATIVO', 'PERTO_DO_PRAZO')
                  AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))
                  AND LOWER(TRIM(barcode)) = LOWER(TRIM(?))
                  {self._owner_filter()[0]}
                ORDER BY {self._expiry_order_clause()}
                LIMIT 1
                """,
                (barcode_clean, *self._owner_filter()[1]),
            )
            return rows[0] if rows else None
        except sqlite3.Error as e:
            print(f"Erro SQL ao buscar codigo de barras: {e}")
            return None
        except Exception as e:
            print(f"Erro geral ao buscar codigo de barras: {e}")
            return None

    def add_sale(
        self,
        product_id,
        quantity,
        sale_price,
        username=None,
        role=None,
        terminal_id=None,
        is_promotional=False,
        vat_rule_code=None,
    ):
        """Adicionar nova venda - SUPORTA QUANTIDADES DECIMAIS (KG) - ATUALIZA ESTOQUE"""
        try:
            quantity = float(quantity)
            promo_flag = 1 if is_promotional else 0
            sale_date = self._now_str()
            created_by = username or "SYSTEM"
            created_role = role or "manager"

            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(f"""
                SELECT description, existing_stock, sold_stock, is_sold_by_weight, unit_purchase_price, vat_rule_code
                FROM products
                WHERE id = ?
                {scope_sql}
            """, (product_id, *scope_params))

            product_info = self.cursor.fetchone()

            if not product_info:
                print(f"Erro: Produto ID {product_id} nao encontrado!")
                return None

            product_name = product_info[0]
            stock_before = product_info[1]
            sold_before = product_info[2]
            is_weight = product_info[3]
            unit_purchase_price = product_info[4] or 0
            product_vat_rule = self._normalize_vat_rule_code(product_info[5])
            normalized_vat_rule = self._normalize_vat_rule_code(vat_rule_code or product_vat_rule)
            vat_data = self.calculate_vat_breakdown(
                sale_price,
                quantity=quantity,
                vat_rule_code=normalized_vat_rule,
                reference_date=sale_date,
            )
            total_price = float(vat_data["gross_total"])

            if stock_before < quantity:
                print(f"Erro: Estoque insuficiente! Disponivel: {stock_before:.2f}, Solicitado: {quantity:.2f}")
                return None

            tipo = "kg" if is_weight else "un"

            movement_id = self._record_stock_movement_tx(
                self.cursor,
                product_id,
                "SALE",
                quantity,
                "OUT",
                reason="Venda",
                created_by=created_by,
                created_role=created_role,
                terminal_id=terminal_id,
                unit_cost=unit_purchase_price,
                unit_price=sale_price,
                approval_status="APPROVED",
                approved_by=created_by,
                approved_at=sale_date,
                apply_stock=True,
            )

            if not movement_id:
                self.conn.rollback()
                return None

            self.cursor.execute("""
                INSERT INTO sales (
                    product_id,
                    quantity,
                    sale_price,
                    total_price,
                    is_promotional,
                    sale_date,
                    created_by,
                    created_role,
                    terminal_id,
                    vat_rule_code,
                    vat_label,
                    vat_rate_percent,
                    vat_taxable_ratio,
                    net_total,
                    vat_amount,
                    gross_total,
                    owner_username
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_id,
                quantity,
                sale_price,
                total_price,
                promo_flag,
                sale_date,
                created_by,
                created_role,
                terminal_id,
                normalized_vat_rule,
                vat_data["rule_label"],
                vat_data["rate_percent"],
                vat_data["taxable_ratio"],
                vat_data["net_total"],
                vat_data["vat_amount"],
                vat_data["gross_total"],
                self._owner_value(created_by),
            ))
            sale_id = self.cursor.lastrowid

            self.conn.commit()

            self.cursor.execute("SELECT existing_stock, sold_stock FROM products WHERE id = ?", (product_id,))
            after_info = self.cursor.fetchone()
            stock_after = after_info[0]
            sold_after = after_info[1]

            if should_log_debug():
                print("")
                print("=" * 70)
                print("VENDA REGISTRADA COM SUCESSO!")
                print("=" * 70)
                print(f"   Produto: {product_name}")
                print(f"   Quantidade: {quantity:.2f} {tipo}")
                print(f"   Preco unitario: {sale_price:.2f} MZN")
                print(f"   Total: {total_price:.2f} MZN")
                print(
                    f"   IVA: {vat_data['short_label']} | Base liquida: "
                    f"{vat_data['net_total']:.2f} MZN | Imposto: {vat_data['vat_amount']:.2f} MZN"
                )
                print(f"   Base de preco: {'PROMOCIONAL' if promo_flag else 'NORMAL'}")
                print("   ---")
                print(f"   Estoque ANTES: {stock_before:.2f} {tipo}")
                print(f"   Estoque DEPOIS: {stock_after:.2f} {tipo} (- {quantity:.2f})")
                print(f"   Total vendido: {sold_after:.2f} {tipo} (+ {quantity:.2f})")
                print("=" * 70)
                print("")

            return sale_id

        except sqlite3.Error as e:
            print(f"Erro SQL ao adicionar venda: {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
            return None
        except Exception as e:
            print(f"Erro geral ao adicionar venda: {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
            return None

    def _get_sale_returned_qty_tx(self, cursor, sale_id):
        cursor.execute(
            "SELECT COALESCE(SUM(returned_qty), 0) FROM sales_returns WHERE sale_id = ?",
            (sale_id,),
        )
        row = cursor.fetchone()
        return float(row[0] or 0.0) if row else 0.0

    def _query_sales_with_returns(self, where_clause="", params=(), limit=None, offset=0):
        query = """
            SELECT
                s.id,
                COALESCE(p.description, pa.description) AS product_name,
                s.quantity,
                s.sale_price,
                s.total_price,
                s.sale_date,
                COALESCE(sr.returned_qty, 0) AS returned_qty,
                CASE
                    WHEN (s.quantity - COALESCE(sr.returned_qty, 0)) > 0
                        THEN (s.quantity - COALESCE(sr.returned_qty, 0))
                    ELSE 0
                END AS available_qty,
                s.created_by,
                s.created_role,
                COALESCE(s.is_promotional, 0) AS is_promotional,
                s.product_id
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.id
            LEFT JOIN products_archive pa ON s.product_id = pa.id
            LEFT JOIN (
                SELECT sale_id, COALESCE(SUM(returned_qty), 0) AS returned_qty
                FROM sales_returns
                GROUP BY sale_id
            ) sr ON sr.sale_id = s.id
        """
        scope_sql, scope_params = self._owner_filter("s")
        if where_clause:
            query += f" WHERE {where_clause}{scope_sql}"
            final_params = [*(params or ()), *scope_params]
        else:
            query += f" WHERE 1=1{scope_sql}"
            final_params = list(scope_params)
        query += " ORDER BY s.sale_date DESC, s.id DESC"
        if limit:
            query += " LIMIT ? OFFSET ?"
            final_params.extend([int(limit), max(0, int(offset or 0))])
        self.cursor.execute(query, tuple(final_params))
        return self.cursor.fetchall()

    def get_sale_details(self, sale_id):
        try:
            rows = self._query_sales_with_returns("s.id = ?", (sale_id,))
            if not rows:
                return None
            return rows[0]
        except Exception as e:
            print(f"Erro ao obter detalhes da venda: {e}")
            return None

    def refund_sale_item(self, sale_id, quantity, reason="", username=None, role=None, terminal_id=None):
        """Registra estorno/devolucao parcial ou total de uma venda."""
        try:
            sale_id = int(sale_id)
            quantity = float(quantity)
            if quantity <= 0:
                return {"ok": False, "message": "Quantidade invalida"}

            self.cursor.execute(
                """
                SELECT id, product_id, quantity, sale_price
                FROM sales
                WHERE id = ?
                """,
                (sale_id,),
            )
            sale = self.cursor.fetchone()
            if not sale:
                return {"ok": False, "message": "Venda nao encontrada"}

            _sid, product_id, sold_qty, sale_price = sale
            sold_qty = float(sold_qty or 0)
            sale_price = float(sale_price or 0)

            already_returned = self._get_sale_returned_qty_tx(self.cursor, sale_id)
            available_qty = max(0.0, sold_qty - already_returned)
            if available_qty <= 0:
                return {"ok": False, "message": "Venda ja estornada por completo"}
            if quantity > (available_qty + 1e-9):
                return {
                    "ok": False,
                    "message": f"Quantidade acima do disponivel para estorno ({available_qty:.2f})",
                }

            created_by = username or "SYSTEM"
            created_role = role or "manager"
            reason = (reason or "").strip() or "Devolucao de venda"
            total_refund = quantity * sale_price
            now_str = self._now_str()

            movement_id = self._record_stock_movement_tx(
                self.cursor,
                product_id,
                "RETURN",
                quantity,
                "IN",
                reason=reason,
                note=f"Estorno da venda #{sale_id}",
                reference_table="sales",
                reference_id=sale_id,
                created_by=created_by,
                created_role=created_role,
                terminal_id=terminal_id,
                unit_price=sale_price,
                approval_status="APPROVED",
                approved_by=created_by,
                approved_at=now_str,
                apply_stock=True,
            )
            if not movement_id:
                self.conn.rollback()
                return {"ok": False, "message": "Falha ao aplicar retorno de stock"}

            self.cursor.execute(
                """
                INSERT INTO sales_returns (
                    sale_id,
                    product_id,
                    returned_qty,
                    sale_price,
                    total_refund,
                    reason,
                    created_at,
                    created_by,
                    created_role,
                    terminal_id,
                    stock_movement_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sale_id,
                    product_id,
                    quantity,
                    sale_price,
                    total_refund,
                    reason,
                    now_str,
                    created_by,
                    created_role,
                    terminal_id,
                    movement_id,
                ),
            )
            return_id = self.cursor.lastrowid
            self.conn.commit()
            return {
                "ok": True,
                "message": "Estorno registado com sucesso",
                "return_id": return_id,
                "movement_id": movement_id,
                "sale_id": sale_id,
                "qty": quantity,
                "total_refund": total_refund,
            }
        except sqlite3.Error as e:
            print(f"Erro SQL ao estornar venda: {e}")
            self.conn.rollback()
            return {"ok": False, "message": f"Erro SQL: {e}"}
        except Exception as e:
            print(f"Erro ao estornar venda: {e}")
            self.conn.rollback()
            return {"ok": False, "message": str(e)}

    def get_all_sales(self, limit=None, offset=0):
        """Obter todas as vendas"""
        try:
            return self._query_sales_with_returns(limit=limit, offset=offset)
        except sqlite3.Error as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao obter vendas: {e}")
            return []
    
    def get_recent_sales(self, limit=50):
        """Obter as vendas mais recentes para consulta rapida."""
        return self.get_all_sales(limit=limit, offset=0)

    def get_sales_by_date(self, date_str, limit=None, offset=0):
        """Buscar vendas por data especÃƒÆ’Ã‚Â­fica"""
        try:
            date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            formatted_date = date_obj.strftime("%Y-%m-%d")
            
            return self._query_sales_with_returns(
                "DATE(s.sale_date) = ?",
                (formatted_date,),
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao buscar vendas por data: {e}")
            return []

    def get_sales_by_date_range(self, start_date, end_date, limit=None, offset=0):
        """Buscar vendas por perÃƒÆ’Ã‚Â­odo (intervalo de datas)"""
        try:
            start_obj = datetime.strptime(start_date, "%d/%m/%Y")
            end_obj = datetime.strptime(end_date, "%d/%m/%Y")
            
            formatted_start = start_obj.strftime("%Y-%m-%d")
            formatted_end = end_obj.strftime("%Y-%m-%d")
            
            return self._query_sales_with_returns(
                "DATE(s.sale_date) BETWEEN ? AND ?",
                (formatted_start, formatted_end),
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao buscar vendas por perÃƒÆ’Ã‚Â­odo: {e}")
            return []

    def get_sales_by_month(self, month, year, limit=None, offset=0):
        """Buscar vendas por mÃƒÆ’Ã‚Âªs especÃƒÆ’Ã‚Â­fico"""
        try:
            return self._query_sales_with_returns(
                "strftime('%m', s.sale_date) = ? AND strftime('%Y', s.sale_date) = ?",
                (f"{month:02d}", str(year)),
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao buscar vendas por mÃƒÆ’Ã‚Âªs: {e}")
            return []

    def get_sales_by_year(self, year, limit=None, offset=0):
        """Buscar vendas por ano especÃƒÆ’Ã‚Â­fico"""
        try:
            return self._query_sales_with_returns(
                "strftime('%Y', s.sale_date) = ?",
                (str(year),),
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao buscar vendas por ano: {e}")
            return []

    def get_today_sales(self):
        """Buscar vendas de hoje"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            return self._query_sales_with_returns(
                "DATE(s.sale_date) = ?",
                (today,),
            )
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao buscar vendas de hoje: {e}")
            return []

    def get_sales_statistics_by_date(self, date_str):
        """Obter estatÃƒÆ’Ã‚Â­sticas de vendas por data especÃƒÆ’Ã‚Â­fica"""
        try:
            date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            formatted_date = date_obj.strftime("%Y-%m-%d")
            
            self.cursor.execute("""
                SELECT 
                    COUNT(*) as total_sales,
                    SUM(s.quantity) as total_quantity,
                    SUM(s.total_price) as total_revenue,
                    AVG(s.total_price) as average_sale,
                    MIN(s.total_price) as min_sale,
                    MAX(s.total_price) as max_sale
                FROM sales s
                WHERE DATE(s.sale_date) = ?
            """, (formatted_date,))
            
            return self.cursor.fetchone()
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao obter estatÃƒÆ’Ã‚Â­sticas por data: {e}")
            return None

    def get_monthly_sales_summary(self, month, year):
        """Obter resumo de vendas mensais"""
        try:
            self.cursor.execute("""
                SELECT 
                    DATE(s.sale_date) as date,
                    COUNT(*) as daily_sales,
                    SUM(s.quantity) as daily_quantity,
                    SUM(s.total_price) as daily_revenue
                FROM sales s
                WHERE strftime('%m', s.sale_date) = ? AND strftime('%Y', s.sale_date) = ?
                GROUP BY DATE(s.sale_date)
                ORDER BY DATE(s.sale_date) DESC
            """, (f"{month:02d}", str(year)))
            
            return self.cursor.fetchall()
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao obter resumo mensal: {e}")
            return []
    
    # ==================== MÃƒÆ’Ã¢â‚¬Â°TODOS PARA GERENTES ====================

    def get_all_managers(self):
        """Obter todos os gerentes"""
        try:
            self.cursor.execute("SELECT username FROM users WHERE role = 'manager'")
            return [manager[0] for manager in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao buscar gerentes: {e}")
            return []
    
    def delete_manager(self, username):
        """Excluir um gerente especÃƒÆ’Ã‚Â­fico"""
        try:
            self.cursor.execute("SELECT username FROM users WHERE role = 'manager'")
            current_managers = self.cursor.fetchall()
            
            self.cursor.execute(
                "SELECT id FROM users WHERE username = ? AND role = 'manager'", 
                (username,)
            )
            manager = self.cursor.fetchone()
            
            if not manager:
                return False, "Gerente nÃƒÆ’Ã‚Â£o encontrado"
            
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'manager'")
            manager_count = self.cursor.fetchone()[0]
            
            if manager_count <= 1:
                return False, "NÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© possÃƒÆ’Ã‚Â­vel excluir o ÃƒÆ’Ã‚Âºltimo gerente"
            
            self.cursor.execute(
                "DELETE FROM users WHERE username = ? AND role = 'manager'", 
                (username,)
            )
            self.conn.commit()
            
            print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Gerente '{username}' excluÃƒÆ’Ã‚Â­do com sucesso!")
            return True, "Gerente excluÃƒÆ’Ã‚Â­do com sucesso"
        
        except sqlite3.Error as e:
            self.conn.rollback()
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao excluir gerente: {e}")
            return False, f"Erro ao excluir gerente: {str(e)}"
        except Exception as e:
            self.conn.rollback()
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro inesperado: {e}")
            return False, f"Erro inesperado: {str(e)}"
    
    def get_products_with_barcodes(self):
        """Obter produtos que possuem codigo de barras"""
        try:
            self.cursor.execute(
                """
                SELECT id, description, barcode, existing_stock, is_sold_by_weight
                FROM products
                WHERE barcode IS NOT NULL AND barcode != ''
                ORDER BY id
                """
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos com barcode: {e}")
            return []

    def get_known_barcodes(self):
        """Obter todos os codigos de barras conhecidos, incluindo arquivados."""
        try:
            self.cursor.execute(
                """
                SELECT DISTINCT barcode
                FROM (
                    SELECT TRIM(barcode) AS barcode
                    FROM products
                    WHERE barcode IS NOT NULL AND TRIM(barcode) != ''

                    UNION ALL

                    SELECT TRIM(barcode) AS barcode
                    FROM products_archive
                    WHERE barcode IS NOT NULL AND TRIM(barcode) != ''
                )
                WHERE barcode IS NOT NULL AND barcode != ''
                ORDER BY barcode
                """
            )
            return [row[0] for row in self.cursor.fetchall() if row and row[0]]
        except sqlite3.Error as e:
            print(f"Erro ao obter codigos conhecidos: {e}")
            return []

    def get_products_for_losses(self):
        """Obter produtos para tela de perdas"""
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                f"""
                SELECT id, description, existing_stock, sale_price,
                       unit_purchase_price, barcode, is_sold_by_weight,
                       expiry_date, status, vat_rule_code
                FROM products
                WHERE existing_stock > 0
                {scope_sql}
                ORDER BY LOWER(COALESCE(description, '')) ASC, {self._expiry_order_clause()}
                """,
                tuple(scope_params),
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos para perdas: {e}")
            return []

    def get_products_for_restock(self, include_velocity=False, velocity_days=14):
        """Obter produtos para tela de reposicao"""
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                f"""
                SELECT id, description, existing_stock, sale_price,
                       unit_purchase_price, barcode, is_sold_by_weight,
                       expiry_date, status, vat_rule_code
                FROM products
                WHERE 1=1
                {scope_sql}
                ORDER BY LOWER(COALESCE(description, '')) ASC, {self._expiry_order_clause()}
                """,
                tuple(scope_params),
            )
            rows = self.cursor.fetchall()
            if not include_velocity:
                return rows

            velocity = _fetch_sales_velocity(self, days=velocity_days)
            enriched = []
            for row in rows:
                pid, name, stock, price, cost, barcode, is_weight, exp, status, vat_rule_code = row
                stock_val = _safe_float(stock, 0.0)
                avg_daily = _safe_float(velocity.get(pid, 0.0), 0.0)
                days_left = (stock_val / avg_daily) if avg_daily > 0 else None
                enriched.append(
                    (
                        pid,
                        name,
                        stock_val,
                        price,
                        cost,
                        barcode,
                        is_weight,
                        exp,
                        status,
                        vat_rule_code,
                        avg_daily,
                        days_left,
                    )
                )

            enriched.sort(
                key=lambda r: (
                    r[10] is None,
                    r[10] if r[10] is not None else 999999,
                    r[2],
                )
            )
            return enriched
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos para reposicao: {e}")
            return []

    def get_products_for_stock_control(self, include_velocity=False, velocity_days=14):
        """Obter produtos para painel unificado de controlo de stock."""
        try:
            scope_sql, scope_params = self._owner_filter("p")
            self.cursor.execute(
                f"""
                SELECT
                    p.id,
                    p.description,
                    p.existing_stock,
                    p.sale_price,
                    p.unit_purchase_price,
                    p.barcode,
                    p.is_sold_by_weight,
                    p.expiry_date,
                    p.status,
                    MAX(sm.created_at) AS last_stock_update_at
                FROM products p
                LEFT JOIN stock_movements sm
                    ON sm.product_id = p.id
                   AND sm.applied = 1
                WHERE 1=1
                {scope_sql}
                GROUP BY
                    p.id,
                    p.description,
                    p.existing_stock,
                    p.sale_price,
                    p.unit_purchase_price,
                    p.barcode,
                    p.is_sold_by_weight,
                    p.expiry_date,
                    p.status
                """,
                tuple(scope_params),
            )
            rows = self.cursor.fetchall()

            velocity = _fetch_sales_velocity(self, days=velocity_days) if include_velocity else {}
            enriched = []
            for row in rows:
                (
                    pid,
                    name,
                    stock,
                    price,
                    cost,
                    barcode,
                    is_weight,
                    exp,
                    status,
                    last_update_at,
                ) = row
                stock_val = _safe_float(stock, 0.0)
                avg_daily = _safe_float(velocity.get(pid, 0.0), 0.0) if include_velocity else 0.0
                days_left = (stock_val / avg_daily) if avg_daily > 0 else None
                enriched.append(
                    (
                        pid,
                        name,
                        stock_val,
                        price,
                        cost,
                        barcode,
                        is_weight,
                        exp,
                        status,
                        avg_daily,
                        days_left,
                        last_update_at,
                    )
                )

            if include_velocity:
                enriched.sort(
                    key=lambda r: (
                        r[10] is None,
                        r[10] if r[10] is not None else 999999,
                        r[2],
                    )
                )
            else:
                enriched.sort(key=lambda r: (r[2], (r[1] or "").lower()))
            return enriched
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos para controlo de stock: {e}")
            return []

    def get_stock_movements(
        self,
        start_dt,
        end_dt,
        direction=None,
        product_id=None,
        include_sales=True,
        limit=300,
    ):
        """Lista movimentos de stock para painel unificado."""
        start = self._to_dt_str(start_dt, end=False)
        end = self._to_dt_str(end_dt, end=True)
        try:
            where = [
                "sm.applied = 1",
                "sm.created_at BETWEEN ? AND ?",
            ]
            params = [start, end]
            owner = self._active_owner()
            if owner:
                where.append("COALESCE(sm.owner_username, '') = ?")
                params.append(owner)

            if direction in ("IN", "OUT"):
                where.append("sm.direction = ?")
                params.append(direction)

            if product_id is not None:
                where.append("sm.product_id = ?")
                params.append(int(product_id))

            if not include_sales:
                where.append("sm.movement_type <> 'SALE'")

            limit_clause = ""
            if limit:
                limit_clause = "LIMIT ?"
                params.append(int(limit))

            self.cursor.execute(
                f"""
                SELECT
                    sm.id,
                    sm.created_at,
                    CASE WHEN sm.direction = 'IN' THEN sm.created_at ELSE NULL END AS entry_date,
                    CASE WHEN sm.direction = 'OUT' THEN sm.created_at ELSE NULL END AS exit_date,
                    DATE(sm.created_at) AS update_day,
                    sm.direction,
                    sm.movement_type,
                    sm.product_id,
                    COALESCE(p.description, pa.description) AS product_name,
                    sm.qty,
                    sm.unit,
                    sm.unit_cost,
                    sm.total_cost,
                    sm.stock_before,
                    sm.stock_after,
                    sm.reason,
                    sm.note,
                    sm.created_by,
                    sm.supplier_name,
                    sm.invoice_number
                FROM stock_movements sm
                LEFT JOIN products p ON sm.product_id = p.id
                LEFT JOIN products_archive pa ON sm.product_id = pa.id
                WHERE {" AND ".join(where)}
                ORDER BY sm.created_at DESC
                {limit_clause}
                """,
                tuple(params),
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter movimentos de stock: {e}")
            return []

    def get_products_for_filter(self):
        """Obter lista simples de produtos para filtros"""
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                "SELECT id, description FROM products WHERE 1=1" + scope_sql + " ORDER BY description",
                tuple(scope_params),
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos para filtro: {e}")
            return []

    def get_categories(self):
        """Obter lista de categorias distintas"""
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                "SELECT DISTINCT category FROM products "
                "WHERE category IS NOT NULL AND category != ''" + scope_sql + " ORDER BY category",
                tuple(scope_params),
            )
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Erro ao obter categorias: {e}")
            return []

    def get_sales_users_for_filter(self):
        """Listar utilizadores que registaram vendas para filtros de relatorio."""
        try:
            scope_sql, scope_params = self._owner_filter("s")
            self.cursor.execute(f"""
                SELECT DISTINCT COALESCE(NULLIF(TRIM(s.created_by), ''), 'Sistema') AS username
                FROM sales s
                WHERE 1=1
                {scope_sql}
                ORDER BY username COLLATE NOCASE
            """, scope_params)
            names = {
                str(row[0] or "").strip()
                for row in self.cursor.fetchall()
                if str(row[0] or "").strip()
            }
            owner = self._active_owner()
            if owner:
                self.cursor.execute(
                    """
                    SELECT username FROM users
                    WHERE role = 'manager'
                      AND COALESCE(NULLIF(TRIM(data_owner), ''), username) = ?
                    ORDER BY username COLLATE NOCASE
                    """,
                    (owner,),
                )
            else:
                self.cursor.execute(
                    "SELECT username FROM users WHERE role = 'manager' ORDER BY username COLLATE NOCASE"
                )
            names.update(
                str(row[0] or "").strip()
                for row in self.cursor.fetchall()
                if str(row[0] or "").strip()
            )
            return sorted(names, key=lambda value: value.lower())
        except sqlite3.Error as e:
            print(f"Erro ao obter vendedores para filtro: {e}")
            return []

    def get_report_data(self, start_date, end_date, product_id=None, category=None, seller=None):
        """Obter dados agregados para relatorios"""
        query = """
        SELECT 
            p.id,
            p.description,
            p.category,
            p.existing_stock,
            p.sale_price,
            p.total_purchase_price,
            p.unit_purchase_price,
            p.expiry_date,
            COALESCE(SUM(s.quantity), 0) as sold_in_period,
            COALESCE(SUM(s.total_price), 0) as total_sales
        FROM products p
        LEFT JOIN sales s
            ON p.id = s.product_id
           AND s.sale_date BETWEEN ? AND ?
        WHERE 1=1
        """
        params = [
            start_date,
            end_date,
        ]
        seller = str(seller or "").strip()
        if seller:
            query = query.replace(
                "AND s.sale_date BETWEEN ? AND ?",
                "AND s.sale_date BETWEEN ? AND ?\n           AND COALESCE(NULLIF(TRIM(s.created_by), ''), 'Sistema') = ?",
            )
            params.append(seller)
        scope_sql, scope_params = self._owner_filter("p")
        query += scope_sql
        params.extend(scope_params)

        if product_id:
            query += " AND p.id = ?"
            params.append(product_id)

        if category:
            query += " AND p.category = ?"
            params.append(category)

        query += """
        GROUP BY 
            p.id, p.description, p.existing_stock, p.sale_price,
            p.total_purchase_price, p.unit_purchase_price, p.category, p.expiry_date
        """
        if seller:
            query += "\nHAVING COALESCE(SUM(s.quantity), 0) > 0"

        try:
            self.cursor.execute(query, params)
            columns = [desc[0] for desc in self.cursor.description]
            return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Erro ao obter dados filtrados: {e}")
            return []

    def get_productivity_report_data(self, start_date, end_date):
        """Obter dados agregados de produtividade por dia e terminal."""
        start_dt = _parse_datetime_value(start_date)
        end_dt = _parse_datetime_value(end_date, end_of_day=True)
        if not start_dt or not end_dt:
            return {
                "summary": {
                    "start_date": str(start_date or ""),
                    "end_date": str(end_date or ""),
                    "total_sales": 0,
                    "total_revenue": 0.0,
                    "total_quantity": 0.0,
                    "avg_ticket": 0.0,
                    "active_terminals": 0,
                    "avg_margin_percent": None,
                    "avg_discount_percent": 0.0,
                    "best_day": None,
                },
                "daily_series": [],
                "terminal_series": [],
            }

        query = """
        SELECT
            DATE(s.sale_date) AS sale_day,
            COALESCE(NULLIF(s.terminal_id, ''), 'CAIXA-PRINCIPAL') AS terminal_id,
            COUNT(*) AS sales_count,
            COALESCE(SUM(s.quantity), 0) AS quantity,
            COALESCE(SUM(s.total_price), 0) AS revenue,
            COALESCE(
                SUM(
                    COALESCE(s.quantity, 0) *
                    COALESCE(COALESCE(p.unit_purchase_price, pa.unit_purchase_price), 0)
                ),
                0
            ) AS total_cost,
            COALESCE(
                AVG(
                    CASE
                        WHEN COALESCE(COALESCE(p.sale_price, pa.sale_price), s.sale_price, 0) > 0 THEN
                            CASE
                                WHEN COALESCE(COALESCE(p.sale_price, pa.sale_price), s.sale_price) > COALESCE(s.sale_price, 0)
                                THEN
                                    (
                                        COALESCE(COALESCE(p.sale_price, pa.sale_price), s.sale_price) - COALESCE(s.sale_price, 0)
                                    ) / COALESCE(COALESCE(p.sale_price, pa.sale_price), s.sale_price)
                                ELSE 0
                            END
                        ELSE 0
                    END
                ),
                0
            ) AS avg_discount_ratio,
            MIN(s.sale_date) AS first_sale_at,
            MAX(s.sale_date) AS last_sale_at
        FROM sales s
        LEFT JOIN products p ON s.product_id = p.id
        LEFT JOIN products_archive pa ON s.product_id = pa.id
        WHERE s.sale_date BETWEEN ? AND ?
        GROUP BY DATE(s.sale_date), COALESCE(NULLIF(s.terminal_id, ''), 'CAIXA-PRINCIPAL')
        ORDER BY sale_day ASC, terminal_id ASC
        """

        try:
            self.cursor.execute(
                query,
                (
                    start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            rows = self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter produtividade filtrada: {e}")
            return {
                "summary": {
                    "start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_date": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_sales": 0,
                    "total_revenue": 0.0,
                    "total_quantity": 0.0,
                    "avg_ticket": 0.0,
                    "active_terminals": 0,
                    "avg_margin_percent": None,
                    "avg_discount_percent": 0.0,
                    "best_day": None,
                },
                "daily_series": [],
                "terminal_series": [],
            }

        daily_map = {}
        terminal_map = {}
        total_sales = 0
        total_revenue = 0.0
        total_quantity = 0.0
        total_cost = 0.0
        total_discount_weight = 0.0

        for row in rows:
            sale_day = str(row[0] or "")
            terminal_id = str(row[1] or "CAIXA-PRINCIPAL")
            sales_count = int(row[2] or 0)
            quantity = _safe_float(row[3], 0.0)
            revenue = _safe_float(row[4], 0.0)
            cost = _safe_float(row[5], 0.0)
            avg_discount_ratio = _safe_float(row[6], 0.0)
            first_sale_at = row[7]
            last_sale_at = row[8]

            total_sales += sales_count
            total_revenue += revenue
            total_quantity += quantity
            total_cost += cost
            total_discount_weight += avg_discount_ratio * sales_count

            day_entry = daily_map.setdefault(
                sale_day,
                {
                    "date": sale_day,
                    "sales_count": 0,
                    "revenue": 0.0,
                    "quantity": 0.0,
                    "terminals": set(),
                },
            )
            day_entry["sales_count"] += sales_count
            day_entry["revenue"] += revenue
            day_entry["quantity"] += quantity
            day_entry["terminals"].add(terminal_id)

            terminal_entry = terminal_map.setdefault(
                terminal_id,
                {
                    "terminal_id": terminal_id,
                    "sales_count": 0,
                    "revenue": 0.0,
                    "quantity": 0.0,
                    "total_cost": 0.0,
                    "discount_weight": 0.0,
                    "active_days": set(),
                    "first_sale_at": None,
                    "last_sale_at": None,
                },
            )
            terminal_entry["sales_count"] += sales_count
            terminal_entry["revenue"] += revenue
            terminal_entry["quantity"] += quantity
            terminal_entry["total_cost"] += cost
            terminal_entry["discount_weight"] += avg_discount_ratio * sales_count
            terminal_entry["active_days"].add(sale_day)
            if first_sale_at and (not terminal_entry["first_sale_at"] or str(first_sale_at) < str(terminal_entry["first_sale_at"])):
                terminal_entry["first_sale_at"] = first_sale_at
            if last_sale_at and (not terminal_entry["last_sale_at"] or str(last_sale_at) > str(terminal_entry["last_sale_at"])):
                terminal_entry["last_sale_at"] = last_sale_at

        daily_series = []
        cursor_day = start_dt.date()
        end_day = end_dt.date()
        while cursor_day <= end_day:
            day_key = cursor_day.isoformat()
            day_entry = daily_map.get(day_key)
            if day_entry:
                daily_series.append(
                    {
                        "date": day_key,
                        "sales_count": int(day_entry["sales_count"]),
                        "revenue": round(_safe_float(day_entry["revenue"]), 2),
                        "quantity": round(_safe_float(day_entry["quantity"]), 3),
                        "active_terminals": len(day_entry["terminals"]),
                    }
                )
            else:
                daily_series.append(
                    {
                        "date": day_key,
                        "sales_count": 0,
                        "revenue": 0.0,
                        "quantity": 0.0,
                        "active_terminals": 0,
                    }
                )
            cursor_day += timedelta(days=1)

        best_day = None
        if daily_series:
            candidate = max(
                daily_series,
                key=lambda item: (
                    int(item.get("sales_count") or 0),
                    _safe_float(item.get("revenue")),
                    str(item.get("date") or ""),
                ),
            )
            if int(candidate.get("sales_count") or 0) > 0:
                best_day = {
                    "date": str(candidate.get("date") or ""),
                    "sales_count": int(candidate.get("sales_count") or 0),
                    "revenue": round(_safe_float(candidate.get("revenue")), 2),
                }

        terminal_series = []
        for terminal_id, terminal_entry in terminal_map.items():
            revenue = _safe_float(terminal_entry["revenue"])
            sales_count = int(terminal_entry["sales_count"] or 0)
            margin_percent = None
            if revenue > 0:
                margin_percent = ((revenue - _safe_float(terminal_entry["total_cost"])) / revenue) * 100.0
            discount_percent = 0.0
            if sales_count > 0:
                discount_percent = (_safe_float(terminal_entry["discount_weight"]) / sales_count) * 100.0
            terminal_series.append(
                {
                    "terminal_id": terminal_id,
                    "sales_count": sales_count,
                    "revenue": round(revenue, 2),
                    "quantity": round(_safe_float(terminal_entry["quantity"]), 3),
                    "avg_ticket": round(revenue / sales_count, 2) if sales_count > 0 else 0.0,
                    "margin_percent": round(margin_percent, 2) if margin_percent is not None else None,
                    "discount_percent": round(discount_percent, 2),
                    "active_days": len(terminal_entry["active_days"]),
                    "first_sale_at": terminal_entry["first_sale_at"],
                    "last_sale_at": terminal_entry["last_sale_at"],
                }
            )

        terminal_series.sort(
            key=lambda item: (
                -int(item.get("sales_count") or 0),
                -_safe_float(item.get("revenue")),
                str(item.get("terminal_id") or ""),
            )
        )

        avg_margin_percent = None
        if total_revenue > 0:
            avg_margin_percent = ((total_revenue - total_cost) / total_revenue) * 100.0

        avg_discount_percent = 0.0
        if total_sales > 0:
            avg_discount_percent = (total_discount_weight / total_sales) * 100.0

        return {
            "summary": {
                "start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "total_sales": total_sales,
                "total_revenue": round(total_revenue, 2),
                "total_quantity": round(total_quantity, 3),
                "avg_ticket": round(total_revenue / total_sales, 2) if total_sales > 0 else 0.0,
                "active_terminals": len(terminal_series),
                "avg_margin_percent": round(avg_margin_percent, 2) if avg_margin_percent is not None else None,
                "avg_discount_percent": round(avg_discount_percent, 2),
                "best_day": best_day,
            },
            "daily_series": daily_series,
            "terminal_series": terminal_series,
        }

    def get_cash_user_report_data(self, start_date, end_date, seller=None):
        """Obter resumo de abertura/fechamento operacional por usuario e caixa."""
        start_dt = _parse_datetime_value(start_date)
        end_dt = _parse_datetime_value(end_date, end_of_day=True)

        def _empty_payload():
            return {
                "summary": {
                    "start_date": str(start_date or ""),
                    "end_date": str(end_date or ""),
                    "total_users": 0,
                    "total_terminals": 0,
                    "total_days": 0,
                    "total_sales": 0,
                    "total_revenue": 0.0,
                    "total_quantity": 0.0,
                    "avg_ticket": 0.0,
                    "first_opening_at": None,
                    "last_closing_at": None,
                    "leader_user": None,
                },
                "user_series": [],
                "session_rows": [],
            }

        if not start_dt or not end_dt:
            return _empty_payload()

        owner_sql, owner_params = self._owner_filter("s")
        params = [
            start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        ]
        seller = str(seller or "").strip()
        seller_sql = ""
        if seller:
            seller_sql = "AND COALESCE(NULLIF(TRIM(s.created_by), ''), 'Sistema') = ?"
            params.append(seller)
        params.extend(owner_params)

        query = f"""
        SELECT
            DATE(s.sale_date) AS sale_day,
            COALESCE(NULLIF(s.created_by, ''), 'Sistema') AS username,
            COALESCE(NULLIF(s.created_role, ''), 'manager') AS role,
            COALESCE(NULLIF(s.terminal_id, ''), 'CAIXA-PRINCIPAL') AS terminal_id,
            MIN(s.sale_date) AS opening_at,
            MAX(s.sale_date) AS closing_at,
            COUNT(*) AS sales_count,
            COALESCE(SUM(s.quantity), 0) AS quantity,
            COALESCE(SUM(s.total_price), 0) AS revenue,
            MIN(s.id) AS first_sale_id,
            MAX(s.id) AS last_sale_id
        FROM sales s
        WHERE s.sale_date BETWEEN ? AND ?
        {seller_sql}
        {owner_sql}
        GROUP BY
            DATE(s.sale_date),
            COALESCE(NULLIF(s.created_by, ''), 'Sistema'),
            COALESCE(NULLIF(s.created_role, ''), 'manager'),
            COALESCE(NULLIF(s.terminal_id, ''), 'CAIXA-PRINCIPAL')
        ORDER BY sale_day ASC, username ASC, terminal_id ASC
        """

        try:
            self.cursor.execute(query, params)
            rows = self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter relatorio de caixa por usuario: {e}")
            return _empty_payload()

        session_rows = []
        user_map = {}
        terminals = set()
        days = set()
        total_sales = 0
        total_revenue = 0.0
        total_quantity = 0.0
        first_opening_at = None
        last_closing_at = None

        for row in rows:
            sale_day = str(row[0] or "")
            username = str(row[1] or "Sistema")
            role = str(row[2] or "manager")
            terminal_id = str(row[3] or "CAIXA-PRINCIPAL")
            opening_at = row[4]
            closing_at = row[5]
            sales_count = int(row[6] or 0)
            quantity = _safe_float(row[7], 0.0)
            revenue = _safe_float(row[8], 0.0)
            first_sale_id = row[9]
            last_sale_id = row[10]

            terminals.add(terminal_id)
            if sale_day:
                days.add(sale_day)
            total_sales += sales_count
            total_revenue += revenue
            total_quantity += quantity
            if opening_at and (not first_opening_at or str(opening_at) < str(first_opening_at)):
                first_opening_at = opening_at
            if closing_at and (not last_closing_at or str(closing_at) > str(last_closing_at)):
                last_closing_at = closing_at

            session_rows.append(
                {
                    "date": sale_day,
                    "username": username,
                    "role": role,
                    "terminal_id": terminal_id,
                    "opening_at": opening_at,
                    "closing_at": closing_at,
                    "sales_count": sales_count,
                    "quantity": round(quantity, 3),
                    "revenue": round(revenue, 2),
                    "avg_ticket": round(revenue / sales_count, 2) if sales_count > 0 else 0.0,
                    "first_sale_id": first_sale_id,
                    "last_sale_id": last_sale_id,
                }
            )

            user_entry = user_map.setdefault(
                username,
                {
                    "username": username,
                    "role": role,
                    "sales_count": 0,
                    "revenue": 0.0,
                    "quantity": 0.0,
                    "terminals": set(),
                    "active_days": set(),
                    "first_opening_at": None,
                    "last_closing_at": None,
                },
            )
            user_entry["sales_count"] += sales_count
            user_entry["revenue"] += revenue
            user_entry["quantity"] += quantity
            user_entry["terminals"].add(terminal_id)
            if sale_day:
                user_entry["active_days"].add(sale_day)
            if opening_at and (
                not user_entry["first_opening_at"]
                or str(opening_at) < str(user_entry["first_opening_at"])
            ):
                user_entry["first_opening_at"] = opening_at
            if closing_at and (
                not user_entry["last_closing_at"]
                or str(closing_at) > str(user_entry["last_closing_at"])
            ):
                user_entry["last_closing_at"] = closing_at

        user_series = []
        for user_entry in user_map.values():
            sales_count = int(user_entry["sales_count"] or 0)
            revenue = _safe_float(user_entry["revenue"], 0.0)
            user_series.append(
                {
                    "username": user_entry["username"],
                    "role": user_entry["role"],
                    "sales_count": sales_count,
                    "revenue": round(revenue, 2),
                    "quantity": round(_safe_float(user_entry["quantity"]), 3),
                    "avg_ticket": round(revenue / sales_count, 2) if sales_count > 0 else 0.0,
                    "active_days": len(user_entry["active_days"]),
                    "active_terminals": len(user_entry["terminals"]),
                    "first_opening_at": user_entry["first_opening_at"],
                    "last_closing_at": user_entry["last_closing_at"],
                }
            )

        user_series.sort(
            key=lambda item: (
                -_safe_float(item.get("revenue")),
                -int(item.get("sales_count") or 0),
                str(item.get("username") or ""),
            )
        )

        leader_user = None
        if user_series:
            leader = user_series[0]
            leader_user = {
                "username": leader.get("username"),
                "sales_count": int(leader.get("sales_count") or 0),
                "revenue": round(_safe_float(leader.get("revenue")), 2),
            }

        return {
            "summary": {
                "start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "total_users": len(user_series),
                "total_terminals": len(terminals),
                "total_days": len(days),
                "total_sales": total_sales,
                "total_revenue": round(total_revenue, 2),
                "total_quantity": round(total_quantity, 3),
                "avg_ticket": round(total_revenue / total_sales, 2) if total_sales > 0 else 0.0,
                "first_opening_at": first_opening_at,
                "last_closing_at": last_closing_at,
                "leader_user": leader_user,
            },
            "user_series": user_series,
            "session_rows": session_rows,
        }

    def get_admin_home_snapshot(self, lookback_days=7):
        """Retorna um snapshot agregado para a HOME do administrador."""
        try:
            lookback_days = max(3, min(int(lookback_days or 7), 30))
        except Exception:
            lookback_days = 7

        now = datetime.now()
        today_date = now.date()
        start_date = today_date - timedelta(days=lookback_days - 1)
        today_iso = today_date.isoformat()
        start_iso = start_date.isoformat()
        month_key = now.strftime("%m")
        year_key = now.strftime("%Y")
        low_threshold = 5
        owner = self._active_owner()

        def _empty_snapshot():
            return {
                "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "lookback_days": lookback_days,
                "summary": {
                    "total_products": 0,
                    "critical_stock": 0,
                    "out_of_stock": 0,
                    "sales_today_count": 0,
                    "revenue_today": 0.0,
                    "revenue_month": 0.0,
                    "total_users": 0,
                    "total_clients": None,
                    "active_suppliers": 0,
                },
                "comparison": {
                    "recent_average_revenue": 0.0,
                    "delta_percent": None,
                    "direction": "none",
                },
                "sales_series": [],
                "stock_flow_series": [],
                "top_products": [],
                "alerts": {
                    "counts": {
                        "critical_stock": 0,
                        "out_of_stock": 0,
                        "expired": 0,
                        "expiring_soon": 0,
                        "pending_approvals": 0,
                        "fraud_alerts": 0,
                        "negative_profit": 0,
                    },
                    "low_stock_items": [],
                    "out_of_stock_items": [],
                    "expired_items": [],
                    "expiring_items": [],
                    "pending_items": [],
                    "fraud_items": [],
                    "negative_profit_items": [],
                },
                "context": {
                    "top_product_today": None,
                    "peak_hour": None,
                },
            }

        snapshot = _empty_snapshot()

        try:
            insights = self.get_admin_insights() or {}
            expiry_levels = insights.get("expiry_levels") or {}

            product_scope_sql, product_scope_params = self._owner_filter()
            self.cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT {self._catalog_identity_sql()} AS catalog_key
                    FROM products
                    WHERE 1=1 {product_scope_sql}
                    GROUP BY catalog_key
                )
                """,
                tuple(product_scope_params),
            )
            total_products = int(self.cursor.fetchone()[0] or 0)

            self.cursor.execute(
                "SELECT COUNT(*) FROM products WHERE existing_stock > 0 AND existing_stock <= ?"
                + product_scope_sql,
                (low_threshold, *product_scope_params),
            )
            critical_stock_count = int(self.cursor.fetchone()[0] or 0)

            self.cursor.execute(
                "SELECT COUNT(*) FROM products WHERE existing_stock <= 0" + product_scope_sql,
                tuple(product_scope_params),
            )
            out_of_stock_count = int(self.cursor.fetchone()[0] or 0)

            self.cursor.execute("SELECT COUNT(*) FROM users")
            total_users = int(self.cursor.fetchone()[0] or 0)

            self.cursor.execute(
                "SELECT COUNT(DISTINCT supplier_name) FROM stock_movements "
                "WHERE supplier_name IS NOT NULL AND TRIM(supplier_name) != ''"
                + (" AND COALESCE(owner_username, '') = ?" if owner else ""),
                (owner,) if owner else (),
            )
            active_suppliers = int(self.cursor.fetchone()[0] or 0)

            self.cursor.execute(
                "SELECT COUNT(*), COALESCE(SUM(total_price), 0) "
                "FROM sales WHERE DATE(sale_date) = ?"
                + (" AND COALESCE(owner_username, '') = ?" if owner else ""),
                (today_iso, owner) if owner else (today_iso,),
            )
            sales_today_count, revenue_today = self.cursor.fetchone()
            sales_today_count = int(sales_today_count or 0)
            revenue_today = round(_safe_float(revenue_today), 2)

            self.cursor.execute(
                "SELECT COALESCE(SUM(total_price), 0) "
                "FROM sales WHERE strftime('%m', sale_date) = ? AND strftime('%Y', sale_date) = ?"
                + (" AND COALESCE(owner_username, '') = ?" if owner else ""),
                (month_key, year_key, owner) if owner else (month_key, year_key),
            )
            revenue_month = round(_safe_float(self.cursor.fetchone()[0]), 2)

            self.cursor.execute(
                "SELECT id, description, existing_stock, is_sold_by_weight "
                "FROM products WHERE existing_stock <= 0 "
                + product_scope_sql
                + " ORDER BY LOWER(description) ASC LIMIT 6",
                tuple(product_scope_params),
            )
            out_of_stock_items = [
                {
                    "product_id": row[0],
                    "name": row[1],
                    "stock": round(_safe_float(row[2]), 2),
                    "is_weight": bool(row[3]),
                }
                for row in self.cursor.fetchall()
            ]

            self.cursor.execute(
                "SELECT DATE(sale_date) AS sale_day, COUNT(*) AS sales_count, "
                "COALESCE(SUM(total_price), 0) AS revenue "
                "FROM sales WHERE DATE(sale_date) BETWEEN ? AND ? "
                + ("AND COALESCE(owner_username, '') = ? " if owner else "")
                + "GROUP BY DATE(sale_date) ORDER BY DATE(sale_date) ASC",
                (start_iso, today_iso, owner) if owner else (start_iso, today_iso),
            )
            sales_map = {
                str(row[0]): {
                    "sales_count": int(row[1] or 0),
                    "revenue": round(_safe_float(row[2]), 2),
                }
                for row in self.cursor.fetchall()
            }

            self.cursor.execute(
                "SELECT DATE(created_at) AS movement_day, "
                "COALESCE(SUM(CASE WHEN direction = 'IN' THEN qty ELSE 0 END), 0) AS qty_in, "
                "COALESCE(SUM(CASE WHEN direction = 'OUT' THEN qty ELSE 0 END), 0) AS qty_out "
                "FROM stock_movements "
                "WHERE applied = 1 AND DATE(created_at) BETWEEN ? AND ? "
                + ("AND COALESCE(owner_username, '') = ? " if owner else "")
                + "GROUP BY DATE(created_at) ORDER BY DATE(created_at) ASC",
                (start_iso, today_iso, owner) if owner else (start_iso, today_iso),
            )
            stock_map = {
                str(row[0]): {
                    "in_qty": round(_safe_float(row[1]), 2),
                    "out_qty": round(_safe_float(row[2]), 2),
                }
                for row in self.cursor.fetchall()
            }

            self.cursor.execute(
                "SELECT COALESCE(p.description, pa.description), "
                "COALESCE(SUM(s.quantity), 0) AS total_qty, "
                "COALESCE(SUM(s.total_price), 0) AS total_revenue "
                "FROM sales s "
                "LEFT JOIN products p ON s.product_id = p.id "
                "LEFT JOIN products_archive pa ON s.product_id = pa.id "
                "WHERE DATE(s.sale_date) BETWEEN ? AND ? "
                + ("AND COALESCE(s.owner_username, '') = ? " if owner else "")
                + "GROUP BY s.product_id "
                "ORDER BY total_revenue DESC, total_qty DESC LIMIT 5",
                (start_iso, today_iso, owner) if owner else (start_iso, today_iso),
            )
            top_products = [
                {
                    "name": row[0] or "Produto",
                    "quantity": round(_safe_float(row[1]), 2),
                    "revenue": round(_safe_float(row[2]), 2),
                }
                for row in self.cursor.fetchall()
            ]

            self.cursor.execute(
                "SELECT COALESCE(p.description, pa.description), "
                "COALESCE(SUM(s.quantity), 0) AS total_qty, "
                "COALESCE(SUM(s.total_price), 0) AS total_revenue "
                "FROM sales s "
                "LEFT JOIN products p ON s.product_id = p.id "
                "LEFT JOIN products_archive pa ON s.product_id = pa.id "
                "WHERE DATE(s.sale_date) = ? "
                + ("AND COALESCE(s.owner_username, '') = ? " if owner else "")
                + "GROUP BY s.product_id "
                "ORDER BY total_revenue DESC, total_qty DESC LIMIT 1",
                (today_iso, owner) if owner else (today_iso,),
            )
            row = self.cursor.fetchone()
            top_product_today = None
            if row:
                top_product_today = {
                    "name": row[0] or "Produto",
                    "quantity": round(_safe_float(row[1]), 2),
                    "revenue": round(_safe_float(row[2]), 2),
                }

            self.cursor.execute(
                "SELECT strftime('%H', sale_date) AS hour_key, COALESCE(SUM(total_price), 0) AS total_revenue "
                "FROM sales WHERE DATE(sale_date) = ? "
                + ("AND COALESCE(owner_username, '') = ? " if owner else "")
                + "GROUP BY hour_key ORDER BY total_revenue DESC LIMIT 1",
                (today_iso, owner) if owner else (today_iso,),
            )
            row = self.cursor.fetchone()
            peak_hour = None
            if row and row[0] is not None:
                peak_hour = f"{row[0]}:00-{row[0]}:59"

            sales_series = []
            stock_flow_series = []
            current_day = start_date
            while current_day <= today_date:
                day_key = current_day.isoformat()
                sales_entry = sales_map.get(day_key, {})
                stock_entry = stock_map.get(day_key, {})
                sales_series.append(
                    {
                        "date": day_key,
                        "sales_count": int(sales_entry.get("sales_count") or 0),
                        "revenue": round(_safe_float(sales_entry.get("revenue")), 2),
                    }
                )
                stock_flow_series.append(
                    {
                        "date": day_key,
                        "in_qty": round(_safe_float(stock_entry.get("in_qty")), 2),
                        "out_qty": round(_safe_float(stock_entry.get("out_qty")), 2),
                    }
                )
                current_day += timedelta(days=1)

            recent_values = [item["revenue"] for item in sales_series[:-1] if _safe_float(item["revenue"]) >= 0]
            recent_average = round(sum(recent_values) / len(recent_values), 2) if recent_values else 0.0
            delta_percent = None
            direction = "none"
            if recent_average > 0:
                delta_percent = round(((revenue_today - recent_average) / recent_average) * 100.0, 2)
                if delta_percent >= 5:
                    direction = "above"
                elif delta_percent <= -5:
                    direction = "below"
                else:
                    direction = "stable"
            elif revenue_today > 0:
                direction = "above"

            low_stock_items = []
            for name, stock, is_weight, days_left, product_id in (insights.get("low_stock") or [])[:6]:
                low_stock_items.append(
                    {
                        "product_id": product_id,
                        "name": name,
                        "stock": round(_safe_float(stock), 2),
                        "is_weight": bool(is_weight),
                        "days_left": round(_safe_float(days_left), 1) if days_left is not None and _safe_float(days_left) < 999 else None,
                    }
                )

            def _expiry_items(rows):
                items = []
                for name, days_left, date_str, stock, unit in list(rows or [])[:6]:
                    items.append(
                        {
                            "name": name,
                            "days_left": int(days_left or 0),
                            "date": date_str,
                            "stock": round(_safe_float(stock), 2),
                            "unit": unit,
                        }
                    )
                return items

            expired_items = _expiry_items(expiry_levels.get("vencido"))
            expiring_items = _expiry_items(
                (expiry_levels.get("critico") or []) + (expiry_levels.get("alto") or [])
            )

            negative_profit_items = [
                {
                    "name": row[0],
                    "profit_per_unit": round(_safe_float(row[1]), 2),
                }
                for row in list(insights.get("negative_profit") or [])[:6]
            ]

            pending_items = []
            for row in (self.get_pending_approvals() or [])[:6]:
                pending_items.append(
                    {
                        "id": row[0],
                        "product_id": row[1],
                        "product_name": row[2],
                        "movement_type": row[3],
                        "qty": round(_safe_float(row[4]), 2),
                        "unit": row[5],
                        "total_cost": round(_safe_float(row[6]), 2),
                        "created_at": row[11],
                        "created_by": row[12],
                    }
                )

            fraud_items = []
            for item in (self.detect_fraud_patterns(days_lookback=30) or [])[:6]:
                fraud_items.append(
                    {
                        "title": item.get("title"),
                        "severity": int(item.get("severity") or 0),
                        "description": item.get("description"),
                    }
                )

            snapshot["summary"] = {
                "total_products": total_products,
                "critical_stock": critical_stock_count,
                "out_of_stock": out_of_stock_count,
                "sales_today_count": sales_today_count,
                "revenue_today": revenue_today,
                "revenue_month": revenue_month,
                "total_users": total_users,
                "total_clients": None,
                "active_suppliers": active_suppliers,
            }
            snapshot["comparison"] = {
                "recent_average_revenue": recent_average,
                "delta_percent": delta_percent,
                "direction": direction,
            }
            snapshot["sales_series"] = sales_series
            snapshot["stock_flow_series"] = stock_flow_series
            snapshot["top_products"] = top_products
            snapshot["alerts"] = {
                "counts": {
                    "critical_stock": len(low_stock_items),
                    "out_of_stock": out_of_stock_count,
                    "expired": len(expired_items),
                    "expiring_soon": len(expiring_items),
                    "pending_approvals": len(pending_items),
                    "fraud_alerts": len(fraud_items),
                    "negative_profit": len(negative_profit_items),
                },
                "low_stock_items": low_stock_items,
                "out_of_stock_items": out_of_stock_items,
                "expired_items": expired_items,
                "expiring_items": expiring_items,
                "pending_items": pending_items,
                "fraud_items": fraud_items,
                "negative_profit_items": negative_profit_items,
            }
            snapshot["context"] = {
                "top_product_today": top_product_today,
                "peak_hour": peak_hour,
            }
            return snapshot
        except Exception as e:
            print(f"Erro ao obter snapshot da HOME admin: {e}")
            return snapshot

    def get_user_logs(self, user_filter="", action_filter="", role_filter="", limit=100, offset=0):
        """Obter logs do sistema com filtros"""
        query = (
            "SELECT id, username, role, action, details, timestamp "
            "FROM user_logs WHERE 1=1"
        )
        params = []
        scope_sql, scope_params = self._owner_filter()
        query += scope_sql
        params.extend(scope_params)

        if user_filter:
            query += " AND username LIKE ?"
            params.append(f"%{user_filter}%")

        if action_filter:
            query += " AND action LIKE ?"
            params.append(f"%{action_filter}%")

        if role_filter:
            query += " AND role = ?"
            params.append(role_filter)

        query += " ORDER BY timestamp DESC"
        if limit:
            query += " LIMIT ? OFFSET ?"
            params.append(int(limit))
            params.append(max(0, int(offset or 0)))

        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter logs: {e}")
            return []

    def clear_user_logs(self):
        """Apagar todos os logs"""
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                "DELETE FROM user_logs WHERE 1=1" + scope_sql,
                tuple(scope_params),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao apagar logs: {e}")
            self.conn.rollback()
            return False

    def get_admin_insights(self):
        """Retorna insights completos para o admin"""
        today_date = datetime.now().date()
        today = today_date.strftime("%Y-%m-%d")

        self.cursor.execute(
            "SELECT COALESCE(SUM(total_price), 0), COUNT(*) "
            "FROM sales WHERE DATE(sale_date) = ?",
            (today,),
        )
        total_sales, total_count = self.cursor.fetchone()
        total_sales = _safe_float(total_sales, 0.0)
        total_count = int(total_count or 0)

        self.cursor.execute(
            "SELECT COALESCE(p.description, pa.description), COALESCE(SUM(s.total_price), 0) AS total_val "
            "FROM sales s "
            "LEFT JOIN products p ON s.product_id = p.id "
            "LEFT JOIN products_archive pa ON s.product_id = pa.id "
            "WHERE DATE(s.sale_date) = ? "
            "GROUP BY s.product_id ORDER BY total_val DESC LIMIT 1",
            (today,),
        )
        row = self.cursor.fetchone()
        top_product = row[0] if row else "n/d"

        self.cursor.execute(
            "SELECT strftime('%H', sale_date) AS h, COALESCE(SUM(total_price), 0) AS total_val "
            "FROM sales WHERE DATE(sale_date) = ? "
            "GROUP BY h ORDER BY total_val DESC LIMIT 1",
            (today,),
        )
        row = self.cursor.fetchone()
        peak_hour = f"{row[0]}:00-{row[0]}:59" if row else "n/d"

        low_threshold = 5
        self.cursor.execute(
            "SELECT id, description, existing_stock, is_sold_by_weight FROM products "
            "WHERE existing_stock <= ? ORDER BY existing_stock ASC",
            (low_threshold,),
        )
        low_stock_raw = self.cursor.fetchall()

        low_stock = []
        for prod_id, name, stock, is_weight in low_stock_raw:
            daily_sales = _get_product_daily_sales(self, prod_id)
            days_left = _safe_float(stock) / max(daily_sales, 0.1) if daily_sales > 0 else 999
            low_stock.append((name, stock, is_weight, days_left, prod_id))

        self.cursor.execute(
            "SELECT description, profit_per_unit FROM products "
            "WHERE profit_per_unit < 0 ORDER BY profit_per_unit ASC"
        )
        negative_profit = self.cursor.fetchall()

        self.cursor.execute(
            "SELECT description, expiry_date, existing_stock, is_sold_by_weight "
            "FROM products "
            "WHERE expiry_date IS NOT NULL AND expiry_date != ''"
        )
        expiring_15 = []
        expiring_7 = []
        expiry_levels = {
            "vencido": [],
            "critico": [],
            "alto": [],
            "medio": [],
            "leve": [],
        }
        expiring_90 = []
        for name, expiry_date, stock, is_by_weight in self.cursor.fetchall():
            exp_date = _parse_date(expiry_date)
            if not exp_date:
                continue
            days_left = (exp_date - today_date).days
            unit = "kg" if is_by_weight else "un"
            expiry_tuple = (
                name,
                days_left,
                exp_date.strftime("%d/%m/%Y"),
                _safe_float(stock),
                unit,
            )

            if days_left <= 0:
                expiry_levels["vencido"].append(expiry_tuple)
                continue
            if days_left <= 7:
                expiring_7.append(expiry_tuple)
                expiry_levels["critico"].append(expiry_tuple)
            elif days_left <= 15:
                expiring_15.append(expiry_tuple)
                expiry_levels["alto"].append(expiry_tuple)
            elif days_left <= 30:
                expiry_levels["alto"].append(expiry_tuple)
            elif days_left <= 60:
                expiry_levels["medio"].append(expiry_tuple)
            elif days_left <= 90:
                expiry_levels["leve"].append(expiry_tuple)
            if days_left <= 90:
                expiring_90.append(expiry_tuple)

        expiring_7.sort(key=lambda x: x[1])
        expiring_15.sort(key=lambda x: x[1])
        expiring_90.sort(key=lambda x: x[1])
        for level in ("vencido", "critico", "alto", "medio", "leve"):
            expiry_levels[level].sort(key=lambda x: x[1])

        forecasts, expiry_risk = _build_forecasts(self, days=14, limit=20)

        summary = [
            f"Total vendido hoje: {total_sales:.2f} MZN",
            f"Total de vendas hoje: {total_count}",
            f"Produto lider: {top_product}",
            f"Horario mais forte: {peak_hour}",
        ]

        alerts = []
        if total_count == 0:
            alerts.append("Sem vendas registadas hoje.")
        if low_stock:
            alerts.append(f"{len(low_stock)} produtos com stock baixo (<= {low_threshold}).")
        if expiry_levels["vencido"]:
            alerts.append(f"{len(expiry_levels['vencido'])} produtos vencidos.")
        if expiry_levels["critico"]:
            alerts.append(f"{len(expiry_levels['critico'])} produtos em alerta critico (7 dias).")
        if expiry_levels["alto"]:
            alerts.append(f"{len(expiry_levels['alto'])} produtos em alerta alto (30 dias).")
        if expiry_levels["medio"]:
            alerts.append(f"{len(expiry_levels['medio'])} produtos em alerta medio (60 dias).")
        if expiry_levels["leve"]:
            alerts.append(f"{len(expiry_levels['leve'])} produtos em alerta leve (90 dias).")
        if negative_profit:
            alerts.append(f"{len(negative_profit)} produtos com lucro negativo.")

        recommendations = []
        recommendations_stock = []
        recommendations_expiry = []

        if low_stock:
            for name, stock, is_weight, days_left, _pid in low_stock[:3]:
                unit = "kg" if is_weight else "un"
                rec = f"{name}: stock baixo ({stock:.1f} {unit}) - repor"
                recommendations.append(rec)
                recommendations_stock.append(rec)

        expiry_priority = (
            expiry_levels["vencido"]
            + expiry_levels["critico"]
            + expiry_levels["alto"]
            + expiry_levels["medio"]
            + expiry_levels["leve"]
        )
        for name, days, _date_str, _stock, _unit in expiry_priority[:3]:
            if days <= 0:
                rec = f"{name} vencido - retirar da venda"
            elif days <= 7:
                rec = f"{name} vence em {days} dias - priorizar venda"
            else:
                rec = f"{name} vence em {days} dias - acompanhar"
            recommendations.append(rec)
            recommendations_expiry.append(rec)

        if negative_profit:
            names = ", ".join([p[0] for p in negative_profit[:3]])
            recommendations.append(f"Rever preco de: {names}.")

        if not recommendations:
            recommendations.append("Sem recomendacoes criticas no momento.")

        alert_count = (
            (1 if total_count == 0 else 0)
            + len(low_stock)
            + len(expiry_levels["vencido"])
            + len(expiry_levels["critico"])
            + len(expiry_levels["alto"])
            + len(expiry_levels["medio"])
            + len(expiry_levels["leve"])
            + len(negative_profit)
        )

        expiry_total = (
            len(expiry_levels["vencido"])
            + len(expiry_levels["critico"])
            + len(expiry_levels["alto"])
            + len(expiry_levels["medio"])
            + len(expiry_levels["leve"])
        )

        return {
            "summary": summary,
            "alerts": alerts,
            "recommendations": recommendations,
            "recommendations_stock": recommendations_stock,
            "recommendations_expiry": recommendations_expiry,
            "low_stock": low_stock,
            "expiring_15": expiring_15,
            "expiring_7": expiring_7,
            "expiring_90": expiring_90,
            "expiry_levels": expiry_levels,
            "stock_forecast": forecasts,
            "expiry_risk": expiry_risk,
            "negative_profit": negative_profit,
            "alert_count": alert_count,
            "badge_counts": {
                "stock": len(low_stock),
                "expiry_vencido": len(expiry_levels["vencido"]),
                "expiry_critico": len(expiry_levels["critico"]),
                "expiry_alto": len(expiry_levels["alto"]),
                "expiry_medio": len(expiry_levels["medio"]),
                "expiry_leve": len(expiry_levels["leve"]),
                "expiry_total": expiry_total,
                "expiry_7": len(expiring_7),
                "expiry_15": len(expiring_15),
                "total": len(low_stock) + expiry_total,
            },
        }

    def get_admin_insights_ai(self):
        """Placeholder para compatibilidade: retorna insights base"""
        return self.get_admin_insights()

    def _update_product_impl(
        self,
        id,
        description,
        category,
        existing_stock,
        sold_stock,
        sale_price,
        total_purchase_price,
        unit_purchase_price,
        barcode=None,
        expiry_date=None,
        is_sold_by_weight=False,
        package_quantity=None,
        units_per_package=None,
        allow_pack_sale=False,
        vat_rule_code=DEFAULT_VAT_RULE_CODE,
    ):
        """Atualizar produto existente"""
        try:
            sale_price = float(sale_price)
            total_purchase_price = float(total_purchase_price)
            unit_purchase_price = float(unit_purchase_price)
            profit_per_unit = sale_price - unit_purchase_price
            normalized_barcode = self._normalize_barcode_value(barcode)
            normalized_expiry = self._normalize_expiry_value(expiry_date)
            normalized_vat_rule = self._normalize_vat_rule_code(vat_rule_code)
            normalized_units, normalized_allow = self._normalize_pack_sale_fields(
                is_sold_by_weight,
                units_per_package,
                allow_pack_sale,
            )
            if self._find_existing_batch(normalized_barcode, normalized_expiry, exclude_id=id):
                raise ValueError(
                    "Ja existe um lote com este codigo de barras e validade. Use a reposicao "
                    "para somar stock ou informe uma validade diferente."
                )

            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                """UPDATE products SET
                   description = ?, category = ?, existing_stock = ?, sold_stock = ?,
                   sale_price = ?, total_purchase_price = ?, unit_purchase_price = ?,
                   profit_per_unit = ?, barcode = ?, expiry_date = ?, is_sold_by_weight = ?, package_quantity = ?,
                   units_per_package = ?, allow_pack_sale = ?, vat_rule_code = ?
                   WHERE id = ?""" + scope_sql,
                (
                    description,
                    category,
                    float(existing_stock),
                    float(sold_stock),
                    sale_price,
                    total_purchase_price,
                    unit_purchase_price,
                    profit_per_unit,
                    normalized_barcode,
                    normalized_expiry,
                    1 if is_sold_by_weight else 0,
                    package_quantity,
                    normalized_units,
                    normalized_allow,
                    normalized_vat_rule,
                    id,
                    *scope_params,
                ),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return False
            self.conn.commit()
            return True
        except (sqlite3.Error, ValueError):
            self.conn.rollback()
            raise

    # ==================== CONTEXT MANAGER ====================
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


