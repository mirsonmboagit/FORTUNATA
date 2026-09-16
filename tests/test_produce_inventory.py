from datetime import date, timedelta

from tests.helpers import TemporaryDatabaseTestCase


class ProduceInventoryTests(TemporaryDatabaseTestCase):
    def add_sacks(self, stock=1, weight=None, **kwargs):
        product_id = self.db.add_product(
            "Cebola", "Horticolas", stock, 0, 5, stock * 800, 800,
            produce_options={"stock_mode": "SACKS", "sack_weight_kg": weight},
            **kwargs,
        )
        self.assertIsNotNone(product_id)
        return product_id

    def stock(self, product_id):
        return self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (product_id,))

    def test_no_weight_required_and_settings_are_persisted(self):
        pid = self.add_sacks()
        self.assertEqual(self.db.get_produce_settings(pid), {
            "stock_mode": "SACKS", "sack_weight_kg": None, "sacks_available": 1,
        })
        row = self.db.get_products_for_sale_catalog_page()[0]
        self.assertEqual(row[13], "SACKS")
        self.assertEqual(row[11], f"sacks:{pid}")

    def test_loose_sales_charge_correct_amount_without_subtracting_sacks(self):
        pid = self.add_sacks()
        for mode, qty, price in [("unit", 3, 5), ("heap", 2, 20), ("weight", 0.375, 80), ("amount", 1, 20)]:
            with self.subTest(mode=mode):
                sale_id = self.db.add_sale(pid, qty, price, produce_sale_mode=mode)
                self.assertIsNotNone(sale_id)
                self.assertEqual(self.stock(pid), 1)
                self.assertAlmostEqual(self.fetch_scalar("SELECT total_price FROM sales WHERE id = ?", (sale_id,)), qty * price)
                result = self.db.refund_sale_item(sale_id, qty)
                self.assertTrue(result["ok"], result)
                self.assertEqual(self.stock(pid), 1)

    def test_whole_sack_sale_and_refund_adjust_one_sack(self):
        pid = self.add_sacks()
        sale_id = self.db.add_sale(pid, 1, 1000, produce_sale_mode="sack")
        self.assertIsNotNone(sale_id)
        self.assertEqual(self.stock(pid), 0)
        self.assertTrue(self.db.refund_sale_item(sale_id, 1)["ok"])
        self.assertEqual(self.stock(pid), 1)

    def test_finish_sack_does_not_create_another_sale_or_allow_negative_stock(self):
        pid = self.add_sacks()
        self.assertIsNotNone(self.db.add_sale(pid, 3, 5, produce_sale_mode="unit"))
        result = self.db.finish_produce_sack(pid)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.stock(pid), 0)
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM sales"), 1)
        self.assertFalse(self.db.finish_produce_sack(pid)["ok"])
        self.assertIsNone(self.db.add_sale(pid, 1, 5, produce_sale_mode="unit"))

    def test_weight_is_information_and_does_not_limit_piece_sales(self):
        pid = self.add_sacks(weight=25)
        self.assertIsNotNone(self.db.add_sale(pid, 40, 5, produce_sale_mode="unit"))
        self.assertEqual(self.stock(pid), 1)

    def test_restock_counts_sacks_and_keeps_weight_optional(self):
        pid = self.add_sacks(stock=1)
        movement_id = self.db.restock_product(pid, 2, 900, created_by="maria", created_role="manager")
        self.assertIsNotNone(movement_id)
        self.assertEqual(self.stock(pid), 3)
        settings = self.db.get_produce_settings(pid)
        self.assertEqual(settings["stock_mode"], "SACKS")
        self.assertIsNone(settings["sack_weight_kg"])
        self.assertEqual(self.fetch_scalar("SELECT profit_per_unit FROM products WHERE id = ?", (pid,)), 0.0)

    def test_invalid_or_missing_sale_mode_cannot_bypass_stock(self):
        pid = self.add_sacks()
        self.assertIsNone(self.db.add_sale(pid, 1, 5))
        self.assertIsNone(self.db.add_sale(pid, 2, 1000, produce_sale_mode="sack"))
        normal = self.add_sample_product(stock=1)
        self.assertIsNone(self.db.add_sale(normal, 20, 5, produce_sale_mode="unit"))
        self.assertEqual(self.stock(normal), 1)

    def test_atomic_checkout_replay_and_changed_mode(self):
        pid = self.add_sacks(stock=2)
        items = [{"product_id": pid, "quantity": 1, "sale_price": 20, "produce_sale_mode": "heap"}]
        first = self.db.add_sales_transaction("produce-1", items)
        self.assertTrue(first["ok"], first)
        second = self.db.add_sales_transaction("produce-1", items)
        self.assertTrue(second["idempotent"], second)
        changed = self.db.add_sales_transaction("produce-1", [dict(items[0], produce_sale_mode="sack")])
        self.assertFalse(changed["ok"])
        normal = self.add_sample_product(stock=1)
        failed = self.db.add_sales_transaction("produce-fail", items + [{"product_id": normal, "quantity": 2, "sale_price": 10}])
        self.assertFalse(failed["ok"])
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM sales"), 1)
        self.assertEqual(self.stock(pid), 2)

    def test_expired_produce_cannot_be_sold(self):
        pid = self.add_sacks(expiry_date=(date.today() - timedelta(days=1)).isoformat())
        self.assertIsNone(self.db.add_sale(pid, 3, 5, produce_sale_mode="unit"))

    def test_invalid_optional_weights_are_rejected(self):
        for weight in [0, -1, float("nan"), float("inf")]:
            self.assertIsNone(self.db.add_product(
                "Cebola", "Horticolas", 1, 0, 5, 800, 800,
                produce_options={"stock_mode": "SACKS", "sack_weight_kg": weight},
            ))
