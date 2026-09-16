import builtins
import json
import os
import secrets
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, date
from time import perf_counter
import bcrypt

from database.automation import DatabaseAutomationMixin
from utils.business.email_service import (
    EmailServiceError,
    is_valid_email,
    normalize_email,
    send_email_verification_code,
    send_password_changed_notice,
    send_password_reset_code,
)
from utils.core.perf_utils import perf_log, should_log_debug
from utils.config.paths import DB_BACKUP_DIR, resolve_path
from utils.business.vat import (
    DEFAULT_VAT_RULE_CODE,
    VAT_RULES,
    compute_vat_breakdown,
    normalize_reference_date,
)
from utils.business.sales_transactions import REFUND_WINDOW_MINUTES, refund_window_status
from utils.business.product_catalog import aggregate_admin_product_rows

NEAR_EXPIRY_DAYS = 15
LOSS_QTY_LIMIT_UN = 10
LOSS_QTY_LIMIT_KG = 10.0
LOSS_VALUE_LIMIT_MZN = 5000
LOSS_TYPES = {"DAMAGE", "EXPIRED", "THEFT", "ADJUSTMENT"}
LOSS_TYPE_LABELS = {
    "ADJUSTMENT": "Ajuste",
    "DAMAGE": "Danificado",
    "EXPIRED": "Expirado",
    "THEFT": "Roubo",
}
EXPIRY_LOSS_REASON = "Data de validade"
# Qualquer perda declarada por um gerente exige validacao administrativa antes
# de alterar o stock. Os limites abaixo mantem-se apenas como parametros de
# analise e de alertas; nao criam excecoes a esta regra.
LOSS_TYPES_ALWAYS_REQUIRING_APPROVAL = set(LOSS_TYPES)
LOSS_RECURRENCE_PERIODS = 3
ARCHIVED_PRODUCT_STATUS = "ARQUIVADO"
ARCHIVED_PRODUCT_REASON = "Removido do catalogo; historico preservado"


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


def _loss_type_label(value):
    """Traduz o código interno de perda apenas para apresentação."""
    code = str(value or "").strip().upper()
    return LOSS_TYPE_LABELS.get(code, code.replace("_", " ").capitalize() or "Perda")


def _inventory_quantity(value, is_sold_by_weight=False, field_name="Quantidade"):
    """Validate discrete stock for units while preserving decimal kg values."""
    quantity = float(value)
    if not bool(is_sold_by_weight) and not quantity.is_integer():
        raise ValueError(f"{field_name} deve ser inteiro para produtos por unidade.")
    return quantity


def _transaction_key_sql(table_alias=""):
    """Expressao SQL que identifica uma transacao, incluindo registos antigos."""
    prefix = f"{table_alias}." if table_alias else ""
    return (
        "COALESCE(NULLIF(TRIM("
        f"{prefix}transaction_code"
        "), ''), 'sale:' || "
        f"{prefix}id)"
    )


def _transaction_count_sql(table_alias=""):
    """Conta vendas finalizadas, e nao as linhas de produto que as compoem."""
    return f"COUNT(DISTINCT {_transaction_key_sql(table_alias)})"


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
        "FROM sales_history WHERE DATE(sale_date) >= ? "
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
        "SELECT COALESCE(SUM(quantity), 0) FROM sales_history "
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
        "FROM products WHERE COALESCE(status, 'ATIVO') <> ? " + scope_sql,
        (ARCHIVED_PRODUCT_STATUS, *scope_params),
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

from database.produce import ProduceInventoryMixin, PRODUCE_MODES


class Database(ProduceInventoryMixin, DatabaseAutomationMixin):
    # Camada principal de acesso ao SQLite.
    SKU_PREFIX_DEFAULT = "LOJA"
    BACKUP_RETENTION_DAYS = 30
    BACKUP_INTERVAL_HOURS = 24
    RECONCILE_INTERVAL_MINUTES = 60
    RECONCILE_DIFF_TOLERANCE = 0.0001
    LOGIN_MAX_FAILED_ATTEMPTS = 5
    LOGIN_LOCK_MINUTES = 15
    SALES_ARCHIVE_AFTER_DAYS = 365
    SALES_ARCHIVE_BATCH_SIZE = 1000

    def __init__(
        self, db_name="inventory.db", db_path=None, db_folder="database", *,
        initialize=True, configure_journal=True,
    ):
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
        self._configure_journal = bool(configure_journal)
        self.backup_root = str(DB_BACKUP_DIR)
        self.current_user = None
        self.current_role = None
        self.current_data_owner = None
        # Mantem apenas o motivo seguro do ultimo login nesta instancia. A
        # interface continua a receber a role ou None, como antes, para nao
        # revelar se um utilizador existe a quem tenta entrar.
        self._last_authentication_status = "unknown"
        self.sku_prefix = self._sanitize_sku_token(
            os.getenv("SKU_PREFIX", self.SKU_PREFIX_DEFAULT),
            fallback=self.SKU_PREFIX_DEFAULT,
            max_len=8,
        )
        self.connect()
        if initialize:
            self.setup()
            self._setup_produce_inventory()
        # A view temporaria inclui o arquivo sem alterar as consultas ja
        # existentes a ``sales_history``. Ela precisa existir em cada conexao,
        # inclusive nas conexoes usadas por workers.
        self._configure_sales_archive()

    def background_connection(self):
        """Captura a sessao e abre/fecha uma conexao na thread consumidora.

        A base desta instancia ja passou por setup; a nova conexao nao deve
        repetir migracoes nem partilhar o cursor ou a transacao da interface.
        """
        db_path = self.db_path
        context = (self.current_user, self.current_role, self.current_data_owner, self.sku_prefix)

        @contextmanager
        def connection():
            db = Database(db_path=db_path, initialize=False, configure_journal=False)
            try:
                db.current_user, db.current_role, db.current_data_owner, db.sku_prefix = context
                # Um worker breve nao necessita do cache de 20 MiB do POS.
                db.conn.execute("PRAGMA cache_size = -4096")
                yield db
            finally:
                db.close()

        return connection()
    
    def connect(self):
        """Conectar ao banco de dados"""
        try:
            # IMPORTANTE: Usamos o self.db_path aqui
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
            self.cursor = self.conn.cursor()
            self.cursor.execute("PRAGMA busy_timeout = 30000")
            self.cursor.execute("PRAGMA foreign_keys = ON")
            try:
                if self._configure_journal:
                    self.cursor.execute("PRAGMA journal_mode = WAL")
                self.cursor.execute("PRAGMA synchronous = NORMAL")
                self.cursor.execute("PRAGMA temp_store = MEMORY")
                self.cursor.execute("PRAGMA cache_size = -20000")
                self.cursor.execute("PRAGMA mmap_size = 134217728")
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

    def _configure_sales_archive(self):
        """Liga o arquivo de vendas e mantem o historico transparente.

        O arquivo contem apenas vendas finalizadas ha mais de um ano sem
        devolucoes. Assim, o POS continua a usar a base operacional pequena,
        enquanto relatorios que consultam ``sales_history`` continuam a ver
        todo o historico.
        """
        archive_path = os.path.join(self.db_folder, "sales_archive.db")
        self.sales_archive_path = archive_path
        try:
            attached = [row[1] for row in self.conn.execute("PRAGMA database_list")]
            if "sales_archive" not in attached:
                self.conn.execute("ATTACH DATABASE ? AS sales_archive", (archive_path,))

            # CTAS preserva exatamente as colunas da versao instalada de
            # sales, sem levar FKs para uma base que deliberadamente nao tem
            # catalogo de produtos. Os IDs mantem-se para auditoria.
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS sales_archive.sales "
                "AS SELECT * FROM main.sales WHERE 0"
            )
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS sales_archive.idx_sales_archive_id "
                "ON sales(id)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS sales_archive.idx_sales_archive_date "
                "ON sales(sale_date)"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS sales_archive.produce_sales "
                "AS SELECT * FROM main.produce_sales WHERE 0"
            )
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS sales_archive.idx_produce_sales_archive_id "
                "ON produce_sales(sale_id)"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS sales_archive.archive_metadata ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

            # Uma TEMP VIEW tem precedencia sobre a view persistente de mesmo
            # nome e pode referenciar uma base ATTACHed (algo que uma view
            # persistente do SQLite nao permite). Vendas arquivadas nunca
            # possuem devolucao, pois sao filtradas no arquivamento.
            self.conn.execute("DROP VIEW IF EXISTS temp.sales_history")
            self.conn.execute(
                "CREATE TEMP VIEW sales_history AS "
                "SELECT s.* FROM main.sales s "
                "LEFT JOIN (SELECT sale_id, COALESCE(SUM(returned_qty), 0) returned_qty "
                "FROM main.sales_returns GROUP BY sale_id) sr ON sr.sale_id = s.id "
                "WHERE COALESCE(sr.returned_qty, 0) <= 0.000001 "
                "UNION ALL SELECT * FROM sales_archive.sales"
            )
            self.conn.commit()
        except sqlite3.Error as exc:
            # Arquivo indisponivel nunca pode impedir o caixa de abrir. As
            # vendas continuam na base principal e a tentativa sera repetida.
            print(f"Erro ao preparar arquivo de vendas: {exc}")

    def archive_sales_older_than(self, days=None, batch_size=None):
        """Move com seguranca vendas antigas para ``sales_archive.db``.

        Apenas vendas sem devolucao sao movidas. A operacao conserva os IDs e
        tambem move metadados de venda avulsa; e uma unica transacao SQLite,
        portanto uma falha nao deixa uma venda apenas em uma das bases.
        Retorna a quantidade efetivamente arquivada.
        """
        days = self.SALES_ARCHIVE_AFTER_DAYS if days is None else max(1, int(days))
        batch_size = self.SALES_ARCHIVE_BATCH_SIZE if batch_size is None else max(1, int(batch_size))
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._configure_sales_archive()
            rows = self.conn.execute(
                "SELECT s.id FROM main.sales s "
                "LEFT JOIN main.sales_returns sr ON sr.sale_id = s.id "
                "WHERE s.sale_date < ? GROUP BY s.id HAVING COUNT(sr.id) = 0 "
                "ORDER BY s.id LIMIT ?",
                (cutoff, batch_size),
            ).fetchall()
            sale_ids = [int(row[0]) for row in rows]
            if not sale_ids:
                return 0
            placeholders = ",".join("?" for _ in sale_ids)
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "INSERT OR IGNORE INTO sales_archive.sales "
                f"SELECT * FROM main.sales WHERE id IN ({placeholders})",
                sale_ids,
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO sales_archive.produce_sales "
                f"SELECT * FROM main.produce_sales WHERE sale_id IN ({placeholders})",
                sale_ids,
            )
            self.conn.execute(
                f"DELETE FROM main.produce_sales WHERE sale_id IN ({placeholders})", sale_ids
            )
            self.conn.execute(
                f"DELETE FROM main.sales WHERE id IN ({placeholders})", sale_ids
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO sales_archive.archive_metadata(key, value) VALUES (?, ?)",
                ("last_archive_at", self._now_str()),
            )
            self.conn.commit()
            return len(sale_ids)
        except (sqlite3.Error, ValueError) as exc:
            self.conn.rollback()
            print(f"Erro ao arquivar vendas antigas: {exc}")
            return 0

    def _run_sales_archive_maintenance(self):
        """Executa no maximo uma vez por dia, apos uma venda confirmada."""
        try:
            row = self.conn.execute(
                "SELECT value FROM sales_archive.archive_metadata WHERE key = 'last_auto_check'"
            ).fetchone()
            today = datetime.now().strftime("%Y-%m-%d")
            if row and str(row[0]) == today:
                return 0
            self.conn.execute(
                "INSERT OR REPLACE INTO sales_archive.archive_metadata(key, value) VALUES (?, ?)",
                ("last_auto_check", today),
            )
            self.conn.commit()
            return self.archive_sales_older_than()
        except sqlite3.Error as exc:
            print(f"Erro na manutencao do arquivo de vendas: {exc}")
            return 0

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
        for table in ("products", "products_archive"):
            # Um cursor de leitura independente permite processar lotes sem
            # materializar o catalogo inteiro nem reescrever SKUs identicos.
            reader = self.conn.execute(f"SELECT id, description, sku FROM {table}")
            try:
                while rows := reader.fetchmany(512):
                    updates = []
                    for product_id, description, current_sku in rows:
                        sku = self._build_sku(product_id, description)
                        if sku != current_sku:
                            updates.append((sku, product_id))
                    if updates:
                        self.cursor.executemany(
                            f"UPDATE {table} SET sku = ? WHERE id = ?", updates
                        )
            finally:
                reader.close()

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
                if "full_name" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
                if "data_owner" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN data_owner TEXT")
                if "email_verified" not in cols:
                    self.cursor.execute(
                        "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0"
                    )
                if "email_verified_at" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
                # Campos de governanca de conta. Sao adicionados separadamente
                # para que bases de dados antigas sejam atualizadas sem perder
                # utilizadores nem as suas palavras-passe com hash.
                if "is_active" not in cols:
                    self.cursor.execute(
                        "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
                    )
                if "must_change_password" not in cols:
                    self.cursor.execute(
                        "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
                    )
                if "created_at" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
                if "password_changed_at" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")
                if "last_login_at" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
                if "failed_login_attempts" not in cols:
                    self.cursor.execute(
                        "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0"
                    )
                if "locked_until" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
                if "blocked_at" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN blocked_at TEXT")
                if "blocked_reason" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN blocked_reason TEXT")
                self.cursor.execute(
                    "UPDATE users SET email = NULL "
                    "WHERE email IS NOT NULL AND TRIM(email) = ''"
                )
                self.cursor.execute(
                    "UPDATE users SET email = LOWER(TRIM(email)) WHERE email IS NOT NULL"
                )
                self.cursor.execute(
                    "UPDATE users SET is_active = 1 WHERE is_active IS NULL"
                )
                self.cursor.execute(
                    "UPDATE users SET must_change_password = 0 "
                    "WHERE must_change_password IS NULL"
                )
                self.cursor.execute(
                    "UPDATE users SET failed_login_attempts = 0 "
                    "WHERE failed_login_attempts IS NULL"
                )
            except sqlite3.Error as e:
                print(f"Erro ao adicionar colunas de contacto: {e}")

            # Uma instalacao nova deve ter somente um administrador. Bases
            # antigas podem conter mais de um admin; nesses casos preservamos
            # os dados tal como estao e deixamos a regularizacao para uma
            # decisao explicita, sem criar um indice que pudesse falhar.
            try:
                self.cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
                admin_count = int(self.cursor.fetchone()[0] or 0)
                if admin_count <= 1:
                    self.cursor.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_single_admin "
                        "ON users(role) WHERE role = 'admin'"
                    )
            except sqlite3.Error as e:
                print(f"Erro ao preparar regra de administrador unico: {e}")

            # Codigos de uso unico para confirmar o e-mail cadastrado.
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS email_verifications (
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
                "CREATE INDEX IF NOT EXISTS idx_email_verifications_username "
                "ON email_verifications(username)"
            )

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
            # Codigos longos de recuperacao offline, gerados pelo administrador.
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS account_recovery_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users(username)
            )''')
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_account_recovery_codes_username "
                "ON account_recovery_codes(username)"
            )
            # Recibo local de uso do codigo SIGE-ADM1. Impede que o mesmo
            # codigo volte a criar uma conta mesmo se alguem tentar apagar a
            # conta admin pela interface normal.
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_provisioning_receipts (
                provisioning_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                consumed_at TEXT NOT NULL
            )''')
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
            # Regras comerciais configuradas pelo administrador.  Ficam
            # separadas do produto para que uma alteracao seja aplicada de
            # forma uniforme aos proximos cadastros e edicoes.
            self.cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS business_rules (
                    owner_username TEXT NOT NULL,
                    rule_key TEXT NOT NULL,
                    rule_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT,
                    PRIMARY KEY (owner_username, rule_key)
                )
                '''
            )
            # Campos livres do catalogo: o administrador pode adaptar o
            # formulario sem alterar o esquema principal de products.
            self.cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS product_custom_fields (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_username TEXT NOT NULL,
                    field_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    field_type TEXT NOT NULL DEFAULT 'TEXT',
                    required INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_username, field_key)
                )
                '''
            )
            self.cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS product_custom_field_values (
                    product_id INTEGER NOT NULL,
                    field_id INTEGER NOT NULL,
                    value TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (product_id, field_id),
                    FOREIGN KEY (product_id) REFERENCES products(id),
                    FOREIGN KEY (field_id) REFERENCES product_custom_fields(id)
                )
                '''
            )
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
            ensure_column("sales", "transaction_code", "TEXT")
            ensure_column("sales", "payment_method", "TEXT DEFAULT 'cash'")
            ensure_column("sales", "discount_amount", "REAL DEFAULT 0")
            ensure_column("sales", "discount_reason", "TEXT")
            ensure_column("sales", "discount_authorized_by", "TEXT")
            ensure_column("sales", "cash_session_id", "INTEGER")
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_date_transaction "
                "ON sales(sale_date, transaction_code)"
            )

            # Cabeçalho de uma venda composta. Permite que clientes remotos
            # repitam com segurança a mesma transação após uma falha de rede:
            # a chave da transação é única e todas as linhas são confirmadas
            # na mesma transação SQLite.
            self.cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS sale_transactions (
                    transaction_code TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    created_role TEXT,
                    terminal_id TEXT,
                    payment_method TEXT NOT NULL DEFAULT 'cash',
                    cash_session_id INTEGER,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'COMPLETED',
                    owner_username TEXT
                )
                '''
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sale_transactions_owner_date "
                "ON sale_transactions(owner_username, created_at)"
            )

            # Abertura e fecho de caixa por atendente/terminal.
            self.cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS cash_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'manager',
                    terminal_id TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    opening_amount REAL NOT NULL DEFAULT 0,
                    opening_note TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    closed_at TEXT,
                    counted_amount REAL,
                    expected_cash REAL,
                    difference_amount REAL,
                    closing_note TEXT,
                    closed_by TEXT,
                    owner_username TEXT
                )
                '''
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_cash_sessions_open "
                "ON cash_sessions(username, terminal_id, status)"
            )

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

            # Fonte unica para consultas historicas de vendas. Qualquer item
            # com estorno continua preservado somente nas tabelas de auditoria
            # (sales_returns e stock_movements), mas fica fora de historicos,
            # indicadores e relatorios de venda.
            self.cursor.execute("DROP VIEW IF EXISTS sales_history")
            self.cursor.execute(
                """
                CREATE VIEW sales_history AS
                SELECT s.*
                FROM sales s
                LEFT JOIN (
                    SELECT sale_id, COALESCE(SUM(returned_qty), 0) AS returned_qty
                    FROM sales_returns
                    GROUP BY sale_id
                ) sr ON sr.sale_id = s.id
                WHERE COALESCE(sr.returned_qty, 0) <= 0.000001
                """
            )

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

            # Fotos obrigatorias para perdas por dano. A imagem fica fora do
            # SQLite; o banco guarda apenas o caminho privado e metadados.
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS damage_evidence (
                id TEXT PRIMARY KEY,
                movement_id INTEGER UNIQUE,
                storage_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                analysis_json TEXT NOT NULL,
                analysis_status TEXT NOT NULL DEFAULT 'APPROVED',
                model TEXT,
                analyzed_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT,
                owner_username TEXT,
                FOREIGN KEY (movement_id) REFERENCES stock_movements(id)
            )''')

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
                '''
                CREATE TABLE IF NOT EXISTS physical_inventories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'COUNTING',
                    started_at TEXT NOT NULL,
                    started_by TEXT NOT NULL,
                    terminal_id TEXT,
                    note TEXT,
                    completed_at TEXT,
                    completed_by TEXT,
                    cancelled_at TEXT,
                    cancelled_by TEXT,
                    owner_username TEXT
                )
                '''
            )
            self.cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS physical_inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inventory_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    product_name TEXT NOT NULL,
                    unit TEXT NOT NULL DEFAULT 'UN',
                    snapshot_qty REAL NOT NULL DEFAULT 0,
                    counted_qty REAL,
                    difference_qty REAL,
                    counted_at TEXT,
                    counted_by TEXT,
                    count_note TEXT,
                    applied_difference REAL,
                    movement_id INTEGER,
                    UNIQUE(inventory_id, product_id),
                    FOREIGN KEY (inventory_id) REFERENCES physical_inventories(id),
                    FOREIGN KEY (product_id) REFERENCES products(id),
                    FOREIGN KEY (movement_id) REFERENCES stock_movements(id)
                )
                '''
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_inventory_status ON physical_inventories(status, started_at DESC)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_inventory_items_session ON physical_inventory_items(inventory_id, counted_at)"
            )

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
                    "damage_evidence",
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
                "CREATE INDEX IF NOT EXISTS idx_damage_evidence_owner_status_date "
                "ON damage_evidence (owner_username, analysis_status, created_at)"
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
                "CREATE INDEX IF NOT EXISTS idx_products_owner_status "
                "ON products (COALESCE(owner_username, ''), status)"
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
                "CREATE INDEX IF NOT EXISTS idx_products_barcode_normalized "
                "ON products (LOWER(TRIM(barcode))) "
                "WHERE barcode IS NOT NULL AND TRIM(barcode) <> ''"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_owner_barcode_normalized "
                "ON products (COALESCE(owner_username, ''), LOWER(TRIM(barcode))) "
                "WHERE barcode IS NOT NULL AND TRIM(barcode) <> ''"
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
            # Os filtros historicos usam DATE e COALESCE; os indices nas
            # colunas originais nao cobrem estas expressoes.
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_owner_day "
                "ON sales (COALESCE(owner_username, ''), DATE(sale_date))"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_terminal_date "
                "ON sales (terminal_id, sale_date)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_logs_timestamp "
                "ON user_logs (timestamp)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_logs_scope_timestamp "
                "ON user_logs (COALESCE(owner_username, ''), timestamp DESC)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_logs_scope_role_timestamp "
                "ON user_logs (COALESCE(owner_username, ''), role, timestamp DESC)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_logs_scope_action_timestamp "
                "ON user_logs (COALESCE(owner_username, ''), action, timestamp DESC)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_logs_scope_user_timestamp "
                "ON user_logs (COALESCE(owner_username, ''), username, timestamp DESC)"
            )
            
            self.conn.commit()
            try:
                self.cleanup_unbound_damage_evidence(hours=24)
            except Exception:
                pass
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
        """Valida credenciais sem revelar estados sensiveis ao ecrã de login.

        A API historica continua a devolver a role quando a autenticacao e
        valida e ``None`` nos restantes casos. O motivo seguro fica disponivel
        em :meth:`get_last_authentication_status` para a propria aplicacao.
        """
        username = str(username or "").strip()
        password_text = str(password or "")
        self._last_authentication_status = "invalid"
        if not username or not password_text:
            return None
        try:
            self.cursor.execute(
                """
                SELECT password, role, COALESCE(is_active, 1),
                       COALESCE(failed_login_attempts, 0), locked_until
                FROM users WHERE username = ?
                """,
                (username,),
            )
            result = self.cursor.fetchone()
            if not result:
                return None

            stored_hash, role, is_active, failed_attempts, locked_until_raw = result
            if not bool(is_active):
                self._last_authentication_status = "inactive"
                return None

            now = datetime.now().replace(microsecond=0)
            locked_until = _parse_datetime_value(locked_until_raw)
            if locked_until and locked_until > now:
                self._last_authentication_status = "locked"
                return None
            if locked_until:
                # Uma suspensao temporaria vencida e limpa antes da nova
                # tentativa, para que o contador recomece de forma previsivel.
                self.cursor.execute(
                    "UPDATE users SET failed_login_attempts = 0, locked_until = NULL "
                    "WHERE username = ?",
                    (username,),
                )
                self.conn.commit()
                failed_attempts = 0

            if isinstance(stored_hash, str):
                stored_hash = stored_hash.encode("utf-8")
            try:
                authenticated = bcrypt.checkpw(password_text.encode("utf-8"), stored_hash)
            except (TypeError, ValueError):
                authenticated = False

            if authenticated:
                self.cursor.execute(
                    """
                    UPDATE users
                    SET last_login_at = ?, failed_login_attempts = 0,
                        locked_until = NULL
                    WHERE username = ?
                    """,
                    (now.isoformat(), username),
                )
                self.conn.commit()
                self._last_authentication_status = "authenticated"
                return role

            attempts = max(0, int(failed_attempts or 0)) + 1
            if attempts >= self.LOGIN_MAX_FAILED_ATTEMPTS:
                lock_until = now + timedelta(minutes=self.LOGIN_LOCK_MINUTES)
                self.cursor.execute(
                    """
                    UPDATE users
                    SET failed_login_attempts = ?, locked_until = ?
                    WHERE username = ?
                    """,
                    (attempts, lock_until.isoformat(), username),
                )
                self._last_authentication_status = "locked"
            else:
                self.cursor.execute(
                    "UPDATE users SET failed_login_attempts = ? WHERE username = ?",
                    (attempts, username),
                )
                self._last_authentication_status = "invalid"
            self.conn.commit()
            return None
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao validar usuÃƒÆ’Ã‚Â¡rio: {e}")
            try:
                self.conn.rollback()
            except sqlite3.Error:
                pass
            self._last_authentication_status = "error"
            return None

    def get_last_authentication_status(self):
        """Devolve o estado seguro da ultima autenticacao desta instancia."""
        return self._last_authentication_status

    @staticmethod
    def _notify_superadmin_account_event(username, event_name):
        """Entrega um alerta opcional sem deixar SMTP afetar a transacao local."""
        try:
            # A funcao de alertas envia SMTP de forma assincrona. Importacao
            # tardia mantem compatibilidade com instalacoes ainda sem o modulo.
            from licensing.account_events import notify_superadmin_account_event

            notify_superadmin_account_event(username, event_name)
        except Exception:
            # O evento e adicional. Falhas de e-mail nunca podem desfazer uma
            # alteracao local ja confirmada.
            pass

    def is_password_change_required(self, username):
        """Indica se a conta tem de trocar a palavra-passe antes de uso normal."""
        username = str(username or "").strip()
        if not username:
            return False
        try:
            self.cursor.execute(
                "SELECT COALESCE(must_change_password, 0) FROM users WHERE username = ?",
                (username,),
            )
            row = self.cursor.fetchone()
            return bool(row and row[0])
        except sqlite3.Error as e:
            print(f"Erro ao consultar troca obrigatoria de senha: {e}")
            return False

    def get_user_security_status(self, username):
        """Resumo seguro de governanca; nunca inclui a palavra-passe nem hash."""
        username = str(username or "").strip()
        if not username:
            return None
        try:
            self.cursor.execute(
                """
                SELECT username, role, COALESCE(is_active, 1),
                       COALESCE(must_change_password, 0), created_at,
                       password_changed_at, last_login_at,
                       COALESCE(failed_login_attempts, 0), locked_until,
                       blocked_at, blocked_reason
                FROM users WHERE username = ?
                """,
                (username,),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            keys = (
                "username", "role", "is_active", "must_change_password",
                "created_at", "password_changed_at", "last_login_at",
                "failed_login_attempts", "locked_until", "blocked_at",
                "blocked_reason",
            )
            status = dict(zip(keys, row))
            status["is_active"] = bool(status["is_active"])
            status["must_change_password"] = bool(status["must_change_password"])
            status["failed_login_attempts"] = int(status["failed_login_attempts"] or 0)
            return status
        except sqlite3.Error as e:
            print(f"Erro ao consultar seguranca da conta: {e}")
            return None


    def has_admin(self):
        """Verificar se existe algum admin cadastrado"""
        try:
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            return self.cursor.fetchone()[0] > 0
        except (sqlite3.Error, ValueError) as e:
            print(f"Erro ao verificar admin: {e}")
            return False

    def _email_in_use(self, email, exclude_username=None):
        normalized = normalize_email(email)
        if not normalized:
            return False
        if exclude_username:
            self.cursor.execute(
                "SELECT 1 FROM users "
                "WHERE LOWER(TRIM(COALESCE(email, ''))) = ? AND username != ? LIMIT 1",
                (normalized, exclude_username),
            )
        else:
            self.cursor.execute(
                "SELECT 1 FROM users "
                "WHERE LOWER(TRIM(COALESCE(email, ''))) = ? LIMIT 1",
                (normalized,),
            )
        return self.cursor.fetchone() is not None

    @staticmethod
    def _mask_email(email):
        normalized = normalize_email(email)
        if not is_valid_email(normalized):
            return None
        local, domain = normalized.rsplit("@", 1)
        if len(local) <= 2:
            masked_local = local[:1] + "*" * max(1, len(local) - 1)
        else:
            masked_local = local[:2] + "*" * max(2, len(local) - 2)
        return f"{masked_local}@{domain}"

    @staticmethod
    def _new_six_digit_code():
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _code_matches(code, stored_hash):
        candidate = str(code or "").strip()
        if not candidate or not stored_hash:
            return False
        hashed = stored_hash.encode("utf-8") if isinstance(stored_hash, str) else stored_hash
        try:
            return bcrypt.checkpw(candidate.encode("utf-8"), hashed)
        except (TypeError, ValueError):
            return False

    def _assign_unowned_records_to_first_admin(self, username):
        """Associa dados legados ao primeiro admin, sem tocar em dados ja donos."""
        for table in (
            "products",
            "products_archive",
            "sales",
            "sales_returns",
            "stock_movements",
            "damage_evidence",
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

    @staticmethod
    def _valid_bcrypt_hash(password_hash):
        """Confirma formato bcrypt sem guardar ou revelar nenhum segredo."""
        if isinstance(password_hash, str):
            password_hash = password_hash.encode("utf-8")
        if not isinstance(password_hash, (bytes, bytearray)):
            return None
        password_hash = bytes(password_hash)
        if len(password_hash) != 60 or not password_hash.startswith((b"$2a$", b"$2b$", b"$2y$")):
            return None
        try:
            # A comparacao e intencionalmente falsa; bcrypt apenas valida o
            # formato/custo do hash recebido no codigo assinado.
            bcrypt.checkpw(b"provisioning-hash-validation", password_hash)
        except (TypeError, ValueError):
            return None
        return password_hash

    def create_admin(self, username, password, email=None):
        """Cria o unico admin de uma instalacao quando ainda nao existe um."""
        username = str(username or "").strip()
        password_text = str(password or "")
        if not username or not password_text:
            return False
        normalized_email = normalize_email(email) if email is not None else None
        if normalized_email == "":
            normalized_email = None
        if normalized_email is not None and not is_valid_email(normalized_email):
            return False
        try:
            # O bloqueio de escrita elimina a corrida entre duas tentativas de
            # criacao e complementa o indice parcial nas bases novas.
            self.cursor.execute("BEGIN IMMEDIATE")
            if normalized_email is not None and self._email_in_use(normalized_email):
                self.conn.rollback()
                return False
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            if int(self.cursor.fetchone()[0] or 0) > 0:
                self.conn.rollback()
                return False
            self.cursor.execute("SELECT COUNT(*) FROM users")
            had_users = int(self.cursor.fetchone()[0] or 0) > 0
            now = datetime.now().replace(microsecond=0).isoformat()
            hashed_password = bcrypt.hashpw(password_text.encode("utf-8"), bcrypt.gensalt())
            self.cursor.execute(
                """
                INSERT INTO users (
                    username, password, role, email, email_verified,
                    email_verified_at, data_owner, is_active,
                    must_change_password, created_at, password_changed_at,
                    failed_login_attempts, locked_until
                ) VALUES (?, ?, 'admin', ?, 0, NULL, ?, 1, 0, ?, ?, 0, NULL)
                """,
                (username, hashed_password, normalized_email, username, now, now),
            )
            if not had_users:
                self._assign_unowned_records_to_first_admin(username)
            self.conn.commit()
            self.log_action(username, "admin", "CREATE_USER", f"Admin criado: {username}")
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao criar admin: {e}")
            self.conn.rollback()
            return False

    def create_provisioned_admin(self, username, password_hash, email=None, provisioning_id=None):
        """Importa o unico admin a partir de credenciais bcrypt provisionadas.

        ``password_hash`` e ``provisioning_id`` veem do codigo de
        provisionamento assinado. O recibo do identificador torna a
        importacao de uso unico; a palavra-passe temporaria nunca chega a
        esta base em texto.
        """
        username = str(username or "").strip()
        hashed_password = self._valid_bcrypt_hash(password_hash)
        try:
            code_id = str(uuid.UUID(str(provisioning_id or "")))
        except (ValueError, AttributeError):
            code_id = ""
        if not username or not hashed_password or not code_id:
            return False
        normalized_email = normalize_email(email) if email is not None else None
        if normalized_email == "":
            normalized_email = None
        if normalized_email is not None and not is_valid_email(normalized_email):
            return False
        try:
            self.cursor.execute("BEGIN IMMEDIATE")
            self.cursor.execute(
                "SELECT 1 FROM admin_provisioning_receipts WHERE provisioning_id = ?",
                (code_id,),
            )
            if self.cursor.fetchone():
                self.conn.rollback()
                return False
            if normalized_email is not None and self._email_in_use(normalized_email):
                self.conn.rollback()
                return False
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            if int(self.cursor.fetchone()[0] or 0) > 0:
                self.conn.rollback()
                return False
            self.cursor.execute("SELECT COUNT(*) FROM users")
            had_users = int(self.cursor.fetchone()[0] or 0) > 0
            now = datetime.now().replace(microsecond=0).isoformat()
            self.cursor.execute(
                """
                INSERT INTO users (
                    username, password, role, email, email_verified,
                    email_verified_at, data_owner, is_active,
                    must_change_password, created_at, password_changed_at,
                    failed_login_attempts, locked_until
                ) VALUES (?, ?, 'admin', ?, 0, NULL, ?, 1, 1, ?, NULL, 0, NULL)
                """,
                (username, hashed_password, normalized_email, username, now),
            )
            if not had_users:
                self._assign_unowned_records_to_first_admin(username)
            self.cursor.execute(
                "INSERT INTO admin_provisioning_receipts (provisioning_id, username, consumed_at) "
                "VALUES (?, ?, ?)",
                (code_id, username, now),
            )
            self.conn.commit()
            self.log_action(
                username,
                "admin",
                "CREATE_PROVISIONED_ADMIN",
                "Conta admin provisionada; troca obrigatoria de palavra-passe.",
            )
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao importar admin provisionado: {e}")
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
        """Atualiza a senha e encerra o estado de credencial temporaria."""
        username = str(username or "").strip()
        password_text = str(new_password or "")
        if not username or not password_text:
            return False
        try:
            hashed_password = bcrypt.hashpw(password_text.encode("utf-8"), bcrypt.gensalt())
            now = datetime.now().replace(microsecond=0).isoformat()
            if role:
                self.cursor.execute(
                    """
                    UPDATE users
                    SET password = ?, must_change_password = 0,
                        password_changed_at = ?, failed_login_attempts = 0,
                        locked_until = NULL
                    WHERE username = ? AND role = ?
                    """,
                    (hashed_password, now, username, role),
                )
            else:
                self.cursor.execute(
                    """
                    UPDATE users
                    SET password = ?, must_change_password = 0,
                        password_changed_at = ?, failed_login_attempts = 0,
                        locked_until = NULL
                    WHERE username = ?
                    """,
                    (hashed_password, now, username),
                )
            if self.cursor.rowcount != 1:
                self.conn.rollback()
                return False
            # Um reset/recuperacao anterior nao pode ser reutilizado depois de
            # uma nova palavra-passe ter sido escolhida.
            self.cursor.execute("DELETE FROM password_resets WHERE username = ?", (username,))
            self.cursor.execute(
                "DELETE FROM account_recovery_codes WHERE username = ? AND used_at IS NULL",
                (username,),
            )
            self.conn.commit()
            self._notify_superadmin_account_event(username, "PASSWORD_CHANGED")
            self.log_action(username, role or self.get_user_role(username) or "user", "PASSWORD_CHANGED", "Palavra-passe alterada")
            return True
        except (sqlite3.Error, TypeError, ValueError) as e:
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
            old_username = str(old_username or "").strip()
            new_username = str(new_username or "").strip()
            password_text = str(new_password or "")
            if not old_username or not new_username or not password_text:
                return False
            self.cursor.execute(
                "SELECT COUNT(*) FROM users WHERE username = ? AND username != ?",
                (new_username, old_username),
            )
            if self.cursor.fetchone()[0] > 0:
                return False

            hashed_password = bcrypt.hashpw(password_text.encode("utf-8"), bcrypt.gensalt())
            now = datetime.now().replace(microsecond=0).isoformat()
            self.cursor.execute(
                """
                UPDATE users
                SET username = ?, password = ?, must_change_password = 0,
                    password_changed_at = ?, failed_login_attempts = 0,
                    locked_until = NULL
                WHERE username = ? AND role = 'admin'
                """,
                (new_username, hashed_password, now, old_username),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return False
            self.cursor.execute(
                "DELETE FROM password_resets WHERE username = ?", (old_username,)
            )
            self.cursor.execute(
                "DELETE FROM account_recovery_codes WHERE username = ? AND used_at IS NULL",
                (old_username,),
            )
            self.conn.commit()
            self._notify_superadmin_account_event(new_username, "PASSWORD_CHANGED")
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

    def get_user_full_name(self, username):
        """Devolve o nome de apresentacao do utilizador, nunca o login."""
        username = str(username or "").strip()
        if not username:
            return ""
        try:
            self.cursor.execute(
                "SELECT COALESCE(NULLIF(TRIM(full_name), ''), '') FROM users WHERE username = ?",
                (username,),
            )
            row = self.cursor.fetchone()
            return str(row[0] or "").strip() if row else ""
        except sqlite3.Error as e:
            print(f"Erro ao obter nome completo: {e}")
            return ""

    def set_user_full_name(self, username, full_name):
        """Guarda o nome que deve aparecer em documentos de venda."""
        username = str(username or "").strip()
        full_name = " ".join(str(full_name or "").split())
        if not username or len(full_name) < 3:
            return False
        try:
            self.cursor.execute(
                "UPDATE users SET full_name = ? WHERE username = ?",
                (full_name, username),
            )
            if self.cursor.rowcount != 1:
                self.conn.rollback()
                return False
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao guardar nome completo: {e}")
            self.conn.rollback()
            return False

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
        """Cria apenas gerentes; admins entram pelo provisionamento assinado."""
        try:
            username = str(username or "").strip()
            role = str(role or "").strip().lower()
            if not username or not password or role != "manager":
                return False
            email = normalize_email(email) if email is not None else None
            if email == "":
                email = None
            if email is not None:
                if not is_valid_email(email) or self._email_in_use(email):
                    return False
            phone = str(phone).strip() if phone else None
            owner = str(data_owner or username or "").strip() or username
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            now = datetime.now().replace(microsecond=0).isoformat()
            self.cursor.execute(
                """
                INSERT INTO users (
                    username, password, role, email, phone, data_owner,
                    email_verified, email_verified_at, is_active,
                    must_change_password, created_at, password_changed_at,
                    failed_login_attempts, locked_until
                ) VALUES (?, ?, 'manager', ?, ?, ?, 0, NULL, 1, 0, ?, ?, 0, NULL)
                """,
                (username, hashed_password, email, phone, owner, now, now),
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

    def update_user_email(self, username, email):
        """Atualiza o endereco cadastrado e exige uma nova verificacao."""
        username = str(username or "").strip()
        normalized = normalize_email(email)
        if not username or not is_valid_email(normalized):
            return False
        try:
            self.cursor.execute(
                "SELECT email FROM users WHERE username = ?",
                (username,),
            )
            row = self.cursor.fetchone()
            if not row or self._email_in_use(normalized, exclude_username=username):
                return False

            current = normalize_email(row[0])
            if current == normalized:
                if row[0] != normalized:
                    self.cursor.execute(
                        "UPDATE users SET email = ? WHERE username = ?",
                        (normalized, username),
                    )
                    self.conn.commit()
                return True

            self.cursor.execute(
                "UPDATE users SET email = ?, email_verified = 0, email_verified_at = NULL "
                "WHERE username = ?",
                (normalized, username),
            )
            self.cursor.execute(
                "DELETE FROM email_verifications WHERE username = ?",
                (username,),
            )
            self.cursor.execute(
                "DELETE FROM password_resets WHERE username = ?",
                (username,),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Erro ao atualizar e-mail: {e}")
            self.conn.rollback()
            return False

    def get_user_email_status(self, username):
        """Retorna apenas o estado e uma versao mascarada do e-mail."""
        try:
            self.cursor.execute(
                "SELECT email, COALESCE(email_verified, 0) FROM users WHERE username = ?",
                (str(username or "").strip(),),
            )
            row = self.cursor.fetchone()
            if not row:
                return {"has_email": False, "verified": False, "masked_email": None}
            has_email = is_valid_email(row[0])
            return {
                "has_email": has_email,
                "verified": bool(has_email and row[1]),
                "masked_email": self._mask_email(row[0]) if has_email else None,
            }
        except sqlite3.Error as e:
            print(f"Erro ao obter estado do e-mail: {e}")
            return {"has_email": False, "verified": False, "masked_email": None}

    def is_user_email_verified(self, username):
        return bool(self.get_user_email_status(username).get("verified"))

    @staticmethod
    def _code_retry_after(last_sent_at, resend_seconds, now):
        if not last_sent_at:
            return 0
        try:
            sent_at = datetime.fromisoformat(str(last_sent_at))
        except (TypeError, ValueError):
            return 0
        remaining = float(resend_seconds) - (now - sent_at).total_seconds()
        return max(0, int(remaining) + (1 if remaining > int(remaining) else 0))

    def request_email_verification(self, username, resend_seconds=60, expiry_minutes=10):
        """Envia um codigo ao endereco ja armazenado no cadastro."""
        username = str(username or "").strip()
        resend_seconds = max(60, min(3600, int(resend_seconds or 60)))
        expiry_minutes = max(1, min(10, int(expiry_minutes or 10)))
        try:
            self.cursor.execute(
                "SELECT email, COALESCE(email_verified, 0) FROM users WHERE username = ?",
                (username,),
            )
            user = self.cursor.fetchone()
            if not user:
                return {"ok": False, "reason": "user_not_found"}
            email, verified = user
            if verified:
                return {"ok": True, "reason": "already_verified", "retry_after": 0}
            if not email:
                return {"ok": False, "reason": "no_email"}
            email = normalize_email(email)
            if not is_valid_email(email):
                return {"ok": False, "reason": "invalid_email"}

            now = datetime.now().replace(microsecond=0)
            self.cursor.execute(
                "SELECT last_sent_at FROM email_verifications WHERE username = ?",
                (username,),
            )
            record = self.cursor.fetchone()
            retry_after = self._code_retry_after(
                record[0] if record else None, resend_seconds, now
            )
            if retry_after:
                return {
                    "ok": False,
                    "reason": "rate_limited",
                    "retry_after": retry_after,
                }

            code = self._new_six_digit_code()
            code_hash = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            expires_at = now + timedelta(minutes=expiry_minutes)
            try:
                send_email_verification_code(email, username, code)
            except EmailServiceError as exc:
                print(f"Erro ao enviar verificacao de e-mail: {exc}")
                return {"ok": False, "reason": "email_unavailable"}

            self.cursor.execute(
                """
                INSERT INTO email_verifications
                    (username, code_hash, expires_at, attempts, last_sent_at, created_at)
                VALUES (?, ?, ?, 0, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    code_hash = excluded.code_hash,
                    expires_at = excluded.expires_at,
                    attempts = 0,
                    last_sent_at = excluded.last_sent_at,
                    created_at = excluded.created_at
                """,
                (
                    username,
                    code_hash,
                    expires_at.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self.conn.commit()
            return {
                "ok": True,
                "reason": "sent",
                "retry_after": resend_seconds,
                "expires_in": expiry_minutes * 60,
            }
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao solicitar verificacao de e-mail: {e}")
            self.conn.rollback()
            return {"ok": False, "reason": "error"}

    def confirm_email_verification(self, username, code, max_attempts=5):
        """Confirma um codigo valido, dentro do prazo e ainda nao utilizado."""
        username = str(username or "").strip()
        max_attempts = max(1, min(5, int(max_attempts or 5)))
        try:
            self.cursor.execute(
                "SELECT code_hash, expires_at, COALESCE(attempts, 0) "
                "FROM email_verifications WHERE username = ?",
                (username,),
            )
            row = self.cursor.fetchone()
            if not row:
                return {"ok": False, "reason": "not_found"}

            code_hash, expires_raw, attempts = row
            now = datetime.now().replace(microsecond=0)
            try:
                expires_at = datetime.fromisoformat(str(expires_raw))
            except (TypeError, ValueError):
                expires_at = now - timedelta(seconds=1)
            if now >= expires_at:
                self.cursor.execute(
                    "DELETE FROM email_verifications WHERE username = ?", (username,)
                )
                self.conn.commit()
                return {"ok": False, "reason": "expired"}

            if not self._code_matches(code, code_hash):
                attempts = int(attempts or 0) + 1
                if attempts >= max_attempts:
                    self.cursor.execute(
                        "DELETE FROM email_verifications WHERE username = ?", (username,)
                    )
                    self.conn.commit()
                    return {"ok": False, "reason": "too_many_attempts", "remaining": 0}
                self.cursor.execute(
                    "UPDATE email_verifications SET attempts = ? WHERE username = ?",
                    (attempts, username),
                )
                self.conn.commit()
                return {
                    "ok": False,
                    "reason": "invalid",
                    "remaining": max_attempts - attempts,
                }

            verified_at = now.isoformat()
            self.cursor.execute(
                "UPDATE users SET email_verified = 1, email_verified_at = ? "
                "WHERE username = ?",
                (verified_at, username),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            self.cursor.execute(
                "DELETE FROM email_verifications WHERE username = ? AND code_hash = ?",
                (username, code_hash),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            self.conn.commit()
            return {"ok": True, "reason": "verified"}
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao confirmar e-mail: {e}")
            self.conn.rollback()
            return {"ok": False, "reason": "error"}

    def generate_recovery_codes(self, username, count=8):
        """Gera codigos offline; o texto claro e devolvido apenas nesta operacao."""
        username = str(username or "").strip()
        try:
            count = max(4, min(12, int(count or 8)))
            self.cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
            user = self.cursor.fetchone()
            if not user:
                return {"ok": False, "reason": "not_found"}
            now = datetime.now().replace(microsecond=0).isoformat()
            codes = []
            self.cursor.execute("DELETE FROM account_recovery_codes WHERE username = ?", (username,))
            for _ in range(count):
                raw = secrets.token_hex(8).upper()
                code = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:]}"
                code_hash = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                self.cursor.execute(
                    "INSERT INTO account_recovery_codes "
                    "(username, code_hash, created_at) VALUES (?, ?, ?)",
                    (username, code_hash, now),
                )
                codes.append(code)
            self.conn.commit()
            return {"ok": True, "username": username, "codes": codes, "created_at": now}
        except (sqlite3.Error, TypeError, ValueError) as exc:
            print(f"Erro ao gerar codigos de recuperacao: {exc}")
            self.conn.rollback()
            return {"ok": False, "reason": "error"}

    def confirm_recovery_code(self, username, code, new_password, min_password_length=8):
        """Usa um codigo offline uma unica vez para trocar a senha."""
        username = str(username or "").strip()
        code = str(code or "").strip().upper()
        min_password_length = max(8, int(min_password_length or 8))
        if len(str(new_password or "")) < min_password_length:
            return {"ok": False, "reason": "weak_password", "min_length": min_password_length}
        try:
            self.cursor.execute(
                "SELECT id, code_hash FROM account_recovery_codes "
                "WHERE username = ? AND used_at IS NULL",
                (username,),
            )
            rows = self.cursor.fetchall()
            matched_id = None
            for row_id, code_hash in rows:
                if self._code_matches(code, code_hash):
                    matched_id = row_id
                    break
            if matched_id is None:
                return {"ok": False, "reason": "invalid"}
            hashed_password = bcrypt.hashpw(str(new_password).encode("utf-8"), bcrypt.gensalt())
            now = datetime.now().replace(microsecond=0).isoformat()
            self.cursor.execute(
                "UPDATE account_recovery_codes SET used_at = ? "
                "WHERE id = ? AND used_at IS NULL", (now, matched_id)
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return {"ok": False, "reason": "invalid"}
            self.cursor.execute(
                """
                UPDATE users
                SET password = ?, must_change_password = 0,
                    password_changed_at = ?, failed_login_attempts = 0,
                    locked_until = NULL
                WHERE username = ?
                """,
                (hashed_password, now, username),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            self.cursor.execute(
                "DELETE FROM account_recovery_codes WHERE username = ? AND used_at IS NULL",
                (username,),
            )
            self.cursor.execute("DELETE FROM password_resets WHERE username = ?", (username,))
            self.conn.commit()
            self._notify_superadmin_account_event(username, "PASSWORD_CHANGED")
            return {"ok": True, "reason": "password_reset"}
        except (sqlite3.Error, TypeError, ValueError) as exc:
            print(f"Erro ao confirmar codigo de recuperacao: {exc}")
            self.conn.rollback()
            return {"ok": False, "reason": "error"}

    def request_password_reset(self, username, resend_seconds=60, expiry_minutes=10):
        """Solicita recuperacao sem aceitar ou revelar o endereco de destino."""
        username = str(username or "").strip()
        resend_seconds = max(60, min(3600, int(resend_seconds or 60)))
        expiry_minutes = max(1, min(10, int(expiry_minutes or 10)))
        generic = {
            "ok": True,
            "reason": "accepted",
            "retry_after": resend_seconds,
        }
        try:
            self.cursor.execute("SELECT email FROM users WHERE username = ?", (username,))
            user = self.cursor.fetchone()
            if not user or not user[0] or not is_valid_email(user[0]):
                return generic
            email = normalize_email(user[0])

            now = datetime.now().replace(microsecond=0)
            self.cursor.execute(
                "SELECT last_sent_at FROM password_resets WHERE username = ?",
                (username,),
            )
            record = self.cursor.fetchone()
            retry_after = self._code_retry_after(
                record[0] if record else None, resend_seconds, now
            )
            if retry_after:
                return {"ok": True, "reason": "accepted", "retry_after": retry_after}

            code = self._new_six_digit_code()
            code_hash = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            expires_at = now + timedelta(minutes=expiry_minutes)
            try:
                send_password_reset_code(email, username, code)
            except EmailServiceError as exc:
                print(f"Erro ao enviar recuperacao de senha: {exc}")
                return {"ok": False, "reason": "email_unavailable"}

            self.cursor.execute(
                """
                INSERT INTO password_resets
                    (username, code_hash, expires_at, attempts, last_sent_at, created_at)
                VALUES (?, ?, ?, 0, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    code_hash = excluded.code_hash,
                    expires_at = excluded.expires_at,
                    attempts = 0,
                    last_sent_at = excluded.last_sent_at,
                    created_at = excluded.created_at
                """,
                (
                    username,
                    code_hash,
                    expires_at.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self.conn.commit()
            return generic
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao solicitar recuperacao de senha: {e}")
            self.conn.rollback()
            return {"ok": False, "reason": "error"}

    def confirm_password_reset(
        self,
        username,
        code,
        new_password,
        max_attempts=5,
        min_password_length=8,
    ):
        """Consome o codigo e troca a senha na mesma transacao."""
        username = str(username or "").strip()
        max_attempts = max(1, min(5, int(max_attempts or 5)))
        min_password_length = max(8, int(min_password_length or 8))
        if len(str(new_password or "")) < min_password_length:
            return {
                "ok": False,
                "reason": "weak_password",
                "min_length": min_password_length,
            }
        try:
            self.cursor.execute(
                """
                SELECT pr.code_hash, pr.expires_at, COALESCE(pr.attempts, 0),
                       u.email, u.role,
                       COALESCE(NULLIF(TRIM(u.data_owner), ''), u.username)
                FROM password_resets pr
                JOIN users u ON u.username = pr.username
                WHERE pr.username = ?
                """,
                (username,),
            )
            row = self.cursor.fetchone()
            if not row:
                return {"ok": False, "reason": "not_found"}

            code_hash, expires_raw, attempts, email, role, owner = row
            now = datetime.now().replace(microsecond=0)
            try:
                expires_at = datetime.fromisoformat(str(expires_raw))
            except (TypeError, ValueError):
                expires_at = now - timedelta(seconds=1)
            if now >= expires_at:
                self.cursor.execute("DELETE FROM password_resets WHERE username = ?", (username,))
                self.conn.commit()
                return {"ok": False, "reason": "expired"}

            if not self._code_matches(code, code_hash):
                attempts = int(attempts or 0) + 1
                if attempts >= max_attempts:
                    self.cursor.execute(
                        "DELETE FROM password_resets WHERE username = ?", (username,)
                    )
                    self.conn.commit()
                    return {"ok": False, "reason": "too_many_attempts", "remaining": 0}
                self.cursor.execute(
                    "UPDATE password_resets SET attempts = ? WHERE username = ?",
                    (attempts, username),
                )
                self.conn.commit()
                return {
                    "ok": False,
                    "reason": "invalid",
                    "remaining": max_attempts - attempts,
                }

            hashed_password = bcrypt.hashpw(
                str(new_password).encode("utf-8"), bcrypt.gensalt()
            )
            self.cursor.execute(
                "DELETE FROM password_resets WHERE username = ? AND code_hash = ?",
                (username, code_hash),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            self.cursor.execute(
                """
                UPDATE users
                SET password = ?, email_verified = 1, email_verified_at = ?,
                    must_change_password = 0, password_changed_at = ?,
                    failed_login_attempts = 0, locked_until = NULL
                WHERE username = ?
                """,
                (hashed_password, now.isoformat(), now.isoformat(), username),
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            self.cursor.execute(
                "DELETE FROM account_recovery_codes WHERE username = ? AND used_at IS NULL",
                (username,),
            )
            self.cursor.execute(
                """
                INSERT INTO user_logs
                    (username, role, action, details, timestamp, owner_username)
                VALUES (?, ?, 'RESET_PASSWORD_EMAIL', ?, ?, ?)
                """,
                (
                    username,
                    role,
                    "Senha redefinida por codigo enviado ao e-mail cadastrado",
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    owner or username,
                ),
            )
            self.conn.commit()
            self._notify_superadmin_account_event(username, "PASSWORD_CHANGED")

            notice_sent = True
            try:
                send_password_changed_notice(email, username)
            except EmailServiceError as exc:
                notice_sent = False
                print(f"Senha alterada, mas o aviso por e-mail falhou: {exc}")
            return {
                "ok": True,
                "reason": "password_reset",
                "notice_sent": notice_sent,
            }
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao confirmar recuperacao de senha: {e}")
            self.conn.rollback()
            return {"ok": False, "reason": "error"}

    def update_admin_profile(self, current_username, new_username=None, new_password=None):
        """Atualizar username e/ou senha do admin"""
        if not new_username and not new_password:
            return False
        try:
            current_username = str(current_username or "").strip()
            new_username = str(new_username or "").strip() if new_username else None
            password_text = str(new_password or "") if new_password else None
            if not current_username:
                return False
            if new_username and self.user_exists(new_username, exclude_username=current_username):
                return False
            update_parts = []
            params = []
            if new_username:
                update_parts.append("username = ?")
                params.append(new_username)
            if password_text:
                hashed_password = bcrypt.hashpw(password_text.encode("utf-8"), bcrypt.gensalt())
                update_parts.append("password = ?")
                params.append(hashed_password)
                now = datetime.now().replace(microsecond=0).isoformat()
                update_parts.extend(
                    (
                        "must_change_password = 0",
                        "password_changed_at = ?",
                        "failed_login_attempts = 0",
                        "locked_until = NULL",
                    )
                )
                params.append(now)
            params.append(current_username)
            self.cursor.execute(
                f"UPDATE users SET {', '.join(update_parts)} WHERE username = ? AND role = 'admin'",
                params,
            )
            if self.cursor.rowcount == 0:
                self.conn.rollback()
                return False
            if password_text:
                self.cursor.execute(
                    "DELETE FROM password_resets WHERE username = ?", (current_username,)
                )
                self.cursor.execute(
                    "DELETE FROM account_recovery_codes WHERE username = ? AND used_at IS NULL",
                    (current_username,),
                )
            self.conn.commit()
            if password_text:
                self._notify_superadmin_account_event(
                    new_username or current_username,
                    "PASSWORD_CHANGED",
                )
            return True
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao atualizar admin: {e}")
            self.conn.rollback()
            return False

    def set_security_questions(self, username, answers):
        """Configurar perguntas de seguranca para um usuario"""
        try:
            from utils.business.security_questions import REQUIRED_QUESTION_COUNT, hash_answer
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
            from utils.business.security_questions import REQUIRED_QUESTION_COUNT, check_answer
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

    def _resolve_loss_actor(self, created_by=None, created_role=None):
        """Usa a sessao ativa quando existir; evita confiar no papel informado pelo cliente."""
        session_user = str(self.current_user or "").strip()
        session_role = str(self.current_role or "").strip().lower()
        requested_user = str(created_by or "").strip()
        requested_role = str(created_role or "").strip().lower()

        user = session_user or requested_user or None
        role = session_role if session_role in {"admin", "manager"} else requested_role
        return user, role

    @staticmethod
    def _is_expiry_loss_reason(reason):
        return str(reason or "").strip().casefold() == EXPIRY_LOSS_REASON.casefold()

    def _is_expired_loss_allowed(self, product_id, reason):
        """Confirma no banco que uma perda por validade corresponde a um lote vencido."""
        if not self._is_expiry_loss_reason(reason):
            return False

        scope_sql, scope_params = self._owner_filter()
        self.cursor.execute(
            f"SELECT expiry_date FROM products WHERE id = ? {scope_sql}",
            (product_id, *scope_params),
        )
        row = self.cursor.fetchone()
        expiry_date = _parse_date(row[0]) if row else None
        # O dia indicado ainda faz parte da validade. So expira no dia seguinte.
        return bool(expiry_date and expiry_date < date.today())

    @staticmethod
    def _shift_month(reference_date, months):
        month_index = (reference_date.year * 12 + reference_date.month - 1) + int(months)
        return date(month_index // 12, (month_index % 12) + 1, 1)

    def _manager_loss_history(self, username, since_date):
        """Datas e quantidades das perdas ainda validas do mesmo gerente."""
        username = str(username or "").strip()
        if not username:
            return [], (0.0, 0.0)

        loss_types = tuple(sorted(LOSS_TYPES))
        placeholders = ",".join(["?"] * len(loss_types))
        scope_sql, scope_params = self._owner_filter("sm")
        day_start = date.today().isoformat() + " 00:00:00"
        self.cursor.execute(
            f"""
            SELECT sm.created_at,
                   COALESCE(SUM(CASE WHEN UPPER(COALESCE(sm.unit, 'UN')) = 'UN' THEN sm.qty ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN UPPER(COALESCE(sm.unit, '')) = 'KG' THEN sm.qty ELSE 0 END), 0)
            FROM stock_movements sm
            WHERE sm.created_by = ?
              AND LOWER(COALESCE(sm.created_role, '')) = 'manager'
              AND sm.direction = 'OUT'
              AND sm.movement_type IN ({placeholders})
              AND COALESCE(sm.approval_status, 'APPROVED') IN ('APPROVED', 'PENDING')
              AND sm.created_at >= ?
              {scope_sql}
            GROUP BY sm.created_at
            ORDER BY sm.created_at ASC
            """,
            (username, *loss_types, since_date.isoformat() + " 00:00:00", *scope_params),
        )
        rows = self.cursor.fetchall()

        self.cursor.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN UPPER(COALESCE(sm.unit, 'UN')) = 'UN' THEN sm.qty ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN UPPER(COALESCE(sm.unit, '')) = 'KG' THEN sm.qty ELSE 0 END), 0)
            FROM stock_movements sm
            WHERE sm.created_by = ?
              AND LOWER(COALESCE(sm.created_role, '')) = 'manager'
              AND sm.direction = 'OUT'
              AND sm.movement_type IN ({placeholders})
              AND COALESCE(sm.approval_status, 'APPROVED') IN ('APPROVED', 'PENDING')
              AND sm.created_at >= ?
              {scope_sql}
            """,
            (username, *loss_types, day_start, *scope_params),
        )
        daily_totals = self.cursor.fetchone() or (0.0, 0.0)
        return rows, (_safe_float(daily_totals[0]), _safe_float(daily_totals[1]))

    def _manager_loss_recurrence_reason(self, username):
        """Deteta tres dias, semanas ou meses consecutivos com perdas do gerente."""
        current_day = date.today()
        earliest_month = self._shift_month(
            current_day.replace(day=1),
            -(LOSS_RECURRENCE_PERIODS - 1),
        )
        rows, _daily_totals = self._manager_loss_history(username, earliest_month)
        loss_days = {_parse_date(row[0]) for row in rows}
        loss_days.discard(None)
        loss_days.add(current_day)  # Inclui a perda que esta a ser analisada.

        if all((current_day - timedelta(days=index)) in loss_days for index in range(LOSS_RECURRENCE_PERIODS)):
            return f"Perdas em {LOSS_RECURRENCE_PERIODS} dias consecutivos"

        current_week = current_day - timedelta(days=current_day.weekday())
        loss_weeks = {day_value - timedelta(days=day_value.weekday()) for day_value in loss_days}
        if all(
            (current_week - timedelta(days=7 * index)) in loss_weeks
            for index in range(LOSS_RECURRENCE_PERIODS)
        ):
            return f"Perdas em {LOSS_RECURRENCE_PERIODS} semanas consecutivas"

        current_month = current_day.replace(day=1)
        loss_months = {day_value.replace(day=1) for day_value in loss_days}
        if all(
            self._shift_month(current_month, -index) in loss_months
            for index in range(LOSS_RECURRENCE_PERIODS)
        ):
            return f"Perdas em {LOSS_RECURRENCE_PERIODS} meses consecutivos"
        return None

    def _loss_approval_reason(self, movement_code, qty, unit_cost, is_by_weight, created_by, created_role):
        """Devolve o motivo para uma perda registada por gerente ficar pendente."""
        if str(created_role or "").strip().lower() != "manager":
            return None
        movement_code = str(movement_code or "").upper()
        if movement_code in LOSS_TYPES_ALWAYS_REQUIRING_APPROVAL:
            return "Perda registada por gerente requer aprovacao administrativa"
        return None

    def _loss_requires_admin_approval(self, movement_code, qty, unit_cost, is_by_weight, created_by, created_role):
        return bool(
            self._loss_approval_reason(
                movement_code,
                qty,
                unit_cost,
                is_by_weight,
                created_by,
                created_role,
            )
        )

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
        movement_unit=None,
    ):
        scope_sql, scope_params = self._owner_filter()
        cursor.execute(
            f"""
            SELECT existing_stock, sold_stock, unit_purchase_price,
                   sale_price, is_sold_by_weight, stock_mode
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
        if not is_by_weight and movement_unit != "KG" and not qty.is_integer():
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

        unit = movement_unit or ("SACO" if product[5] == "SACKS" else ("KG" if is_by_weight else "UN"))
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

    # ==================== FOTO OBRIGATORIA DE DANO ====================
    def create_damage_evidence(
        self,
        evidence_id,
        storage_path,
        sha256,
        mime_type,
        file_size,
        analysis,
        created_by=None,
    ):
        """Persiste uma foto anexada que ainda nao esta ligada a uma perda."""
        analysis = dict(analysis or {})
        attached = bool(analysis.get("attached") or analysis.get("approved"))
        if not evidence_id or not storage_path or not attached:
            return False
        # Em API, a sessao ativa e a fonte de autoridade; o campo enviado pelo
        # cliente nao pode ser usado para aceder a uma evidencia de outro dono.
        owner = self._active_owner() or self._owner_value(created_by)
        now_str = self._now_str()
        try:
            self.cursor.execute(
                """
                INSERT INTO damage_evidence (
                    id, storage_path, sha256, mime_type, file_size,
                    analysis_json, analysis_status, model, analyzed_at,
                    created_at, created_by, owner_username
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(evidence_id), str(storage_path), str(sha256), str(mime_type),
                    int(file_size), json.dumps(analysis, ensure_ascii=False, sort_keys=True),
                    "ATTACHED" if analysis.get("attached") else "APPROVED",
                    str(analysis.get("model") or ""), now_str, now_str,
                    created_by, owner,
                ),
            )
            self.conn.commit()
            return True
        except (sqlite3.Error, TypeError, ValueError) as exc:
            print(f"Erro ao guardar evidencia de dano: {exc}")
            self.conn.rollback()
            return False

    def cleanup_unbound_damage_evidence(self, hours=24):
        """Remove referencias de fotos anexadas que nunca foram usadas."""
        try:
            cutoff = (datetime.now() - timedelta(hours=max(1.0, float(hours)))).isoformat(timespec="seconds")
            owner = self._active_owner()
            where = ["movement_id IS NULL", "created_at < ?"]
            params = [cutoff]
            if owner:
                where.append("COALESCE(owner_username, '') = ?")
                params.append(owner)
            self.cursor.execute(
                "SELECT id, storage_path FROM damage_evidence WHERE " + " AND ".join(where),
                tuple(params),
            )
            rows = self.cursor.fetchall()
            if rows:
                self.cursor.execute(
                    "DELETE FROM damage_evidence WHERE " + " AND ".join(where),
                    tuple(params),
                )
                self.conn.commit()
            paths = [row[1] for row in rows]
            if paths:
                try:
                    from utils.business.damage_evidence import remove_stored_evidence
                    for path in paths:
                        remove_stored_evidence(path)
                except Exception:
                    pass
            return paths
        except (sqlite3.Error, TypeError, ValueError) as exc:
            print(f"Erro ao limpar evidencias expiradas: {exc}")
            self.conn.rollback()
            return []

    def delete_damage_evidence(self, evidence_id):
        """Descarta uma evidencia ainda nao associada e devolve o caminho do ficheiro."""
        if not evidence_id:
            return None
        try:
            owner = self._active_owner()
            where = ["id = ?", "movement_id IS NULL"]
            params = [str(evidence_id)]
            if owner:
                where.append("COALESCE(owner_username, '') = ?")
                params.append(owner)
            self.cursor.execute(
                "SELECT storage_path FROM damage_evidence WHERE " + " AND ".join(where),
                tuple(params),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            self.cursor.execute(
                "DELETE FROM damage_evidence WHERE " + " AND ".join(where),
                tuple(params),
            )
            self.conn.commit()
            try:
                from utils.business.damage_evidence import remove_stored_evidence
                remove_stored_evidence(row[0])
            except Exception:
                pass
            return row[0]
        except sqlite3.Error as exc:
            print(f"Erro ao remover evidencia de dano: {exc}")
            self.conn.rollback()
            return None

    def _attached_damage_evidence(self, evidence_id, created_by=None):
        """Obtem uma foto anexada, livre e pertencente ao mesmo dono."""
        if not evidence_id:
            return None
        owner = self._active_owner() or self._owner_value(created_by)
        self.cursor.execute(
            """
            SELECT id, storage_path
            FROM damage_evidence
            WHERE id = ?
              AND analysis_status IN ('ATTACHED', 'APPROVED')
              AND movement_id IS NULL
              AND COALESCE(owner_username, '') = ?
            """,
            (str(evidence_id), owner),
        )
        return self.cursor.fetchone()

    def get_damage_evidence(self, evidence_id):
        """Devolve metadados da foto, sem expor o caminho privado da imagem."""
        if not evidence_id:
            return None
        try:
            owner = self._active_owner()
            where = ["id = ?"]
            params = [str(evidence_id)]
            if owner:
                where.append("COALESCE(owner_username, '') = ?")
                params.append(owner)
            self.cursor.execute(
                """
                SELECT id, movement_id, sha256, mime_type, file_size, analysis_json,
                       analysis_status, model, analyzed_at, created_at, created_by
                FROM damage_evidence WHERE """ + " AND ".join(where),
                tuple(params),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            try:
                analysis = json.loads(row[5] or "{}")
            except (TypeError, ValueError):
                analysis = {}
            return {
                "id": row[0], "movement_id": row[1], "sha256": row[2],
                "mime_type": row[3], "file_size": row[4], "analysis": analysis,
                "status": row[6], "model": row[7], "analyzed_at": row[8],
                "created_at": row[9], "created_by": row[10],
            }
        except sqlite3.Error as exc:
            print(f"Erro ao obter evidencia de dano: {exc}")
            return None

    def get_damage_evidence_storage_path(self, evidence_id):
        """Uso interno da API para servir a imagem apos validar o dono."""
        if not evidence_id:
            return None
        try:
            owner = self._active_owner()
            where = ["id = ?"]
            params = [str(evidence_id)]
            if owner:
                where.append("COALESCE(owner_username, '') = ?")
                params.append(owner)
            self.cursor.execute(
                "SELECT storage_path FROM damage_evidence WHERE " + " AND ".join(where),
                tuple(params),
            )
            row = self.cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

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
        evidence_id=None,
    ):
        """Registra movimento e aplica no stock imediatamente."""
        try:
            movement_code = str(movement_type or "").upper()
            direction_code = str(direction or "").upper()
            reason = str(reason or "").strip()
            if direction_code == "OUT" and movement_code in LOSS_TYPES and not reason:
                return None

            if direction_code == "OUT" and movement_code == "EXPIRED":
                if not self._is_expired_loss_allowed(product_id, reason):
                    return None

            if direction_code == "OUT" and movement_code in LOSS_TYPES:
                created_by, created_role = self._resolve_loss_actor(created_by, created_role)
                # Mantem a regra no banco tambem para chamadas que nao passem
                # pela tela de perdas (API, importacoes ou futuras interfaces).
                self.cursor.execute(
                    """
                    SELECT unit_purchase_price, is_sold_by_weight
                    FROM products WHERE id = ?
                    """,
                    (product_id,),
                )
                loss_product = self.cursor.fetchone()
                if not loss_product:
                    return None
                effective_cost = unit_cost if unit_cost is not None else loss_product[0]
                if self._loss_requires_admin_approval(
                    movement_code,
                    qty,
                    effective_cost,
                    loss_product[1],
                    created_by,
                    created_role,
                ):
                    return self.request_stock_movement(
                        product_id,
                        movement_code,
                        qty,
                        reason,
                        created_by,
                        created_role,
                        terminal_id=terminal_id,
                        note=note,
                        evidence_path=evidence_path,
                        reference_table=reference_table,
                        reference_id=reference_id,
                        unit_cost=unit_cost,
                        unit_price=unit_price,
                        direction=direction,
                        evidence_id=evidence_id,
                    )

            attached_evidence = None
            if direction_code == "OUT" and movement_code == "DAMAGE":
                attached_evidence = self._attached_damage_evidence(evidence_id, created_by)
                if not attached_evidence:
                    return None
                # O caminho vem apenas da foto anexada, nunca de texto do cliente.
                evidence_path = attached_evidence[1]

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
            if attached_evidence:
                self.cursor.execute(
                    """
                    UPDATE damage_evidence
                    SET movement_id = ?
                    WHERE id = ? AND movement_id IS NULL
                      AND analysis_status IN ('ATTACHED', 'APPROVED')
                    """,
                    (movement_id, attached_evidence[0]),
                )
                if self.cursor.rowcount != 1:
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
        evidence_id=None,
    ):
        """Registra movimento e decide se precisa aprovacao."""
        try:
            movement_code = str(movement_type or "").upper()
            direction_code = str(direction or "").upper()
            reason = str(reason or "").strip()
            if direction is None:
                if movement_code in LOSS_TYPES or movement_code == "SALE":
                    direction = "OUT"
                elif movement_code == "RETURN":
                    direction = "IN"
                direction_code = str(direction or "").upper()

            if direction_code == "OUT" and movement_code in LOSS_TYPES and not reason:
                return None
            if direction_code == "OUT" and movement_code == "EXPIRED":
                if not self._is_expired_loss_allowed(product_id, reason):
                    return None

            if direction_code == "OUT" and movement_code in LOSS_TYPES:
                created_by, created_role = self._resolve_loss_actor(created_by, created_role)

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

            attached_evidence = None
            if direction_code == "OUT" and movement_code == "DAMAGE":
                attached_evidence = self._attached_damage_evidence(evidence_id, created_by)
                if not attached_evidence:
                    return None
                evidence_path = attached_evidence[1]

            if direction == "OUT" and stock_before < qty:
                return None

            approval_reason = None
            needs_approval = (
                direction_code == "OUT"
                and movement_code in LOSS_TYPES
            )
            if needs_approval:
                approval_reason = self._loss_approval_reason(
                    movement_code,
                    qty,
                    unit_cost,
                    is_by_weight,
                    created_by,
                    created_role,
                )
                needs_approval = bool(approval_reason)

            if needs_approval:
                approval_note = f"Aprovacao administrativa: {approval_reason}"
                note = f"{note} | {approval_note}" if note else approval_note
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
                if attached_evidence:
                    self.cursor.execute(
                        """
                        UPDATE damage_evidence
                        SET movement_id = ?
                        WHERE id = ? AND movement_id IS NULL
                          AND analysis_status IN ('ATTACHED', 'APPROVED')
                        """,
                        (movement_id, attached_evidence[0]),
                    )
                    if self.cursor.rowcount != 1:
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
                evidence_id=evidence_id,
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
                SELECT product_id, movement_type, direction, qty, approval_status, applied, reason
                FROM stock_movements WHERE id = ?
                """,
                (movement_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                return False

            product_id, movement_type, direction, qty, approval_status, applied, reason = row
            if approval_status != "PENDING" or applied:
                return False

            if movement_type == "EXPIRED" and not self._is_expired_loss_allowed(product_id, reason):
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

    def approve_all_pending_stock_movements(self, approved_by):
        """Tenta aprovar todas as perdas pendentes e devolve um resumo seguro."""
        try:
            pending = list(self.get_pending_approvals() or [])
            approved_ids = []
            failed_ids = []
            for row in pending:
                movement_id = row[0] if row else None
                if movement_id is None:
                    continue
                if self.approve_stock_movement(movement_id, approved_by):
                    approved_ids.append(movement_id)
                else:
                    failed_ids.append(movement_id)
            return {
                "approved_ids": approved_ids,
                "failed_ids": failed_ids,
                "approved_count": len(approved_ids),
                "failed_count": len(failed_ids),
            }
        except (sqlite3.Error, TypeError, ValueError) as e:
            print(f"Erro ao aprovar perdas pendentes: {e}")
            self.conn.rollback()
            return {
                "approved_ids": [],
                "failed_ids": [],
                "approved_count": 0,
                "failed_count": 0,
            }

    def get_stock_movement_approval_status(self, movement_id):
        """Retorna o estado de aprovacao do movimento acabado de solicitar."""
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                f"""
                SELECT approval_status, applied
                FROM stock_movements
                WHERE id = ? {scope_sql}
                """,
                (movement_id, *scope_params),
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            return {
                "approval_status": str(row[0] or ""),
                "applied": bool(row[1]),
            }
        except sqlite3.Error as e:
            print(f"Erro ao obter estado de aprovacao: {e}")
            return None

    def reject_stock_movement(self, movement_id, rejected_by=None):
        """Rejeita movimento pendente sem alterar o stock."""
        try:
            movement_id = int(movement_id)
        except (TypeError, ValueError):
            return False

        try:
            self.cursor.execute(
                """
                SELECT approval_status, applied
                FROM stock_movements
                WHERE id = ?
                """,
                (movement_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                return False

            approval_status, applied = row
            if approval_status != "PENDING" or applied:
                return False

            now_str = self._now_str()
            rejection_note = f"Movimento rejeitado por {rejected_by or 'admin'} em {now_str}"
            self.cursor.execute(
                """
                UPDATE stock_movements
                SET approval_status = 'REJECTED',
                    approved_by = ?,
                    approved_at = ?,
                    applied = 0,
                    note = CASE
                        WHEN COALESCE(note, '') = '' THEN ?
                        ELSE note || ' | ' || ?
                    END
                WHERE id = ?
                """,
                (
                    rejected_by or "admin",
                    now_str,
                    rejection_note,
                    rejection_note,
                    movement_id,
                ),
            )
            changed = self.cursor.rowcount > 0
            self.conn.commit()
            return changed
        except sqlite3.Error as e:
            print(f"Erro ao rejeitar movimento: {e}")
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
                FROM sales_history
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

            source_produce = self.get_produce_settings(product_id)
            target_product_id = int(product_id)
            if normalized_barcode and target_expiry != normalized_base_expiry:
                sibling = self._find_existing_batch(normalized_barcode, target_expiry)
                if sibling:
                    target_product_id = int(sibling[0])
                    if self.get_produce_settings(target_product_id)["stock_mode"] != source_produce["stock_mode"]:
                        raise ValueError("O lote de destino usa outra unidade de stock")
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

            self._save_produce_options_tx(target_product_id, source_produce)
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
            profit_per_unit = 0 if source_produce["stock_mode"] == "SACKS" else sale_price - new_unit_cost

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

    def get_loss_history_items(self, start_dt, end_dt, limit=300):
        """Lista registos individuais para o historico com referencia da evidencia."""
        start = self._to_dt_str(start_dt, end=False)
        end = self._to_dt_str(end_dt, end=True)
        try:
            loss_types = list(LOSS_TYPES)
            placeholders = ",".join(["?"] * len(loss_types))
            params = [*loss_types, start, end]
            where_owner, owner_params = self._owner_filter("sm")
            params.extend(owner_params)
            limit_clause = "LIMIT ?" if limit else ""
            if limit:
                params.append(int(limit))
            self.cursor.execute(
                f"""
                SELECT sm.id, sm.created_at,
                       COALESCE(p.description, pa.description) AS product_name,
                       sm.movement_type, sm.qty, sm.unit, sm.total_cost,
                       sm.total_price, sm.reason, sm.note, sm.created_by,
                       de.id AS evidence_id
                FROM stock_movements sm
                LEFT JOIN products p ON sm.product_id = p.id
                LEFT JOIN products_archive pa ON sm.product_id = pa.id
                LEFT JOIN damage_evidence de ON de.movement_id = sm.id
                WHERE sm.applied = 1
                  AND sm.direction = 'OUT'
                  AND sm.movement_type IN ({placeholders})
                  AND sm.created_at BETWEEN ? AND ?
                  {where_owner}
                ORDER BY sm.created_at DESC
                {limit_clause}
                """,
                tuple(params),
            )
            columns = (
                "movement_id", "created_at", "product", "movement_type", "qty", "unit",
                "total_cost", "total_price", "reason", "note", "created_by", "evidence_id",
            )
            return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
        except sqlite3.Error as exc:
            print(f"Erro ao obter historico de perdas: {exc}")
            return []

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
                FROM sales_history
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
        # Esta analise e chamada pelo monitor em segundo plano. Nao pode
        # reutilizar ``self.cursor``, pois a interface pode estar a executar
        # outra consulta no mesmo instante (SQLite nao permite uso recursivo
        # de um cursor). Uma conexao de leitura isolada evita esse conflito.
        try:
            fraud_conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            fraud_conn.execute("PRAGMA busy_timeout = 30000")
            fraud_cursor = fraud_conn.cursor()
        except sqlite3.Error as e:
            print(f"Erro ao iniciar deteccao de fraude: {e}")
            return []

        # 1. Utilizadores com perdas acima da mÃƒÆ’Ã‚Â©dia
        try:
            start = self._to_dt_str(start_date, end=False)
            end = self._to_dt_str(end_date, end=True)
            loss_types = list(LOSS_TYPES)
            placeholders = ",".join(["?"] * len(loss_types))
            
            fraud_cursor.execute(
                f"""
                SELECT 
                    created_by,
                    COUNT(*) as loss_count,
                    COALESCE(SUM(ABS(qty)), 0) as total_quantity
                FROM stock_movements
                WHERE COALESCE(approval_status, 'APPROVED') IN ('PENDING', 'APPROVED')
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                  AND created_by IS NOT NULL
                  AND LOWER(COALESCE(created_role, '')) = 'manager'
                GROUP BY created_by
                """,
                (*loss_types, start, end),
            )
            
            users_data = fraud_cursor.fetchall()
            
            if len(users_data) >= 2:
                quantities = [float(row[2] or 0) for row in users_data]
                avg_quantity = sum(quantities) / len(quantities)
                threshold = avg_quantity * 1.5
                
                for user, count, quantity in users_data:
                    quantity = float(quantity or 0)
                    if avg_quantity > 0 and quantity > threshold:
                        percentage_above = ((quantity - avg_quantity) / avg_quantity) * 100
                        severity = 3 if percentage_above > 100 else (2 if percentage_above > 50 else 1)
                        
                        alerts.append({
                            'alert_type': 'HIGH_LOSS_USER',
                            'severity': severity,
                            'title': f'Utilizador com perdas elevadas: {user}',
                            'description': f'{user} registou {quantity:.2f} unidade(s) em {count} perda(s) ({percentage_above:.1f}% acima da media de quantidade)',
                            'related_user': user,
                            'related_product_id': None,
                            'data': {
                                'user': user,
                                'loss_count': count,
                                'total_quantity': quantity,
                                'average_quantity': avg_quantity,
                                'percentage_above': percentage_above
                            }
                        })
        except Exception as e:
            print(f"Erro ao detectar utilizadores com perdas elevadas: {e}")
        
        # 2. Produtos com perdas repetidas
        try:
            fraud_cursor.execute(
                f"""
                SELECT 
                    sm.product_id,
                    COALESCE(p.description, pa.description),
                    COUNT(*) as loss_count,
                    COALESCE(SUM(ABS(sm.qty)), 0) as total_quantity
                FROM stock_movements sm
                LEFT JOIN products p ON sm.product_id = p.id
                LEFT JOIN products_archive pa ON sm.product_id = pa.id
                WHERE COALESCE(sm.approval_status, 'APPROVED') IN ('PENDING', 'APPROVED')
                  AND sm.direction = 'OUT'
                  AND sm.movement_type IN ({placeholders})
                  AND sm.created_at BETWEEN ? AND ?
                  AND LOWER(COALESCE(sm.created_role, '')) = 'manager'
                GROUP BY sm.product_id
                HAVING total_quantity >= 3
                ORDER BY total_quantity DESC
                """,
                (*loss_types, start, end),
            )
            
            for product_id, description, count, quantity in fraud_cursor.fetchall():
                quantity = float(quantity or 0)
                severity = 3 if quantity >= 10 else (2 if quantity >= 6 else 1)
                
                alerts.append({
                    'alert_type': 'REPEATED_PRODUCT_LOSS',
                    'severity': severity,
                    'title': f'Produto com perdas repetidas: {description}',
                    'description': f'{description} acumulou {quantity:.2f} unidade(s) em {count} registo(s) de perda',
                    'related_user': None,
                    'related_product_id': product_id,
                    'data': {
                        'product_id': product_id,
                        'product_name': description,
                        'loss_count': count,
                        'total_quantity': quantity
                    }
                })
        except Exception as e:
            print(f"Erro ao detectar produtos com perdas repetidas: {e}")
        
        # 3. Perdas fora do horÃƒÆ’Ã‚Â¡rio (22h-6h)
        try:
            fraud_cursor.execute(
                f"""
                SELECT 
                    id,
                    product_id,
                    created_by,
                    created_at,
                    movement_type,
                    qty,
                    unit
                FROM stock_movements
                WHERE COALESCE(approval_status, 'APPROVED') IN ('PENDING', 'APPROVED')
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                  AND LOWER(COALESCE(created_role, '')) = 'manager'
                  AND (
                      CAST(strftime('%H', created_at) AS INTEGER) >= 22
                      OR CAST(strftime('%H', created_at) AS INTEGER) < 6
                  )
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (*loss_types, start, end),
            )
            
            for row in fraud_cursor.fetchall():
                movement_id, product_id, user, created_at, movement_type, quantity, unit = row
                time_str = created_at.split()[1] if ' ' in created_at else 'N/A'
                movement_label = _loss_type_label(movement_type)
                
                alerts.append({
                    'alert_type': 'OFF_HOURS_LOSS',
                    'severity': 2,
                    'title': f'Perda fora do horÃƒÆ’Ã‚Â¡rio: {user}',
                    'description': f'Perda de {float(quantity or 0):.2f} {unit or "un"} registada às {time_str} por {user} ({movement_label})',
                    'related_user': user,
                    'related_product_id': product_id,
                    'data': {
                        'movement_id': movement_id,
                        'user': user,
                        'time': time_str,
                        'movement_type': movement_type,
                        'quantity': float(quantity or 0),
                        'unit': unit or 'un'
                    }
                })
        except Exception as e:
            print(f"Erro ao detectar perdas fora do horÃƒÆ’Ã‚Â¡rio: {e}")
        
        # 4. Perdas sem evidencia (acima de 50% do limite)
        try:
            quantity_threshold = LOSS_QTY_LIMIT_UN
            
            fraud_cursor.execute(
                f"""
                SELECT 
                    id,
                    product_id,
                    created_by,
                    movement_type,
                    qty,
                    unit
                FROM stock_movements
                WHERE COALESCE(approval_status, 'APPROVED') IN ('PENDING', 'APPROVED')
                  AND direction = 'OUT'
                  AND movement_type IN ({placeholders})
                  AND created_at BETWEEN ? AND ?
                  AND LOWER(COALESCE(created_role, '')) = 'manager'
                  AND ABS(COALESCE(qty, 0)) >= ?
                  AND (evidence_path IS NULL OR evidence_path = '')
                ORDER BY ABS(COALESCE(qty, 0)) DESC
                LIMIT 10
                """,
                (*loss_types, start, end, quantity_threshold),
            )
            
            for row in fraud_cursor.fetchall():
                movement_id, product_id, user, movement_type, quantity, unit = row
                quantity = float(quantity or 0)
                movement_label = _loss_type_label(movement_type)
                
                alerts.append({
                    'alert_type': 'NO_EVIDENCE',
                    'severity': 2,
                    'title': f'Perda sem evidência: {quantity:.2f} {unit or "un"}',
                    'description': f'{user} registou {movement_label.lower()} de {quantity:.2f} {unit or "un"} sem foto/comprovativo',
                    'related_user': user,
                    'related_product_id': product_id,
                    'data': {
                        'movement_id': movement_id,
                        'user': user,
                        'movement_type': movement_type,
                        'quantity': quantity,
                        'unit': unit or 'un'
                    }
                })
        except Exception as e:
            print(f"Erro ao detectar perdas sem evidencia: {e}")
        
        fraud_conn.close()
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

    @staticmethod
    def _default_product_business_rules():
        """Defaults conservadores para uma instalacao que ainda nao configurou regras."""
        return {
            "default_profit_margin_percent": 30.0,
            "minimum_profit_margin_percent": 0.0,
            "enforce_minimum_margin": False,
            # Preserva o comportamento de bases ja instaladas. O administrador
            # pode ativar a protecao contra prejuizo nas regras comerciais.
            "allow_negative_margin": True,
        }

    def get_product_business_rules(self):
        """Obtem as regras de preco do proprietario ativo, com valores seguros por omissao."""
        rules = self._default_product_business_rules()
        owner = self._owner_value()
        try:
            self.cursor.execute(
                "SELECT rule_key, rule_value FROM business_rules WHERE owner_username = ?",
                (owner,),
            )
            stored = {key: value for key, value in self.cursor.fetchall()}
            for key in rules:
                if key not in stored:
                    continue
                value = json.loads(stored[key])
                if key in {"enforce_minimum_margin", "allow_negative_margin"}:
                    rules[key] = bool(value)
                else:
                    rules[key] = float(value)
        except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
            # Uma configuracao danificada nao pode impedir a venda; os valores
            # padrao continuam a ser usados ate o administrador corrigi-la.
            return self._default_product_business_rules()
        return rules

    def update_product_business_rules(self, rules, username=None):
        """Valida e guarda a politica comercial definida pelo administrador."""
        if self.current_role and self.current_role != "admin":
            raise PermissionError("Somente o administrador pode alterar regras comerciais.")
        if not isinstance(rules, dict):
            raise ValueError("As regras comerciais devem ser um conjunto de valores.")
        defaults = self._default_product_business_rules()
        normalized = dict(defaults)
        for key in defaults:
            if key not in rules:
                continue
            if key in {"enforce_minimum_margin", "allow_negative_margin"}:
                normalized[key] = bool(rules[key])
            else:
                normalized[key] = float(rules[key])
        for key in ("default_profit_margin_percent", "minimum_profit_margin_percent"):
            if not 0 <= normalized[key] <= 1000:
                raise ValueError("A margem deve estar entre 0% e 1000%.")
        if normalized["enforce_minimum_margin"] and normalized["minimum_profit_margin_percent"] < 0:
            raise ValueError("A margem minima nao pode ser negativa.")

        owner = self._owner_value(username)
        updated_by = username or self.current_user or "SYSTEM"
        now = self._now_str()
        try:
            for key, value in normalized.items():
                self.cursor.execute(
                    '''INSERT INTO business_rules (owner_username, rule_key, rule_value, updated_at, updated_by)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(owner_username, rule_key) DO UPDATE SET
                           rule_value = excluded.rule_value,
                           updated_at = excluded.updated_at,
                           updated_by = excluded.updated_by''',
                    (owner, key, json.dumps(value), now, updated_by),
                )
            self.conn.commit()
            return normalized
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def _validate_product_pricing(self, sale_price, unit_purchase_price):
        """Aplica a politica comercial no ponto de persistencia, nao apenas na UI."""
        sale_price = float(sale_price)
        unit_purchase_price = float(unit_purchase_price)
        rules = self.get_product_business_rules()
        if unit_purchase_price < 0 or sale_price < 0:
            raise ValueError("Os precos nao podem ser negativos.")
        profit = sale_price - unit_purchase_price
        if profit < 0 and not rules["allow_negative_margin"]:
            raise ValueError("O preco de venda nao pode ser inferior ao custo de compra.")
        if rules["enforce_minimum_margin"] and unit_purchase_price > 0:
            margin = (profit / unit_purchase_price) * 100
            minimum = rules["minimum_profit_margin_percent"]
            if margin + 1e-9 < minimum:
                minimum_price = unit_purchase_price * (1 + minimum / 100)
                raise ValueError(
                    f"Preco abaixo da margem minima de {minimum:.2f}%. "
                    f"Preco minimo: {minimum_price:.2f}."
                )

    def _ensure_admin_business_configuration(self):
        if self.current_role and self.current_role != "admin":
            raise PermissionError("Somente o administrador pode configurar o formulario.")

    @staticmethod
    def _normalize_custom_field_type(field_type):
        field_type = str(field_type or "TEXT").strip().upper()
        if field_type not in {"TEXT", "NUMBER"}:
            raise ValueError("O tipo do campo deve ser TEXTO ou NUMERO.")
        return field_type

    def list_product_custom_fields(self, active_only=True):
        owner = self._owner_value()
        query = """SELECT id, field_key, label, field_type, required, active, sort_order
                   FROM product_custom_fields WHERE owner_username = ?"""
        params = [owner]
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY sort_order, id"
        try:
            self.cursor.execute(query, params)
            return [
                {
                    "id": row[0], "key": row[1], "label": row[2], "type": row[3],
                    "required": bool(row[4]), "active": bool(row[5]), "sort_order": row[6],
                }
                for row in self.cursor.fetchall()
            ]
        except sqlite3.Error:
            return []

    def create_product_custom_field(self, label, field_type="TEXT", required=False):
        self._ensure_admin_business_configuration()
        label = str(label or "").strip()
        if not label or len(label) > 80:
            raise ValueError("O nome do campo deve ter entre 1 e 80 caracteres.")
        field_type = self._normalize_custom_field_type(field_type)
        owner = self._owner_value()
        base_key = "".join(char.lower() if char.isalnum() else "_" for char in label).strip("_") or "campo"
        now = self._now_str()
        try:
            self.cursor.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM product_custom_fields WHERE owner_username = ?",
                (owner,),
            )
            order = int(self.cursor.fetchone()[0] or 1)
            field_key = base_key
            suffix = 2
            while self.cursor.execute(
                "SELECT 1 FROM product_custom_fields WHERE owner_username = ? AND field_key = ?",
                (owner, field_key),
            ).fetchone():
                field_key = f"{base_key}_{suffix}"
                suffix += 1
            self.cursor.execute(
                '''INSERT INTO product_custom_fields
                   (owner_username, field_key, label, field_type, required, active, sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)''',
                (owner, field_key, label, field_type, int(bool(required)), order, now, now),
            )
            field_id = self.cursor.lastrowid
            self.conn.commit()
            return {"id": field_id, "key": field_key, "label": label, "type": field_type,
                    "required": bool(required), "active": True, "sort_order": order}
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def update_product_custom_field(self, field_id, label, field_type="TEXT", required=False, active=True):
        self._ensure_admin_business_configuration()
        label = str(label or "").strip()
        if not label or len(label) > 80:
            raise ValueError("O nome do campo deve ter entre 1 e 80 caracteres.")
        field_type = self._normalize_custom_field_type(field_type)
        try:
            self.cursor.execute(
                """UPDATE product_custom_fields SET label = ?, field_type = ?, required = ?, active = ?, updated_at = ?
                   WHERE id = ? AND owner_username = ?""",
                (label, field_type, int(bool(required)), int(bool(active)), self._now_str(), int(field_id), self._owner_value()),
            )
            if self.cursor.rowcount == 0:
                raise ValueError("Campo personalizado nao encontrado.")
            self.conn.commit()
            return True
        except (sqlite3.Error, ValueError):
            self.conn.rollback()
            raise

    def delete_product_custom_field(self, field_id):
        """Remove o campo do formulario sem apagar os valores historicos."""
        return self.update_product_custom_field(
            field_id,
            next((field["label"] for field in self.list_product_custom_fields(False) if field["id"] == int(field_id)), "Campo"),
            next((field["type"] for field in self.list_product_custom_fields(False) if field["id"] == int(field_id)), "TEXT"),
            required=False,
            active=False,
        )

    def get_product_custom_field_values(self, product_id):
        try:
            self.cursor.execute(
                "SELECT field_id, value FROM product_custom_field_values WHERE product_id = ?",
                (int(product_id),),
            )
            return {str(row[0]): row[1] or "" for row in self.cursor.fetchall()}
        except (sqlite3.Error, TypeError, ValueError):
            return {}

    def _save_product_custom_field_values_tx(self, product_id, values):
        if values is None:
            return
        if not isinstance(values, dict):
            raise ValueError("Os campos personalizados sao invalidos.")
        definitions = {str(field["id"]): field for field in self.list_product_custom_fields(True)}
        for field_id, definition in definitions.items():
            value = str(values.get(field_id, values.get(int(field_id), "")) or "").strip()
            if definition["required"] and not value:
                raise ValueError(f"{definition['label']} e obrigatorio.")
            if value and definition["type"] == "NUMBER":
                try:
                    number = float(value.replace(",", "."))
                    if number != number or abs(number) == float("inf"):
                        raise ValueError
                except (TypeError, ValueError):
                    raise ValueError(f"{definition['label']} deve ser numerico.")
            self.cursor.execute(
                '''INSERT INTO product_custom_field_values (product_id, field_id, value, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(product_id, field_id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at''',
                (int(product_id), int(field_id), value or None, self._now_str()),
            )

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
        produce_options=None,
        custom_fields=None,
    ):
        """Adicionar um novo produto ao banco de dados"""
        try:
            if produce_options is not None:
                produce_mode, _ = self._normalize_produce_options(produce_options)
                if produce_mode == "SACKS" and (is_sold_by_weight or allow_pack_sale):
                    raise ValueError("Sacos avulsos nao usam conversao por embalagem ou stock em kg")
            is_sold_by_weight = bool(is_sold_by_weight)
            incoming_stock = _inventory_quantity(
                existing_stock,
                is_sold_by_weight,
                "Estoque inicial",
            )
            sold_stock = _inventory_quantity(
                sold_stock,
                is_sold_by_weight,
                "Estoque vendido",
            )
            sale_price = float(sale_price)
            total_purchase_price = float(total_purchase_price)
            unit_purchase_price = float(unit_purchase_price)
            self._validate_product_pricing(sale_price, unit_purchase_price)
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
                existing_mode = self.get_produce_settings(product_id)["stock_mode"]
                incoming_mode, _ = self._normalize_produce_options(produce_options)
                if existing_mode != incoming_mode:
                    raise ValueError("Este codigo e validade ja usam outra unidade de stock")
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
                self._save_produce_options_tx(product_id, produce_options)
                self._save_product_custom_field_values_tx(product_id, custom_fields)
                self.conn.commit()
                tipo = "KG" if is_sold_by_weight else "UNIDADE"
                print(f"Lote existente fundido com sucesso! ID: {product_id} | Tipo: {tipo}")
                return product_id

            product_id = self._insert_product_row(
                description=description,
                category=category,
                existing_stock=incoming_stock,
                sold_stock=sold_stock,
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
            self._save_produce_options_tx(product_id, produce_options)
            self._save_product_custom_field_values_tx(product_id, custom_fields)
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
        produce_options=None,
        custom_fields=None,
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
            produce_options=produce_options,
            custom_fields=custom_fields,
        )
        try:
            sale_price = float(sale_price)
            total_purchase_price = float(total_purchase_price)
            unit_purchase_price = float(unit_purchase_price)
            self._validate_product_pricing(sale_price, unit_purchase_price)
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
            print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Produto {id} guardado com sucesso! | Tipo: {tipo}")
            
        except (sqlite3.Error, ValueError) as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao atualizar produto: {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
    
    def delete_product(self, id, username=None):
        """Elimina produtos sem historico e arquiva os que ja foram utilizados."""
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

            if row[14] == ARCHIVED_PRODUCT_STATUS:
                return True

            if self._product_has_related_records(id):
                return self.set_product_status(
                    id,
                    ARCHIVED_PRODUCT_STATUS,
                    ARCHIVED_PRODUCT_REASON,
                    user,
                    source="MANUAL",
                )

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

    def get_archived_products(self):
        """Inclui os dois formatos de arquivo, apenas no espaco da sessao."""
        scope, params = self._owner_filter()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = []
            for table, source in (("products", "catalog"), ("products_archive", "archive")):
                condition = "status = ?" if source == "catalog" else "1=1"
                args = [ARCHIVED_PRODUCT_STATUS, *params] if source == "catalog" else params
                for row in conn.execute(f"SELECT * FROM {table} WHERE {condition}{scope}", args):
                    item = dict(row)
                    item["archive_source"] = source
                    rows.append(item)
            return sorted(rows, key=lambda row: (str(row["description"]).casefold(), row["id"]))

    def restore_archived_product(self, product_id, archive_source, username=None):
        """Restaura atomicamente, sem sobrepor IDs, SKUs ou lotes existentes."""
        if archive_source not in ("catalog", "archive"):
            return {"ok": False, "message": "Origem do arquivo invalida."}
        if self.current_role and self.current_role != "admin":
            return {"ok": False, "message": "Apenas o administrador pode restaurar produtos."}
        table = "products" if archive_source == "catalog" else "products_archive"
        scope, params = self._owner_filter()
        try:
            with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(f"SELECT * FROM {table} WHERE id = ?{scope}", (product_id, *params)).fetchone()
                if row is None or (archive_source == "catalog" and row["status"] != ARCHIVED_PRODUCT_STATUS):
                    return {"ok": False, "message": "Produto arquivado nao encontrado ou ja restaurado."}
                item = dict(row)
                if archive_source == "archive" and conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone():
                    return {"ok": False, "message": "Este ID ja pertence a outro produto. O arquivo foi preservado."}
                duplicate = conn.execute(
                    """SELECT id FROM products WHERE id != ? AND COALESCE(owner_username, '') = ?
                       AND LOWER(TRIM(barcode)) = LOWER(TRIM(?)) AND TRIM(COALESCE(barcode, '')) != ''
                       AND TRIM(COALESCE(expiry_date, '')) = TRIM(COALESCE(?, ''))""",
                    (product_id, item.get("owner_username") or "", item.get("barcode"), item.get("expiry_date")),
                ).fetchone()
                if duplicate:
                    return {"ok": False, "message": f"Ja existe o lote #{duplicate['id']} com o mesmo codigo e validade. O arquivo foi preservado."}
                status = item.get("status") or "ATIVO"
                source = item.get("status_source") or "MANUAL"
                if archive_source == "catalog":
                    previous = conn.execute(
                        "SELECT old_status, source FROM product_status_history WHERE product_id = ? AND new_status = ? ORDER BY id DESC LIMIT 1",
                        (product_id, ARCHIVED_PRODUCT_STATUS),
                    ).fetchone()
                    status = previous["old_status"] if previous else "ATIVO"
                if status == ARCHIVED_PRODUCT_STATUS:
                    status = "ATIVO"
                expiry = self._parse_expiry_date(item.get("expiry_date"))
                if status in ("ATIVO", "PERTO_DO_PRAZO", "EXPIRADO"):
                    today = datetime.now().date()
                    status = "EXPIRADO" if expiry and expiry < today else "PERTO_DO_PRAZO" if expiry and expiry <= today + timedelta(days=NEAR_EXPIRY_DAYS) else "ATIVO"
                    source = "AUTO"
                now = self._now_str()
                user = username or self.current_user or "SYSTEM"
                reason = "Produto restaurado do arquivo"
                if archive_source == "archive":
                    columns = [r[1] for r in conn.execute("PRAGMA table_info(products)") if r[1] in item]
                    conn.execute(f"INSERT INTO products ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                                 [item[column] for column in columns])
                    conn.execute("DELETE FROM products_archive WHERE id = ?", (product_id,))
                conn.execute("UPDATE products SET status = ?, status_source = ?, status_reason = ?, status_updated_at = ?, status_updated_by = ? WHERE id = ?",
                             (status, source, reason, now, user, product_id))
                conn.execute("""INSERT INTO product_status_history
                    (product_id, old_status, new_status, reason, source, changed_at, changed_by, owner_username)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (product_id, ARCHIVED_PRODUCT_STATUS, status, reason, source, now, user, item.get("owner_username")))
            return {"ok": True, "message": f"Produto restaurado ao catalogo. Estado: {status}."}
        except sqlite3.Error:
            return {"ok": False, "message": "Nao foi possivel restaurar: conflito ou erro na base de dados. O arquivo foi preservado."}

    def _product_has_related_records(self, product_id):
        """Indica se o produto e referenciado por alguma chave estrangeira.

        A verificacao usa o proprio esquema SQLite, para que novas tabelas que
        referenciem ``products`` tambem bloqueiem a eliminacao fisica.
        """
        tables = self.cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

        for (table_name,) in tables:
            quoted_table = '"' + str(table_name).replace('"', '""') + '"'
            foreign_keys = self.cursor.execute(
                f"PRAGMA foreign_key_list({quoted_table})"
            ).fetchall()
            for foreign_key in foreign_keys:
                referenced_table = foreign_key[2]
                column_name = foreign_key[3]
                referenced_column = foreign_key[4]
                if referenced_table != "products" or referenced_column not in (None, "id"):
                    continue

                quoted_column = '"' + str(column_name).replace('"', '""') + '"'
                self.cursor.execute(
                    f"SELECT 1 FROM {quoted_table} WHERE {quoted_column} = ? LIMIT 1",
                    (product_id,),
                )
                if self.cursor.fetchone():
                    return True
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
                WHERE COALESCE(p.status, 'ATIVO') <> ?
            """
            params = [ARCHIVED_PRODUCT_STATUS]
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

    def get_all_products_catalog_page(
        self,
        search_text="",
        category=None,
        sold_by_weight=None,
        limit=120,
        offset=0,
        selected_lot_ids_by_catalog_key=None,
    ):
        """Devolve somente uma página administrativa do catálogo.

        A versão anterior buscava todos os lotes, agrupava em Python e só então
        fatiava a página. Isso anulava a paginação em catálogos grandes.
        """
        started_at = perf_counter()
        try:
            page_size = max(1, int(limit or 120))
            page_offset = max(0, int(offset or 0))
            count_query = "SELECT COUNT(*) FROM products p WHERE COALESCE(p.status, 'ATIVO') <> ?"
            count_params = [ARCHIVED_PRODUCT_STATUS]
            scope_sql, scope_params = self._owner_filter("p")
            count_query += scope_sql
            count_params.extend(scope_params)
            search = (search_text or "").strip().lower()
            if search:
                like = f"%{search}%"
                count_query += """ AND (CAST(p.id AS TEXT) LIKE ?
                                        OR LOWER(COALESCE(p.description, '')) LIKE ?
                                        OR LOWER(COALESCE(p.category, '')) LIKE ?
                                        OR LOWER(COALESCE(p.barcode, '')) LIKE ?
                                        OR LOWER(COALESCE(p.sku, '')) LIKE ?)"""
                count_params.extend((like, like, like, like, like))
            if category and category not in ("Todas", "Todas as Categorias"):
                count_query += " AND p.category = ?"
                count_params.append(category)
            if sold_by_weight is not None:
                count_query += " AND p.is_sold_by_weight = ?"
                count_params.append(1 if bool(sold_by_weight) else 0)
            total = int(self._readonly_fetchall(count_query, count_params)[0][0])
            rows = self.get_all_products_page(
                search_text=search_text,
                category=category,
                sold_by_weight=sold_by_weight,
                limit=page_size + 1,
                offset=page_offset,
            ) or []
            has_more = len(rows) > page_size
            page_rows = rows[:page_size]
            # Em catálogos que cabem integralmente numa página preservamos a
            # semântica histórica: lotes irmãos chegam já consolidados e o
            # total é exato. Em bases grandes, ``has_more`` evita carregar as
            # páginas restantes só para descobrir esse total.
            if not has_more and page_offset == 0:
                page_rows = aggregate_admin_product_rows(
                    page_rows,
                    selected_lot_ids_by_catalog_key,
                )
                return {
                    "rows": page_rows,
                    "has_more": False,
                    "total": len(page_rows),
                    "aggregated": True,
                }
            result = {
                "rows": page_rows,
                "has_more": has_more,
                "total": total,
                "aggregated": False,
            }
            perf_log(
                "db.get_all_products_catalog_page",
                started_at,
                f"rows={len(page_rows)} limit={page_size} offset={page_offset}",
            )
            return result
        except Exception as exc:
            print(f"Erro ao obter catalogo administrativo de produtos: {exc}")
            return {"rows": [], "has_more": False, "total": 0, "aggregated": True}

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
                    "stock_mode": row[13] if len(row) > 13 else "EXACT",
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
                    item["stock_mode"],
                )
            )
        return result

    @staticmethod
    def _catalog_identity_from_sale_row(row):
        if len(row) > 13 and row[13] == "SACKS":
            return f"sacks:{int(row[0])}"
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
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code, NULL, 1, stock_mode
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
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code, NULL, 1, stock_mode
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
                  AND COALESCE(p.status, 'ATIVO') <> ?
                {scope_sql}
                ORDER BY p.description ASC
            """, (ARCHIVED_PRODUCT_STATUS, *scope_params))
            results = self.cursor.fetchall()
            print(f"ÃƒÂ¢Ã…Â¡Ã¢â‚¬â€œÃƒÂ¯Ã‚Â¸Ã‚Â Produtos vendidos por KG: {len(results)}")
            return results
            
        except sqlite3.Error as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao obter produtos por peso: {e}")
            return []
    
    def get_product_by_barcode(self, barcode):
        """Buscar produto pelo cÃƒÆ’Ã‚Â³digo de barras - VERSÃƒÆ’Ã†â€™O ROBUSTA COM SUPORTE A KG"""
        try:
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
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code, NULL, 1, stock_mode
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
                "SELECT barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''"
                + scope_sql
                + " ORDER BY id DESC LIMIT 5",
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
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code, NULL, 1, stock_mode
                FROM products
                WHERE barcode IS NOT NULL
                  AND TRIM(barcode) != ''
                  AND LOWER(TRIM(barcode)) = LOWER(TRIM(?))
                  AND COALESCE(status, 'ATIVO') <> ?
            """
            params = [barcode_clean, ARCHIVED_PRODUCT_STATUS]
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
                       expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code, NULL, 1, stock_mode
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

    def get_sale_lots_by_barcode_fast(self, barcode):
        """Retorna os lotes vendaveis de um barcode para a fila do scanner.

        Esta consulta roda na conexao exclusiva do worker do scanner e evita
        abrir uma segunda conexao ou carregar o catalogo inteiro para juntar
        lotes com o mesmo barcode.
        """
        barcode_clean = self._normalize_barcode_value(barcode)
        if not barcode_clean:
            return []
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                f"""
            SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight,
                   expiry_date, status, units_per_package, allow_pack_sale, vat_rule_code, NULL, 1, stock_mode
            FROM products
            WHERE barcode IS NOT NULL
              AND TRIM(barcode) != ''
              AND LOWER(TRIM(barcode)) = LOWER(TRIM(?))
              AND existing_stock > 0
              AND status IN ('ATIVO', 'PERTO_DO_PRAZO')
              AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))
              {scope_sql}
            ORDER BY {self._expiry_order_clause()}
                """,
                (barcode_clean, *scope_params),
            )
            return self.cursor.fetchall()
        except sqlite3.Error as exc:
            print(f"Erro SQL ao consultar lotes do scanner: {exc}")
            return []
        except Exception as e:
            print(f"Erro geral ao consultar lotes do scanner: {e}")
            return []

    def _add_sale_tx(
        self,
        product_id,
        quantity,
        sale_price,
        username=None,
        role=None,
        terminal_id=None,
        is_promotional=False,
        vat_rule_code=None,
        transaction_code=None,
        payment_method="cash",
        discount_amount=0.0,
        cash_session_id=None,
        discount_reason=None,
        discount_authorized_by=None,
        produce_sale_mode=None,
        commit=True,
    ):
        """Grava uma linha de venda; permite uma transacao composta atomica."""
        try:
            quantity = float(quantity)
            promo_flag = 1 if is_promotional else 0
            sale_date = self._now_str()
            created_by = username or "SYSTEM"
            created_role = role or "manager"
            payment_method = str(payment_method or "cash").strip().lower()
            if payment_method not in {"cash", "card", "mobile", "emola"}:
                payment_method = "cash"
            discount_amount = max(0.0, float(discount_amount or 0.0))

            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(f"""
                SELECT description, existing_stock, sold_stock, is_sold_by_weight,
                       unit_purchase_price, vat_rule_code, status, stock_mode
                FROM products
                WHERE id = ?
                {scope_sql}
            """, (product_id, *scope_params))

            product_info = self.cursor.fetchone()

            if not product_info:
                print(f"Erro: Produto ID {product_id} nao encontrado!")
                return None

            if product_info[6] == ARCHIVED_PRODUCT_STATUS:
                print(f"Erro: Produto ID {product_id} esta arquivado e nao pode ser vendido!")
                return None

            import math
            if not math.isfinite(quantity) or quantity <= 0 or not math.isfinite(float(sale_price)) or float(sale_price) < 0:
                raise ValueError("Quantidade ou preco invalido")
            produce = product_info[7] == "SACKS"
            if produce:
                if produce_sale_mode not in PRODUCE_MODES:
                    raise ValueError("Escolha a forma de venda avulsa")
                if product_info[6] not in ("ATIVO", "PERTO_DO_PRAZO") or self._is_product_expired_for_sale(product_id):
                    raise ValueError("Produto indisponivel para venda")
                if produce_sale_mode != "weight" and not quantity.is_integer():
                    raise ValueError("Quantidade deve ser inteira")
                if produce_sale_mode == "amount" and quantity != 1:
                    raise ValueError("Venda por valor deve ter quantidade 1")
            elif produce_sale_mode is not None:
                raise ValueError("Produto nao permite venda avulsa")
            apply_stock = not produce or produce_sale_mode == "sack"
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

            if (apply_stock and stock_before < quantity) or (produce and stock_before < 1):
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
                unit_cost=unit_purchase_price if apply_stock else 0,
                unit_price=sale_price,
                approval_status="APPROVED",
                approved_by=created_by,
                approved_at=sale_date,
                apply_stock=apply_stock,
                movement_unit=PRODUCE_MODES.get(produce_sale_mode) if produce else None,
            )

            if not movement_id:
                if commit:
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
                    , transaction_code
                    , payment_method
                    , discount_amount
                    , cash_session_id
                    , discount_reason
                    , discount_authorized_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                str(transaction_code or "").strip() or None,
                payment_method,
                discount_amount,
                int(cash_session_id) if cash_session_id else None,
                str(discount_reason or "").strip() or None,
                str(discount_authorized_by or "").strip() or None,
            ))
            sale_id = self.cursor.lastrowid
            if produce:
                self.cursor.execute(
                    "INSERT INTO produce_sales (sale_id, sale_mode, stock_applied) VALUES (?, ?, ?)",
                    (sale_id, produce_sale_mode, int(apply_stock)),
                )

            if commit:
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
            if commit:
                self.conn.rollback()
            return None
        except Exception as e:
            print(f"Erro geral ao adicionar venda: {e}")
            import traceback
            traceback.print_exc()
            if commit:
                self.conn.rollback()
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
        transaction_code=None,
        payment_method="cash",
        discount_amount=0.0,
        cash_session_id=None,
        discount_reason=None,
        discount_authorized_by=None,
        produce_sale_mode=None,
    ):
        """Regista uma linha isolada, mantendo compatibilidade com o POS desktop."""
        sale_id = self._add_sale_tx(
            product_id,
            quantity,
            sale_price,
            username=username,
            role=role,
            terminal_id=terminal_id,
            is_promotional=is_promotional,
            vat_rule_code=vat_rule_code,
            transaction_code=transaction_code,
            payment_method=payment_method,
            discount_amount=discount_amount,
            cash_session_id=cash_session_id,
            discount_reason=discount_reason,
            discount_authorized_by=discount_authorized_by,
            produce_sale_mode=produce_sale_mode,
            commit=True,
        )
        if sale_id:
            self._run_sales_archive_maintenance()
        return sale_id

    @staticmethod
    def _transaction_item_signature(items):
        """Assinatura minima usada para rejeitar reuso acidental de um codigo."""
        result = []
        for raw_item in items or []:
            item = dict(raw_item or {})
            product_id = int(item.get("product_id", item.get("id")) or 0)
            quantity = round(float(item.get("quantity", item.get("qty")) or 0.0), 6)
            unit_price = round(
                float(item.get("sale_price", item.get("effective_unit_price", item.get("price"))) or 0.0),
                6,
            )
            result.append((product_id, quantity, unit_price, item.get("produce_sale_mode") or ""))
        return sorted(result)

    def add_sales_transaction(
        self,
        transaction_code,
        items,
        username=None,
        role=None,
        terminal_id=None,
        payment_method="cash",
        cash_session_id=None,
        discount_reason=None,
        discount_authorized_by=None,
    ):
        """Confirma todas as linhas de um carrinho numa unica transacao SQLite.

        A mesma ``transaction_code`` pode ser reenviada depois de uma resposta
        perdida. Se a venda ja foi concluida com os mesmos itens, devolvemos o
        sucesso idempotente sem mexer novamente no stock.
        """
        code = str(transaction_code or "").strip()
        normalized_items = [dict(item) for item in (items or []) if isinstance(item, dict)]
        if not code:
            return {"ok": False, "message": "Codigo de transacao obrigatorio"}
        if not normalized_items:
            return {"ok": False, "message": "Venda sem itens"}

        try:
            expected_signature = self._transaction_item_signature(normalized_items)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Itens de venda invalidos"}
        if not expected_signature or any(product_id <= 0 or quantity <= 0 or price < 0 for product_id, quantity, price, _mode in expected_signature):
            return {"ok": False, "message": "Itens de venda invalidos"}

        created_by = str(username or "SYSTEM").strip() or "SYSTEM"
        created_role = str(role or "manager").strip() or "manager"
        normalized_payment = str(payment_method or "cash").strip().lower()
        if normalized_payment not in {"cash", "card", "mobile", "emola"}:
            normalized_payment = "cash"
        normalized_terminal = str(terminal_id or "").strip() or None
        normalized_cash_session = int(cash_session_id) if cash_session_id else None
        owner_value = self._owner_value(created_by)

        try:
            self.cursor.execute(
                """
                SELECT status, item_count, created_by, created_role, terminal_id,
                       payment_method, cash_session_id, owner_username
                FROM sale_transactions WHERE transaction_code = ?
                """,
                (code,),
            )
            header = self.cursor.fetchone()
            if header:
                self.cursor.execute(
                    "SELECT product_id, quantity, sale_price, id, "
                    "COALESCE((SELECT sale_mode FROM produce_sales WHERE sale_id = sales.id), '') FROM sales "
                    "WHERE transaction_code = ? ORDER BY id",
                    (code,),
                )
                stored_rows = self.cursor.fetchall()
                stored_signature = sorted(
                    (int(row[0]), round(float(row[1] or 0.0), 6), round(float(row[2] or 0.0), 6), row[4])
                    for row in stored_rows
                )
                metadata_matches = (
                    int(header[1] or 0) == len(normalized_items)
                    and str(header[2] or "") == created_by
                    and str(header[3] or "") == created_role
                    and (str(header[4] or "").strip() or None) == normalized_terminal
                    and str(header[5] or "cash").strip().lower() == normalized_payment
                    and (int(header[6]) if header[6] else None) == normalized_cash_session
                    and str(header[7] or "") == str(owner_value or "")
                )
                if (
                    str(header[0] or "").upper() == "COMPLETED"
                    and metadata_matches
                    and stored_signature == expected_signature
                ):
                    return {
                        "ok": True,
                        "idempotent": True,
                        "transaction_code": code,
                        "sale_ids": [int(row[3]) for row in stored_rows],
                    }
                return {"ok": False, "message": "Codigo de transacao ja pertence a outra venda"}

            # Registos legados nao possuem cabecalho; protege contra duplicar
            # uma venda se um cliente antigo tiver usado o mesmo codigo.
            self.cursor.execute("SELECT id FROM sales WHERE transaction_code = ? LIMIT 1", (code,))
            if self.cursor.fetchone():
                return {"ok": False, "message": "Codigo de transacao ja existe sem cabecalho"}

            self.conn.execute("BEGIN IMMEDIATE")
            self.cursor.execute(
                """
                INSERT INTO sale_transactions (
                    transaction_code, created_at, created_by, created_role,
                    terminal_id, payment_method, cash_session_id, item_count,
                    status, owner_username
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PROCESSING', ?)
                """,
                (
                    code,
                    self._now_str(),
                    created_by,
                    created_role,
                    normalized_terminal,
                    normalized_payment,
                    normalized_cash_session,
                    len(normalized_items),
                    owner_value,
                ),
            )

            self._validate_produce_checkout(normalized_items)
            sale_ids = []
            for item in normalized_items:
                product_id = int(item.get("product_id", item.get("id")) or 0)
                quantity = float(item.get("quantity", item.get("qty")) or 0.0)
                unit_price = float(
                    item.get("sale_price", item.get("effective_unit_price", item.get("price"))) or 0.0
                )
                sale_id = self._add_sale_tx(
                    product_id,
                    quantity,
                    unit_price,
                    username=created_by,
                    role=created_role,
                    terminal_id=terminal_id,
                    produce_sale_mode=item.get("produce_sale_mode"),
                    is_promotional=bool(item.get("is_promotional")),
                    vat_rule_code=item.get("vat_rule_code"),
                    transaction_code=code,
                    payment_method=item.get("payment_method") or normalized_payment,
                    discount_amount=item.get("discount_amount", 0.0),
                    cash_session_id=item.get("cash_session_id", cash_session_id),
                    discount_reason=item.get("discount_reason", discount_reason),
                    discount_authorized_by=item.get("discount_authorized_by", discount_authorized_by),
                    commit=False,
                )
                if not sale_id:
                    raise RuntimeError("Nao foi possivel gravar todos os itens da venda")
                sale_ids.append(int(sale_id))

            self.cursor.execute(
                "UPDATE sale_transactions SET status = 'COMPLETED' WHERE transaction_code = ?",
                (code,),
            )
            self.conn.commit()
            self._run_sales_archive_maintenance()
            return {
                "ok": True,
                "idempotent": False,
                "transaction_code": code,
                "sale_ids": sale_ids,
            }
        except Exception as exc:
            try:
                self.conn.rollback()
            except Exception:
                pass
            print(f"Erro ao concluir transacao de venda: {exc}")
            return {"ok": False, "message": "Nao foi possivel concluir a venda"}

    def get_open_cash_session(self, username=None, terminal_id=None):
        """Retorna o caixa aberto do atendente neste terminal."""
        username = str(username or self.current_user or "").strip()
        terminal_id = str(terminal_id or "POS").strip() or "POS"
        if not username:
            return None
        self.cursor.execute(
            f"""
            SELECT id, username, role, terminal_id, opened_at, opening_amount,
                   opening_note, status
            FROM cash_sessions
            WHERE username = ? AND terminal_id = ? AND status = 'OPEN'
            ORDER BY id DESC LIMIT 1
            """,
            (username, terminal_id),
        )
        row = self.cursor.fetchone()
        if not row:
            return None
        keys = ("id", "username", "role", "terminal_id", "opened_at", "opening_amount", "opening_note", "status")
        return dict(zip(keys, row))

    def open_cash_session(self, username, terminal_id, opening_amount=0.0, note="", role=None):
        username = str(username or "").strip()
        terminal_id = str(terminal_id or "POS").strip() or "POS"
        if not username:
            return {"ok": False, "message": "Utilizador invalido"}
        try:
            opening_amount = float(opening_amount or 0.0)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Fundo inicial invalido"}
        if opening_amount < 0:
            return {"ok": False, "message": "O fundo inicial nao pode ser negativo"}
        existing = self.get_open_cash_session(username, terminal_id)
        if existing:
            return {"ok": True, "message": "Caixa ja estava aberto", "session": existing, "created": False}
        now = self._now_str()
        self.cursor.execute(
            """
            INSERT INTO cash_sessions (
                username, role, terminal_id, opened_at, opening_amount,
                opening_note, status, owner_username
            ) VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (username, role or self.current_role or "manager", terminal_id, now,
             opening_amount, str(note or "").strip(), self._owner_value(username)),
        )
        session_id = self.cursor.lastrowid
        self.conn.commit()
        self.log_action(username, role or "manager", "OPEN_CASH", f"Caixa #{session_id} | Fundo: {opening_amount:.2f} MT | Terminal: {terminal_id}")
        return {"ok": True, "message": "Caixa aberto com sucesso", "session": self.get_open_cash_session(username, terminal_id), "created": True}

    def get_cash_session_summary(self, session_id):
        self.cursor.execute(
            "SELECT id, username, terminal_id, opened_at, opening_amount, status, closed_at, counted_amount, expected_cash, difference_amount FROM cash_sessions WHERE id = ?",
            (int(session_id),),
        )
        session = self.cursor.fetchone()
        if not session:
            return None
        self.cursor.execute(
            f"""
            SELECT COALESCE(payment_method, 'cash'),
                   COALESCE(SUM(gross_total), 0),
                   {_transaction_count_sql()},
                   COALESCE(SUM(discount_amount), 0)
            FROM sales WHERE cash_session_id = ?
            GROUP BY COALESCE(payment_method, 'cash')
            """,
            (int(session_id),),
        )
        methods = {row[0]: {"total": float(row[1] or 0), "transactions": int(row[2] or 0), "discounts": float(row[3] or 0)} for row in self.cursor.fetchall()}
        self.cursor.execute(
            """
            SELECT COALESCE(SUM(sr.total_refund), 0)
            FROM sales_returns sr JOIN sales s ON s.id = sr.sale_id
            WHERE s.cash_session_id = ? AND COALESCE(s.payment_method, 'cash') = 'cash'
            """,
            (int(session_id),),
        )
        cash_refunds = float((self.cursor.fetchone() or [0])[0] or 0)
        opening = float(session[4] or 0)
        expected = opening + float(methods.get("cash", {}).get("total", 0)) - cash_refunds
        return {
            "id": session[0], "username": session[1], "terminal_id": session[2],
            "opened_at": session[3], "opening_amount": opening, "status": session[5],
            "closed_at": session[6], "counted_amount": session[7],
            "expected_cash": round(expected, 2), "difference_amount": session[9],
            "payment_methods": methods, "cash_refunds": round(cash_refunds, 2),
            "sales_total": round(sum(item["total"] for item in methods.values()), 2),
            "transaction_count": sum(item["transactions"] for item in methods.values()),
            "discount_total": round(sum(item["discounts"] for item in methods.values()), 2),
        }

    def close_cash_session(self, session_id, counted_amount, note="", closed_by=None, role=None):
        summary = self.get_cash_session_summary(session_id)
        if not summary:
            return {"ok": False, "message": "Sessao de caixa nao encontrada"}
        if summary["status"] != "OPEN":
            return {"ok": False, "message": "Este caixa ja esta fechado"}
        try:
            counted_amount = float(counted_amount)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Valor contado invalido"}
        if counted_amount < 0:
            return {"ok": False, "message": "O valor contado nao pode ser negativo"}
        expected = float(summary["expected_cash"])
        difference = round(counted_amount - expected, 2)
        closed_by = str(closed_by or self.current_user or summary["username"]).strip()
        self.cursor.execute(
            """
            UPDATE cash_sessions SET status='CLOSED', closed_at=?, counted_amount=?,
                expected_cash=?, difference_amount=?, closing_note=?, closed_by=?
            WHERE id=? AND status='OPEN'
            """,
            (self._now_str(), counted_amount, expected, difference, str(note or "").strip(), closed_by, int(session_id)),
        )
        self.conn.commit()
        self.log_action(closed_by, role or self.current_role or "manager", "CLOSE_CASH", f"Caixa #{session_id} | Esperado: {expected:.2f} MT | Contado: {counted_amount:.2f} MT | Diferenca: {difference:.2f} MT")
        closed = self.get_cash_session_summary(session_id)
        return {"ok": True, "message": "Caixa fechado com sucesso", "summary": closed}

    def get_active_physical_inventory(self):
        scope_sql, scope_params = self._owner_filter()
        self.cursor.execute(
            f"""
            SELECT id, name, status, started_at, started_by, terminal_id, note
            FROM physical_inventories
            WHERE status = 'COUNTING'{scope_sql}
            ORDER BY id DESC LIMIT 1
            """,
            tuple(scope_params),
        )
        row = self.cursor.fetchone()
        if not row:
            return None
        keys = ("id", "name", "status", "started_at", "started_by", "terminal_id", "note")
        return dict(zip(keys, row))

    def list_physical_inventories(self, limit=50, status=None):
        clauses = ["1=1"]
        params = []
        scope_sql, scope_params = self._owner_filter()
        normalized_status = str(status or "").strip().upper()
        if normalized_status in {"COUNTING", "COMPLETED", "CANCELLED"}:
            clauses.append("status = ?")
            params.append(normalized_status)
        params.extend(scope_params)
        params.append(max(1, min(int(limit or 50), 500)))
        self.cursor.execute(
            f"""
            SELECT id, name, status, started_at, started_by, completed_at,
                   completed_by, cancelled_at, cancelled_by, note
            FROM physical_inventories
            WHERE {' AND '.join(clauses)}{scope_sql}
            ORDER BY id DESC LIMIT ?
            """,
            tuple(params),
        )
        keys = ("id", "name", "status", "started_at", "started_by", "completed_at", "completed_by", "cancelled_at", "cancelled_by", "note")
        rows = []
        for row in self.cursor.fetchall():
            payload = dict(zip(keys, row))
            summary = self.get_physical_inventory_summary(payload["id"])
            if summary:
                payload.update({
                    "total_items": summary["total_items"],
                    "counted_items": summary["counted_items"],
                    "divergent_items": summary["divergent_items"],
                })
            rows.append(payload)
        return rows

    def start_physical_inventory(self, name, started_by, terminal_id=None, note=""):
        name = str(name or "").strip() or f"Inventario {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        started_by = str(started_by or self.current_user or "").strip()
        if not started_by:
            return {"ok": False, "message": "Utilizador invalido"}
        active = self.get_active_physical_inventory()
        if active:
            return {"ok": False, "message": "Ja existe um inventario em contagem", "inventory": active}
        try:
            now = self._now_str()
            owner = self._owner_value(started_by)
            self.cursor.execute(
                """
                INSERT INTO physical_inventories (
                    name, status, started_at, started_by, terminal_id, note, owner_username
                ) VALUES (?, 'COUNTING', ?, ?, ?, ?, ?)
                """,
                (name, now, started_by, terminal_id, str(note or "").strip(), owner),
            )
            inventory_id = self.cursor.lastrowid
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                f"""
                INSERT INTO physical_inventory_items (
                    inventory_id, product_id, product_name, unit, snapshot_qty
                )
                SELECT ?, id, description,
                       CASE WHEN COALESCE(is_sold_by_weight, 0) = 1 THEN 'KG' ELSE 'UN' END,
                       COALESCE(existing_stock, 0)
                FROM products
                WHERE COALESCE(status, 'ATIVO') <> ?{scope_sql}
                """,
                (inventory_id, ARCHIVED_PRODUCT_STATUS, *scope_params),
            )
            item_count = self.cursor.rowcount
            self.conn.commit()
            self.log_action(started_by, self.current_role or "admin", "START_INVENTORY", f"Inventario #{inventory_id}: {name} | {item_count} produtos")
            return {"ok": True, "message": "Inventario iniciado", "inventory": self.get_active_physical_inventory(), "item_count": item_count}
        except sqlite3.Error as exc:
            self.conn.rollback()
            return {"ok": False, "message": f"Erro ao iniciar inventario: {exc}"}

    def get_physical_inventory_items(self, inventory_id, query=None, only_uncounted=False, limit=100, offset=0):
        clauses = ["i.inventory_id = ?"]
        params = [int(inventory_id)]
        if only_uncounted:
            clauses.append("i.counted_qty IS NULL")
        query = str(query or "").strip()
        if query:
            clauses.append("(LOWER(i.product_name) LIKE LOWER(?) OR CAST(i.product_id AS TEXT) = ?)")
            params.extend([f"%{query}%", query])
        params.extend([max(1, min(int(limit or 100), 100000)), max(0, int(offset or 0))])
        self.cursor.execute(
            f"""
            SELECT i.id, i.product_id, i.product_name, i.unit, i.snapshot_qty,
                   i.counted_qty, i.difference_qty, i.counted_at, i.counted_by,
                   i.count_note, i.applied_difference, i.movement_id,
                   COALESCE(p.existing_stock, i.snapshot_qty) AS current_qty
            FROM physical_inventory_items i
            LEFT JOIN products p ON p.id = i.product_id
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE WHEN i.counted_qty IS NULL THEN 0 ELSE 1 END, i.product_name
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        )
        keys = ("item_id", "product_id", "product_name", "unit", "snapshot_qty", "counted_qty", "difference_qty", "counted_at", "counted_by", "count_note", "applied_difference", "movement_id", "current_qty")
        return [dict(zip(keys, row)) for row in self.cursor.fetchall()]

    def record_physical_inventory_count(self, inventory_id, product_id, counted_qty, counted_by, note=""):
        try:
            counted_qty = float(counted_qty)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Quantidade contada invalida"}
        if counted_qty < 0:
            return {"ok": False, "message": "A quantidade nao pode ser negativa"}
        self.cursor.execute("SELECT status FROM physical_inventories WHERE id = ?", (int(inventory_id),))
        status = self.cursor.fetchone()
        if not status or status[0] != "COUNTING":
            return {"ok": False, "message": "Inventario nao esta em contagem"}
        self.cursor.execute(
            "SELECT snapshot_qty FROM physical_inventory_items WHERE inventory_id = ? AND product_id = ?",
            (int(inventory_id), int(product_id)),
        )
        row = self.cursor.fetchone()
        if not row:
            return {"ok": False, "message": "Produto nao pertence a este inventario"}
        difference = round(counted_qty - float(row[0] or 0), 6)
        self.cursor.execute(
            """
            UPDATE physical_inventory_items
            SET counted_qty=?, difference_qty=?, counted_at=?, counted_by=?, count_note=?
            WHERE inventory_id=? AND product_id=?
            """,
            (counted_qty, difference, self._now_str(), str(counted_by or self.current_user or "SYSTEM"), str(note or "").strip(), int(inventory_id), int(product_id)),
        )
        self.conn.commit()
        return {"ok": True, "message": "Contagem guardada", "difference_qty": difference}

    def get_physical_inventory_summary(self, inventory_id):
        self.cursor.execute(
            "SELECT id, name, status, started_at, started_by, completed_at, completed_by, cancelled_at, cancelled_by FROM physical_inventories WHERE id=?",
            (int(inventory_id),),
        )
        inv = self.cursor.fetchone()
        if not inv:
            return None
        self.cursor.execute(
            """
            SELECT COUNT(*), COUNT(counted_qty),
                   SUM(CASE WHEN ABS(COALESCE(difference_qty, 0)) > 0.000001 THEN 1 ELSE 0 END),
                   COALESCE(SUM(ABS(COALESCE(difference_qty, 0))), 0)
            FROM physical_inventory_items WHERE inventory_id=?
            """,
            (int(inventory_id),),
        )
        total, counted, divergent, absolute_difference = self.cursor.fetchone()
        return {
            "id": inv[0], "name": inv[1], "status": inv[2], "started_at": inv[3], "started_by": inv[4],
            "completed_at": inv[5], "completed_by": inv[6], "cancelled_at": inv[7], "cancelled_by": inv[8],
            "total_items": int(total or 0), "counted_items": int(counted or 0),
            "pending_items": int(total or 0) - int(counted or 0), "divergent_items": int(divergent or 0),
            "absolute_difference": float(absolute_difference or 0),
        }

    def complete_physical_inventory(self, inventory_id, completed_by, allow_partial=False, note=""):
        summary = self.get_physical_inventory_summary(inventory_id)
        if not summary or summary["status"] != "COUNTING":
            return {"ok": False, "message": "Inventario nao esta em contagem"}
        if summary["counted_items"] == 0:
            return {"ok": False, "message": "Nenhum produto foi contado"}
        if summary["pending_items"] and not allow_partial:
            return {"ok": False, "message": f"Ainda faltam {summary['pending_items']} produtos"}
        try:
            items = self.get_physical_inventory_items(inventory_id, limit=100000)
            adjustment_count = 0
            for item in items:
                if item["counted_qty"] is None:
                    continue
                current_qty = float(item["current_qty"] or 0)
                target_qty = float(item["counted_qty"] or 0)
                difference = round(target_qty - current_qty, 6)
                movement_id = None
                if abs(difference) > 0.000001:
                    movement_id = self._record_stock_movement_tx(
                        self.cursor, item["product_id"], "ADJUSTMENT", abs(difference),
                        "IN" if difference > 0 else "OUT",
                        reason="Inventario fisico",
                        note=f"Inventario #{inventory_id}: {summary['name']} | {str(note or '').strip()}",
                        reference_table="physical_inventories", reference_id=int(inventory_id),
                        created_by=completed_by, created_role="admin",
                        approval_status="APPROVED", approved_by=completed_by,
                        approved_at=self._now_str(), apply_stock=True,
                    )
                    if not movement_id:
                        raise sqlite3.Error(f"Falha ao ajustar produto #{item['product_id']}")
                    adjustment_count += 1
                self.cursor.execute(
                    "UPDATE physical_inventory_items SET applied_difference=?, movement_id=? WHERE id=?",
                    (difference, movement_id, item["item_id"]),
                )
            now = self._now_str()
            self.cursor.execute(
                "UPDATE physical_inventories SET status='COMPLETED', completed_at=?, completed_by=?, note=CASE WHEN ?='' THEN note ELSE ? END WHERE id=? AND status='COUNTING'",
                (now, str(completed_by or self.current_user or "admin"), str(note or "").strip(), str(note or "").strip(), int(inventory_id)),
            )
            self.conn.commit()
            self.log_action(completed_by, "admin", "COMPLETE_INVENTORY", f"Inventario #{inventory_id} | Contados: {summary['counted_items']} | Ajustes: {adjustment_count}")
            return {"ok": True, "message": "Inventario concluido", "adjustment_count": adjustment_count, "summary": self.get_physical_inventory_summary(inventory_id)}
        except sqlite3.Error as exc:
            self.conn.rollback()
            return {"ok": False, "message": f"Erro ao concluir inventario: {exc}"}

    def cancel_physical_inventory(self, inventory_id, cancelled_by, reason=""):
        self.cursor.execute(
            "UPDATE physical_inventories SET status='CANCELLED', cancelled_at=?, cancelled_by=?, note=CASE WHEN ?='' THEN note ELSE ? END WHERE id=? AND status='COUNTING'",
            (self._now_str(), str(cancelled_by or self.current_user or "admin"), str(reason or "").strip(), str(reason or "").strip(), int(inventory_id)),
        )
        changed = self.cursor.rowcount > 0
        self.conn.commit()
        if changed:
            self.log_action(cancelled_by, "admin", "CANCEL_INVENTORY", f"Inventario #{inventory_id} | Motivo: {reason or 'nao informado'}")
        return {"ok": changed, "message": "Inventario cancelado" if changed else "Inventario nao pode ser cancelado"}
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
                s.product_id,
                s.transaction_code
            FROM sales_history s
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
                SELECT id, product_id, quantity, sale_price, sale_date
                FROM sales
                WHERE id = ?
                """,
                (sale_id,),
            )
            sale = self.cursor.fetchone()
            if not sale:
                return {"ok": False, "message": "Venda nao encontrada"}

            _sid, product_id, sold_qty, sale_price, sale_date = sale
            refund_allowed, _seconds_left = refund_window_status(sale_date)
            if not refund_allowed:
                return {
                    "ok": False,
                    "message": (
                        f"O prazo de {REFUND_WINDOW_MINUTES} minutos para estorno desta venda expirou"
                    ),
                }
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

            produce_sale = self.conn.execute(
                "SELECT sale_mode, stock_applied FROM produce_sales WHERE sale_id = ?", (sale_id,)
            ).fetchone()
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
                apply_stock=bool(produce_sale[1]) if produce_sale else True,
                unit_cost=0 if produce_sale and not produce_sale[1] else None,
                movement_unit=PRODUCE_MODES.get(produce_sale[0]) if produce_sale else None,
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
            self.log_action(
                created_by,
                created_role,
                "REFUND_SALE",
                f"Venda #{sale_id} | Quantidade: {quantity:.2f} | Reembolso: {total_refund:.2f} MT | Motivo: {reason}",
            )
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
            
            transaction_key = _transaction_key_sql("s")
            self.cursor.execute(f"""
                WITH transactions AS (
                    SELECT
                        {transaction_key} AS transaction_key,
                        COALESCE(SUM(s.quantity), 0) AS total_quantity,
                        COALESCE(SUM(s.total_price), 0) AS total_revenue
                    FROM sales_history s
                    WHERE DATE(s.sale_date) = ?
                    GROUP BY {transaction_key}
                )
                SELECT
                    COUNT(*) AS total_sales,
                    COALESCE(SUM(total_quantity), 0) AS total_quantity,
                    COALESCE(SUM(total_revenue), 0) AS total_revenue,
                    COALESCE(AVG(total_revenue), 0) AS average_sale,
                    COALESCE(MIN(total_revenue), 0) AS min_sale,
                    COALESCE(MAX(total_revenue), 0) AS max_sale
                FROM transactions
            """, (formatted_date,))
            
            return self.cursor.fetchone()
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao obter estatÃƒÆ’Ã‚Â­sticas por data: {e}")
            return None

    def get_monthly_sales_summary(self, month, year):
        """Obter resumo de vendas mensais"""
        try:
            self.cursor.execute(f"""
                SELECT 
                    DATE(s.sale_date) as date,
                    {_transaction_count_sql("s")} as daily_sales,
                    SUM(s.quantity) as daily_quantity,
                    SUM(s.total_price) as daily_revenue
                FROM sales_history s
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
                  AND COALESCE(status, 'ATIVO') <> ?
                ORDER BY id
                """,
                (ARCHIVED_PRODUCT_STATUS,),
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
                  AND COALESCE(status, 'ATIVO') <> ?
                {scope_sql}
                ORDER BY LOWER(COALESCE(description, '')) ASC, {self._expiry_order_clause()}
                """,
                (ARCHIVED_PRODUCT_STATUS, *scope_params),
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
                       expiry_date, status, vat_rule_code, sold_stock
                FROM products
                WHERE COALESCE(status, 'ATIVO') <> ?
                {scope_sql}
                ORDER BY LOWER(COALESCE(description, '')) ASC, {self._expiry_order_clause()}
                """,
                (ARCHIVED_PRODUCT_STATUS, *scope_params),
            )
            rows = self.cursor.fetchall()
            if not include_velocity:
                # Preserva o formato histórico para os outros ecrãs. A coluna
                # extra só é usada pela previsão de compras.
                return [row[:10] for row in rows]

            velocity = _fetch_sales_velocity(self, days=velocity_days)
            enriched = []
            for row in rows:
                (
                    pid, name, stock, price, cost, barcode, is_weight, exp,
                    status, vat_rule_code, sold_stock,
                ) = row
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
                        sold_stock,
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
                    MAX(sm.created_at) AS last_stock_update_at,
                    p.sold_stock
                FROM products p
                LEFT JOIN stock_movements sm
                    ON sm.product_id = p.id
                   AND sm.applied = 1
                WHERE COALESCE(p.status, 'ATIVO') <> ?
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
                    p.status,
                    p.sold_stock
                """,
                (ARCHIVED_PRODUCT_STATUS, *scope_params),
            )
            rows = self.cursor.fetchall()
            if not include_velocity:
                return [row[:10] for row in rows]

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
                    sold_stock,
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
                        sold_stock,
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

    def get_products_for_losses_page(self, search_text="", limit=10, offset=0):
        """Página de produtos elegíveis para perdas, filtrada no SQLite."""
        try:
            scope_sql, scope_params = self._owner_filter()
            params = [ARCHIVED_PRODUCT_STATUS, *scope_params]
            query = """SELECT id, description, existing_stock, sale_price,
                       unit_purchase_price, barcode, is_sold_by_weight,
                       expiry_date, status, vat_rule_code
                FROM products WHERE existing_stock > 0
                  AND COALESCE(status, 'ATIVO') <> ?""" + scope_sql
            search = str(search_text or "").strip().lower()
            if search:
                like = f"%{search}%"
                query += " AND (CAST(id AS TEXT) LIKE ? OR LOWER(description) LIKE ? OR LOWER(COALESCE(barcode, '')) LIKE ?)"
                params.extend((like, like, like))
            size = max(1, min(100, int(limit or 10)))
            query += " ORDER BY id ASC LIMIT ? OFFSET ?"
            params.extend((size + 1, max(0, int(offset or 0))))
            rows = self._readonly_fetchall(query, params)
            return {"rows": rows[:size], "has_more": len(rows) > size}
        except sqlite3.Error as exc:
            print(f"Erro ao obter página de produtos para perdas: {exc}")
            return {"rows": [], "has_more": False}

    def get_products_for_stock_control_page(self, search_text="", limit=100, offset=0):
        """Página leve do controlo de stock, própria para catálogos grandes.

        Não agrega movimentos nem vendas de todo o catálogo. A última alteração
        e a velocidade são calculadas apenas para a página devolvida.
        """
        try:
            page_size = max(1, min(500, int(limit or 100)))
            page_offset = max(0, int(offset or 0))
            scope_sql, scope_params = self._owner_filter("p")
            params = [ARCHIVED_PRODUCT_STATUS, *scope_params]
            query = """
                SELECT p.id, p.description, p.existing_stock, p.sale_price,
                       p.unit_purchase_price, p.barcode, p.is_sold_by_weight,
                       p.expiry_date, p.status, p.sold_stock
                FROM products p
                WHERE COALESCE(p.status, 'ATIVO') <> ?
            """ + scope_sql
            search = str(search_text or "").strip().lower()
            if search:
                like = f"%{search}%"
                query += """ AND (CAST(p.id AS TEXT) LIKE ?
                                  OR LOWER(COALESCE(p.description, '')) LIKE ?
                                  OR LOWER(COALESCE(p.barcode, '')) LIKE ?)"""
                params.extend((like, like, like))
            # A prioridade detalhada de reposição é calculada apenas depois de
            # pesquisar. Para a tabela inicial, ordenar pelo PK permite ao
            # SQLite devolver a primeira página sem classificar o catálogo.
            query += " ORDER BY p.id ASC LIMIT ? OFFSET ?"
            params.extend((page_size + 1, page_offset))
            rows = self._readonly_fetchall(query, params)
            has_more = len(rows) > page_size
            rows = rows[:page_size]
            if not rows:
                return {"rows": [], "has_more": False}
            ids = [row[0] for row in rows]
            marks = ",".join("?" for _ in ids)
            last_updates = dict(self._readonly_fetchall(
                f"SELECT product_id, MAX(created_at) FROM stock_movements WHERE applied = 1 AND product_id IN ({marks}) GROUP BY product_id",
                ids,
            ))
            velocity = dict(self._readonly_fetchall(
                f"SELECT product_id, SUM(quantity) / 14.0 FROM sales WHERE sale_date >= DATE('now', '-14 days') AND product_id IN ({marks}) GROUP BY product_id",
                ids,
            ))
            result = []
            for row in rows:
                stock = _safe_float(row[2], 0.0)
                avg = _safe_float(velocity.get(row[0]), 0.0)
                result.append((*row[:9], avg, (stock / avg) if avg > 0 else None, last_updates.get(row[0]), row[9]))
            return {"rows": result, "has_more": has_more}
        except sqlite3.Error as exc:
            print(f"Erro ao obter página de controlo de stock: {exc}")
            return {"rows": [], "has_more": False}

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
                "WHERE category IS NOT NULL AND category != '' "
                "AND COALESCE(status, 'ATIVO') <> ?" + scope_sql + " ORDER BY category",
                (ARCHIVED_PRODUCT_STATUS, *scope_params),
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
                FROM sales_history s
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

    def get_products_sale_revision(self):
        """Assinatura barata para saber se stock/catalogo mudou sem recarregar linhas."""
        try:
            scope_sql, scope_params = self._owner_filter()
            self.cursor.execute(
                """
                SELECT COUNT(*),
                       ROUND(COALESCE(SUM(existing_stock), 0), 6),
                       ROUND(COALESCE(SUM(sold_stock), 0), 6),
                       COALESCE(MAX(id), 0),
                       COALESCE(MAX(status_updated_at), '')
                FROM products WHERE COALESCE(status, 'ATIVO') <> ?
                """ + scope_sql,
                (ARCHIVED_PRODUCT_STATUS, *scope_params),
            )
            row = self.cursor.fetchone() or (0, 0, 0, 0, "")
            return "|".join(str(value) for value in row)
        except sqlite3.Error:
            return ""

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
        LEFT JOIN sales_history s
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

        query = f"""
        SELECT
            DATE(s.sale_date) AS sale_day,
            COALESCE(NULLIF(s.terminal_id, ''), 'CAIXA-PRINCIPAL') AS terminal_id,
            {_transaction_count_sql("s")} AS sales_count,
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
                FROM sales_history s
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
            {_transaction_count_sql("s")} AS sales_count,
            COALESCE(SUM(s.quantity), 0) AS quantity,
            COALESCE(SUM(s.total_price), 0) AS revenue,
            MIN(s.id) AS first_sale_id,
            MAX(s.id) AS last_sale_id
        FROM sales_history s
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
            lookback_days = max(7, min(int(lookback_days or 30), 3650))
        except Exception:
            lookback_days = 30

        now = datetime.now()
        today_date = now.date()
        start_date = today_date - timedelta(days=lookback_days - 1)
        group_by_month = lookback_days >= 365
        if group_by_month:
            start_date = date(start_date.year, start_date.month, 1)
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
                    "user_logs_today": 0,
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
                "SELECT COUNT(*) FROM products WHERE existing_stock > 0 "
                "AND (existing_stock + COALESCE(sold_stock, 0)) > 0 "
                "AND existing_stock < (existing_stock + COALESCE(sold_stock, 0)) * 0.30"
                + product_scope_sql,
                tuple(product_scope_params),
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
                "SELECT COUNT(*) FROM user_logs WHERE DATE(timestamp) = ?"
                + (" AND COALESCE(owner_username, '') = ?" if owner else ""),
                (today_iso, owner) if owner else (today_iso,),
            )
            user_logs_today = int(self.cursor.fetchone()[0] or 0)

            self.cursor.execute(
                "SELECT COUNT(DISTINCT supplier_name) FROM stock_movements "
                "WHERE supplier_name IS NOT NULL AND TRIM(supplier_name) != ''"
                + (" AND COALESCE(owner_username, '') = ?" if owner else ""),
                (owner,) if owner else (),
            )
            active_suppliers = int(self.cursor.fetchone()[0] or 0)

            self.cursor.execute(
                f"SELECT {_transaction_count_sql()}, COALESCE(SUM(total_price), 0) "
                "FROM sales_history WHERE DATE(sale_date) = ?"
                + (" AND COALESCE(owner_username, '') = ?" if owner else ""),
                (today_iso, owner) if owner else (today_iso,),
            )
            sales_today_count, revenue_today = self.cursor.fetchone()
            sales_today_count = int(sales_today_count or 0)
            revenue_today = round(_safe_float(revenue_today), 2)

            self.cursor.execute(
                "SELECT COALESCE(SUM(total_price), 0) "
                "FROM sales_history WHERE strftime('%m', sale_date) = ? AND strftime('%Y', sale_date) = ?"
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

            sales_period_expr = "strftime('%Y-%m', sale_date)" if group_by_month else "DATE(sale_date)"
            movement_period_expr = "strftime('%Y-%m', created_at)" if group_by_month else "DATE(created_at)"

            self.cursor.execute(
                f"SELECT {sales_period_expr} AS sale_period, {_transaction_count_sql()} AS sales_count, "
                "COALESCE(SUM(total_price), 0) AS revenue "
                "FROM sales_history WHERE DATE(sale_date) BETWEEN ? AND ? "
                + ("AND COALESCE(owner_username, '') = ? " if owner else "")
                + f"GROUP BY {sales_period_expr} ORDER BY {sales_period_expr} ASC",
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
                f"SELECT {movement_period_expr} AS movement_period, "
                "COALESCE(SUM(CASE WHEN direction = 'IN' THEN qty ELSE 0 END), 0) AS qty_in, "
                "COALESCE(SUM(CASE WHEN direction = 'OUT' THEN qty ELSE 0 END), 0) AS qty_out "
                "FROM stock_movements "
                "WHERE applied = 1 AND DATE(created_at) BETWEEN ? AND ? "
                + ("AND COALESCE(owner_username, '') = ? " if owner else "")
                + f"GROUP BY {movement_period_expr} ORDER BY {movement_period_expr} ASC",
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
                "FROM sales_history s "
                "LEFT JOIN products p ON s.product_id = p.id "
                "LEFT JOIN products_archive pa ON s.product_id = pa.id "
                "WHERE DATE(s.sale_date) BETWEEN ? AND ? "
                + ("AND COALESCE(s.owner_username, '') = ? " if owner else "")
                + "GROUP BY s.product_id "
                "ORDER BY total_revenue DESC, total_qty DESC LIMIT 8",
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
                "FROM sales_history s "
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
                "FROM sales_history WHERE DATE(sale_date) = ? "
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
            if group_by_month:
                periods = []
                current_month = date(start_date.year, start_date.month, 1)
                final_month = date(today_date.year, today_date.month, 1)
                while current_month <= final_month:
                    month_key_full = current_month.isoformat()
                    month_key_short = current_month.strftime("%Y-%m")
                    periods.append(
                        (
                            month_key_short,
                            month_key_full,
                            current_month.strftime("%m/%Y"),
                        )
                    )
                    if current_month.month == 12:
                        current_month = date(current_month.year + 1, 1, 1)
                    else:
                        current_month = date(current_month.year, current_month.month + 1, 1)
            else:
                periods = []
                current_day = start_date
                while current_day <= today_date:
                    day_key = current_day.isoformat()
                    periods.append((day_key, day_key, current_day.strftime("%d/%m")))
                    current_day += timedelta(days=1)

            for period_key, date_key, label in periods:
                sales_entry = sales_map.get(period_key, {})
                stock_entry = stock_map.get(period_key, {})
                sales_series.append(
                    {
                        "date": date_key,
                        "label": label,
                        "sales_count": int(sales_entry.get("sales_count") or 0),
                        "revenue": round(_safe_float(sales_entry.get("revenue")), 2),
                    }
                )
                stock_flow_series.append(
                    {
                        "date": date_key,
                        "label": label,
                        "in_qty": round(_safe_float(stock_entry.get("in_qty")), 2),
                        "out_qty": round(_safe_float(stock_entry.get("out_qty")), 2),
                    }
                )

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
            for name, stock, is_weight, days_left, product_id in (insights.get("low_stock") or []):
                if _safe_float(stock) <= 0:
                    continue
                low_stock_items.append(
                    {
                        "product_id": product_id,
                        "name": name,
                        "stock": round(_safe_float(stock), 2),
                        "is_weight": bool(is_weight),
                        "days_left": round(_safe_float(days_left), 1) if days_left is not None and _safe_float(days_left) < 999 else None,
                    }
                )
                if len(low_stock_items) >= 6:
                    break

            def _expiry_product_id(name, date_str):
                try:
                    parsed = datetime.strptime(str(date_str or ""), "%d/%m/%Y").strftime("%Y-%m-%d")
                except Exception:
                    parsed = str(date_str or "").strip()
                try:
                    self.cursor.execute(
                        "SELECT id FROM products "
                        "WHERE description = ? AND (expiry_date = ? OR DATE(expiry_date) = ?) "
                        "ORDER BY id ASC LIMIT 1",
                        (name, parsed, parsed),
                    )
                    row = self.cursor.fetchone()
                    return row[0] if row else None
                except Exception:
                    return None

            def _expiry_items(rows):
                items = []
                for name, days_left, date_str, stock, unit in list(rows or [])[:6]:
                    items.append(
                        {
                            "product_id": _expiry_product_id(name, date_str),
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
                "user_logs_today": user_logs_today,
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
                    "critical_stock": critical_stock_count,
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

    def get_user_logs(
        self,
        user_filter="",
        action_filter="",
        role_filter="",
        limit=100,
        offset=0,
        exclude_actions=None,
        details_limit=None,
        date_filter=None,
    ):
        """Obter logs do sistema com filtros"""
        details_expr = "details"
        if details_limit:
            safe_details_limit = max(40, min(int(details_limit), 1000))
            details_expr = (
                "CASE "
                "WHEN details IS NULL THEN NULL "
                f"WHEN LENGTH(details) > {safe_details_limit} "
                f"THEN SUBSTR(details, 1, {safe_details_limit}) || '...' "
                "ELSE details END"
            )
        query = (
            f"SELECT id, username, role, action, {details_expr}, timestamp "
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

        if date_filter:
            try:
                selected_date = datetime.strptime(str(date_filter), "%Y-%m-%d")
            except (TypeError, ValueError):
                return []
            next_date = selected_date + timedelta(days=1)
            query += " AND timestamp >= ? AND timestamp < ?"
            params.extend((
                selected_date.strftime("%Y-%m-%d 00:00:00"),
                next_date.strftime("%Y-%m-%d 00:00:00"),
            ))

        if exclude_actions:
            ignored = [
                str(action or "").strip().upper()
                for action in exclude_actions
                if str(action or "").strip()
            ]
            if ignored:
                placeholders = ",".join("?" for _ in ignored)
                query += f" AND UPPER(action) NOT IN ({placeholders})"
                params.extend(ignored)

        query += " ORDER BY timestamp DESC, id DESC"
        if limit:
            query += " LIMIT ? OFFSET ?"
            params.append(int(limit))
            params.append(max(0, int(offset or 0)))

        read_cursor = self.conn.cursor()
        try:
            # Os logs sao consultados numa thread pelo painel. Um cursor
            # exclusivo evita concorrer com as consultas da Home no cursor
            # partilhado e mantem a abertura do popup imediata.
            read_cursor.execute(query, params)
            return read_cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter logs: {e}")
            return []
        finally:
            read_cursor.close()

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
            f"SELECT COALESCE(SUM(total_price), 0), {_transaction_count_sql()} "
            "FROM sales_history WHERE DATE(sale_date) = ?",
            (today,),
        )
        total_sales, total_count = self.cursor.fetchone()
        total_sales = _safe_float(total_sales, 0.0)
        total_count = int(total_count or 0)

        self.cursor.execute(
            "SELECT COALESCE(p.description, pa.description), COALESCE(SUM(s.total_price), 0) AS total_val "
            "FROM sales_history s "
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
            "FROM sales_history WHERE DATE(sale_date) = ? "
            "GROUP BY h ORDER BY total_val DESC LIMIT 1",
            (today,),
        )
        row = self.cursor.fetchone()
        peak_hour = f"{row[0]}:00-{row[0]}:59" if row else "n/d"

        self.cursor.execute(
            "SELECT id, description, existing_stock, is_sold_by_weight FROM products "
            "WHERE existing_stock > 0 "
            "AND (existing_stock + COALESCE(sold_stock, 0)) > 0 "
            "AND existing_stock < (existing_stock + COALESCE(sold_stock, 0)) * 0.30 "
            "ORDER BY existing_stock ASC",
        )
        low_stock_raw = self.cursor.fetchall()

        low_stock = []
        daily_sales_by_product = _fetch_sales_velocity(self) if low_stock_raw else {}
        for prod_id, name, stock, is_weight in low_stock_raw:
            daily_sales = daily_sales_by_product.get(prod_id, 0.0)
            days_left = _safe_float(stock) / max(daily_sales, 0.1) if daily_sales > 0 else 999
            low_stock.append((name, stock, is_weight, days_left, prod_id))

        self.cursor.execute(
            "SELECT description, profit_per_unit FROM products "
            "WHERE profit_per_unit < 0 ORDER BY profit_per_unit ASC"
        )
        negative_profit = self.cursor.fetchall()
        # Os Insights do administrador incluem os mesmos padroes usados pelo
        # botao de fraude; apenas perdas de gerente entram nesta analise.
        fraud_alerts = self.detect_fraud_patterns(days_lookback=30) or []

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
            alerts.append(f"{len(low_stock)} produtos com stock critico (abaixo de 30%).")
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
        if fraud_alerts:
            alerts.append(f"{len(fraud_alerts)} alertas de fraude requerem verificacao.")

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
            + len(fraud_alerts)
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
            "fraud_alerts": fraud_alerts,
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
                "fraud": len(fraud_alerts),
                "total": len(low_stock) + expiry_total + len(fraud_alerts),
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
        produce_options=None,
        custom_fields=None,
    ):
        """Atualizar produto existente"""
        try:
            if produce_options is not None:
                produce_mode, _ = self._normalize_produce_options(produce_options)
                if produce_mode == "SACKS" and (is_sold_by_weight or allow_pack_sale):
                    raise ValueError("Sacos avulsos nao usam conversao por embalagem ou stock em kg")
            is_sold_by_weight = bool(is_sold_by_weight)
            existing_stock = _inventory_quantity(
                existing_stock,
                is_sold_by_weight,
                "Estoque atual",
            )
            sold_stock = _inventory_quantity(
                sold_stock,
                is_sold_by_weight,
                "Estoque vendido",
            )
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
                    existing_stock,
                    sold_stock,
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
            self._save_produce_options_tx(id, produce_options)
            self._save_product_custom_field_values_tx(id, custom_fields)
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


