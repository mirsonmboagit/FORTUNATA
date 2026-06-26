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

