from datetime import date, timedelta

from database.database import EXPIRY_LOSS_REASON
from tests.helpers import TemporaryDatabaseTestCase


class LossControlsTests(TemporaryDatabaseTestCase):
    def test_expired_loss_requires_selected_reason_and_an_expired_date(self):
        future_product = self.add_sample_product(stock=4, expiry_date=(date.today() + timedelta(days=1)).isoformat())

        self.assertIsNone(
            self.db.record_stock_movement(
                future_product,
                "EXPIRED",
                1,
                "OUT",
                reason=EXPIRY_LOSS_REASON,
                created_by="maria",
                created_role="manager",
            )
        )
        self.assertEqual(
            self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (future_product,)),
            4.0,
        )

        expired_product = self.add_sample_product(stock=4, expiry_date=(date.today() - timedelta(days=1)).isoformat())
        self.assertIsNone(
            self.db.record_stock_movement(
                expired_product,
                "EXPIRED",
                1,
                "OUT",
                reason="Produto estragado",
                created_by="maria",
                created_role="manager",
            )
        )

        movement_id = self.db.record_stock_movement(
            expired_product,
            "EXPIRED",
            1,
            "OUT",
            reason=EXPIRY_LOSS_REASON,
            created_by="maria",
            created_role="manager",
        )
        self.assertIsNotNone(movement_id)
        self.assertEqual(
            self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (expired_product,)),
            4.0,
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(movement_id),
            {"approval_status": "PENDING", "applied": False},
        )

    def test_every_manager_loss_waits_for_admin_but_admin_losses_do_not(self):
        product_id = self.add_sample_product(stock=40, unit_purchase_price=100)

        pending_id = self.db.request_stock_movement(
            product_id,
            "ADJUSTMENT",
            1,
            "Contagem de stock",
            "maria",
            "manager",
            direction="OUT",
        )
        self.assertIsNotNone(pending_id)
        self.assertEqual(
            self.db.get_stock_movement_approval_status(pending_id),
            {"approval_status": "PENDING", "applied": False},
        )
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (product_id,)), 40.0)

        admin_id = self.db.request_stock_movement(
            product_id,
            "ADJUSTMENT",
            1,
            "Contagem de stock",
            "admin",
            "admin",
            direction="OUT",
        )
        self.assertIsNotNone(admin_id)
        self.assertEqual(
            self.db.get_stock_movement_approval_status(admin_id),
            {"approval_status": "APPROVED", "applied": True},
        )
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (product_id,)), 39.0)

        theft_id = self.db.request_stock_movement(
            product_id,
            "THEFT",
            1,
            "Furto confirmado",
            "maria",
            "manager",
            direction="OUT",
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(theft_id),
            {"approval_status": "PENDING", "applied": False},
        )

    def test_manager_losses_are_pending_across_products_and_by_weight(self):
        first_product = self.add_sample_product(description="Produto A", stock=20)
        second_product = self.add_sample_product(description="Produto B", stock=20)

        first_id = self.db.request_stock_movement(
            first_product,
            "ADJUSTMENT",
            6,
            "Contagem de stock",
            "maria",
            "manager",
            direction="OUT",
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(first_id),
            {"approval_status": "PENDING", "applied": False},
        )
        combined_id = self.db.request_stock_movement(
            second_product,
            "ADJUSTMENT",
            5,
            "Contagem de stock",
            "maria",
            "manager",
            direction="OUT",
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(combined_id),
            {"approval_status": "PENDING", "applied": False},
        )
        self.assertIn(
            "Perda registada por gerente requer aprovacao administrativa",
            self.fetch_scalar("SELECT note FROM stock_movements WHERE id = ?", (combined_id,)),
        )

        weighted_product = self.add_sample_product(
            description="Produto a peso",
            stock=20,
            is_sold_by_weight=True,
        )
        ten_kg_id = self.db.request_stock_movement(
            weighted_product,
            "ADJUSTMENT",
            10,
            "Contagem de stock",
            "ana",
            "manager",
            direction="OUT",
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(ten_kg_id),
            {"approval_status": "PENDING", "applied": False},
        )
        over_ten_kg_id = self.db.request_stock_movement(
            weighted_product,
            "ADJUSTMENT",
            0.5,
            "Contagem de stock",
            "ana",
            "manager",
            direction="OUT",
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(over_ten_kg_id),
            {"approval_status": "PENDING", "applied": False},
        )

    def test_manager_losses_remain_pending_regardless_of_history(self):
        product_id = self.add_sample_product(stock=60)

        def register_then_backdate(username, target_day):
            movement_id = self.db.request_stock_movement(
                product_id,
                "ADJUSTMENT",
                1,
                "Contagem de stock",
                username,
                "manager",
                direction="OUT",
            )
            self.assertEqual(
                self.db.get_stock_movement_approval_status(movement_id),
                {"approval_status": "PENDING", "applied": False},
            )
            self.db.cursor.execute(
                "UPDATE stock_movements SET created_at = ? WHERE id = ?",
                (f"{target_day.isoformat()} 12:00:00", movement_id),
            )
            self.db.conn.commit()

        today = date.today()
        register_then_backdate("maria", today - timedelta(days=2))
        register_then_backdate("maria", today - timedelta(days=1))
        day_streak_id = self.db.request_stock_movement(
            product_id, "ADJUSTMENT", 1, "Contagem de stock", "maria", "manager", direction="OUT"
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(day_streak_id),
            {"approval_status": "PENDING", "applied": False},
        )
        self.assertIn(
            "Perda registada por gerente requer aprovacao administrativa",
            self.fetch_scalar("SELECT note FROM stock_movements WHERE id = ?", (day_streak_id,)),
        )

        current_week = today - timedelta(days=today.weekday())
        register_then_backdate("ana", current_week - timedelta(days=14))
        register_then_backdate("ana", current_week - timedelta(days=7))
        week_streak_id = self.db.request_stock_movement(
            product_id, "ADJUSTMENT", 1, "Contagem de stock", "ana", "manager", direction="OUT"
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(week_streak_id),
            {"approval_status": "PENDING", "applied": False},
        )
        self.assertIn(
            "Perda registada por gerente requer aprovacao administrativa",
            self.fetch_scalar("SELECT note FROM stock_movements WHERE id = ?", (week_streak_id,)),
        )

        current_month = today.replace(day=1)
        register_then_backdate("joana", self.db._shift_month(current_month, -2))
        register_then_backdate("joana", self.db._shift_month(current_month, -1))
        month_streak_id = self.db.request_stock_movement(
            product_id, "ADJUSTMENT", 1, "Contagem de stock", "joana", "manager", direction="OUT"
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(month_streak_id),
            {"approval_status": "PENDING", "applied": False},
        )
        self.assertIn(
            "Perda registada por gerente requer aprovacao administrativa",
            self.fetch_scalar("SELECT note FROM stock_movements WHERE id = ?", (month_streak_id,)),
        )

    def test_approve_all_pending_losses_applies_each_pending_movement(self):
        first_product = self.add_sample_product(description="Produto A", stock=5)
        second_product = self.add_sample_product(description="Produto B", stock=7)

        first_id = self.db.request_stock_movement(
            first_product,
            "ADJUSTMENT",
            1,
            "Contagem de stock",
            "maria",
            "manager",
            direction="OUT",
        )
        second_id = self.db.record_stock_movement(
            second_product,
            "THEFT",
            2,
            "OUT",
            reason="Furto confirmado",
            created_by="maria",
            created_role="manager",
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(first_id),
            {"approval_status": "PENDING", "applied": False},
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(second_id),
            {"approval_status": "PENDING", "applied": False},
        )

        summary = self.db.approve_all_pending_stock_movements("admin")

        self.assertEqual(summary["approved_count"], 2)
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(
            self.db.get_stock_movement_approval_status(first_id),
            {"approval_status": "APPROVED", "applied": True},
        )
        self.assertEqual(
            self.db.get_stock_movement_approval_status(second_id),
            {"approval_status": "APPROVED", "applied": True},
        )
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (first_product,)), 4.0)
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (second_product,)), 5.0)

    def test_fraud_detection_considers_only_manager_losses(self):
        product_id = self.add_sample_product(stock=10)

        for _ in range(3):
            self.assertIsNotNone(
                self.db.record_stock_movement(
                    product_id,
                    "ADJUSTMENT",
                    1,
                    "OUT",
                    reason="Contagem de stock",
                    created_by="admin",
                    created_role="admin",
                )
            )
        self.assertEqual(self.db.detect_fraud_patterns(), [])

        for _ in range(3):
            self.assertIsNotNone(
                self.db.record_stock_movement(
                    product_id,
                    "ADJUSTMENT",
                    1,
                    "OUT",
                    reason="Contagem de stock",
                    created_by="maria",
                    created_role="manager",
                )
            )

        alert_types = {alert["alert_type"] for alert in self.db.detect_fraud_patterns()}
        self.assertIn("REPEATED_PRODUCT_LOSS", alert_types)

        insights = self.db.get_admin_insights()
        self.assertTrue(insights["fraud_alerts"])
        self.assertEqual(
            insights["badge_counts"]["fraud"],
            len(insights["fraud_alerts"]),
        )
        self.assertIn("alertas de fraude", " ".join(insights["alerts"]).lower())

    def test_fraud_detection_uses_quantity_not_monetary_value(self):
        product_id = self.add_sample_product(stock=10, unit_purchase_price=100000)
        movement_id = self.db.record_stock_movement(
            product_id,
            "ADJUSTMENT",
            1,
            "OUT",
            reason="Contagem de stock",
            created_by="maria",
            created_role="manager",
        )
        self.assertIsNotNone(movement_id)
        self.db.cursor.execute(
            "UPDATE stock_movements SET created_at = ? WHERE id = ?",
            (f"{date.today().isoformat()} 12:00:00", movement_id),
        )
        self.db.conn.commit()

        alerts = self.db.detect_fraud_patterns()

        self.assertEqual(alerts, [])

    def test_fraud_detection_uses_an_isolated_read_cursor(self):
        original_cursor = self.db.cursor

        class SharedCursorMustNotBeUsed:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("O cursor partilhado nao deve ser usado na deteccao de fraude")

        self.db.cursor = SharedCursorMustNotBeUsed()
        try:
            self.assertEqual(self.db.detect_fraud_patterns(), [])
        finally:
            self.db.cursor = original_cursor
