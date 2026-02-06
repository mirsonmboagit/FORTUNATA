import sqlite3
import os
from datetime import datetime
import bcrypt

class Database:
    def __init__(self, db_name="inventory.db"):
        # Guardamos o nome simples
        self.db_name = db_name 
        
        # Definimos a pasta
        self.db_folder = "database"
        
        # Criamos a pasta se não existir
        if not os.path.exists(self.db_folder):
            os.makedirs(self.db_folder)
            print(f"📁 Pasta '{self.db_folder}' criada!")

        # Construímos o caminho completo
        self.db_path = os.path.join(self.db_folder, self.db_name)
        
        self.conn = None
        self.cursor = None
        self.connect()
        self.setup()
    
    def connect(self):
        """Conectar ao banco de dados"""
        try:
            # IMPORTANTE: Usamos o self.db_path aqui
            self.conn = sqlite3.connect(self.db_path)
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
            
            # Adicionar usuário padrão se não existir
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
            if self.cursor.fetchone()[0] == 0:
                # Hash da senha padrão "123456"
                default_password = bcrypt.hashpw("123456".encode('utf-8'), bcrypt.gensalt())
                self.cursor.execute(
                    "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                    ("admin", default_password, "admin")
                )
            
            # Tabela de produtos (atualizada com barcode, expiry_date e is_sold_by_weight)
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
                is_sold_by_weight INTEGER DEFAULT 0
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
            
            # Adicionar coluna is_sold_by_weight se não existir
            if 'is_sold_by_weight' not in columns:
                print("⚙️ Adicionando coluna 'is_sold_by_weight' à tabela products...")
                self.cursor.execute("ALTER TABLE products ADD COLUMN is_sold_by_weight INTEGER DEFAULT 0")
                print("✅ Coluna 'is_sold_by_weight' adicionada com sucesso!")
            
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
                    is_sold_by_weight INTEGER DEFAULT 0
                )''')
                
                # Copiar dados para tabela temporária
                self.cursor.execute('''
                INSERT INTO products_temp 
                SELECT id, description, category, CAST(existing_stock AS REAL), 
                       CAST(sold_stock AS REAL), sale_price, total_purchase_price, 
                       unit_purchase_price, profit_per_unit, barcode, expiry_date, 
                       date_added, is_sold_by_weight
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
                FOREIGN KEY (product_id) REFERENCES products (id)
            )''')
            
            self.conn.commit()
            print("✅ Banco de dados configurado com suporte completo a vendas por KG!")
            
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
    
    def add_product(self, description, category, existing_stock, sold_stock, sale_price, total_purchase_price, unit_purchase_price, barcode=None, expiry_date=None, is_sold_by_weight=False):
        """Adicionar um novo produto ao banco de dados"""
        try:
            profit_per_unit = sale_price - unit_purchase_price
            date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
            self.cursor.execute(''' 
            INSERT INTO products (description, category, existing_stock, sold_stock, sale_price, total_purchase_price, unit_purchase_price, profit_per_unit, barcode, expiry_date, date_added, is_sold_by_weight)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) 
            ''', (description, category, float(existing_stock), float(sold_stock), sale_price, total_purchase_price, unit_purchase_price, profit_per_unit, barcode, expiry_date, date_added, 1 if is_sold_by_weight else 0))
            
            self.conn.commit()
            
            product_id = self.cursor.lastrowid
            tipo = "KG" if is_sold_by_weight else "UNIDADE"
            print(f"✅ Produto adicionado com sucesso! ID: {product_id} | Tipo: {tipo}")
            
            return product_id  # Retorna o ID do produto criado
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao adicionar produto: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def update_product(self, id, description, category, existing_stock, sold_stock, sale_price, total_purchase_price, unit_purchase_price, barcode=None, expiry_date=None, is_sold_by_weight=False):
        """Atualizar produto existente"""
        try:
            profit_per_unit = sale_price - unit_purchase_price
            self.cursor.execute(
                """UPDATE products SET 
                   description = ?, category = ?, existing_stock = ?, sold_stock = ?, 
                   sale_price = ?, total_purchase_price = ?, unit_purchase_price = ?, 
                   profit_per_unit = ?, barcode = ?, expiry_date = ?, is_sold_by_weight = ?
                   WHERE id = ?""", 
                (description, category, float(existing_stock), float(sold_stock), sale_price, 
                 total_purchase_price, unit_purchase_price, profit_per_unit, barcode, expiry_date, 1 if is_sold_by_weight else 0, id)
            )
            self.conn.commit()
            
            tipo = "KG" if is_sold_by_weight else "UNIDADE"
            print(f"✅ Produto {id} atualizado com sucesso! | Tipo: {tipo}")
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao atualizar produto: {e}")
            import traceback
            traceback.print_exc()
    
    def delete_product(self, id):
        """Excluir produto"""
        try:
            self.cursor.execute("DELETE FROM products WHERE id = ?", (id,))
            self.conn.commit()
            
            print(f"✅ Produto {id} excluído com sucesso!")
            
        except sqlite3.Error as e:
            print(f"❌ Erro ao excluir produto: {e}")
            self.conn.rollback()
    
    def get_all_products(self):
        """Obter todos os produtos - COM SUPORTE A KG"""
        try:
            self.cursor.execute(""" 
                SELECT 
                    p.id,                           -- 0
                    p.description,                  -- 1
                    p.existing_stock,               -- 2 (REAL - suporta decimais)
                    p.sold_stock,                   -- 3 (REAL - suporta decimais)
                    p.sale_price,                   -- 4
                    p.total_purchase_price,         -- 5
                    p.unit_purchase_price,          -- 6
                    p.profit_per_unit,              -- 7
                    (p.profit_per_unit * p.sold_stock) as total_profit,  -- 8
                    CASE 
                        WHEN p.sold_stock > 0 THEN (p.profit_per_unit * p.sold_stock * 100) / (p.unit_purchase_price * p.sold_stock)
                        ELSE 0 
                    END as profit_percentage,       -- 9
                    (p.sale_price - p.unit_purchase_price) / p.unit_purchase_price * 100 as price_percentage,  -- 10
                    p.category,                     -- 11
                    p.barcode,                      -- 12
                    p.expiry_date,                  -- 13
                    p.date_added,                   -- 14
                    p.is_sold_by_weight             -- 15
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
                    p.is_sold_by_weight
                FROM products p
                WHERE p.id = ?""", (id,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"❌ Erro ao obter produto: {e}")
            return None
    
    def get_products_for_sale(self):
        """Obter produtos disponíveis para venda - COM INFO DE PESO"""
        try:
            self.cursor.execute(""" 
                SELECT id, description, existing_stock, sale_price, barcode, is_sold_by_weight
                FROM products
                WHERE existing_stock > 0
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
                    p.is_sold_by_weight
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
    
    def add_sale(self, product_id, quantity, sale_price):
        """Adicionar nova venda - SUPORTA QUANTIDADES DECIMAIS (KG) - ATUALIZA ESTOQUE"""
        try:
            # Converter quantidade para float para garantir compatibilidade
            quantity = float(quantity)
            total_price = quantity * sale_price
            sale_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Buscar informações do produto ANTES da venda
            self.cursor.execute("""
                SELECT description, existing_stock, sold_stock, is_sold_by_weight 
                FROM products 
                WHERE id = ?
            """, (product_id,))
            
            product_info = self.cursor.fetchone()
            
            if not product_info:
                print(f"❌ Produto ID {product_id} não encontrado!")
                return None
            
            product_name = product_info[0]
            stock_before = product_info[1]
            sold_before = product_info[2]
            is_weight = product_info[3]
            
            # Verificar se há estoque suficiente
            if stock_before < quantity:
                print(f"❌ Estoque insuficiente! Disponível: {stock_before:.2f}, Solicitado: {quantity:.2f}")
                return None
            
            tipo = "kg" if is_weight else "un"
            
            # ===== ATUALIZAR ESTOQUE E VENDIDOS =====
            # existing_stock DIMINUI (estoque disponível)
            # sold_stock AUMENTA (total vendido)
            self.cursor.execute("""
                UPDATE products 
                SET existing_stock = existing_stock - ?, 
                    sold_stock = sold_stock + ? 
                WHERE id = ?
            """, (quantity, quantity, product_id))
            
            # Registrar a venda na tabela sales
            self.cursor.execute("""
                INSERT INTO sales (product_id, quantity, sale_price, total_price, sale_date) 
                VALUES (?, ?, ?, ?, ?)
            """, (product_id, quantity, sale_price, total_price, sale_date))
            
            self.conn.commit()
            
            # Buscar estoque DEPOIS da venda
            self.cursor.execute("SELECT existing_stock, sold_stock FROM products WHERE id = ?", (product_id,))
            after_info = self.cursor.fetchone()
            stock_after = after_info[0]
            sold_after = after_info[1]
            
            # Log detalhado
            print(f"\n{'='*70}")
            print(f"💰 VENDA REGISTRADA COM SUCESSO!")
            print(f"{'='*70}")
            print(f"   Produto: {product_name}")
            print(f"   Quantidade: {quantity:.2f} {tipo}")
            print(f"   Preço unitário: {sale_price:.2f} MZN")
            print(f"   Total: {total_price:.2f} MZN")
            print(f"   ---")
            print(f"   📦 Estoque ANTES: {stock_before:.2f} {tipo}")
            print(f"   📦 Estoque DEPOIS: {stock_after:.2f} {tipo} (▼ {quantity:.2f})")
            print(f"   📊 Total vendido: {sold_after:.2f} {tipo} (▲ {quantity:.2f})")
            print(f"{'='*70}\n")
            
            return self.cursor.lastrowid
            
        except sqlite3.Error as e:
            print(f"❌ Erro SQL ao adicionar venda: {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
            return None
        except Exception as e:
            print(f"❌ Erro geral ao adicionar venda: {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
            return None
    
    def get_all_sales(self):
        """Obter todas as vendas"""
        try:
            self.cursor.execute(""" 
                SELECT s.id, p.description, s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                JOIN products p ON s.product_id = p.id
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
                SELECT s.id, p.description, s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                JOIN products p ON s.product_id = p.id
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
                SELECT s.id, p.description, s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                JOIN products p ON s.product_id = p.id
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
                SELECT s.id, p.description, s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                JOIN products p ON s.product_id = p.id
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
                SELECT s.id, p.description, s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                JOIN products p ON s.product_id = p.id
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
                SELECT s.id, p.description, s.quantity, s.sale_price, s.total_price, s.sale_date
                FROM sales s
                JOIN products p ON s.product_id = p.id
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
    
    # ==================== CONTEXT MANAGER ====================
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
