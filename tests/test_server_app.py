from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from datetime import date, datetime
from threading import Lock
from unittest import mock

from tests.helpers import ProjectTestCase


class FakeDatabase:
    instances = []

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.active_user = None
        self.active_role = None
        self.calls = []
        FakeDatabase.instances.append(self)

    def set_active_user(self, username=None, role=None):
        self.active_user = username
        self.active_role = role

    def get_recent_sales(self, limit=50):
        self.calls.append(("get_recent_sales", limit))
        return [
            {
                "day": date(2026, 6, 26),
                "created_at": datetime(2026, 6, 26, 12, 30),
                "raw": b"\x01\x02",
                "row": ("sale", 1),
            }
        ]

    def get_all_products(self):
        return [{"id": 1, "description": "Arroz"}]

    def run_automation_tasks(self):
        self.calls.append(("run_automation_tasks",))
        return {"backup": {"executed": True, "ok": True}, "reconcile": {"executed": False}}


def import_server_app_with_fakes(api_key="secret", app_env="development"):
    FakeDatabase.instances = []
    fake_database_module = types.ModuleType("database.database")
    fake_database_module.Database = FakeDatabase

    fake_app_config = types.ModuleType("utils.app_config")
    fake_app_config.get_app_config = lambda force_reload=False: {
        "api_key": api_key,
        "db_path": "unit-test.sqlite3",
        "app_env": app_env,
    }
    fake_app_config.get_api_config = lambda force_reload=False: {
        "runner": "flask",
        "host": "127.0.0.1",
        "port": 8080,
    }

    fake_paths = types.ModuleType("utils.paths")
    fake_paths.ROOT_DIR = "."
    fake_paths.ensure_runtime_dirs = lambda *args, **kwargs: tuple()
    fake_paths.set_project_cwd = lambda: "."

    fake_logging = types.ModuleType("utils.logging_setup")
    fake_logging.configure_runtime_logging = lambda *args, **kwargs: None

    module_names = ["server.app", "database.database", "utils.app_config", "utils.paths", "utils.logging_setup"]
    saved = {name: sys.modules.get(name) for name in module_names}
    for name in module_names:
        sys.modules.pop(name, None)

    replacements = {
        "database.database": fake_database_module,
        "utils.app_config": fake_app_config,
        "utils.paths": fake_paths,
        "utils.logging_setup": fake_logging,
    }

    try:
        with mock.patch.dict(sys.modules, replacements), mock.patch.dict(os.environ, {"API_KEY": ""}, clear=False):
            module = importlib.import_module("server.app")
    finally:
        for name in ("database.database", "utils.app_config", "utils.paths", "utils.logging_setup"):
            if saved[name] is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved[name]

    return module, saved.get("server.app")


class ServerAppTests(ProjectTestCase):
    def tearDown(self):
        sys.modules.pop("server.app", None)
        super().tearDown()

    def test_health_requires_configured_api_key(self):
        module, previous = import_server_app_with_fakes(api_key="secret")
        self.addCleanup(lambda: sys.modules.__setitem__("server.app", previous) if previous else sys.modules.pop("server.app", None))
        client = module.create_app().test_client()

        unauthorized = client.get("/health")
        ok = client.get("/health", headers={"X-API-KEY": "secret"})

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.get_json()["ok"])
        self.assertEqual(ok.get_json()["db_path"], "unit-test.sqlite3")

    def test_health_hides_db_path_in_production(self):
        module, previous = import_server_app_with_fakes(api_key="", app_env="production")
        self.addCleanup(lambda: sys.modules.__setitem__("server.app", previous) if previous else sys.modules.pop("server.app", None))
        with mock.patch.dict(os.environ, {"API_KEY": ""}, clear=False):
            client = module.create_app().test_client()

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("db_path", response.get_json())

    def test_rpc_rejects_invalid_payload_and_unknown_methods(self):
        module, previous = import_server_app_with_fakes(api_key="")
        self.addCleanup(lambda: sys.modules.__setitem__("server.app", previous) if previous else sys.modules.pop("server.app", None))
        with mock.patch.dict(os.environ, {"API_KEY": ""}, clear=False):
            client = module.create_app().test_client()

        bad_args = client.post("/rpc", json={"method": "get_all_products", "args": "bad"})
        forbidden = client.post("/rpc", json={"method": "drop_everything"})

        self.assertEqual(bad_args.status_code, 400)
        self.assertEqual(bad_args.get_json()["error"], "invalid_args")
        self.assertEqual(forbidden.status_code, 400)
        self.assertEqual(forbidden.get_json()["error"], "method_not_allowed")

    def test_rpc_calls_allowed_method_sets_session_and_normalizes_result(self):
        module, previous = import_server_app_with_fakes(api_key="")
        self.addCleanup(lambda: sys.modules.__setitem__("server.app", previous) if previous else sys.modules.pop("server.app", None))
        with mock.patch.dict(os.environ, {"API_KEY": ""}, clear=False):
            app = module.create_app()
        client = app.test_client()

        response = client.post(
            "/rpc",
            json={
                "method": "get_recent_sales",
                "args": [5],
                "session": {"username": "maria", "role": "manager"},
            },
        )
        payload = response.get_json()
        db = app.config["DB_INSTANCE"]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.active_user, "maria")
        self.assertEqual(db.active_role, "manager")
        self.assertEqual(payload["result"][0]["day"], "2026-06-26")
        self.assertEqual(payload["result"][0]["created_at"], "2026-06-26T12:30:00")
        self.assertEqual(payload["result"][0]["raw"], "0102")
        self.assertEqual(payload["result"][0]["row"], ["sale", 1])

    def test_automation_scheduler_runs_once_with_app_lock(self):
        module, previous = import_server_app_with_fakes(api_key="")
        self.addCleanup(lambda: sys.modules.__setitem__("server.app", previous) if previous else sys.modules.pop("server.app", None))
        app = module.create_app()
        scheduler = module._AutomationScheduler(app, interval_seconds=5, startup_delay_seconds=0)

        scheduler._run_once()

        self.assertIn(("run_automation_tasks",), app.config["DB_INSTANCE"].calls)
        self.assertIsInstance(app.config["DB_LOCK"], Lock().__class__)


if __name__ == "__main__":
    unittest.main()
