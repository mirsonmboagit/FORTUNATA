"""Sacks are counted; loose produce sales never imply a weight conversion."""
import math
from datetime import date


PRODUCE_MODES = {"unit": "UN", "heap": "MONTINHO", "weight": "KG", "amount": "VALOR", "sack": "SACO"}


class ProduceInventoryMixin:
    def _is_product_expired_for_sale(self, product_id):
        row = self.conn.execute("SELECT expiry_date FROM products WHERE id = ?", (product_id,)).fetchone()
        expiry = self._parse_expiry_date(row[0]) if row else None
        return bool(expiry and expiry < date.today())

    def _setup_produce_inventory(self):
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(products)")}
        if "stock_mode" not in columns:
            self.conn.execute("ALTER TABLE products ADD COLUMN stock_mode TEXT NOT NULL DEFAULT 'EXACT'")
        if "sack_weight_kg" not in columns:
            self.conn.execute("ALTER TABLE products ADD COLUMN sack_weight_kg REAL")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS produce_sales (
            sale_id INTEGER PRIMARY KEY,
            sale_mode TEXT NOT NULL,
            stock_applied INTEGER NOT NULL
        )""")
        self.conn.commit()

    @staticmethod
    def _normalize_produce_options(options):
        options = dict(options or {})
        mode = str(options.get("stock_mode") or "EXACT").upper()
        if mode not in {"EXACT", "SACKS"}:
            raise ValueError("Modo de stock invalido")
        weight = options.get("sack_weight_kg")
        if weight in (None, ""):
            weight = None
        else:
            weight = float(weight)
            if not math.isfinite(weight) or weight <= 0:
                raise ValueError("Peso opcional deve ser maior que zero")
        return mode, weight if mode == "SACKS" else None

    def _save_produce_options_tx(self, product_id, options):
        if options is None:
            return
        mode, weight = self._normalize_produce_options(options)
        current = self.conn.execute("SELECT stock_mode FROM products WHERE id = ?", (product_id,)).fetchone()
        if current and current[0] != mode:
            history = self.conn.execute(
                "SELECT 1 FROM stock_movements WHERE product_id = ? LIMIT 1", (product_id,)
            ).fetchone()
            if history:
                raise ValueError("Este produto ja tem movimentos. Cadastre um novo produto para mudar a unidade do stock.")
        self.cursor.execute(
            "UPDATE products SET stock_mode = ?, sack_weight_kg = ? WHERE id = ?",
            (mode, weight, product_id),
        )
        if mode == "SACKS":
            # A piece price and a sack cost cannot define a per-unit margin.
            self.cursor.execute("UPDATE products SET profit_per_unit = 0 WHERE id = ?", (product_id,))

    def _validate_produce_checkout(self, items):
        needed = {}
        for item in items:
            mode = item.get("produce_sale_mode")
            if not mode:
                continue
            pid = int(item.get("product_id", item.get("id")))
            state = needed.setdefault(pid, [0.0, False])
            if mode == "sack":
                state[0] += float(item.get("quantity", item.get("qty")) or 0)
            else:
                state[1] = True
        for pid, (whole, loose) in needed.items():
            settings = self.get_produce_settings(pid)
            if not settings or settings["stock_mode"] != "SACKS" or settings["sacks_available"] < whole + int(loose):
                raise ValueError("Sacos insuficientes para as vendas inteiras e avulsas do carrinho")

    def get_produce_settings(self, product_id):
        scope, params = self._owner_filter()
        row = self.conn.execute(
            "SELECT stock_mode, sack_weight_kg, existing_stock FROM products WHERE id = ?" + scope,
            (product_id, *params),
        ).fetchone()
        if not row:
            return None
        return dict(stock_mode=row[0], sack_weight_kg=row[1], sacks_available=row[2])

    def finish_produce_sack(self, product_id, username=None, role=None):
        """Close one consumed sack without calling it a loss or another sale."""
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            settings = self.get_produce_settings(product_id)
            if not settings or settings["stock_mode"] != "SACKS" or settings["sacks_available"] < 1:
                raise ValueError("Nenhum saco disponivel para terminar")
            movement = self._record_stock_movement_tx(
                self.cursor, product_id, "SACK_FINISHED", 1, "OUT",
                reason="Saco terminado nas vendas avulsas", created_by=username,
                created_role=role, unit_price=0, apply_stock=True,
            )
            if not movement:
                raise ValueError("Nao foi possivel terminar o saco")
            self.conn.commit()
            return {"ok": True}
        except Exception as exc:
            self.conn.rollback()
            return {"ok": False, "message": str(exc)}
