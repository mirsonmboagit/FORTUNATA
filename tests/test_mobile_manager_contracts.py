from pathlib import Path

from database.client import DatabaseClient
from mobile.manager.sales_screen import MobileManagerSalesScreen, _aggregate_lots


ROOT = Path(__file__).resolve().parents[1]


def test_mobile_catalog_aggregates_sibling_lots_without_losing_stock():
    rows = [
        [1, "Agua", 1, 40, "100", 0, None, "ATIVO", 0, 0, "STANDARD"],
        [2, "Agua", 3, 40, "100", 0, None, "ATIVO", 0, 0, "STANDARD"],
    ]

    products = _aggregate_lots(rows)

    assert len(products) == 1
    assert products[0]["id"] == 1
    assert products[0]["stock"] == 4
    assert products[0]["lot_count"] == 2
    assert products[0]["catalog_key"] == "bc:100"


def test_mobile_sale_allocation_uses_all_lots_for_one_cart_line():
    class FakeDb:
        def get_products_by_barcode(self, *_args, **_kwargs):
            return [
                [1, "Agua", 1, 40, "100", 0, None, "ATIVO", 0, 0, "STANDARD"],
                [2, "Agua", 3, 40, "100", 0, None, "ATIVO", 0, 0, "STANDARD"],
            ]

        def get_products_for_sale_page(self, **_kwargs):
            return []

    class Harness:
        _allocate_discount = MobileManagerSalesScreen._allocate_discount
        _live_lots_for_item = MobileManagerSalesScreen._live_lots_for_item
        _build_commit_allocations = MobileManagerSalesScreen._build_commit_allocations

        def __init__(self):
            self.db = FakeDb()

    allocations, conflicts = Harness()._build_commit_allocations(
        [
            {
                "id": 1,
                "name": "Agua",
                "barcode": "100",
                "catalog_key": "bc:100",
                "qty": 2,
                "price": 40,
                "vat_rule_code": "STANDARD",
            }
        ],
        discount=4,
    )

    assert conflicts == []
    assert [item["id"] for item in allocations] == [1, 2]
    assert [item["qty"] for item in allocations] == [1, 1]
    assert sum(item["discount_amount"] for item in allocations) == 4
    assert {item["effective_unit_price"] for item in allocations} == {38.0}


def test_remote_client_preserves_sale_transaction_and_cash_metadata():
    client = DatabaseClient(config={"api_base_url": "https://api.example", "api_key": "x" * 24})
    calls = []
    client._rpc = lambda method, *args, **kwargs: calls.append((method, args, kwargs)) or 42

    assert client.add_sale(
        4,
        2,
        99,
        "mirson",
        "manager",
        transaction_code="MOB-1",
        payment_method="mobile",
        discount_amount=5,
        cash_session_id=7,
        discount_reason="Campanha",
        discount_authorized_by="mirson",
    ) == 42

    method, args, kwargs = calls.pop()
    assert method == "add_sale"
    assert args == (4, 2, 99, "mirson", "manager")
    assert kwargs["transaction_code"] == "MOB-1"
    assert kwargs["payment_method"] == "mobile"
    assert kwargs["cash_session_id"] == 7
    assert kwargs["discount_amount"] == 5


def test_remote_client_exposes_atomic_sale_transaction_call():
    client = DatabaseClient(config={"api_base_url": "https://api.example", "api_key": "x" * 24})
    calls = []
    client._rpc = lambda method, *args, **kwargs: calls.append((method, args, kwargs)) or {"ok": True}

    result = client.add_sales_transaction(
        "MOB-ATOMIC-1",
        [{"id": 4, "qty": 2, "effective_unit_price": 99}],
        username="mirson",
        role="manager",
        terminal_id="MOBILE-1",
        payment_method="card",
        cash_session_id=7,
    )

    assert result == {"ok": True}
    method, args, kwargs = calls.pop()
    assert method == "add_sales_transaction"
    assert args == ("MOB-ATOMIC-1", [{"id": 4, "qty": 2, "effective_unit_price": 99}])
    assert kwargs["terminal_id"] == "MOBILE-1"
    assert kwargs["payment_method"] == "card"


def test_mobile_sale_retry_reuses_the_same_transaction_and_allocations():
    class FakeDb:
        def __init__(self):
            self.calls = []
            self.fail_first = True

        def add_sales_transaction(self, code, items, **kwargs):
            self.calls.append((code, [dict(item) for item in items], kwargs))
            if self.fail_first:
                return {"ok": False, "message": "timeout"}
            return {"ok": True, "idempotent": True}

        @staticmethod
        def last_error():
            return "ligacao interrompida"

    class Harness:
        finalize_sale = MobileManagerSalesScreen.finalize_sale
        _sale_fingerprint = staticmethod(MobileManagerSalesScreen._sale_fingerprint)

        def __init__(self):
            self.db = FakeDb()
            self.cart_items = [
                {
                    "id": 4,
                    "name": "Agua",
                    "barcode": "100",
                    "catalog_key": "bc:100",
                    "qty": 2,
                    "price": 40,
                    "vat_rule_code": "STANDARD",
                }
            ]
            self.cash_session = {"id": 7}
            self.discount_amount = 0
            self.payment_method = "card"
            self.paid_amount_text = ""
            self.total_amount = 80
            self.sale_in_progress = False
            self._pending_sale = None
            self.messages = []
            self.status_message = ""

        @staticmethod
        def _current_user():
            return "mirson"

        @staticmethod
        def _current_role():
            return "manager"

        @staticmethod
        def _get_terminal_id():
            return "MOBILE-RETRY"

        @staticmethod
        def _refresh_totals():
            return None

        @staticmethod
        def _schedule_render():
            return None

        @staticmethod
        def show_tab(*_args, **_kwargs):
            return None

        @staticmethod
        def load_products(*_args, **_kwargs):
            return None

        @staticmethod
        def load_history(*_args, **_kwargs):
            return None

        def _show_message(self, title, message):
            self.messages.append((title, message))

        def _invalidate_pending_sale(self):
            self._pending_sale = None

        @staticmethod
        def _build_commit_allocations(cart, discount):
            return ([{**cart[0], "effective_unit_price": 40, "discount_amount": discount}], [])

        def clear_cart(self):
            self.cart_items = []

        @staticmethod
        def _background(task, callback):
            try:
                callback(result=task())
            except Exception as exc:  # pragma: no cover - behavior exercised by screen runtime
                callback(error=exc)

    screen = Harness()
    screen.finalize_sale()

    pending = dict(screen._pending_sale)
    assert pending["transaction_code"].startswith("MOB-RETRY-")
    assert pending["fingerprint"]
    assert pending["allocations"]
    assert len(screen.db.calls) == 1
    assert screen.messages[-1][0] == "Confirmacao pendente"

    screen.db.fail_first = False
    screen.finalize_sale()

    assert len(screen.db.calls) == 2
    assert screen.db.calls[1][0] == screen.db.calls[0][0]
    assert screen.db.calls[1][1] == screen.db.calls[0][1]
    assert screen._pending_sale is None
    assert screen.cart_items == []


def test_remote_client_exposes_cash_session_api_calls():
    client = DatabaseClient(config={"api_base_url": "https://api.example", "api_key": "x" * 24})
    calls = []
    client._rpc = lambda method, *args, **kwargs: calls.append((method, args, kwargs)) or {"ok": True}

    client.get_open_cash_session("mirson", "MOBILE-1")
    client.open_cash_session("mirson", "MOBILE-1", 20, role="manager")
    client.get_cash_session_summary(5)
    client.close_cash_session(5, 120, closed_by="mirson", role="manager")

    assert [call[0] for call in calls] == [
        "get_open_cash_session",
        "open_cash_session",
        "get_cash_session_summary",
        "close_cash_session",
    ]
    assert calls[1][1] == ("mirson", "MOBILE-1")
    assert calls[1][2]["opening_amount"] == 20
    assert calls[3][2]["closed_by"] == "mirson"


def test_mobile_build_contract_excludes_windows_scanner_stack():
    spec = (ROOT / "buildozer-manager-mobile.spec").read_text(encoding="utf-8")
    requirements = "\n".join(
        line.strip().lower()
        for line in (ROOT / "requirements-mobile.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    sales_source = (ROOT / "mobile" / "manager" / "sales_screen.py").read_text(encoding="utf-8").lower()

    assert "android.permissions = internet" in spec.lower()
    assert "android.private_storage = true" in spec.lower()
    assert "utils/hardware" in spec.lower()
    for forbidden in ("pywin32", "opencv", "pyzbar", "pymupdf"):
        assert forbidden not in requirements
    assert "import cv2" not in sales_source
    assert "from pyzbar" not in sales_source


def test_mobile_entrypoint_is_remote_only_and_has_android_files():
    source = (ROOT / "manager_mobile_app.py").read_text(encoding="utf-8")

    assert "DatabaseClient" in source
    assert "from database.provider import get_db" not in source
    assert (ROOT / "main.py").is_file()
    assert (ROOT / "mobile" / "manager" / "connection_screen.kv").is_file()
    assert (ROOT / "mobile" / "manager" / "sales_screen.kv").is_file()
