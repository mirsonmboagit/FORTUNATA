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
    def test_composite_sale_is_atomic_and_idempotent(self):
        first = self.add_sample_product(description="Agua", barcode="mob-a", stock=2, sale_price=40)
        second = self.add_sample_product(description="Sumo", barcode="mob-b", stock=1, sale_price=60)
        transaction_code = "MOB-ATOMIC-001"

        failed = self.quiet(
            self.db.add_sales_transaction,
            transaction_code,
            [
                {"id": first, "qty": 1, "effective_unit_price": 40},
                {"id": second, "qty": 2, "effective_unit_price": 60},
            ],
            username="maria",
            role="manager",
            terminal_id="MOBILE-1",
            payment_method="card",
        )
        self.assertFalse(failed["ok"])
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (first,)), 2.0)
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM sales WHERE transaction_code=?", (transaction_code,)), 0)
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM sale_transactions WHERE transaction_code=?", (transaction_code,)), 0)

        completed = self.quiet(
            self.db.add_sales_transaction,
            transaction_code,
            [
                {"id": first, "qty": 1, "effective_unit_price": 40},
                {"id": second, "qty": 1, "effective_unit_price": 60},
            ],
            username="maria",
            role="manager",
            terminal_id="MOBILE-1",
            payment_method="card",
        )
        self.assertTrue(completed["ok"])
        self.assertFalse(completed["idempotent"])
        self.assertEqual(len(completed["sale_ids"]), 2)
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (first,)), 1.0)
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (second,)), 0.0)

        retried = self.quiet(
            self.db.add_sales_transaction,
            transaction_code,
            [
                {"id": first, "qty": 1, "effective_unit_price": 40},
                {"id": second, "qty": 1, "effective_unit_price": 60},
            ],
            username="maria",
            role="manager",
            terminal_id="MOBILE-1",
            payment_method="card",
        )
        self.assertTrue(retried["ok"])
        self.assertTrue(retried["idempotent"])
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM sales WHERE transaction_code=?", (transaction_code,)), 2)
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (first,)), 1.0)

    def test_physical_inventory_counts_and_applies_audited_adjustments(self):
        first = self.add_sample_product(description="Arroz", barcode="inv-a", stock=10)
        second = self.add_sample_product(description="Acucar", barcode="inv-b", stock=5)
        started = self.db.start_physical_inventory("Contagem mensal", "admin", "PC-1")
        self.assertTrue(started["ok"])
        inventory_id = started["inventory"]["id"]
        self.assertEqual(started["item_count"], 2)

        self.assertTrue(self.db.record_physical_inventory_count(inventory_id, first, 8, "admin")["ok"])
        self.assertTrue(self.db.record_physical_inventory_count(inventory_id, second, 7, "admin")["ok"])
        summary = self.db.get_physical_inventory_summary(inventory_id)
        self.assertEqual(summary["counted_items"], 2)
        self.assertEqual(summary["divergent_items"], 2)

        completed = self.db.complete_physical_inventory(inventory_id, "admin")
        self.assertTrue(completed["ok"])
        self.assertEqual(completed["adjustment_count"], 2)
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (first,)), 8.0)
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (second,)), 7.0)
        movements = self.db.cursor.execute(
            "SELECT direction, qty, reference_table, reference_id FROM stock_movements WHERE reference_table='physical_inventories' ORDER BY product_id",
        ).fetchall()
        self.assertEqual(len(movements), 2)
        self.assertTrue(all(row[2] == "physical_inventories" and row[3] == inventory_id for row in movements))
        history = self.db.list_physical_inventories()
        self.assertEqual(history[0]["id"], inventory_id)
        self.assertEqual(history[0]["status"], "COMPLETED")
        self.assertEqual(history[0]["divergent_items"], 2)

    def test_physical_inventory_requires_complete_count_unless_partial_is_confirmed(self):
        first = self.add_sample_product(description="Oleo", barcode="inv-c", stock=4)
        self.add_sample_product(description="Sal", barcode="inv-d", stock=6)
        inventory_id = self.db.start_physical_inventory("Parcial", "admin")["inventory"]["id"]
        self.db.record_physical_inventory_count(inventory_id, first, 3, "admin")
        blocked = self.db.complete_physical_inventory(inventory_id, "admin")
        self.assertFalse(blocked["ok"])
        self.assertIn("faltam", blocked["message"])
        completed = self.db.complete_physical_inventory(inventory_id, "admin", allow_partial=True)
        self.assertTrue(completed["ok"])

    def test_cancelled_physical_inventory_does_not_change_stock(self):
        product_id = self.add_sample_product(description="Leite", barcode="inv-e", stock=9)
        inventory_id = self.db.start_physical_inventory("Cancelado", "admin")["inventory"]["id"]
        self.db.record_physical_inventory_count(inventory_id, product_id, 1, "admin")
        cancelled = self.db.cancel_physical_inventory(inventory_id, "admin", "Contagem incorreta")
        self.assertTrue(cancelled["ok"])
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (product_id,)), 9.0)
        self.assertIsNone(self.db.get_active_physical_inventory())

    def test_cash_session_tracks_payment_discount_and_closing_difference(self):
        product_id = self.add_sample_product(stock=10, sale_price=100)
        opened = self.db.open_cash_session("maria", "POS-1", 500, "Inicio", "manager")
        self.assertTrue(opened["ok"])
        session_id = opened["session"]["id"]

        sale_id = self.quiet(
            self.db.add_sale,
            product_id,
            2,
            90,
            username="maria",
            role="manager",
            terminal_id="POS-1",
            transaction_code="TX-1",
            payment_method="cash",
            discount_amount=20,
            cash_session_id=session_id,
        )
        self.assertIsNotNone(sale_id)
        summary = self.db.get_cash_session_summary(session_id)
        self.assertEqual(summary["transaction_count"], 1)
        self.assertEqual(summary["sales_total"], 180.0)
        self.assertEqual(summary["discount_total"], 20.0)
        self.assertEqual(summary["expected_cash"], 680.0)
        sale_finance = self.fetch_one(
            "SELECT transaction_code, payment_method, discount_amount, cash_session_id "
            "FROM sales WHERE id = ?",
            (sale_id,),
        )
        self.assertEqual(sale_finance, ("TX-1", "cash", 20.0, session_id))

        closed = self.db.close_cash_session(session_id, 675, "Faltam 5 MT", "maria", "manager")
        self.assertTrue(closed["ok"])
        self.assertEqual(closed["summary"]["difference_amount"], -5.0)
        self.assertIsNone(self.db.get_open_cash_session("maria", "POS-1"))

    def test_cash_summary_separates_payment_methods_and_subtracts_cash_refunds(self):
        first = self.add_sample_product(description="A", barcode="cash-a", stock=5, sale_price=100)
        second = self.add_sample_product(description="B", barcode="card-b", stock=5, sale_price=200)
        session = self.db.open_cash_session("maria", "POS-2", 100, role="manager")["session"]
        cash_sale = self.quiet(
            self.db.add_sale, first, 1, 100,
            username="maria", terminal_id="POS-2", transaction_code="CASH-1",
            payment_method="cash", cash_session_id=session["id"],
        )
        self.quiet(
            self.db.add_sale, second, 1, 200,
            username="maria", terminal_id="POS-2", transaction_code="CARD-1",
            payment_method="card", cash_session_id=session["id"],
        )
        refunded = self.db.refund_sale_item(cash_sale, 0.5, "Cliente devolveu", "maria", "manager", "POS-2")
        self.assertTrue(refunded["ok"])

        summary = self.db.get_cash_session_summary(session["id"])
        self.assertEqual(summary["payment_methods"]["cash"]["total"], 100.0)
        self.assertEqual(summary["payment_methods"]["card"]["total"], 200.0)
        self.assertEqual(summary["cash_refunds"], 50.0)
        self.assertEqual(summary["expected_cash"], 150.0)

    def test_refund_is_blocked_after_ten_minutes(self):
        product_id = self.add_sample_product(stock=10, sale_price=100)
        sale_id = self.quiet(
            self.db.add_sale,
            product_id,
            1,
            100,
            username="maria",
            role="manager",
            terminal_id="POS-1",
            transaction_code="PRAZO-1",
        )
        expired_at = (datetime.now() - timedelta(minutes=11)).strftime("%Y-%m-%d %H:%M:%S")
        self.db.cursor.execute("UPDATE sales SET sale_date = ? WHERE id = ?", (expired_at, sale_id))
        self.db.conn.commit()

        result = self.db.refund_sale_item(sale_id, 1, "Cliente desistiu", "maria", "manager", "POS-1")

        self.assertFalse(result["ok"])
        self.assertIn("10 minutos", result["message"])
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (product_id,)), 9.0)
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM sales_returns WHERE sale_id = ?", (sale_id,)), 0)

    def test_sales_metrics_count_transactions_instead_of_product_rows(self):
        first = self.add_sample_product(description="Arroz", barcode="tx-a", stock=10, sale_price=100)
        second = self.add_sample_product(description="Oleo", barcode="tx-b", stock=10, sale_price=200)

        self.assertIsNotNone(
            self.quiet(
                self.db.add_sale, first, 1, 100,
                username="maria", role="manager", terminal_id="POS-1", transaction_code="TX-UNICA",
            )
        )
        self.assertIsNotNone(
            self.quiet(
                self.db.add_sale, second, 1, 200,
                username="maria", role="manager", terminal_id="POS-1", transaction_code="TX-UNICA",
            )
        )
        # Registos antigos sem codigo continuam contabilizados individualmente.
        self.assertIsNotNone(
            self.quiet(
                self.db.add_sale, first, 1, 100,
                username="maria", role="manager", terminal_id="POS-1",
            )
        )

        today = datetime.now().strftime("%Y-%m-%d")
        stats = self.db.get_sales_statistics_by_date(datetime.now().strftime("%d/%m/%Y"))
        monthly = self.db.get_monthly_sales_summary(datetime.now().month, datetime.now().year)
        snapshot = self.db.get_admin_home_snapshot(lookback_days=7)
        productivity = self.db.get_productivity_report_data(today, today)
        cash_report = self.db.get_cash_user_report_data(today, today)
        from AI.data_collector import IntelligenceDataCollector
        intelligence_snapshot = IntelligenceDataCollector(db=self.db, default_ttl=5).collect_snapshot()

        self.assertEqual(stats[0], 2)
        self.assertEqual(stats[1], 3.0)
        self.assertEqual(stats[2], 400.0)
        self.assertEqual(stats[3], 200.0)
        self.assertEqual(stats[4], 100.0)
        self.assertEqual(stats[5], 300.0)
        self.assertEqual(monthly[0][1], 2)
        self.assertEqual(snapshot["summary"]["sales_today_count"], 2)
        self.assertEqual(snapshot["summary"]["revenue_today"], 400.0)
        self.assertEqual(productivity["summary"]["total_sales"], 2)
        self.assertEqual(productivity["summary"]["avg_ticket"], 200.0)
        self.assertEqual(cash_report["summary"]["total_sales"], 2)
        self.assertEqual(cash_report["summary"]["avg_ticket"], 200.0)
        self.assertEqual(intelligence_snapshot["vendas_hoje"]["vendas"], 2)
        self.assertEqual(intelligence_snapshot["vendas_hoje"]["ticket_medio"], 200.0)
        self.assertEqual(intelligence_snapshot["atividade_caixa"]["total_vendas_hoje"], 2)


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
