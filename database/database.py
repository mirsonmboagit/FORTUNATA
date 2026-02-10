import sqlite3
import os
import sqlite3
from datetime import datetime, timedelta, date
import bcrypt

NEAR_EXPIRY_DAYS = 15
LOSS_QTY_LIMIT_UN = 10
LOSS_QTY_LIMIT_KG = 5.0
LOSS_VALUE_LIMIT_MZN = 5000
LOSS_TYPES = {"DAMAGE", "EXPIRED", "THEFT", "ADJUSTMENT"}

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


def _fetch_sales_velocity(db, days=14):
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    db.cursor.execute(
        "SELECT product_id, COALESCE(SUM(quantity), 0) "
        "FROM sales WHERE DATE(sale_date) >= ? "
        "GROUP BY product_id",
        (start_date,),
    )
    totals = {row[0]: _safe_float(row[1], 0.0) for row in db.cursor.fetchall()}
    velocity = {}
    for product_id, total_qty in totals.items():
        velocity[product_id] = total_qty / max(days, 1)
    return velocity


def _get_product_daily_sales(db, product_id, days=14):
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    db.cursor.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM sales "
        "WHERE product_id = ? AND DATE(sale_date) >= ?",
        (product_id, start_date),
    )
    total = _safe_float(db.cursor.fetchone()[0], 0.0)
    return total / max(days, 1)


def _build_forecasts(db, days=14, limit=10):
    velocity = _fetch_sales_velocity(db, days=days)
    db.cursor.execute(
        "SELECT id, description, existing_stock, is_sold_by_weight, expiry_date, "
        "sale_price, unit_purchase_price "
        "FROM products"
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

class Database:
    def __init__(self, db_name="inventory.db", db_path=None, db_folder="database"):
        # Guardamos o nome simples
        self.db_name = db_name

        # Definimos a pasta/base do banco
        if db_path:
            self.db_path = os.path.abspath(db_path)
            self.db_folder = os.path.dirname(self.db_path) or "."
            self.db_name = os.path.basename(self.db_path)
        else:
            self.db_folder = db_folder
            self.db_path = os.path.join(self.db_folder, self.db_name)

        # Criamos a pasta se n??o existir
        if self.db_folder and not os.path.exists(self.db_folder):
            os.makedirs(self.db_folder)
            print(f"???? Pasta '{self.db_folder}' criada!")

        self.conn = None
        self.cursor = None
        self.connect()
        self.setup()
    
    def connect(self):
        """Conectar ao banco de dados"""
        try:
            # IMPORTANTE: Usamos o self.db_path aqui
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.cursor = self.conn.cursor()
            print(f"✅ Conectado com sucesso em: {self.db_path}")
        except sqlite3.Error as e:
            print(f"❌ Erro ao conectar: {e}")
    
    def close(self):
        """Fechar a conexão com o banco de dados"""
        if self.conn:
            self.conn.close()
    
    def setup(self):
        """Configurar tabelas do banco de dados"""
        try:
            # Tabela de usuários (administrador e gerente)
            self.cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )''')
            # Garantir colunas de contacto para recuperacao (email/telefone)
            try:
                self.cursor.execute("PRAGMA table_info(users)")
                cols = [row[1] for row in self.cursor.fetchall()]
                if "email" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
                if "phone" not in cols:
                    self.cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")
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
                status_updated_by TEXT
            )''')

            # Tabela de produtos arquivados (excluídos)
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
                deleted_at TEXT,
                deleted_by TEXT
            )''')

            # Tabela de logs do sistema
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                role TEXT,
                action TEXT NOT NULL,
                details TEXT,
                timestamp TEXT NOT NULL
            )''')
            
            # ===== VERIFICAR E ADICIONAR COLUNAS NECESSÁRIAS =====
            self.cursor.execute("PRAGMA table_info(products)")
            columns = [column[1] for column in self.cursor.fetchall()]
            # Nao criar usuario padrao automaticamente
            if 'is_sold_by_weight' not in columns:
                print("⚙️ Adicionando coluna 'is_sold_by_weight' à tabela products...")
                self.cursor.execute("ALTER TABLE products ADD COLUMN is_sold_by_weight INTEGER DEFAULT 0")
                print("✅ Coluna 'is_sold_by_weight' adicionada com sucesso!")
            
            # ===== ADICIONAR COLUNAS DE STATUS (se necessário) =====
            def ensure_column(table, column, col_def):
                self.cursor.execute(f"PRAGMA table_info({table})")
                cols = [c[1] for c in self.cursor.fetchall()]
                if column not in cols:
                    self.cursor.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
                    )

            ensure_column("products", "status", "TEXT DEFAULT 'ATIVO'")
            ensure_column("products", "status_source", "TEXT DEFAULT 'MANUAL'")
            ensure_column("products", "status_reason", "TEXT")
            ensure_column("products", "status_updated_at", "TEXT")
            ensure_column("products", "status_updated_by", "TEXT")
            ensure_column("products", "package_quantity", "TEXT")
            ensure_column("products_archive", "package_quantity", "TEXT")
            ensure_column("products_archive", "status", "TEXT")
            ensure_column("products_archive", "status_source", "TEXT")
            ensure_column("products_archive", "status_reason", "TEXT")
            ensure_column("products_archive", "status_updated_at", "TEXT")
            ensure_column("products_archive", "status_updated_by", "TEXT")
            ensure_column("products_archive", "deleted_at", "TEXT")
            ensure_column("products_archive", "deleted_by", "TEXT")

            # ===== ALTERAR TIPO DE DADOS PARA SUPORTAR DECIMAIS (KG) =====
            # Verificar se as colunas de estoque já são REAL (suportam decimais)
            self.cursor.execute("PRAGMA table_info(products)")
            columns_info = self.cursor.fetchall()
            
            existing_stock_type = None
            sold_stock_type = None
            
            for col in columns_info:
                if col[1] == 'existing_stock':
                    existing_stock_type = col[2]
                elif col[1] == 'sold_stock':
                    sold_stock_type = col[2]
            
            # Se as colunas forem INTEGER, precisamos recriá-las como REAL
            if existing_stock_type == 'INTEGER' or sold_stock_type == 'INTEGER':
                print("⚙️ Convertendo colunas de estoque para suportar valores decimais (KG)...")
                
                # Criar tabela temporária com tipos corretos
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
                    status_updated_by TEXT
                )''')
                
                # Copiar dados para tabela temporária
                self.cursor.execute('''
                INSERT INTO products_temp 
                SELECT id, description, category, CAST(existing_stock AS REAL), 
                       CAST(sold_stock AS REAL), sale_price, total_purchase_price, 
                       unit_purchase_price, profit_per_unit, barcode, expiry_date, 
                       date_added, is_sold_by_weight,
                       NULL,
                       'ATIVO', 'MANUAL', NULL, NULL, NULL
                FROM products
                ''')
                
                # Remover tabela antiga
                self.cursor.execute('DROP TABLE products')
                
                # Renomear tabela temporária
                self.cursor.execute('ALTER TABLE products_temp RENAME TO products')
                
                print("✅ Colunas convertidas para REAL (suportam decimais)!")
            
            # Tabela de vendas (atualizada para aceitar quantidades decimais - KG)
            self.cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                sale_price REAL NOT NULL,
                total_price REAL NOT NULL,
                sale_date TEXT NOT NULL,
                created_by TEXT,
                created_role TEXT,
                terminal_id TEXT,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )''')

            # Garantir novas colunas na tabela sales (bases antigas)
            ensure_column("sales", "created_by", "TEXT")
            ensure_column("sales", "created_role", "TEXT")
            ensure_column("sales", "terminal_id", "TEXT")

            # Atualizar status default para registros antigos
            self.cursor.execute(
                "UPDATE products SET status = 'ATIVO' "
                "WHERE status IS NULL OR status = ''"
            )
            self.cursor.execute(
                "UPDATE products SET status_source = 'MANUAL' "
                "WHERE status_source IS NULL OR status_source = ''"
            )

            # Tabela de movimentos de stock (livro-razão)
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
                FOREIGN KEY (product_id) REFERENCES products (id)
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
                FOREIGN KEY (product_id) REFERENCES products (id)
            )''')

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
                FOREIGN KEY (related_product_id) REFERENCES products (id),
                FOREIGN KEY (related_movement_id) REFERENCES stock_movements (id)
            )''')

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
                "CREATE INDEX IF NOT EXISTS idx_products_status "
                "ON products (status)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_fraud_status "
                "ON fraud_alerts (status, severity)"
            )
            
            self.conn.commit()
            print("✅ Banco de dados configurado com suporte completo a vendas por KG e sistema de perdas!")
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao configurar o banco de dados: {e}")
            import traceback
            traceback.print_exc()
    
    def validate_user(self, username, password):
        """Validar credenciais do usuário usando hashing"""
        try:
            self.cursor.execute(
                "SELECT password, role FROM users WHERE username = ?", (username,)
            )
            result = self.cursor.fetchone()
            if result and bcrypt.checkpw(password.encode('utf-8'), result[0]):
                return result[1]  # Retorna a role do usuário
            return None
        except sqlite3.Error as e:
            print(f"Erro ao validar usuário: {e}")
            return None


    def has_admin(self):
        """Verificar se existe algum admin cadastrado"""
        try:
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            return self.cursor.fetchone()[0] > 0
        except sqlite3.Error as e:
            print(f"Erro ao verificar admin: {e}")
            return False

    def create_admin(self, username, password):
        """Criar admin inicial"""
        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            self.cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, hashed_password, 'admin'),
            )
            self.conn.commit()
            self.log_action(username, 'admin', 'CREATE_USER', f"Admin criado: {username}")
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False
        except sqlite3.Error as e:
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

    def create_user(self, username, password, role, email=None, phone=None):
        """Criar usuario (admin ou manager)"""
        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            self.cursor.execute(
                "INSERT INTO users (username, password, role, email, phone) VALUES (?, ?, ?, ?, ?)",
                (username, hashed_password, role, email, phone),
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
            from utils.security_questions import hash_answer
            hashes = [hash_answer(ans) for ans in answers]
            placeholder = hash_answer("__unused__")
            now = datetime.now().isoformat()
            self.cursor.execute(
                'INSERT OR REPLACE INTO user_security_questions '
                '(username, q1_hash, q2_hash, q3_hash, q4_hash, attempts, lock_until, updated_at) '
                'VALUES (?, ?, ?, ?, ?, 0, NULL, ?)',
                (username, hashes[0], hashes[1], hashes[2], placeholder, now),
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
            q1, q2, q3, _q4, attempts, lock_until = row
            lock_value = None
            if lock_until:
                try:
                    lock_value = datetime.fromisoformat(lock_until).isoformat()
                except Exception:
                    lock_value = lock_until
            return {
                "hashes": [q1, q2, q3],
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
            from utils.security_questions import check_answer
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

            hashes = record.get("hashes", [])[: len(answers)]
            if len(hashes) < len(answers):
                return {"ok": False, "reason": "not_configured"}

            all_ok = True
            for ans, hashed in zip(answers, hashes):
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
        """Registrar ação do usuário no log do sistema"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.cursor.execute(
                """
                INSERT INTO user_logs (username, role, action, details, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, role, action, details, timestamp),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Erro ao registrar log: {e}")
            self.conn.rollback()
    
    # ==================== MÉTODOS PARA PRODUTOS ====================
    
    def _now_str(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _parse_expiry_date(self, text):
        if not text:
            return None
        try:
            return datetime.strptime(str(text), "%Y-%m-%d").date()
        except Exception:
            return None

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
            self.cursor.execute(
                "SELECT status FROM products WHERE id = ?", (product_id,)
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
            self.cursor.execute(
                """
                INSERT INTO product_status_history
                (product_id, old_status, new_status, reason, source, changed_at, changed_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, old_status, new_status, reason, source, now, user),
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

            self.cursor.execute(
                "SELECT id, status, status_source, expiry_date FROM products"
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
        approval_status="APPROVED",
        approved_by=None,
        approved_at=None,
        apply_stock=True,
    ):
        cursor.execute(
            """
            SELECT existing_stock, sold_stock, unit_purchase_price,
                   sale_price, is_sold_by_weight
            FROM products WHERE id = ?
            """,
            (product_id,),
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
                stock_before, stock_after, reason, note, evidence_path,
                reference_table, reference_id, created_at, created_by,
                created_role, terminal_id, approval_status, approved_by,
                approved_at, applied
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id, movement_type, direction, qty, unit,
                unit_cost, unit_price, total_cost, total_price,
                stock_before, stock_after, reason, note, evidence_path,
                reference_table, reference_id, now_str, created_by,
                created_role, terminal_id, approval_status, approved_by,
                approved_at, applied
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
        reason="Reposição de stock",
        note="",
        evidence_path=None,
        created_by=None,
        created_role=None,
        terminal_id=None,
    ):
        """Registra reposição de stock e atualiza custo médio."""
        try:
            qty = float(qty)
            unit_cost = float(unit_cost)
            if qty <= 0 or unit_cost <= 0:
                return None

            self.cursor.execute(
                """
                SELECT existing_stock, unit_purchase_price, sale_price
                FROM products WHERE id = ?
                """,
                (product_id,),
            )
            product = self.cursor.fetchone()
            if not product:
                return None

            stock_before = float(product[0])
            old_cost = float(product[1] or 0)
            sale_price = float(product[2] or 0)

            movement_id = self._record_stock_movement_tx(
                self.cursor,
                product_id,
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
                (new_unit_cost, new_total_purchase, profit_per_unit, product_id),
            )

            self.conn.commit()
            return movement_id
        except sqlite3.Error as e:
            print(f"Erro ao repor stock: {e}")
            self.conn.rollback()
            return None

    def get_loss_records(self, start_dt, end_dt, limit=200):
        """Lista detalhada de perdas no período."""
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

    # ==================== NOVO: MÉTODOS DE CÁLCULO DE PERDAS ====================
    
    def get_restock_records(self, start_dt, end_dt, limit=300):
        """Lista detalhada de reposiÃ§Ãµes no perÃ­odo."""
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
            print(f"Erro ao obter reposiÃ§Ãµes: {e}")
            return []

    def calculate_loss_metrics(self, start_dt, end_dt):
        """
        Calcula todas as métricas de perdas para um período
        
        Returns:
            Dict com todas as métricas ou None em caso de erro
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
            print(f"Erro ao calcular métricas de perdas: {e}")
            return None

    # ==================== NOVO: DETECÇÃO DE FRAUDE ====================
    
    def detect_fraud_patterns(self, days_lookback=30):
        """
        Detecta padrões suspeitos nos últimos X dias
        
        Returns:
            Lista de alertas ordenados por severidade
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_lookback)
        
        alerts = []
        
        # 1. Utilizadores com perdas acima da média
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
                            'description': f'{user} registou perdas de {cost:.2f} MZN ({percentage_above:.1f}% acima da média)',
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
        
        # 3. Perdas fora do horário (22h-6h)
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
                    'title': f'Perda fora do horário: {user}',
                    'description': f'Perda registada às {time_str} por {user} ({movement_type}, {cost:.2f} MZN)',
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
            print(f"Erro ao detectar perdas fora do horário: {e}")
        
        # 4. Perdas sem evidência (acima de 50% do limite)
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
                    'title': f'Perda sem evidência: {cost:.2f} MZN',
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
            print(f"Erro ao detectar perdas sem evidência: {e}")
        
        return sorted(alerts, key=lambda x: x['severity'], reverse=True)

    # ==================== NOVO: APROVAÇÕES PENDENTES ====================
    
    def get_pending_approvals(self):
        """Obter todas as perdas pendentes de aprovação"""
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
            print(f"Erro ao obter aprovações pendentes: {e}")
            return []

    def add_product(self, description, category, existing_stock, sold_stock, sale_price, total_purchase_price, unit_purchase_price, barcode=None, expiry_date=None, is_sold_by_weight=False, package_quantity=None):
        """Adicionar um novo produto ao banco de dados"""
        try:
            profit_per_unit = sale_price - unit_purchase_price
            date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
            self.cursor.execute(''' 
            INSERT INTO products (description, category, existing_stock, sold_stock, sale_price, total_purchase_price, unit_purchase_price, profit_per_unit, barcode, expiry_date, date_added, is_sold_by_weight, package_quantity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) 
            ''', (description, category, float(existing_stock), float(sold_stock), sale_price, total_purchase_price, unit_purchase_price, profit_per_unit, barcode, expiry_date, date_added, 1 if is_sold_by_weight else 0, package_quantity))
            
            self.conn.commit()
            
            product_id = self.cursor.lastrowid
            tipo = "KG" if is_sold_by_weight else "UNIDADE"
            print(f"✅ Produto adicionado com sucesso! ID: {product_id} | Tipo: {tipo}")
            
            return product_id
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao adicionar produto: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def update_product(self, id, description, category, existing_stock, sold_stock, sale_price, total_purchase_price, unit_purchase_price, barcode=None, expiry_date=None, is_sold_by_weight=False, package_quantity=None):
        """Atualizar produto existente"""
        try:
            profit_per_unit = sale_price - unit_purchase_price
            self.cursor.execute(
                """UPDATE products SET 
                   description = ?, category = ?, existing_stock = ?, sold_stock = ?, 
                   sale_price = ?, total_purchase_price = ?, unit_purchase_price = ?, 
                   profit_per_unit = ?, barcode = ?, expiry_date = ?, is_sold_by_weight = ?, package_quantity = ?
                   WHERE id = ?""", 
                (description, category, float(existing_stock), float(sold_stock), sale_price, 
                 total_purchase_price, unit_purchase_price, profit_per_unit, barcode, expiry_date, 1 if is_sold_by_weight else 0, package_quantity, id)
            )
            self.conn.commit()
            
            tipo = "KG" if is_sold_by_weight else "UNIDADE"
            print(f"✅ Produto {id} atualizado com sucesso! | Tipo: {tipo}")
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao atualizar produto: {e}")
            import traceback
            traceback.print_exc()
    
    def delete_product(self, id, username=None):
        """Excluir produto (hard delete) e arquivar histórico"""
        try:
            user = username or "SYSTEM"
            self.cursor.execute(
                """
                SELECT id, description, category, existing_stock, sold_stock, sale_price,
                       total_purchase_price, unit_purchase_price, profit_per_unit, barcode,
                       expiry_date, date_added, is_sold_by_weight, package_quantity,
                       status, status_source, status_reason, status_updated_at, status_updated_by
                FROM products WHERE id = ?
                """,
                (id,),
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
                    deleted_at, deleted_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        try:
            self.cursor.execute(""" 
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
                    p.package_quantity
                FROM products p
                ORDER BY p.id DESC
            """)
            results = self.cursor.fetchall()
            
            if results:
                kg_count = sum(1 for r in results if r[15])
                un_count = len(results) - kg_count
                print(f"\n📊 Total: {len(results)} produtos ({kg_count} por KG, {un_count} por UNIDADE)")
            
            return results
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao obter produtos: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_product(self, id):
        """Obter um produto específico"""
        try:
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
                    p.package_quantity
                FROM products p
                WHERE p.id = ?""", (id,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"❌ Erro ao obter produto: {e}")
            return None
    
    def get_products_for_sale(self):
        """Obter produtos disponíveis para venda - COM INFO DE PESO"""
        try:
            self.refresh_auto_statuses()
            self.cursor.execute(""" 
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight
                FROM products
                WHERE existing_stock > 0
                  AND status IN ('ATIVO', 'PERTO_DO_PRAZO')
                  AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))
                ORDER BY description ASC
            """)
            results = self.cursor.fetchall()
            
            if results:
                print(f"\n🛒 Produtos disponíveis para venda: {len(results)}")
                for r in results:
                    tipo = "⚖️ KG" if r[5] else "📦 UN"
                    print(f"   ID {r[0]:4d}: {r[1]:30s} | Estoque: {r[2]:7.2f} | Tipo: {tipo}")
            
            return results
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao obter produtos para venda: {e}")
            return []
    
    def get_products_by_weight(self):
        """Obter apenas produtos vendidos por peso (kg)"""
        try:
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
                    p.package_quantity
                FROM products p
                WHERE p.is_sold_by_weight = 1
                ORDER BY p.description ASC
            """)
            results = self.cursor.fetchall()
            print(f"⚖️ Produtos vendidos por KG: {len(results)}")
            return results
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao obter produtos por peso: {e}")
            return []
    
    def get_product_by_barcode(self, barcode):
        """Buscar produto pelo código de barras - VERSÃO ROBUSTA COM SUPORTE A KG"""
        try:
            self.refresh_auto_statuses()
            barcode_clean = barcode.strip() if barcode else ""
            
            print(f"\n🔍 DB: Buscando código de barras...")
            print(f"   Código recebido: '{barcode}' (tamanho: {len(barcode)})")
            print(f"   Código limpo: '{barcode_clean}' (tamanho: {len(barcode_clean)})")
            
            if not barcode_clean:
                print(f"   ⚠️ Código vazio após limpeza!")
                return None
            
            # ESTRATÉGIA 1: Busca EXATA
            self.cursor.execute(""" 
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight
                FROM products
                WHERE barcode = ? AND existing_stock > 0
                  AND status IN ('ATIVO', 'PERTO_DO_PRAZO')
                  AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))
            """, (barcode_clean,))
            
            result = self.cursor.fetchone()
            
            if result:
                tipo = "⚖️ KG" if result[5] else "📦 UNIDADE"
                print(f"✅ Encontrado com busca EXATA!")
                print(f"   ID: {result[0]} | Nome: {result[1]} | Tipo: {tipo}")
                return result
            
            # ESTRATÉGIA 2: Busca com TRIM
            self.cursor.execute(""" 
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight
                FROM products
                WHERE TRIM(barcode) = ? AND existing_stock > 0
                  AND status IN ('ATIVO', 'PERTO_DO_PRAZO')
                  AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))
            """, (barcode_clean,))
            
            result = self.cursor.fetchone()
            
            if result:
                tipo = "⚖️ KG" if result[5] else "📦 UNIDADE"
                print(f"✅ Encontrado com busca TRIM!")
                print(f"   ID: {result[0]} | Nome: {result[1]} | Tipo: {tipo}")
                return result
            
            # ESTRATÉGIA 3: Busca case-insensitive
            self.cursor.execute(""" 
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight
                FROM products
                WHERE LOWER(TRIM(barcode)) = LOWER(?) AND existing_stock > 0
                  AND status IN ('ATIVO', 'PERTO_DO_PRAZO')
                  AND (expiry_date IS NULL OR expiry_date = '' OR DATE(expiry_date) >= DATE('now'))
            """, (barcode_clean,))
            
            result = self.cursor.fetchone()
            
            if result:
                tipo = "⚖️ KG" if result[5] else "📦 UNIDADE"
                print(f"✅ Encontrado com busca case-insensitive!")
                print(f"   ID: {result[0]} | Nome: {result[1]} | Tipo: {tipo}")
                return result
            
            print(f"\n❌ Código '{barcode_clean}' NÃO ENCONTRADO no banco de dados")
            
            # Listar códigos disponíveis para debug
            self.cursor.execute("SELECT barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''")
            available_barcodes = self.cursor.fetchall()
            if available_barcodes:
                print(f"\n📋 Códigos disponíveis no banco ({len(available_barcodes)}):")
                for bc in available_barcodes[:5]:  # Mostrar apenas 5 primeiros
                    print(f"   - '{bc[0]}'")
            
            return None
            
        except sqlite3.Error as e:
            print(f"❌ Erro SQL ao buscar código de barras: {e}")
            import traceback
            traceback.print_exc()
            return None
        except Exception as e:
            print(f"❌ Erro geral ao buscar código de barras: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    # ==================== MÉTODOS PARA VENDAS ====================
    
    def add_sale(self, product_id, quantity, sale_price, username=None, role=None, terminal_id=None):
        """Adicionar nova venda - SUPORTA QUANTIDADES DECIMAIS (KG) - ATUALIZA ESTOQUE"""
        try:
            quantity = float(quantity)
            total_price = quantity * sale_price
            sale_date = self._now_str()
            created_by = username or "SYSTEM"
            created_role = role or "manager"

            self.cursor.execute("""
                SELECT description, existing_stock, sold_stock, is_sold_by_weight, unit_purchase_price
                FROM products
                WHERE id = ?
            """, (product_id,))

            product_info = self.cursor.fetchone()

            if not product_info:
                print(f"Erro: Produto ID {product_id} nao encontrado!")
                return None

            product_name = product_info[0]
            stock_before = product_info[1]
            sold_before = product_info[2]
            is_weight = product_info[3]
            unit_purchase_price = product_info[4] or 0

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
                INSERT INTO sales (product_id, quantity, sale_price, total_price, sale_date, created_by, created_role, terminal_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (product_id, quantity, sale_price, total_price, sale_date, created_by, created_role, terminal_id))
            sale_id = self.cursor.lastrowid

            self.conn.commit()

            self.cursor.execute("SELECT existing_stock, sold_stock FROM products WHERE id = ?", (product_id,))
            after_info = self.cursor.fetchone()
            stock_after = after_info[0]
            sold_after = after_info[1]

            print("")
            print("=" * 70)
            print("VENDA REGISTRADA COM SUCESSO!")
            print("=" * 70)
            print(f"   Produto: {product_name}")
            print(f"   Quantidade: {quantity:.2f} {tipo}")
            print(f"   Preco unitario: {sale_price:.2f} MZN")
            print(f"   Total: {total_price:.2f} MZN")
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

    def get_all_sales(self):
        """Obter todas as vendas"""
        try:
            self.cursor.execute(""" 
                SELECT s.id, COALESCE(p.description, pa.description), s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.id
                LEFT JOIN products_archive pa ON s.product_id = pa.id
                ORDER BY s.sale_date DESC
            """)
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"❌ Erro ao obter vendas: {e}")
            return []
    
    def get_sales_by_date(self, date_str):
        """Buscar vendas por data específica"""
        try:
            date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            formatted_date = date_obj.strftime("%Y-%m-%d")
            
            self.cursor.execute("""
                SELECT s.id, COALESCE(p.description, pa.description), s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.id
                LEFT JOIN products_archive pa ON s.product_id = pa.id
                WHERE DATE(s.sale_date) = ?
                ORDER BY s.sale_date DESC
            """, (formatted_date,))
            
            return self.cursor.fetchall()
        except Exception as e:
            print(f"❌ Erro ao buscar vendas por data: {e}")
            return []

    def get_sales_by_date_range(self, start_date, end_date):
        """Buscar vendas por período (intervalo de datas)"""
        try:
            start_obj = datetime.strptime(start_date, "%d/%m/%Y")
            end_obj = datetime.strptime(end_date, "%d/%m/%Y")
            
            formatted_start = start_obj.strftime("%Y-%m-%d")
            formatted_end = end_obj.strftime("%Y-%m-%d")
            
            self.cursor.execute("""
                SELECT s.id, COALESCE(p.description, pa.description), s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.id
                LEFT JOIN products_archive pa ON s.product_id = pa.id
                WHERE DATE(s.sale_date) BETWEEN ? AND ?
                ORDER BY s.sale_date DESC
            """, (formatted_start, formatted_end))
            
            return self.cursor.fetchall()
        except Exception as e:
            print(f"❌ Erro ao buscar vendas por período: {e}")
            return []

    def get_sales_by_month(self, month, year):
        """Buscar vendas por mês específico"""
        try:
            self.cursor.execute("""
                SELECT s.id, COALESCE(p.description, pa.description), s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.id
                LEFT JOIN products_archive pa ON s.product_id = pa.id
                WHERE strftime('%m', s.sale_date) = ? AND strftime('%Y', s.sale_date) = ?
                ORDER BY s.sale_date DESC
            """, (f"{month:02d}", str(year)))
            
            return self.cursor.fetchall()
        except Exception as e:
            print(f"❌ Erro ao buscar vendas por mês: {e}")
            return []

    def get_sales_by_year(self, year):
        """Buscar vendas por ano específico"""
        try:
            self.cursor.execute("""
                SELECT s.id, COALESCE(p.description, pa.description), s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.id
                LEFT JOIN products_archive pa ON s.product_id = pa.id
                WHERE strftime('%Y', s.sale_date) = ?
                ORDER BY s.sale_date DESC
            """, (str(year),))
            
            return self.cursor.fetchall()
        except Exception as e:
            print(f"❌ Erro ao buscar vendas por ano: {e}")
            return []

    def get_today_sales(self):
        """Buscar vendas de hoje"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            self.cursor.execute("""
                SELECT s.id, COALESCE(p.description, pa.description), s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.id
                LEFT JOIN products_archive pa ON s.product_id = pa.id
                WHERE DATE(s.sale_date) = ?
                ORDER BY s.sale_date DESC
            """, (today,))
            
            return self.cursor.fetchall()
        except Exception as e:
            print(f"❌ Erro ao buscar vendas de hoje: {e}")
            return []

    def get_sales_statistics_by_date(self, date_str):
        """Obter estatísticas de vendas por data específica"""
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
            print(f"❌ Erro ao obter estatísticas por data: {e}")
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
            print(f"❌ Erro ao obter resumo mensal: {e}")
            return []
    
    # ==================== MÉTODOS PARA GERENTES ====================

    def get_all_managers(self):
        """Obter todos os gerentes"""
        try:
            self.cursor.execute("SELECT username FROM users WHERE role = 'manager'")
            return [manager[0] for manager in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"❌ Erro ao buscar gerentes: {e}")
            return []
    
    def delete_manager(self, username):
        """Excluir um gerente específico"""
        try:
            self.cursor.execute("SELECT username FROM users WHERE role = 'manager'")
            current_managers = self.cursor.fetchall()
            
            self.cursor.execute(
                "SELECT id FROM users WHERE username = ? AND role = 'manager'", 
                (username,)
            )
            manager = self.cursor.fetchone()
            
            if not manager:
                return False, "Gerente não encontrado"
            
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'manager'")
            manager_count = self.cursor.fetchone()[0]
            
            if manager_count <= 1:
                return False, "Não é possível excluir o último gerente"
            
            self.cursor.execute(
                "DELETE FROM users WHERE username = ? AND role = 'manager'", 
                (username,)
            )
            self.conn.commit()
            
            print(f"✅ Gerente '{username}' excluído com sucesso!")
            return True, "Gerente excluído com sucesso"
        
        except sqlite3.Error as e:
            self.conn.rollback()
            print(f"❌ Erro ao excluir gerente: {e}")
            return False, f"Erro ao excluir gerente: {str(e)}"
        except Exception as e:
            self.conn.rollback()
            print(f"❌ Erro inesperado: {e}")
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

    def get_products_for_losses(self):
        """Obter produtos para tela de perdas"""
        try:
            self.cursor.execute(
                """
                SELECT id, description, existing_stock, sale_price,
                       unit_purchase_price, barcode, is_sold_by_weight,
                       expiry_date, status
                FROM products
                WHERE existing_stock > 0
                """
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos para perdas: {e}")
            return []

    def get_products_for_restock(self):
        """Obter produtos para tela de reposicao"""
        try:
            self.cursor.execute(
                """
                SELECT id, description, existing_stock, sale_price,
                       unit_purchase_price, barcode, is_sold_by_weight,
                       expiry_date, status
                FROM products
                """
            )
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos para reposicao: {e}")
            return []

    def get_products_for_filter(self):
        """Obter lista simples de produtos para filtros"""
        try:
            self.cursor.execute("SELECT id, description FROM products ORDER BY description")
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter produtos para filtro: {e}")
            return []

    def get_categories(self):
        """Obter lista de categorias distintas"""
        try:
            self.cursor.execute(
                "SELECT DISTINCT category FROM products "
                "WHERE category IS NOT NULL AND category != '' ORDER BY category"
            )
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Erro ao obter categorias: {e}")
            return []

    def get_report_data(self, start_date, end_date, product_id=None, category=None):
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

        if product_id:
            query += " AND p.id = ?"
            params.append(product_id)

        if category:
            query += " AND p.category = ?"
            params.append(category)

        query += """
        GROUP BY 
            p.id, p.description, p.existing_stock, p.sale_price,
            p.total_purchase_price, p.unit_purchase_price, p.category
        """

        try:
            self.cursor.execute(query, params)
            columns = [desc[0] for desc in self.cursor.description]
            return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"Erro ao obter dados filtrados: {e}")
            return []

    def get_user_logs(self, user_filter="", action_filter="", role_filter="", limit=100):
        """Obter logs do sistema com filtros"""
        query = "SELECT * FROM user_logs WHERE 1=1"
        params = []

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
            query += " LIMIT ?"
            params.append(limit)

        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Erro ao obter logs: {e}")
            return []

    def clear_user_logs(self):
        """Apagar todos os logs"""
        try:
            self.cursor.execute("DELETE FROM user_logs")
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
        for name, expiry_date, stock, is_by_weight in self.cursor.fetchall():
            exp_date = _parse_date(expiry_date)
            if not exp_date:
                continue
            days_left = (exp_date - today_date).days
            if days_left < 0:
                continue
            unit = "kg" if is_by_weight else "un"
            if days_left <= 7:
                expiring_7.append(
                    (name, days_left, exp_date.strftime("%d/%m/%Y"), _safe_float(stock), unit)
                )
            elif days_left <= 15:
                expiring_15.append(
                    (name, days_left, exp_date.strftime("%d/%m/%Y"), _safe_float(stock), unit)
                )

        expiring_7.sort(key=lambda x: x[1])
        expiring_15.sort(key=lambda x: x[1])

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
        if expiring_15:
            alerts.append(f"{len(expiring_15)} produtos a vencer em ate 15 dias.")
        if expiring_7:
            alerts.append(f"{len(expiring_7)} produtos a vencer em ate 7 dias.")
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

        if expiring_7:
            for name, days, _date_str, _stock, _unit in expiring_7[:3]:
                rec = f"{name} vence em {days} dias - priorizar venda"
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
            + len(expiring_15)
            + len(expiring_7)
            + len(negative_profit)
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
            "stock_forecast": forecasts,
            "expiry_risk": expiry_risk,
            "negative_profit": negative_profit,
            "alert_count": alert_count,
            "badge_counts": {
                "stock": len(low_stock),
                "expiry_7": len(expiring_7),
                "expiry_15": len(expiring_15),
                "total": len(low_stock) + len(expiring_7) + len(expiring_15),
            },
        }

    def get_admin_insights_ai(self):
        """Placeholder para compatibilidade: retorna insights base"""
        return self.get_admin_insights()

    # ==================== CONTEXT MANAGER ====================
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
