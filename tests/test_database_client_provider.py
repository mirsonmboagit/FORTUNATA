from __future__ import annotations

from datetime import date, datetime

from tests.helpers import ProjectTestCase


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.get_calls = []
        self.post_calls = []
        self.next_get = FakeResponse(payload={"ok": True})
        self.next_post = FakeResponse(payload={"ok": True, "result": {"value": 1}})
        self.closed = False

    def get(self, url, headers=None, timeout=None):
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.next_get

    def post(self, url, json=None, headers=None, timeout=None):
        self.post_calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.next_post

    def close(self):
        self.closed = True


class DatabaseClientTests(ProjectTestCase):
    def make_client(self):
        from database.client import DatabaseClient

        return DatabaseClient(
            config={
                "api_base_url": "http://api.local/",
                "api_key": "secret",
                "timeout": 7,
                "http_pool_size": 2,
                "availability_ttl": 30,
                "availability_cooldown": 30,
                "health_timeout": 0.5,
            }
        )

    def test_headers_and_json_compatibility(self):
        client = self.make_client()

        payload = client._to_json_compatible(
            {
                "date": date(2026, 6, 26),
                "timestamp": datetime(2026, 6, 26, 12, 30),
                "items": (1, date(2026, 1, 1)),
            }
        )

        self.assertEqual(client._build_headers(True), {"Content-Type": "application/json", "X-API-KEY": "secret"})
        self.assertEqual(payload["date"], "2026-06-26")
        self.assertEqual(payload["timestamp"], "2026-06-26 12:30:00")
        self.assertEqual(payload["items"], [1, "2026-01-01"])

    def test_healthcheck_marks_available_and_uses_ttl_cache(self):
        client = self.make_client()
        session = FakeSession()
        client._session = session

        self.assertTrue(client.is_available(force=True))
        self.assertTrue(client.is_available(force=False))

        self.assertEqual(len(session.get_calls), 1)
        self.assertIsNone(client.last_error())

    def test_healthcheck_marks_unavailable_on_http_error(self):
        client = self.make_client()
        session = FakeSession()
        session.next_get = FakeResponse(status_code=401, payload={"error": "unauthorized"})
        client._session = session

        self.assertFalse(client.is_available(force=True))
        self.assertIn("401 unauthorized", client.last_error())
        self.assertEqual(client.get_connection_label(), "Local")

    def test_rpc_posts_session_payload_and_caches_read_results(self):
        client = self.make_client()
        session = FakeSession()
        client._session = session
        client.set_active_user("maria", "manager")
        session.next_post = FakeResponse(payload={"ok": True, "result": [{"id": 1}]})

        first = client._rpc("get_all_products_page", search_text="arroz")
        first[0]["id"] = 999
        second = client._rpc("get_all_products_page", search_text="arroz")

        self.assertEqual(second, [{"id": 1}])
        self.assertEqual(len(session.post_calls), 1)
        posted = session.post_calls[0]["json"]
        self.assertEqual(posted["method"], "get_all_products_page")
        self.assertEqual(posted["kwargs"], {"search_text": "arroz"})
        self.assertEqual(posted["session"], {"username": "maria", "role": "manager"})

    def test_rpc_invalidates_cache_after_mutation(self):
        client = self.make_client()
        session = FakeSession()
        client._session = session

        session.next_post = FakeResponse(payload={"ok": True, "result": [{"id": 1}]})
        self.assertEqual(client._rpc("get_all_products_page"), [{"id": 1}])
        self.assertEqual(client._rpc("get_all_products_page"), [{"id": 1}])
        self.assertEqual(len(session.post_calls), 1)

        session.next_post = FakeResponse(payload={"ok": True, "result": True})
        self.assertTrue(client._rpc("add_product", "Arroz"))
        session.next_post = FakeResponse(payload={"ok": True, "result": [{"id": 2}]})
        self.assertEqual(client._rpc("get_all_products_page"), [{"id": 2}])

        self.assertEqual(len(session.post_calls), 3)

    def test_rpc_records_unsupported_safe_method_for_400(self):
        client = self.make_client()
        session = FakeSession()
        session.next_post = FakeResponse(status_code=400, payload={"error": "method_not_allowed"})
        client._session = session

        self.assertIsNone(client._rpc("get_all_products_page"))
        self.assertIn("get_all_products_page", client._unsupported_rpc_methods)
        self.assertIsNone(client._rpc("get_all_products_page"))
        self.assertEqual(len(session.post_calls), 1)

    def test_close_closes_session(self):
        client = self.make_client()
        session = FakeSession()
        client._session = session

        client.close()

        self.assertTrue(session.closed)
        self.assertIsNone(client._session)


class HybridProviderTests(ProjectTestCase):
    class Remote:
        def __init__(self, available=True, error=""):
            self.available = available
            self.error = error
            self.calls = []
            self.closed = False

        def is_available(self):
            return self.available

        def get_health_status(self, force=False):
            return {"ok": self.available, "error": self.error, "base_url": "http://api.local"}

        def last_error(self):
            return self.error

        def get_value(self, value):
            self.calls.append(("remote", value))
            if self.error:
                return None
            return f"remote:{value}"

        def set_active_user(self, username, role):
            self.calls.append(("user", username, role))

        def close(self):
            self.closed = True

    class Local:
        def __init__(self):
            self.calls = []
            self.closed = False

        def get_value(self, value):
            self.calls.append(("local", value))
            return f"local:{value}"

        def set_active_user(self, username, role):
            self.calls.append(("user", username, role))

        def close(self):
            self.closed = True

    def test_hybrid_dispatches_to_remote_when_available(self):
        from database.provider import HybridDatabase

        remote = self.Remote()
        local = self.Local()
        db = HybridDatabase(config={"db_path": "unused.sqlite3"}, remote_db=remote, local_db=local)

        self.assertEqual(db.get_value("x"), "remote:x")
        self.assertEqual(remote.calls, [("remote", "x")])
        self.assertEqual(local.calls, [])
        self.assertTrue(db.using_remote())
        self.assertEqual(db.get_connection_status()["label"], "API")

    def test_hybrid_falls_back_to_local_when_remote_unavailable(self):
        from database.provider import HybridDatabase

        remote = self.Remote(available=False, error="offline")
        local = self.Local()
        db = HybridDatabase(config={"db_path": "unused.sqlite3"}, remote_db=remote, local_db=local)

        self.assertEqual(db.get_value("x"), "local:x")
        status = db.get_connection_status()
        self.assertEqual(status["label"], "Local")
        self.assertIn("offline", status["message"])

    def test_hybrid_falls_back_when_remote_sets_last_error(self):
        from database.provider import HybridDatabase

        remote = self.Remote(available=True, error="rpc failed")
        local = self.Local()
        db = HybridDatabase(config={"db_path": "unused.sqlite3"}, remote_db=remote, local_db=local)

        self.assertEqual(db.get_value("x"), "local:x")
        self.assertEqual(db.last_error(), "")

    def test_hybrid_propagates_active_user_and_closes_backends(self):
        from database.provider import HybridDatabase

        remote = self.Remote()
        local = self.Local()
        db = HybridDatabase(config={"db_path": "unused.sqlite3"}, remote_db=remote, local_db=local)

        db.set_active_user("maria", "manager")
        db.close()

        self.assertIn(("user", "maria", "manager"), remote.calls)
        self.assertIn(("user", "maria", "manager"), local.calls)
        self.assertTrue(remote.closed)
        self.assertTrue(local.closed)

    def test_uses_remote_backend_detects_available_clients(self):
        from database.provider import uses_remote_backend

        self.assertFalse(uses_remote_backend(None))
        self.assertTrue(uses_remote_backend(self.Remote(available=True)))
        self.assertFalse(uses_remote_backend(self.Remote(available=False)))
