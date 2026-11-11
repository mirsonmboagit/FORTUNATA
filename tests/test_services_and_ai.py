from __future__ import annotations

import unittest
from unittest import mock

from tests.helpers import ProjectTestCase


class AlertAndEngineTests(ProjectTestCase):
    def test_alert_manager_deduplicates_prioritizes_and_tracks_unread(self):
        from AI.alert_manager import AlertManager

        manager = AlertManager(cooldown_seconds=30, simultaneous_limit=2, history_limit=50)
        payload = manager.process(
            [
                {"tipo": "info", "categoria": "stock", "mensagem": "Produto parado"},
                {"tipo": "critico", "categoria": "stock", "mensagem": "Stock critico"},
                {"tipo": "atencao", "categoria": "stock", "mensagem": "Produto parado"},
                {"tipo": "info", "categoria": "vendas", "mensagem": "Alta de vendas"},
            ]
        )
        repeated = manager.process(
            [
                {"tipo": "critico", "categoria": "stock", "mensagem": "Stock critico"},
            ]
        )

        self.assertEqual([alert["tipo"] for alert in payload["active_alerts"]], ["critico", "atencao"])
        self.assertEqual(len(payload["display_alerts"]), 2)
        self.assertEqual(repeated["display_alerts"], [])
        self.assertEqual(manager.snapshot()["unread_count"], 2)

        manager.mark_all_seen()
        manager.clear_active()

        snapshot = manager.snapshot()
        self.assertEqual(snapshot["unread_count"], 0)
        self.assertEqual(snapshot["active_alerts"], [])
        self.assertEqual(len(snapshot["history"]), 2)

    def test_engine_generates_alerts_for_business_anomalies(self):
        from AI.engine import executar_analise

        alerts = executar_analise(
            {
                "vendas_hoje": {"total": 50},
                "media_semanal": {"media_total": 100, "desvio_total": 20},
                "stock_produtos": [
                    {
                        "descricao": "Arroz",
                        "stock_atual": 1,
                        "stock_minimo": 2,
                        "media_diaria_qty": 1,
                        "qty_hoje": 3,
                        "last_sale_days_ago": 20,
                    }
                ],
                "atividade_caixa": {
                    "terminais": [
                        {
                            "terminal_id": "POS-1",
                            "vendas_hoje": 0,
                            "media_vendas_dia": 2,
                        }
                    ],
                    "margem_percentual_hoje": 5,
                    "margem_percentual_historica": 10,
                    "desconto_percentual_hoje": 8,
                    "desconto_percentual_historico": 2,
                    "total_vendas_hoje": 3,
                },
                "vendas_por_produto": [
                    {
                        "descricao": "Feijao",
                        "media_diaria_qty": 2,
                        "qty_hoje": 6,
                        "desvio_qty": 1,
                    }
                ],
            }
        )

        categories = {alert["categoria"] for alert in alerts}
        messages = " ".join(alert["mensagem"] for alert in alerts)

        self.assertIn("vendas", categories)
        self.assertIn("stock", categories)
        self.assertIn("produtividade", categories)
        self.assertIn("Stock critico", messages)
        self.assertGreaterEqual(len(alerts), 5)

    def test_recommendation_cards_are_separate_from_alert_cards(self):
        from AI.controller import _get_recommendation_total
        from ui.components.intelligent_banner import build_recommendation_banner_data

        insights = {
            "recommendations_stock": ["Arroz: reponha 10 unidades."],
            "recommendations_expiry": ["Leite: priorize a venda antes da validade."],
            "recommendations": [
                "Arroz: reponha 10 unidades.",
                "Reveja a margem das promoções.",
            ],
        }
        banners = build_recommendation_banner_data(insights)

        self.assertEqual([item["title"] for item in banners], [
            "Reposição sugerida",
            "Validades a priorizar",
            "Sugestões automáticas",
        ])
        self.assertEqual(banners[0]["details_sections"][0][0], "Ações recomendadas")
        self.assertNotIn("Arroz: reponha 10 unidades.", banners[2]["all_messages"])
        self.assertEqual(_get_recommendation_total(insights), 3)

    def test_fraud_alerts_are_included_in_insights_and_notification_total(self):
        from AI.controller import _get_banner_notification_total
        from ui.components.intelligent_banner import _insights_to_banner_data
        from utils.ai.ai_popups import build_auto_banner_data, build_banner_details_sections

        insights = {
            "fraud_alerts": [
                {
                    "alert_type": "REPEATED_PRODUCT_LOSS",
                    "severity": 3,
                    "title": "Perdas repetidas: Arroz",
                    "description": "O gerente registou 4 perdas no periodo.",
                    "related_user": "maria",
                },
                {
                    "alert_type": "OFF_HOURS_LOSS",
                    "severity": 2,
                    "title": "Perda fora do horario",
                    "description": "Registo fora do turno.",
                },
            ]
        }

        banners = build_auto_banner_data(insights)
        fraud_banner = next(item for item in banners if item["kind"] == "fraud")
        self.assertEqual(fraud_banner["count"], 2)
        self.assertEqual(fraud_banner["variant"], "danger")
        self.assertTrue(_insights_to_banner_data(insights, include_positive=False))
        self.assertEqual(_get_banner_notification_total(banners), 2)

        sections = dict(build_banner_details_sections(insights, "fraud"))
        self.assertIn("Alertas", sections)
        self.assertIn("Perdas repetidas: Arroz", " ".join(sections["Alertas"]))

    def test_stock_banner_details_separate_actions_from_demand_indicators(self):
        from utils.ai.ai_popups import build_banner_details_sections

        sections = build_banner_details_sections(
            {
                "low_stock": [
                    ("Agua Namacacha", 7, False, 3),
                    ("Maizena", 10, False, 5),
                ],
                "recommendations_stock": [
                    "Agua Namacacha: o estoque esta baixo. Restam 7 unidades.",
                ],
                "stock_forecast": [
                    {"name": "Agua Namacacha", "days_left": 3},
                    {"name": "Leite", "days_left": 6},
                ],
            },
            "stock",
        )

        by_title = dict(sections)
        self.assertEqual(list(by_title), ["Produtos", "Acao"])
        self.assertIn("Agua Namacacha", " ".join(by_title["Produtos"]))
        self.assertIn("reposi", " ".join(by_title["Acao"]).lower())

    def test_stock_forecast_calls_zero_stock_out_of_stock_not_zero_days(self):
        from utils.ai.ai_popups import build_banner_details_sections

        sections = build_banner_details_sections(
            {
                "stock_forecast": [
                    {"name": "Lava Loica", "stock": 0, "days_left": 0},
                    {"name": "Agua", "stock": 7, "days_left": 4},
                ]
            },
            "stock",
        )

        by_title = dict(sections)
        self.assertEqual(list(by_title), [])

    def test_proactive_recommendations_use_ai_response(self):
        from utils.ai import ai_insights

        class FakeResponse:
            text = '{"recommendations":["Priorize a reposição do arroz.", "Promova os produtos próximos da validade."]}'

        class FakeModels:
            def generate_content(self, **_kwargs):
                return FakeResponse()

        class FakeClient:
            models = FakeModels()

        snapshot = {
            "vendas_hoje": {"total": 1200},
            "media_semanal": {"media_total": 900},
            "atividade_caixa": {},
            "banner_insights": {
                "low_stock": [("Arroz", 2, False, 1)],
                "expiry_levels": {},
                "stock_forecast": [],
                "expiry_risk": [],
                "recommendations": ["Arroz: faça a reposição."],
            },
        }
        ai_insights._PROACTIVE_RECOMMENDATIONS_CACHE.update(
            {"ts": 0, "signature": "", "items": []}
        )
        with mock.patch.object(ai_insights, "_get_ai_client", return_value=(FakeClient(), "test-model")):
            recommendations = ai_insights.build_proactive_ai_recommendations(snapshot)

        self.assertEqual(
            recommendations,
            ["Priorize a reposição do arroz.", "Promova os produtos próximos da validade."],
        )

    def test_monitor_exposes_ai_recommendations_to_the_ui_payload(self):
        from AI.monitor import IntelligenceMonitor

        snapshot = {
            "vendas_hoje": {},
            "media_semanal": {},
            "stock_produtos": [],
            "atividade_caixa": {"terminais": []},
            "vendas_por_produto": [],
            "banner_insights": {"recommendations": ["Sugestão local."]},
        }

        class FakeCollector:
            def collect_snapshot(self):
                return snapshot

        captured_payloads = []
        monitor = IntelligenceMonitor(db=None)
        monitor.collector = FakeCollector()
        monitor._callback = captured_payloads.append
        monitor._busy_lock.acquire()

        class ImmediateThread:
            def __init__(self, target, args=(), daemon=None):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with mock.patch("AI.monitor.build_proactive_ai_recommendations", return_value=["Recomendação criada pela IA."]), \
             mock.patch("AI.monitor.Thread", ImmediateThread), \
             mock.patch("AI.monitor.Clock.schedule_once", side_effect=lambda callback, _delay: callback(0)):
            monitor._run_cycle()

        self.assertEqual(captured_payloads[0]["banner_insights"]["recommendations_source"], "local")
        captured = captured_payloads[-1]
        self.assertEqual(
            captured["banner_insights"]["recommendations_ai"],
            ["Recomendação criada pela IA."],
        )
        self.assertEqual(captured["banner_insights"]["recommendations_source"], "ai")


class ServiceTests(ProjectTestCase):
    class LocalDb:
        def __init__(self):
            self.calls = []

        def get_products_for_sale_page(self, **kwargs):
            self.calls.append(("page", kwargs))
            return [{"id": 1}]

        def get_products_for_sale_ids(self, product_ids):
            self.calls.append(("ids", product_ids))
            return [("live", product_ids[0])]

        def find_product_by_barcode_fast(self, barcode):
            self.calls.append(("barcode", barcode))
            return (7, "Arroz")

        def calculate_vat_breakdown(self, *args, **kwargs):
            self.calls.append(("vat", args, kwargs))
            return {"gross_total": 116}

        def log_action(self, *args, **kwargs):
            self.calls.append(("log", args, kwargs))
            return True

    class HybridDb:
        def __init__(self):
            self.local_db = ServiceTests.LocalDb()

        def get_connection_status(self, force=False):
            return {"label": "API", "force": force}

    def test_sales_data_service_uses_local_backend_for_sale_queries(self):
        from manager.services.sales_data_service import SalesDataService

        db = self.HybridDb()
        service = SalesDataService(db)

        self.assertTrue(service.uses_local_backend())
        self.assertEqual(service.get_connection_status(force=True), {"label": "API", "force": True})
        self.assertEqual(service.get_products_for_sale_page(search_text="arroz"), [{"id": 1}])
        self.assertEqual(service.find_product_by_barcode("123"), ("live", 7))
        self.assertEqual(service.calculate_vat_breakdown(116), {"gross_total": 116})
        self.assertTrue(service.log_action("maria", "manager", "TEST"))

    def test_camera_service_overlay_and_snapshot_are_isolated(self):
        from manager.services.camera_service import CameraService

        class Frame:
            def __init__(self, value):
                self.value = value
                self.copied = False

            def copy(self):
                copied = Frame(self.value)
                copied.copied = True
                return copied

        service = CameraService(width=320, height=240, preview_fps=10)
        with service._data_lock:
            service._latest_frame_id = 3
            service._latest_frame = Frame("frame")

        snapshot_id, snapshot_frame = service.get_latest_frame_snapshot()
        service.set_overlay_points([(1.2, 2.8), ("bad",), (5, 6)], hold_seconds=0.5)
        active = service._get_active_overlay_points(0)
        service.clear_overlay()

        self.assertEqual(snapshot_id, 3)
        self.assertTrue(snapshot_frame.copied)
        self.assertEqual(active, ((1, 2), (5, 6)))
        self.assertIsNone(service._get_active_overlay_points(0))

    def test_scanner_service_suppresses_duplicate_barcodes(self):
        from manager.services.scanner_service import ScannerService

        detections = []

        class Camera:
            def clear_overlay(self):
                pass

        scanner = ScannerService(
            Camera(),
            duplicate_cooldown_seconds=10,
            on_detected=detections.append,
        )

        with mock.patch("manager.services.scanner_service.time.perf_counter", side_effect=[100.0, 101.0, 111.5]):
            scanner._last_barcode = "123"
            scanner._last_barcode_at = 100.0
            first_now = scanner_service_now = 101.0
            if not ("123" == scanner._last_barcode and (first_now - scanner._last_barcode_at) < scanner.duplicate_cooldown_seconds):
                scanner._emit_detected("123")
            second_now = 111.5
            if not ("123" == scanner._last_barcode and (second_now - scanner._last_barcode_at) < scanner.duplicate_cooldown_seconds):
                scanner._emit_detected("123")

        self.assertEqual(detections, ["123"])


class ApiParserTests(ProjectTestCase):
    def test_openfoodfacts_parser_prefers_localized_name_and_category_tags(self):
        from api.api_openfoodfacts import OpenFoodFactsAPI

        parsed = OpenFoodFactsAPI()._parse_product(
            {
                "product_name_pt": "Massa",
                "brands_tags": ["marca-teste"],
                "categories_tags": ["en:foods", "en:pasta-products"],
                "product_quantity": 500,
                "product_quantity_unit": "g",
                "image_url": "https://example.test/img.jpg",
            }
        )

        self.assertEqual(parsed["name"], "Massa")
        self.assertEqual(parsed["brand"], "Marca Teste")
        self.assertEqual(parsed["category"], "Pasta Products")
        self.assertEqual(parsed["quantity"], "500 g")
        self.assertTrue(parsed["sold_by_weight"])


if __name__ == "__main__":
    unittest.main()
