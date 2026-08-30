from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from tests.helpers import ProjectTestCase


class PurchaseSuggestionRuleTests(ProjectTestCase):
    def test_candidates_include_out_of_stock_and_demand_risk(self):
        from utils.business.purchase_suggestions import build_demand_purchase_candidates

        candidates = build_demand_purchase_candidates(
            [
                {
                    "product_ids": (1,), "name": "Sem stock", "stock": 0,
                    "avg_daily": 4, "unit_cost": 10, "sale_price": 20,
                },
                {
                    "product_ids": (2,), "name": "Sem procura", "stock": 2,
                    "avg_daily": 0, "unit_cost": 10, "sale_price": 20,
                },
                {
                    "product_ids": (3,), "name": "Validade proxima", "stock": 2,
                    "avg_daily": 1, "expiry_date": "2030-01-05",
                    "unit_cost": 10, "sale_price": 20,
                },
                {
                    "product_ids": (4,), "name": "Arroz rapido", "stock": 4,
                    "avg_daily": 2, "unit_cost": 10, "sale_price": 20,
                },
                {
                    "product_ids": (5,), "name": "Feijao", "stock": 2,
                    "avg_daily": 0.5, "unit_cost": 10, "sale_price": 20,
                },
            ],
            target_days=14,
            warning_days=7,
            today=date(2030, 1, 1),
        )

        self.assertEqual(
            [item["name"] for item in candidates],
            ["Sem stock", "Arroz rapido", "Feijao"],
        )
        self.assertEqual(candidates[0]["current_stock"], 0.0)
        self.assertEqual(candidates[0]["priority"], "Urgente")
        self.assertEqual(candidates[0]["reason"], "Stock esgotado")
        self.assertEqual(candidates[1]["needed_qty"], 24.0)
        self.assertLess(candidates[0]["coverage_days"], candidates[2]["coverage_days"])

    def test_candidate_below_historical_critical_limit_is_included(self):
        from utils.business.purchase_suggestions import build_demand_purchase_candidates

        candidates = build_demand_purchase_candidates(
            [
                {
                    "product_ids": (7,), "name": "Produto no limite", "stock": 6,
                    "sold_stock": 30, "avg_daily": 0, "unit_cost": 10,
                    "sale_price": 20,
                },
            ],
            target_days=14,
            warning_days=7,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "Stock abaixo do limite crítico")
        self.assertTrue(candidates[0]["must_restock"])
        self.assertGreater(candidates[0]["needed_qty"], 0)

    def test_preventive_three_week_window_keeps_positive_stock_fast_movers_visible(self):
        from utils.business.purchase_suggestions import build_demand_purchase_candidates

        candidates = build_demand_purchase_candidates(
            [
                {
                    "product_ids": (18,), "name": "Maionese", "stock": 12,
                    "avg_daily": 12 / 14, "unit_cost": 100, "sale_price": 220,
                    "expiry_date": "2030-08-23",
                }
            ],
            target_days=30,
            warning_days=21,
            today=date(2026, 8, 26),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["current_stock"], 12.0)
        self.assertEqual(candidates[0]["needed_qty"], 14.0)
        self.assertAlmostEqual(candidates[0]["coverage_days"], 14.0)

    def test_external_context_uses_all_product_api_caches_by_barcode(self):
        from utils.business.purchase_suggestions import load_product_api_context

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            (cache_dir / "products_offline_cache.json").write_text(
                json.dumps(
                    {
                        "123": {
                            "source": "Bazara",
                            "data": {"barcode": "123", "name": "Arroz API", "category": "Alimentos", "price": "45"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (cache_dir / "openfoodfacts_cache.json").write_text(
                json.dumps(
                    {
                        "123": {
                            "source": "Open Food Facts",
                            "data": {"barcode": "123", "name": "Arroz", "category": "Cereais"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (cache_dir / "bazara_offline_cache.json").write_text(
                json.dumps(
                    {"999": {"source": "Bazara", "data": {"barcode": "999", "name": "Outro"}}}
                ),
                encoding="utf-8",
            )

            context = load_product_api_context([{"barcode": " 123 "}], cache_dir=cache_dir)

        self.assertEqual(set(context["123"]["sources"]), {"Bazara", "Open Food Facts"})
        self.assertEqual(context["123"]["categories"], ["Alimentos", "Cereais"])
        self.assertEqual(context["123"]["market_reference_price"], 45.0)


class PurchaseSuggestionAiTests(ProjectTestCase):
    def test_ai_refines_only_eligible_items_and_keeps_api_context(self):
        from utils.ai import ai_insights

        class FakeResponse:
            text = (
                '{"suggestions":['
                '{"product_id":1,"recommended_qty":16,"priority":"alta","reason":"Saida acelerada."},'
                '{"product_id":2,"recommended_qty":0,"priority":"alta","reason":"Ignorar."},'
                '{"product_id":3,"recommended_qty":10,"priority":"urgente","reason":"Sem stock."}'
                ']}'
            )

        class FakeModels:
            def generate_content(self, **_kwargs):
                return FakeResponse()

        class FakeClient:
            models = FakeModels()

        ai_insights._PURCHASE_SUGGESTIONS_CACHE.update({"ts": 0, "signature": "", "result": None})
        candidates = [
            {
                "product_id": 1, "name": "Arroz", "current_stock": 4,
                "avg_daily": 2, "base_needed_qty": 12, "needed_qty": 12,
                "coverage_days": 2, "unit": "UN", "unit_cost": 10, "sale_price": 15,
                "priority": "Urgente", "priority_rank": 0,
                "api_context": {"sources": ["Bazara"], "market_reference_price": 18},
            },
            {
                "product_id": 2, "name": "Sem sugestao", "current_stock": 2,
                "avg_daily": 1, "base_needed_qty": 8, "needed_qty": 8,
                "coverage_days": 2, "unit": "UN", "unit_cost": 10, "sale_price": 15,
                "priority": "Urgente", "priority_rank": 0,
            },
            {
                "product_id": 3, "name": "Esgotado", "current_stock": 0,
                "avg_daily": 3, "base_needed_qty": 10, "needed_qty": 10,
                "coverage_days": 0, "unit": "UN", "unit_cost": 10, "sale_price": 15,
                "priority": "Urgente", "priority_rank": 0, "must_restock": True,
            },
        ]

        with mock.patch.object(ai_insights, "_get_ai_client", return_value=(FakeClient(), "test-model")):
            result = ai_insights.build_ai_purchase_suggestions(candidates)

        self.assertTrue(result["ai_used"])
        self.assertEqual(result["source"], "ai")
        self.assertEqual(result["api_product_count"], 1)
        self.assertEqual(len(result["items"]), 2)
        items_by_name = {item["name"]: item for item in result["items"]}
        self.assertEqual(items_by_name["Arroz"]["needed_qty"], 16.0)
        self.assertEqual(items_by_name["Arroz"]["priority"], "Alta")
        self.assertEqual(items_by_name["Arroz"]["api_context"]["sources"], ["Bazara"])
        self.assertEqual(items_by_name["Esgotado"]["current_stock"], 0)
        self.assertEqual(items_by_name["Esgotado"]["needed_qty"], 10.0)

    def test_ai_empty_response_falls_back_to_visible_demand_forecast(self):
        from utils.ai import ai_insights

        class FakeResponse:
            text = '{"suggestions":[]}'

        class FakeModels:
            def generate_content(self, **_kwargs):
                return FakeResponse()

        class FakeClient:
            models = FakeModels()

        ai_insights._PURCHASE_SUGGESTIONS_CACHE.update({"ts": 0, "signature": "", "result": None})
        candidate = {
            "product_id": 8, "name": "Acucar", "current_stock": 3,
            "avg_daily": 1, "base_needed_qty": 11, "needed_qty": 11,
            "coverage_days": 3, "unit": "UN", "unit_cost": 10, "sale_price": 15,
            "priority": "Alta", "priority_rank": 1,
        }

        with mock.patch.object(ai_insights, "_get_ai_client", return_value=(FakeClient(), "test-model")):
            result = ai_insights.build_ai_purchase_suggestions([candidate])

        self.assertFalse(result["ai_used"])
        self.assertEqual(result["source"], "demand")
        self.assertEqual(result["items"][0]["name"], "Acucar")
        self.assertIn("IA nao devolveu", result["items"][0]["analysis_reason"])
