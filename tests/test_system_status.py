from __future__ import annotations

from datetime import datetime

from tests.helpers import TemporaryDatabaseTestCase


class SystemStatusTests(TemporaryDatabaseTestCase):
    def test_collect_system_status_reports_local_database(self):
        from utils.config.system_status import collect_system_status

        status = collect_system_status(self.db)

        self.assertEqual(status["database"]["exists"], True)
        self.assertEqual(status["database"]["integrity"]["ok"], True)
        self.assertEqual(status["db_mode"], "local")
        self.assertNotIn("api", status)

    def test_collect_system_status_reads_automation_state(self):
        from utils.config.system_status import collect_system_status

        self.db.cursor.execute(
            """
            INSERT INTO automation_state (state_key, state_value, updated_at)
            VALUES (?, ?, ?)
            """,
            ("auto_backup_last_status", "ok", "2026-07-25T10:00:00"),
        )
        self.db.conn.commit()

        status = collect_system_status(self.db)

        self.assertEqual(status["automation"]["last_backup_status"], "ok")

    def test_database_can_create_verified_backup_visible_in_status(self):
        from utils.config.system_status import collect_system_status

        result = self.db.create_verified_backup()
        status = collect_system_status(self.db)

        self.assertTrue(result["ok"])
        self.assertTrue(result["path"])
        self.assertIsNotNone(status["files"]["latest_backup"])

    def test_assess_system_alerts_warns_when_backup_is_missing(self):
        from utils.config.system_status import assess_system_alerts

        alerts = assess_system_alerts(
            {
                "app_env": "development",
                "db_mode": "local",
                "database": {"exists": True, "size_bytes": 1, "integrity": {"ok": True}},
                "api": {"has_api_key": True, "health": {"ok": None}},
                "automation": {},
                "files": {"latest_backup": None},
            },
            now=datetime(2026, 7, 25, 12, 0, 0),
        )

        self.assertIn("backup_missing", {item["code"] for item in alerts})

    def test_assess_system_alerts_ignores_removed_api_settings(self):
        from utils.config.system_status import assess_system_alerts

        alerts = assess_system_alerts(
            {
                "app_env": "production",
                "db_mode": "hybrid",
                "database": {"exists": True, "size_bytes": 1, "integrity": {"ok": True}},
                "api": {"has_api_key": False, "health": {"ok": False}},
                "automation": {"last_backup_run": "2026-07-25T10:00:00"},
                "files": {"latest_backup": None},
            },
            now=datetime(2026, 7, 25, 12, 0, 0),
        )

        codes = {item["code"] for item in alerts}
        self.assertNotIn("api_offline", codes)
        self.assertNotIn("api_key_missing", codes)

    def test_assess_system_alerts_reports_ok_when_no_issue_exists(self):
        from utils.config.system_status import assess_system_alerts

        alerts = assess_system_alerts(
            {
                "app_env": "development",
                "db_mode": "local",
                "database": {"exists": True, "size_bytes": 1, "integrity": {"ok": True}},
                "api": {"has_api_key": True, "health": {"ok": None}},
                "automation": {"last_backup_run": "2026-07-25T10:00:00"},
                "files": {"latest_backup": None},
            },
            now=datetime(2026, 7, 25, 12, 0, 0),
        )

        self.assertEqual(alerts, [{
            "level": "ok",
            "code": "system_ok",
            "message": "Sem alertas.",
        }])
