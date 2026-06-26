from __future__ import annotations

from datetime import datetime, timedelta

from tests.helpers import TemporaryDatabaseTestCase


class DatabaseSetupAndUserTests(TemporaryDatabaseTestCase):
    def test_database_setup_creates_core_tables_and_vat_rules(self):
        tables = {
            row[0]
            for row in self.db.cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        self.assertIn("users", tables)
        self.assertIn("products", tables)
        self.assertIn("sales", tables)
        self.assertIn("vat_rules", tables)
        self.assertGreaterEqual(len(self.db.get_vat_rules()), 4)

    def test_admin_lifecycle_uses_hashed_passwords(self):
        self.assertFalse(self.db.has_admin())
        self.assertTrue(self.quiet(self.db.create_admin, "admin", "secret"))
        self.assertFalse(self.quiet(self.db.create_admin, "admin", "secret"))

        self.assertTrue(self.db.has_admin())
        self.assertEqual(self.db.validate_user("admin", "secret"), "admin")
        self.assertIsNone(self.db.validate_user("admin", "wrong"))
        stored_password = self.fetch_scalar("SELECT password FROM users WHERE username = ?", ("admin",))
        self.assertNotEqual(stored_password, "secret")

    def test_manager_data_owner_defaults_to_username(self):
        self.assertTrue(self.quiet(self.db.create_user, "maria", "123", "manager"))

        self.assertTrue(self.db.user_exists("maria"))
        self.assertEqual(self.db.get_user_role("maria"), "manager")
        self.assertEqual(self.db.get_user_data_owner("maria"), "maria")

    def test_security_questions_validate_and_lock_after_failures(self):
        self.assertTrue(self.quiet(self.db.create_user, "joao", "123", "manager"))
        self.assertTrue(self.quiet(self.db.set_security_questions, "joao", ["Maputo", "Escola 1"]))

        self.assertEqual(self.db.verify_security_answers("joao", ["maputo", "escola 1"])["ok"], True)
        invalid = self.db.verify_security_answers(
            "joao",
            ["x", "y"],
            max_attempts=2,
            lock_minutes=1,
        )
        locked = self.db.verify_security_answers(
            "joao",
            ["x", "y"],
            max_attempts=2,
            lock_minutes=1,
        )

        self.assertEqual(invalid["reason"], "invalid")
        self.assertEqual(locked["reason"], "locked")
        self.assertFalse(locked["ok"])


class DatabaseProductAndSaleTests(TemporaryDatabaseTestCase):
    def test_add_product_persists_sku_vat_and_pack_fields(self):
        product_id = self.add_sample_product(
            description="Coca Cola",
            barcode="  12345  ",
            units_per_package=6,
            allow_pack_sale=True,
        )

        product = self.db.get_product(product_id)

        self.assertEqual(product[1], "Coca Cola")
        self.assertEqual(product[12], "12345")
        self.assertTrue(str(product[22]).startswith("COC-"))
        self.assertEqual(product[23], 6)
        self.assertEqual(product[24], 1)
        self.assertEqual(product[25], "STANDARD")

    def test_add_product_merges_same_barcode_and_expiry_batch(self):
        first_id = self.add_sample_product(barcode="999", stock=10, unit_purchase_price=40)
        second_id = self.add_sample_product(barcode="999", stock=5, unit_purchase_price=60)

        stock, unit_cost = self.fetch_one(
            "SELECT existing_stock, unit_purchase_price FROM products WHERE id = ?",
            (first_id,),
        )

        self.assertEqual(second_id, first_id)
        self.assertEqual(stock, 15.0)
        self.assertAlmostEqual(unit_cost, 46.6666666667, places=5)

    def test_pack_sale_validation_rejects_invalid_package_size(self):
        product_id = self.quiet(
            self.db.add_product,
            "Bolachas",
            "Mercearia",
            10,
            0,
            20,
            100,
            10,
            allow_pack_sale=True,
            units_per_package=1,
        )

        self.assertIsNone(product_id)

    def test_add_sale_decrements_stock_records_sale_and_vat(self):
        product_id = self.add_sample_product(stock=10, sale_price=116, unit_purchase_price=80)
        sale_id = self.quiet(
            self.db.add_sale,
            product_id,
            2,
            116,
            username="maria",
            role="manager",
            terminal_id="POS-1",
        )

        stock, sold = self.fetch_one(
            "SELECT existing_stock, sold_stock FROM products WHERE id = ?",
            (product_id,),
        )
        sale = self.fetch_one(
            "SELECT quantity, total_price, net_total, vat_amount, gross_total, created_by, terminal_id "
            "FROM sales WHERE id = ?",
            (sale_id,),
        )

        self.assertIsNotNone(sale_id)
        self.assertEqual(stock, 8.0)
        self.assertEqual(sold, 2.0)
        self.assertEqual(sale[0], 2.0)
        self.assertEqual(sale[1], 232.0)
        self.assertEqual(sale[2], 200.0)
        self.assertEqual(sale[3], 32.0)
        self.assertEqual(sale[4], 232.0)
        self.assertEqual(sale[5], "maria")
        self.assertEqual(sale[6], "POS-1")

    def test_add_sale_rejects_insufficient_stock_without_mutation(self):
        product_id = self.add_sample_product(stock=1)
        sale_id = self.quiet(self.db.add_sale, product_id, 2, 116)

        stock, sold = self.fetch_one(
            "SELECT existing_stock, sold_stock FROM products WHERE id = ?",
            (product_id,),
        )

        self.assertIsNone(sale_id)
        self.assertEqual(stock, 1.0)
        self.assertEqual(sold, 0.0)

    def test_owner_scope_hides_other_users_products(self):
        self.assertTrue(self.quiet(self.db.create_user, "maria", "123", "manager", data_owner="maria"))
        self.assertTrue(self.quiet(self.db.create_user, "ana", "123", "manager", data_owner="ana"))

        self.db.set_active_user("maria", "manager")
        maria_product = self.add_sample_product(description="Produto Maria", barcode="m1")
        self.db.set_active_user("ana", "manager")
        ana_product = self.add_sample_product(description="Produto Ana", barcode="a1")

        self.assertIsNone(self.db.get_product(maria_product))
        self.assertIsNotNone(self.db.get_product(ana_product))

    def test_vat_rules_can_be_replaced_and_reset(self):
        replacement = [
            {
                "code": "STANDARD",
                "label": "Nova taxa",
                "short_label": "IVA 20%",
                "rate_percent": 20,
                "effective_from": "2026-01-01",
                "price_mode": "INCLUSIVE",
            }
        ]

        self.assertTrue(self.db.replace_vat_rules(replacement))
        breakdown = self.db.calculate_vat_breakdown(120, quantity=1, vat_rule_code="STANDARD", reference_date="2026-06-26")
        self.assertEqual(breakdown["vat_amount"], 20.0)

        self.assertTrue(self.db.reset_vat_rules())
        restored = self.db.calculate_vat_breakdown(116, quantity=1, vat_rule_code="STANDARD", reference_date="2026-06-26")
        self.assertEqual(restored["vat_amount"], 16.0)

    def test_parse_datetime_value_supports_end_of_day(self):
        from database.database import _parse_datetime_value

        parsed = _parse_datetime_value("2026-06-26", end_of_day=True)

        self.assertEqual(parsed.hour, 23)
        self.assertEqual(parsed.minute, 59)
        self.assertEqual(parsed.second, 59)

    def test_expired_status_refreshes_automatically(self):
        product_id = self.add_sample_product(expiry_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))

        summary = self.quiet(self.db.refresh_auto_statuses)
        status = self.fetch_scalar("SELECT status FROM products WHERE id = ?", (product_id,))

        self.assertEqual(summary, 1)
        self.assertEqual(status, "EXPIRADO")
