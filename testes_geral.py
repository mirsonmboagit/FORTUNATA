#!/usr/bin/env python3
"""Suite geral de testes automatizados do projeto.

Executa com:
    python testes_geral.py

Objetivos:
- Validar o fluxo principal do sistema sem tocar na base real.
- Cobrir CRUD, autenticacao, vendas, estorno, funcoes criticas,
  simulacao logica de interface, erros e performance basica.
- Gerar logs com status por teste, falhas e tempo total.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import hashlib
import shutil
import sqlite3
import sys
import time
import types
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import bcrypt as _bcrypt  # noqa: F401
except Exception:
    bcrypt_stub = types.ModuleType("bcrypt")

    def _to_bytes(value):
        if isinstance(value, memoryview):
            return value.tobytes()
        if isinstance(value, str):
            return value.encode("utf-8")
        return value

    def _gensalt():
        return b"codex-test-salt"

    def _hashpw(password, salt):
        password = _to_bytes(password) or b""
        salt = _to_bytes(salt) or b"codex-test-salt"
        digest = hashlib.sha256(salt + b"::" + password).hexdigest().encode("ascii")
        return b"stub$" + digest

    def _checkpw(password, hashed):
        password = _to_bytes(password) or b""
        hashed = _to_bytes(hashed) or b""
        return _hashpw(password, _gensalt()) == hashed

    bcrypt_stub.gensalt = _gensalt
    bcrypt_stub.hashpw = _hashpw
    bcrypt_stub.checkpw = _checkpw
    sys.modules["bcrypt"] = bcrypt_stub

from AI.alert_manager import AlertManager
from AI.engine import executar_analise
from database.client import DatabaseClient
from database.database import Database
from database.provider import HybridDatabase, uses_remote_backend
from utils.receipt_policy import can_emit_receipt, resolve_receipt_data_for_emission
from utils.security_questions import check_answer, hash_answer, normalize_answer

try:
    import requests
except Exception:
    requests = None

try:
    from api.api_openfoodfacts import OpenFoodFactsAPI
    OPENFOODFACTS_IMPORT_ERROR = None
except Exception as exc:
    OpenFoodFactsAPI = None
    OPENFOODFACTS_IMPORT_ERROR = exc

RUN_STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / f"testes_geral_{RUN_STAMP}.log"
TEST_TMP_ROOT = PROJECT_ROOT / ".tmp_testes"
TEST_TMP_ROOT.mkdir(exist_ok=True)

LOGGER = logging.getLogger("testes_geral")
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False
if not LOGGER.handlers:
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    LOGGER.addHandler(file_handler)


@contextlib.contextmanager
def suppress_project_output():
    """Silencia prints do projeto durante operacoes esperadas."""
    with contextlib.redirect_stdout(StringIO()), contextlib.redirect_stderr(StringIO()):
        yield


class LoggedTextTestResult(unittest.TextTestResult):
    """Resultado com logging simples para arquivo."""

    def startTest(self, test):
        self._started_at = time.perf_counter()
        LOGGER.info("START %s", test.id())
        super().startTest(test)

    def addSuccess(self, test):
        elapsed = time.perf_counter() - self._started_at
        LOGGER.info("PASS  %s (%.3fs)", test.id(), elapsed)
        super().addSuccess(test)

    def addFailure(self, test, err):
        elapsed = time.perf_counter() - self._started_at
        LOGGER.error("FAIL  %s (%.3fs)", test.id(), elapsed)
        super().addFailure(test, err)

    def addError(self, test, err):
        elapsed = time.perf_counter() - self._started_at
        LOGGER.error("ERROR %s (%.3fs)", test.id(), elapsed)
        super().addError(test, err)

    def addSkip(self, test, reason):
        elapsed = time.perf_counter() - self._started_at
        LOGGER.warning("SKIP  %s (%.3fs) | %s", test.id(), elapsed, reason)
        super().addSkip(test, reason)


class LoggedTextTestRunner(unittest.TextTestRunner):
    resultclass = LoggedTextTestResult


class BaseProjectTestCase(unittest.TestCase):
    """Base com utilitarios comuns para toda a suite."""

    def quiet(self, func, *args, **kwargs):
        with suppress_project_output():
            return func(*args, **kwargs)

    def assertDurationUnder(self, elapsed_seconds, limit_seconds, label):
        LOGGER.info(
            "PERF  %s | elapsed=%.4fs | limit=%.4fs",
            label,
            elapsed_seconds,
            limit_seconds,
        )
        self.assertLessEqual(
            elapsed_seconds,
            limit_seconds,
            f"Tempo acima do limite em {label}: {elapsed_seconds:.4f}s > {limit_seconds:.4f}s",
        )


class TestesPoliticaRecibo(BaseProjectTestCase):
    def test_recibo_exige_venda_concluida(self):
        self.assertFalse(can_emit_receipt(None))
        self.assertFalse(can_emit_receipt({}))
        self.assertIsNone(resolve_receipt_data_for_emission(None))
        self.assertIsNone(resolve_receipt_data_for_emission({}))

    def test_recibo_pode_ser_emitido_apos_venda(self):
        receipt_data = {"receipt_code": "20260404123000", "items": [{"name": "Arroz"}]}
        self.assertTrue(can_emit_receipt(receipt_data))
        self.assertIs(resolve_receipt_data_for_emission(receipt_data), receipt_data)


class TemporaryDatabaseTestCase(BaseProjectTestCase):
    """Cada teste usa uma base SQLite isolada."""

    def setUp(self):
        super().setUp()
        unique_dir = f"loja_testes_{time.time_ns()}_{id(self)}"
        self.temp_dir = TEST_TMP_ROOT / unique_dir
        self.temp_dir.mkdir(parents=True, exist_ok=False)
        self.db_path = self.temp_dir / "inventory_test.sqlite3"
        self.db = self.quiet(Database, db_path=str(self.db_path))

    def tearDown(self):
        try:
            if getattr(self, "db", None) is not None:
                self.quiet(self.db.close)
        finally:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        super().tearDown()

    def add_sample_product(
        self,
        description="Arroz",
        category="Mercearia",
        stock=10.0,
        sale_price=15.0,
        unit_purchase_price=10.0,
        sold_stock=0.0,
        barcode=None,
        expiry_date="2030-01-01",
        is_sold_by_weight=False,
        package_quantity="1 un",
        units_per_package=None,
        allow_pack_sale=False,
    ):
        total_purchase_price = float(stock) * float(unit_purchase_price)
        product_id = self.quiet(
            self.db.add_product,
            description,
            category,
            stock,
            sold_stock,
            sale_price,
            total_purchase_price,
            unit_purchase_price,
            barcode=barcode,
            expiry_date=expiry_date,
            is_sold_by_weight=is_sold_by_weight,
            package_quantity=package_quantity,
            units_per_package=units_per_package,
            allow_pack_sale=allow_pack_sale,
        )
        self.assertIsNotNone(product_id, "Falha ao criar produto de teste")
        return product_id

    def fetch_one(self, query, params=()):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, tuple(params))
            return cur.fetchone()

    def fetch_scalar(self, query, params=()):
        row = self.fetch_one(query, params)
        return row[0] if row else None


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("Nenhuma resposta fake restante para esta chamada")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class DummyHub:
    def __init__(self, payload):
        self.payload = dict(payload or {})
        self.listeners = set()
        self.subscribe_calls = 0
        self.unsubscribe_calls = 0
        self.request_refresh_calls = 0
        self.mark_all_seen_calls = 0
        self.enabled_states = []
        self.alert_manager = types.SimpleNamespace(
            snapshot=lambda: {"history": list(self.payload.get("history", []))}
        )

    def subscribe(self, listener):
        self.subscribe_calls += 1
        self.listeners.add(listener)
        listener(dict(self.payload))

    def unsubscribe(self, listener):
        self.unsubscribe_calls += 1
        self.listeners.discard(listener)

    def request_refresh(self):
        self.request_refresh_calls += 1

    def mark_all_seen(self):
        self.mark_all_seen_calls += 1

    def set_enabled(self, enabled):
        self.enabled_states.append(bool(enabled))


class DummyContainer:
    def __init__(self):
        self.widgets = []

    def add_widget(self, widget):
        self.widgets.append(widget)


class DummyScreen:
    def __init__(self):
        self.ids = {"ai_banner_container": DummyContainer()}
        self.badge_updates = []

    def update_notification_badge(self, count):
        self.badge_updates.append(count)


@contextlib.contextmanager
def load_proactive_controller_module():
    """Importa AI.controller com dependencias de UI falsas."""

    fake_kivy = types.ModuleType("kivy")
    fake_kivy_app = types.ModuleType("kivy.app")

    class FakeApp:
        running_app = None

        @classmethod
        def get_running_app(cls):
            return cls.running_app

    fake_kivy_app.App = FakeApp

    fake_monitor_module = types.ModuleType("AI.monitor")

    class StubMonitor:
        def __init__(self, db, alert_manager, interval_seconds=30.0):
            self.db = db
            self.alert_manager = alert_manager
            self.interval_seconds = interval_seconds
            self.started = False
            self.callback = None

        def start(self, callback):
            self.started = True
            self.callback = callback

        def stop(self):
            self.started = False

        def request_refresh(self):
            return None

    fake_monitor_module.IntelligenceMonitor = StubMonitor

    fake_banner_module = types.ModuleType("ui.components.intelligent_banner")

    class StubBannerCenter:
        def __init__(self, *args, **kwargs):
            self.init_args = args
            self.init_kwargs = kwargs
            self.history_items = []
            self.show_alerts_calls = []
            self.clear_calls = []
            self.open_history_calls = []

        def set_history(self, history_items):
            self.history_items = list(history_items)

        def show_alerts(self, alerts, insights=None, auto_dismiss_seconds=7.0):
            self.show_alerts_calls.append(
                {
                    "alerts": list(alerts or []),
                    "insights": dict(insights or {}),
                    "auto_dismiss_seconds": auto_dismiss_seconds,
                }
            )

        def clear_visible(self, reset_memory=False):
            self.clear_calls.append(bool(reset_memory))

        def open_history(self, history_items, insights=None):
            self.open_history_calls.append(
                {
                    "history": list(history_items or []),
                    "insights": dict(insights or {}),
                }
            )

    fake_banner_module.IntelligentBannerCenter = StubBannerCenter

    original_controller = sys.modules.pop("AI.controller", None)

    with mock.patch.dict(
        sys.modules,
        {
            "kivy": fake_kivy,
            "kivy.app": fake_kivy_app,
            "AI.monitor": fake_monitor_module,
            "ui.components.intelligent_banner": fake_banner_module,
        },
    ):
        controller_module = importlib.import_module("AI.controller")
        try:
            yield controller_module, FakeApp
        finally:
            sys.modules.pop("AI.controller", None)
            if original_controller is not None:
                sys.modules["AI.controller"] = original_controller


class TestesBaseDeDados(TemporaryDatabaseTestCase):
    def test_conexao_sqlite_e_tabelas_essenciais(self):
        self.assertTrue(self.db_path.exists(), "A base temporaria nao foi criada")
        self.assertIsNotNone(self.db.conn)
        self.assertIsNotNone(self.db.cursor)

        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        expected = {
            "users",
            "products",
            "products_archive",
            "sales",
            "sales_returns",
            "stock_movements",
            "user_logs",
        }
        self.assertTrue(expected.issubset(tables))

    def test_crud_completo_de_produtos(self):
        product_id = self.add_sample_product(
            description="Arroz Branco",
            category="Secos",
            stock=20,
            sale_price=18.0,
            unit_purchase_price=12.0,
            barcode="789123456",
            expiry_date="2031-01-10",
            package_quantity="6 un",
            units_per_package=6,
            allow_pack_sale=True,
        )

        product = self.quiet(self.db.get_product, product_id)
        self.assertIsNotNone(product)
        self.assertEqual(product[1], "Arroz Branco")
        self.assertAlmostEqual(product[2], 20.0)
        self.assertEqual(product[11], "Secos")
        self.assertEqual(product[12], "789123456")
        self.assertEqual(product[23], 6)
        self.assertEqual(product[24], 1)

        self.quiet(
            self.db.update_product,
            product_id,
            "Arroz Integral",
            "Graos",
            25,
            2,
            21.0,
            300.0,
            14.0,
            barcode="789000111",
            expiry_date="2032-02-02",
            is_sold_by_weight=False,
            package_quantity="12 un",
            units_per_package=12,
            allow_pack_sale=True,
        )

        updated = self.quiet(self.db.get_product, product_id)
        self.assertEqual(updated[1], "Arroz Integral")
        self.assertEqual(updated[11], "Graos")
        self.assertAlmostEqual(updated[2], 25.0)
        self.assertAlmostEqual(updated[3], 2.0)
        self.assertAlmostEqual(updated[4], 21.0)
        self.assertEqual(updated[12], "789000111")
        self.assertEqual(updated[21], "12 un")
        self.assertEqual(updated[23], 12)

        deleted = self.quiet(self.db.delete_product, product_id, username="tester")
        self.assertTrue(deleted)
        self.assertIsNone(self.quiet(self.db.get_product, product_id))
        self.assertEqual(
            self.fetch_scalar(
                "SELECT deleted_by FROM products_archive WHERE id = ?",
                (product_id,),
            ),
            "tester",
        )

    def test_autenticacao_e_perguntas_de_seguranca(self):
        created = self.quiet(
            self.db.create_user,
            "gestor",
            "Senha@123",
            "manager",
            "gestor@example.com",
            "+258840000000",
        )
        self.assertTrue(created)
        self.assertTrue(self.quiet(self.db.user_exists, "gestor"))
        self.assertEqual(self.quiet(self.db.get_user_role, "gestor"), "manager")
        self.assertEqual(self.quiet(self.db.validate_user, "gestor", "Senha@123"), "manager")
        self.assertIsNone(self.quiet(self.db.validate_user, "gestor", "senha_errada"))

        updated = self.quiet(
            self.db.update_user_password,
            "gestor",
            "SenhaNova@456",
            role="manager",
        )
        self.assertTrue(updated)
        self.assertEqual(
            self.quiet(self.db.validate_user, "gestor", "SenhaNova@456"),
            "manager",
        )

        saved = self.quiet(
            self.db.set_security_questions,
            "gestor",
            [" Jose Silva ", "Sao Paulo"],
        )
        self.assertTrue(saved)

        security_ok = self.quiet(
            self.db.verify_security_answers,
            "gestor",
            ["jose silva", "sao paulo"],
        )
        self.assertEqual(security_ok, {"ok": True})

    def test_venda_e_estorno_atualizam_stock(self):
        product_id = self.add_sample_product(
            description="Leite",
            category="Laticinios",
            stock=10,
            sale_price=14.0,
            unit_purchase_price=9.0,
            barcode="111222333",
        )

        sale_id = self.quiet(
            self.db.add_sale,
            product_id,
            3,
            14.0,
            username="caixa1",
            role="manager",
        )
        self.assertIsNotNone(sale_id)

        after_sale = self.quiet(self.db.get_product, product_id)
        self.assertAlmostEqual(after_sale[2], 7.0)
        self.assertAlmostEqual(after_sale[3], 3.0)

        sale_details = self.quiet(self.db.get_sale_details, sale_id)
        self.assertIsNotNone(sale_details)
        self.assertAlmostEqual(sale_details[2], 3.0)
        self.assertAlmostEqual(sale_details[6], 0.0)
        self.assertAlmostEqual(sale_details[7], 3.0)

        refund = self.quiet(
            self.db.refund_sale_item,
            sale_id,
            1,
            reason="Cliente desistiu",
            username="caixa1",
            role="manager",
        )
        self.assertTrue(refund["ok"], refund)

        after_refund = self.quiet(self.db.get_product, product_id)
        self.assertAlmostEqual(after_refund[2], 8.0)
        self.assertAlmostEqual(after_refund[3], 2.0)

        sale_details_after = self.quiet(self.db.get_sale_details, sale_id)
        self.assertAlmostEqual(sale_details_after[6], 1.0)
        self.assertAlmostEqual(sale_details_after[7], 2.0)

    def test_relatorio_pdf_de_perdas_e_gerado(self):
        from datetime import timedelta
        from pdfs.loss_report import LossReport

        product_id = self.add_sample_product(
            description="Iogurte Natural",
            category="Laticinios",
            stock=12,
            sale_price=18.0,
            unit_purchase_price=11.0,
            barcode="LOSSPDF001",
        )

        movement_id = self.quiet(
            self.db.record_stock_movement,
            product_id,
            "DAMAGE",
            2,
            "OUT",
            reason="Frasco partido",
            created_by="gestor",
            created_role="admin",
            unit_cost=11.0,
            unit_price=18.0,
        )
        self.assertIsNotNone(movement_id)

        start_dt = datetime.now() - timedelta(days=1)
        end_dt = datetime.now() + timedelta(days=1)
        metrics = self.quiet(self.db.calculate_loss_metrics, start_dt, end_dt) or {}
        records = self.quiet(self.db.get_loss_records, start_dt, end_dt, limit=50) or []

        report = LossReport(output_dir=str(self.temp_dir / "reports"))
        pdf_path = report.generate(
            {"metrics": metrics, "records": records},
            {
                "start_date": start_dt,
                "end_date": end_dt,
                "product": "Todos os Produtos",
                "category": "Todas as Categorias",
            },
        )

        pdf_file = Path(pdf_path)
        self.assertTrue(pdf_file.exists())
        self.assertGreater(pdf_file.stat().st_size, 0)


class TestesFuncoesPrincipais(BaseProjectTestCase):
    def test_normalizacao_de_venda_por_embalagem(self):
        self.assertEqual(
            Database._normalize_pack_sale_fields(False, 6, True),
            (6, 1),
        )
        self.assertEqual(
            Database._normalize_pack_sale_fields(False, None, False),
            (None, 0),
        )
        self.assertEqual(
            Database._normalize_pack_sale_fields(True, 6, True),
            (None, 0),
        )

        for invalid_value in (None, "", 1, "abc"):
            with self.subTest(units_per_package=invalid_value):
                with self.assertRaises(ValueError):
                    Database._normalize_pack_sale_fields(False, invalid_value, True)

    def test_normalizacao_e_hash_de_respostas(self):
        self.assertEqual(normalize_answer("  Sao   Tome  "), "sao tome")
        hashed = hash_answer("Joao da Silva")
        self.assertTrue(check_answer("joao   da silva", hashed))
        self.assertTrue(check_answer("JOAO DA SILVA", memoryview(hashed)))
        self.assertFalse(check_answer("Maria", hashed))

    def test_motor_de_analise_gera_alertas_relevantes(self):
        snapshot = {
            "vendas_hoje": {"total": 55.0},
            "media_semanal": {"media_total": 120.0},
            "stock_produtos": [
                {
                    "descricao": "Leite",
                    "stock_atual": 2.0,
                    "stock_minimo": 5.0,
                    "media_diaria_qty": 2.0,
                    "qty_hoje": 4.0,
                    "last_sale_days_ago": 20,
                }
            ],
            "atividade_caixa": {
                "terminais": [
                    {
                        "terminal_id": "CX-01",
                        "vendas_hoje": 0,
                        "media_vendas_dia": 5.0,
                        "minutos_sem_venda": 120,
                        "limite_inatividade_min": 30,
                    }
                ],
                "margem_percentual_hoje": 10.0,
                "margem_percentual_historica": 20.0,
                "desconto_percentual_hoje": 18.0,
                "desconto_percentual_historico": 10.0,
                "total_vendas_hoje": 6,
            },
            "vendas_por_produto": [
                {
                    "descricao": "Leite",
                    "media_diaria_qty": 2.0,
                    "qty_hoje": 6.0,
                    "desvio_qty": 1.0,
                }
            ],
        }

        alerts = executar_analise(snapshot)
        self.assertGreaterEqual(len(alerts), 5)
        categories = {alert["categoria"] for alert in alerts}
        severities = {alert["tipo"] for alert in alerts}
        messages = " | ".join(alert["mensagem"] for alert in alerts)

        self.assertIn("vendas", categories)
        self.assertIn("stock", categories)
        self.assertIn("produtividade", categories)
        self.assertIn("critico", severities)
        self.assertIn("atencao", severities)
        self.assertIn("Leite", messages)

    @unittest.skipUnless(
        OpenFoodFactsAPI is not None,
        f"OpenFoodFacts indisponivel: {OPENFOODFACTS_IMPORT_ERROR}",
    )
    def test_parser_openfoodfacts_normaliza_campos(self):
        api = OpenFoodFactsAPI()
        product = api._parse_product(
            {
                "product_name_pt": "Arroz Premium",
                "brands_tags": ["marca-exemplo"],
                "categories_tags": ["en:foods", "en:rice-products"],
                "quantity": "1 kg",
                "price": 15.5,
                "image_url": "https://example.com/arroz.png",
            }
        )

        self.assertEqual(product["name"], "Arroz Premium")
        self.assertEqual(product["brand"], "Marca Exemplo")
        self.assertEqual(product["category"], "Rice Products")
        self.assertEqual(product["quantity"], "1 kg")
        self.assertEqual(product["price"], "15.5")
        self.assertTrue(product["sold_by_weight"])
        self.assertEqual(product["image"], "https://example.com/arroz.png")

    def test_database_client_tem_fallback_para_filtro_local(self):
        class FallbackClient(DatabaseClient):
            def __init__(self):
                super().__init__(config={"api_base_url": "http://fake.local", "timeout": 1})

            def _rpc(self, method, *args, **kwargs):
                if method == "get_products_for_sale_page":
                    return None
                if method == "get_products_for_sale":
                    return [
                        (1, "Arroz Branco", 10.0, 15.0, "111"),
                        (2, "Feijao", 7.0, 18.0, "222"),
                        (3, "Arroz Integral", 5.0, 21.0, "333"),
                    ]
                raise AssertionError(f"Metodo nao esperado neste teste: {method}")

        client = FallbackClient()
        rows = client.get_products_for_sale_page(search_text="arroz", limit=2, offset=0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "Arroz Branco")
        self.assertEqual(rows[1][1], "Arroz Integral")

    def test_database_client_cache_serializacao_e_invalidacao(self):
        session = FakeSession(
            [
                FakeResponse(status_code=200, payload={"ok": True, "result": [{"id": 1, "nome": "A"}]}),
                FakeResponse(status_code=200, payload={"ok": True, "result": 99}),
                FakeResponse(status_code=200, payload={"ok": True, "result": [{"id": 2, "nome": "B"}]}),
            ]
        )

        client = DatabaseClient(config={"api_base_url": "http://fake.local", "timeout": 1})
        client._session = session

        first = client.get_all_products()
        first[0]["id"] = 999
        second = client.get_all_products()
        self.assertEqual(len(session.calls), 1, "A segunda chamada deveria vir do cache")
        self.assertEqual(second[0]["id"], 1, "O cache deve devolver copia, nao referencia mutavel")

        add_result = client.add_product("Produto X")
        self.assertEqual(add_result, 99)
        third = client.get_all_products()

        self.assertEqual(len(session.calls), 3)
        self.assertEqual(third[0]["id"], 2)
        client.close()
        self.assertTrue(session.closed)


class TestesInterfaceSimulada(BaseProjectTestCase):
    def test_controller_apresenta_banner_automatico_so_uma_vez(self):
        payload = {
            "display_alerts": [],
            "banner_insights": {"low_stock": [{"descricao": "Leite"}]},
            "history": [{"mensagem": "Stock baixo"}],
            "unread_count": 4,
        }

        with load_proactive_controller_module() as (controller_module, FakeApp):
            FakeApp.running_app = types.SimpleNamespace(smart_monitor_enabled=True)
            hub = DummyHub(payload)
            screen = DummyScreen()

            with mock.patch.object(
                controller_module,
                "get_shared_intelligence_hub",
                return_value=hub,
            ):
                controller = controller_module.ProactiveIntelligenceController(
                    screen=screen,
                    db=object(),
                    history_title="Historico",
                    auto_present_enabled=True,
                )
                controller.start()
                banner_center = controller._banner_center

                self.assertIsNotNone(banner_center)
                self.assertEqual(len(banner_center.show_alerts_calls), 1)
                self.assertEqual(screen.badge_updates[-1], 4)

                controller.stop()
                controller.start()

                self.assertEqual(len(banner_center.show_alerts_calls), 1)
                self.assertIn(False, banner_center.clear_calls)

    def test_controller_abre_historico_e_reseta_memoria_ao_desativar(self):
        payload = {
            "display_alerts": [],
            "banner_insights": {"low_stock": [{"descricao": "Cafe"}]},
            "history": [{"mensagem": "Cafe em falta"}],
            "unread_count": 2,
        }

        with load_proactive_controller_module() as (controller_module, FakeApp):
            FakeApp.running_app = types.SimpleNamespace(smart_monitor_enabled=True)
            hub = DummyHub(payload)
            screen = DummyScreen()

            with mock.patch.object(
                controller_module,
                "get_shared_intelligence_hub",
                return_value=hub,
            ):
                controller = controller_module.ProactiveIntelligenceController(
                    screen=screen,
                    db=object(),
                    history_title="Historico",
                    auto_present_enabled=True,
                )
                controller.start()
                banner_center = controller._banner_center
                self.assertEqual(len(banner_center.show_alerts_calls), 1)

                controller.open_history()
                self.assertEqual(hub.mark_all_seen_calls, 1)
                self.assertEqual(len(banner_center.open_history_calls), 1)

                controller.set_enabled(False)
                self.assertTrue(banner_center.clear_calls[-1])

                controller.set_enabled(True)
                self.assertEqual(len(banner_center.show_alerts_calls), 2)


class TestesModeloHibrido(BaseProjectTestCase):
    def test_hibrido_usa_remoto_quando_api_esta_saudavel(self):
        class RemoteStub:
            def __init__(self):
                self.calls = 0

            def is_available(self, force=False):
                return True

            def last_error(self):
                return ""

            def get_categories(self):
                self.calls += 1
                return ["Remoto"]

        class LocalStub:
            def __init__(self):
                self.calls = 0
                self.db_path = "local.sqlite"

            def get_categories(self):
                self.calls += 1
                return ["Local"]

        remote = RemoteStub()
        local = LocalStub()
        db = HybridDatabase(config={"db_mode": "hybrid"}, remote_db=remote, local_db=local)

        self.assertEqual(db.get_categories(), ["Remoto"])
        self.assertEqual(remote.calls, 1)
        self.assertEqual(local.calls, 0)
        self.assertEqual(db.get_connection_label(), "Hibrido")

    def test_hibrido_cai_para_local_quando_api_esta_indisponivel(self):
        class RemoteStub:
            def __init__(self):
                self.calls = 0

            def is_available(self, force=False):
                return False

            def last_error(self):
                return "API offline"

            def get_categories(self):
                self.calls += 1
                return ["Remoto"]

        class LocalStub:
            def __init__(self):
                self.calls = 0
                self.db_path = "fallback.sqlite"

            def get_categories(self):
                self.calls += 1
                return ["Local"]

        remote = RemoteStub()
        local = LocalStub()
        db = HybridDatabase(config={"db_mode": "hybrid"}, remote_db=remote, local_db=local)

        self.assertEqual(db.get_categories(), ["Local"])
        self.assertEqual(remote.calls, 0)
        self.assertEqual(local.calls, 1)
        self.assertEqual(db.db_path, "fallback.sqlite")
        self.assertEqual(db.get_connection_label(), "Local")

    def test_helper_reconhece_hibrido_com_remoto_ativo(self):
        class RemoteStub:
            def is_available(self, force=False):
                return True

            def last_error(self):
                return ""

        class LocalStub:
            db_path = "local.sqlite"

        db = HybridDatabase(config={"db_mode": "hybrid"}, remote_db=RemoteStub(), local_db=LocalStub())

        self.assertTrue(uses_remote_backend(db))

    def test_helper_reconhece_hibrido_em_fallback_local(self):
        class RemoteStub:
            def is_available(self, force=False):
                return False

            def last_error(self):
                return "API offline"

        class LocalStub:
            db_path = "fallback.sqlite"

        db = HybridDatabase(config={"db_mode": "hybrid"}, remote_db=RemoteStub(), local_db=LocalStub())

        self.assertFalse(uses_remote_backend(db))

    def test_hibrido_limpa_erro_remoto_apos_fallback_local_bem_sucedido(self):
        class RemoteStub:
            def is_available(self, force=False):
                return False

            def last_error(self):
                return "API offline"

            def validate_user(self, username, password):
                return "admin"

        class LocalStub:
            db_path = "fallback.sqlite"

            def validate_user(self, username, password):
                return "admin"

        db = HybridDatabase(config={"db_mode": "hybrid"}, remote_db=RemoteStub(), local_db=LocalStub())

        self.assertEqual(db.validate_user("admin", "123"), "admin")
        self.assertEqual(db.last_error(), "")

    def test_database_client_healthcheck_entra_em_cooldown(self):
        class HealthSession:
            def __init__(self):
                self.get_calls = 0
                self.closed = False

            def get(self, url, headers=None, timeout=None):
                self.get_calls += 1
                raise RuntimeError("offline")

            def close(self):
                self.closed = True

        client = DatabaseClient(
            config={
                "api_base_url": "http://fake.local",
                "timeout": 1,
                "health_timeout": 0.05,
                "availability_cooldown": 30,
                "availability_ttl": 0,
            }
        )
        client._session = HealthSession()

        self.assertFalse(client.is_available(force=True))
        first_calls = client._session.get_calls
        self.assertEqual(first_calls, 1)
        self.assertFalse(client.is_available())
        self.assertEqual(
            client._session.get_calls,
            first_calls,
            "Durante o cooldown nao deveria repetir healthcheck",
        )


class TestesErrosEExcecoes(TemporaryDatabaseTestCase):
    def test_produto_invalido_nao_corrompe_base(self):
        result = self.quiet(
            self.db.add_product,
            "Produto Invalido",
            "Testes",
            "abc",
            0,
            20.0,
            100.0,
            10.0,
        )
        self.assertIsNone(result)
        self.assertEqual(self.quiet(self.db.get_all_products), [])

    def test_venda_invalida_e_lock_de_seguranca_sao_tratados(self):
        product_id = self.add_sample_product(
            description="Sumo",
            stock=2,
            sale_price=10.0,
            unit_purchase_price=6.0,
        )
        sale_id = self.quiet(
            self.db.add_sale,
            product_id,
            5,
            10.0,
            username="caixa1",
            role="manager",
        )
        self.assertIsNone(sale_id)

        product = self.quiet(self.db.get_product, product_id)
        self.assertAlmostEqual(product[2], 2.0)
        self.assertAlmostEqual(product[3], 0.0)

        self.assertTrue(self.quiet(self.db.create_user, "seguranca", "Senha@123", "manager"))
        self.assertTrue(
            self.quiet(
                self.db.set_security_questions,
                "seguranca",
                ["azul", "maputo", "escola 1"],
            )
        )

        first = self.quiet(
            self.db.verify_security_answers,
            "seguranca",
            ["verde", "maputo", "escola 1"],
            max_attempts=2,
            lock_minutes=1,
        )
        second = self.quiet(
            self.db.verify_security_answers,
            "seguranca",
            ["verde", "maputo", "escola 1"],
            max_attempts=2,
            lock_minutes=1,
        )

        self.assertEqual(first["reason"], "invalid")
        self.assertEqual(second["reason"], "locked")

    def test_refund_com_quantidade_invalida_retorna_erro_controlado(self):
        result = self.quiet(self.db.refund_sale_item, 999, 0)
        self.assertFalse(result["ok"])
        self.assertIn("Quantidade invalida", result["message"])

    def test_alert_manager_ignora_alertas_invalidos_sem_crash(self):
        manager = AlertManager(simultaneous_limit=3)
        payload = manager.process(
            [
                None,
                "texto solto",
                {},
                {"tipo": "info", "categoria": "stock"},
                {"tipo": "info", "categoria": "stock", "mensagem": "Reposicao sugerida"},
            ]
        )
        self.assertEqual(len(payload["display_alerts"]), 1)
        self.assertEqual(payload["display_alerts"][0]["mensagem"], "Reposicao sugerida")

    def test_database_client_retorna_none_em_erro_http(self):
        session = FakeSession(
            [
                FakeResponse(
                    status_code=500,
                    payload={"ok": False, "error": "falha interna"},
                    text="falha interna",
                )
            ]
        )
        client = DatabaseClient(config={"api_base_url": "http://fake.local", "timeout": 1})
        client._session = session

        result = client.get_product(1)
        self.assertIsNone(result)
        self.assertIsNotNone(client.last_error())
        self.assertIn("500", client.last_error())

    @unittest.skipUnless(
        OpenFoodFactsAPI is not None and requests is not None,
        f"OpenFoodFacts/requests indisponivel: {OPENFOODFACTS_IMPORT_ERROR}",
    )
    def test_openfoodfacts_timeout_retorna_none_sem_explodir(self):
        api = OpenFoodFactsAPI()
        with mock.patch(
            "api.api_openfoodfacts.requests.get",
            side_effect=requests.exceptions.Timeout,
        ):
            self.assertIsNone(api.fetch("789123"))


class TestesPerformanceBasica(TemporaryDatabaseTestCase):
    def test_insercao_em_lote_e_consulta_paginada_ficam_no_limite(self):
        start_insert = time.perf_counter()
        with suppress_project_output():
            for index in range(60):
                self.db.add_product(
                    f"Produto {index:03d}",
                    "Performance",
                    10 + index,
                    0,
                    20.0,
                    150.0,
                    12.0,
                    barcode=f"PERF{index:03d}",
                    expiry_date="2035-01-01",
                )
        insert_elapsed = time.perf_counter() - start_insert

        start_query = time.perf_counter()
        rows = self.quiet(
            self.db.get_all_products_page,
            search_text="produto",
            limit=25,
            offset=0,
        )
        query_elapsed = time.perf_counter() - start_query

        self.assertEqual(len(rows), 25)
        self.assertDurationUnder(insert_elapsed, 6.0, "insercao_60_produtos")
        self.assertDurationUnder(query_elapsed, 1.5, "consulta_paginada_25_produtos")

    def test_processamento_de_alertas_em_lote_fica_no_limite(self):
        manager = AlertManager(simultaneous_limit=10)
        alerts = [
            {
                "tipo": "info",
                "categoria": "stock",
                "mensagem": f"Alerta {index}",
            }
            for index in range(1000)
        ]

        started = time.perf_counter()
        payload = manager.process(alerts)
        elapsed = time.perf_counter() - started

        self.assertEqual(len(payload["active_alerts"]), 10)
        self.assertEqual(payload["unread_count"], 10)
        self.assertDurationUnder(elapsed, 0.8, "alert_manager_1000_alertas")


def build_suite():
    loader = unittest.TestLoader()
    return loader.loadTestsFromModule(sys.modules[__name__])


def print_summary(result, elapsed):
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = result.testsRun - failures - errors - skipped

    summary_lines = [
        "",
        "=" * 72,
        "RESUMO FINAL DOS TESTES",
        "=" * 72,
        f"Total executado : {result.testsRun}",
        f"Passaram       : {passed}",
        f"Falharam       : {failures}",
        f"Erros          : {errors}",
        f"Saltados       : {skipped}",
        f"Tempo total    : {elapsed:.3f}s",
        f"Log detalhado  : {LOG_PATH}",
        "=" * 72,
    ]
    print("\n".join(summary_lines))
    LOGGER.info(
        "SUMMARY total=%s passed=%s failures=%s errors=%s skipped=%s elapsed=%.3fs log=%s",
        result.testsRun,
        passed,
        failures,
        errors,
        skipped,
        elapsed,
        LOG_PATH,
    )


def main():
    started = time.perf_counter()
    LOGGER.info("Execucao da suite iniciada")
    suite = build_suite()
    runner = LoggedTextTestRunner(verbosity=2)
    result = runner.run(suite)
    elapsed = time.perf_counter() - started
    print_summary(result, elapsed)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
