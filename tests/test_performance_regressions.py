from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import sqlite3
from unittest.mock import patch
from types import SimpleNamespace

from database.database import Database, _fetch_sales_velocity, _get_product_daily_sales
from tests.helpers import TemporaryDatabaseTestCase


class DatabasePerformanceTests(TemporaryDatabaseTestCase):
    def test_sku_rebuild_does_not_rewrite_unchanged_products(self):
        product_id = self.add_sample_product()
        self.db._rebuild_all_skus()
        before = self.db.conn.total_changes
        self.db._rebuild_all_skus()
        self.assertEqual(self.db.conn.total_changes, before)
        self.db.sku_prefix = "NOVA"
        self.db._rebuild_all_skus()
        self.assertEqual(self.db.conn.total_changes - before, 1)
        self.assertEqual(
            self.db.conn.execute("SELECT sku FROM products WHERE id = ?", (product_id,)).fetchone()[0],
            self.db._build_sku(product_id, "Arroz"),
        )

    def test_background_connection_captures_owner_and_preserves_ui_cursor(self):
        product_id = self.add_sample_product()
        self.db.current_user = "ana"
        self.db.current_role = "admin"
        self.db.current_data_owner = "loja-a"
        connection = self.db.background_connection()
        self.db.current_user = "outro"
        self.db.current_data_owner = "loja-b"
        self.db.cursor.execute("SELECT id FROM products WHERE id = ?", (product_id,))

        def work():
            with connection as db:
                self.assertIsNot(db.conn, self.db.conn)
                self.assertEqual(db._active_owner(), "loja-a")
                self.assertEqual(db.current_user, "ana")
                self.assertEqual(db.conn.execute("PRAGMA cache_size").fetchone()[0], -4096)
                db.cursor.execute("SELECT COUNT(*) FROM products").fetchone()
                return db.conn

        with patch.object(Database, "setup", side_effect=AssertionError("Repeated migration")):
            with ThreadPoolExecutor(max_workers=1) as executor:
                closed_connection = executor.submit(work).result(timeout=10)
        self.assertEqual(self.db.cursor.fetchone(), (product_id,))
        with self.assertRaises(sqlite3.ProgrammingError):
            closed_connection.execute("SELECT 1")

    def test_background_connection_closes_on_error(self):
        with self.assertRaisesRegex(ValueError, "worker failed"):
            with self.db.background_connection() as db:
                connection = db.conn
                raise ValueError("worker failed")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_background_connection_does_not_reconfigure_journal_mode(self):
        statements = []
        real_connect = sqlite3.connect

        def traced_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        with patch("database.database.sqlite3.connect", side_effect=traced_connect):
            with self.db.background_connection() as db:
                db.cursor.execute("SELECT 1")
        self.assertNotIn("PRAGMA journal_mode = WAL", statements)
        # O journal ja existe porque foi configurado na conexao principal
        # durante o setup; o worker apenas o reutiliza.
        self.assertEqual(self.db.conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")

    def test_aggregated_velocity_matches_individual_queries_for_each_owner(self):
        ids = [self.add_sample_product(description=f"Produto {i}") for i in range(3)]
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.conn.executemany(
            "INSERT INTO sales (product_id, quantity, sale_price, total_price, sale_date, owner_username) VALUES (?, ?, 10, ?, ?, ?)",
            [(ids[0], 1.5, 15, today, "a"), (ids[0], 2, 20, today, "b"),
             (ids[1], 3, 30, "2000-01-01", "a"), (ids[1], 4, 40, today, "a")],
        )
        self.db.conn.commit()
        for owner in (None, "a", "b", "missing"):
            self.db.current_data_owner = owner
            totals = _fetch_sales_velocity(self.db)
            for product_id in ids:
                self.assertEqual(totals.get(product_id, 0), _get_product_daily_sales(self.db, product_id))

    def test_history_date_query_uses_expression_index(self):
        for condition, args, index in (
            ("COALESCE(owner_username, '') = ? AND DATE(sale_date) = ?", ("a", "2026-09-14"), "idx_sales_owner_day"),
        ):
            plan = self.db.conn.execute(
                "EXPLAIN QUERY PLAN SELECT SUM(total_price) FROM sales_history WHERE " + condition, args
            ).fetchall()
            self.assertTrue(any(index in str(row) for row in plan), plan)


def test_log_row_reuses_widgets_and_resets_text_and_theme():
    from kivy.app import App
    from kivymd.app import MDApp
    from admin.admin_home_screen import AdminLogsDialog, RecycledLogCard

    previous = App.get_running_app()
    app = MDApp()
    app.theme_tokens = {}
    try:
        controller = AdminLogsDialog()
        row = RecycledLogCard()
        row.refresh_view_attrs(None, 0, {
            "row": (1, "ana", "admin", "UPDATE_PRODUCT", "Produto A", "2026-09-14 12:30:00"),
            "tokens": {}, "controller": controller,
        })
        card = row.children[0]
        widgets = list(card.walk())
        new_data = (2, None, None, None, None, None)
        tokens = {"text_secondary": [1, 0, 0, 1], "card_alt": [0, 0, 0, 1]}
        row.refresh_view_attrs(None, 1, {"row": new_data, "tokens": tokens, "controller": controller})
        assert list(card.walk()) == widgets
        expected = controller._build_log_card(new_data, tokens)
        assert [(w.text, list(w.text_color)) for w in card.walk() if hasattr(w, "text")] == [
            (w.text, list(w.text_color)) for w in expected.walk() if hasattr(w, "text")
        ]
        assert list(card.md_bg_color) == list(expected.md_bg_color)
    finally:
        App._running_app = previous


def test_home_discards_snapshot_from_previous_period_and_reloads():
    from admin.admin_home_screen import AdminHomeScreen

    calls = []
    screen = SimpleNamespace(
        _snapshot_token=7, _snapshot_loading=True, _chart_period_days=90,
        manager=SimpleNamespace(current="home"), name="home",
        _ensure_snapshot_loaded=lambda **kwargs: calls.append(kwargs),
    )
    AdminHomeScreen._apply_snapshot(screen, {"lookback_days": 30}, token=7, period_days=30)
    assert calls == [{"force": True}]
    assert not screen._snapshot_loading
    assert not hasattr(screen, "_snapshot")


def test_home_resize_requests_are_coalesced():
    from kivy.clock import Clock
    from admin.admin_home_screen import AdminHomeScreen

    calls = []
    trigger = Clock.create_trigger(lambda dt: calls.append(dt), 0)
    screen = SimpleNamespace(_layout_trigger=trigger)
    for _ in range(20):
        AdminHomeScreen.on_size(screen)
    Clock.tick()
    assert len(calls) == 1
