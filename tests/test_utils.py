from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from tests.helpers import ProjectTestCase


class VatTests(ProjectTestCase):
    def test_normalize_reference_date_accepts_common_formats(self):
        from utils.vat import normalize_reference_date

        self.assertEqual(normalize_reference_date("2026-06-26"), date(2026, 6, 26))
        self.assertEqual(normalize_reference_date("26/06/2026"), date(2026, 6, 26))
        self.assertEqual(normalize_reference_date(datetime(2026, 6, 26, 9, 30)), date(2026, 6, 26))

    def test_resolve_vat_rule_by_historical_date(self):
        from utils.vat import resolve_vat_rule

        old_rule = resolve_vat_rule("standard", "2022-12-31")
        current_rule = resolve_vat_rule("STANDARD", "2026-01-01")

        self.assertEqual(old_rule["rate_percent"], 17.0)
        self.assertEqual(current_rule["rate_percent"], 16.0)

    def test_compute_inclusive_and_exclusive_vat_breakdowns(self):
        from utils.vat import compute_vat_breakdown

        inclusive = compute_vat_breakdown(116, quantity=2, rule_code="STANDARD", reference_date="2026-01-01")
        exclusive_rules = [
            {
                "code": "CUSTOM",
                "label": "Custom",
                "short_label": "IVA 10%",
                "rate_percent": 10,
                "taxable_ratio": 1,
                "effective_from": "2020-01-01",
                "effective_to": None,
                "legal_reference": "Test",
                "price_mode": "EXCLUSIVE",
            }
        ]
        exclusive = compute_vat_breakdown(100, quantity=3, rule_code="CUSTOM", rules=exclusive_rules)

        self.assertEqual(inclusive["gross_total"], 232.0)
        self.assertEqual(inclusive["net_total"], 200.0)
        self.assertEqual(inclusive["vat_amount"], 32.0)
        self.assertEqual(exclusive["net_total"], 300.0)
        self.assertEqual(exclusive["vat_amount"], 30.0)
        self.assertEqual(exclusive["gross_total"], 330.0)

    def test_unknown_vat_choice_falls_back_to_standard(self):
        from utils.vat import describe_vat_choice, resolve_vat_rule

        description = describe_vat_choice("DOES_NOT_EXIST", reference_date="2026-01-01")
        rule = resolve_vat_rule("DOES_NOT_EXIST", reference_date="2026-01-01")

        self.assertEqual(rule["code"], "STANDARD")
        self.assertIn("Taxa geral", description)


class ReceiptSecurityAndTextTests(ProjectTestCase):
    def test_receipt_policy_only_allows_completed_sales(self):
        from utils.receipt_policy import can_emit_receipt, resolve_receipt_data_for_emission

        payload = {"receipt_code": "R-1"}

        self.assertFalse(can_emit_receipt(None))
        self.assertIsNone(resolve_receipt_data_for_emission({}))
        self.assertTrue(can_emit_receipt(payload))
        self.assertIs(resolve_receipt_data_for_emission(payload), payload)

    def test_security_answers_normalize_and_validate_hashes(self):
        from utils.security_questions import check_answer, hash_answer, normalize_answer

        hashed = hash_answer(" Joao   Mucavel ")

        self.assertEqual(normalize_answer(" Joao   Mucavel "), "joao mucavel")
        self.assertTrue(check_answer("joao mucavel", hashed))
        self.assertFalse(check_answer("outra resposta", hashed))

    def test_i18n_normalizes_languages_and_dynamic_text(self):
        from utils.i18n import language_short, normalize_language, translate_text

        self.assertEqual(normalize_language("pt-MZ"), "pt")
        self.assertEqual(normalize_language("zz", fallback="en"), "en")
        self.assertEqual(language_short("english"), "PT")
        self.assertEqual(translate_text("3 produtos", "en"), "3 products")
        self.assertEqual(translate_text("2 alerta(s) pendente(s)", "fr"), "2 alerte(s) en attente")

    def test_system_identity_and_theme_helpers(self):
        from utils.system_identity import DEFAULT_SYSTEM_NAME, MAX_SYSTEM_NAME_LENGTH, normalize_system_name
        from utils.theme import get_theme_tokens

        long_name = "  Loja   Central   " + ("X" * 80)

        self.assertEqual(normalize_system_name(""), DEFAULT_SYSTEM_NAME)
        self.assertLessEqual(len(normalize_system_name(long_name)), MAX_SYSTEM_NAME_LENGTH)
        self.assertNotEqual(get_theme_tokens("Light")["surface"], get_theme_tokens("Dark")["surface"])

    def test_optional_html_stripping_works_without_network(self):
        from api.optional_deps import strip_html_text

        self.assertEqual(strip_html_text("<b>Arroz</b><br>Premium"), "Arroz Premium")

    def test_thermal_receipt_formatter_contains_totals(self):
        from utils.thermal_printer import format_receipt_text

        text = format_receipt_text(
            {
                "store_name": "Loja Teste",
                "receipt_code": "ABC123",
                "issued_at": "2026-06-26 10:00",
                "operator": "Maria",
                "items": [
                    {
                        "name": "Arroz Premium",
                        "qty_text": "2 un",
                        "unit_price": 100,
                        "line_total": 200,
                        "vat_tag": "IVA 16%",
                    }
                ],
                "subtotal": 172.41,
                "vat_total": 27.59,
                "paid_amount": 250,
                "change_amount": 50,
                "total": 200,
            },
            paper_width_mm=58,
        )

        self.assertIn("Loja Teste", text)
        self.assertIn("ABC123", text)
        self.assertIn("TOTAL", text)
        self.assertIn("200.00 MZN", text)


class ConfigAndPathTests(ProjectTestCase):
    def test_device_settings_are_clamped_and_normalized(self):
        from utils.device_config import normalize_device_settings

        settings = normalize_device_settings(
            {
                "physical_scanner_enabled": "nao",
                "physical_scanner_min_length": 100,
                "receipt_auto_print": "sim",
                "receipt_printer_name": "  POS  ",
                "receipt_paper_width_mm": 59,
            }
        )

        self.assertFalse(settings["physical_scanner_enabled"])
        self.assertEqual(settings["physical_scanner_min_length"], 32)
        self.assertTrue(settings["receipt_auto_print"])
        self.assertEqual(settings["receipt_printer_name"], "POS")
        self.assertEqual(settings["receipt_paper_width_mm"], 80)

    def test_app_config_normalizers_clamp_values(self):
        from utils.app_config import _normalize_api_config, _normalize_app_config

        api = _normalize_api_config(
            {
                "host": "0.0.0.0",
                "port": "999999",
                "runner": "bad",
                "threads": "999",
                "connection_limit": "-5",
            }
        )
        app = _normalize_app_config(
            {
                "timeout": "0",
                "health_timeout": "99",
                "availability_ttl": "-1",
                "http_pool_size": "999",
                "db_mode": "bad",
                "api_base_url": "",
            },
            api,
        )

        self.assertEqual(api["port"], 65535)
        self.assertEqual(api["runner"], "waitress")
        self.assertEqual(api["threads"], 64)
        self.assertEqual(api["connection_limit"], 1)
        self.assertEqual(app["timeout"], 1.0)
        self.assertEqual(app["health_timeout"], 10.0)
        self.assertEqual(app["availability_ttl"], 0.2)
        self.assertEqual(app["http_pool_size"], 128)
        self.assertEqual(app["db_mode"], "hybrid")
        self.assertEqual(app["api_base_url"], "http://127.0.0.1:65535")

    def test_runtime_api_key_is_generated_only_for_insecure_config(self):
        from utils import app_config

        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            with mock.patch.object(app_config, "ENV_FILE", env_file), mock.patch.dict(os.environ, {"API_KEY": ""}, clear=False):
                app_config._ensure_runtime_api_key({"api_key": ""})
                self.assertTrue(os.environ.get("API_KEY"))

            self.assertTrue(env_file.exists())
            self.assertIn("API_KEY=", env_file.read_text(encoding="utf-8"))

    def test_env_loader_fallback_reads_export_and_respects_override(self):
        from utils.env_loader import _load_dotenv_fallback

        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("export TOKEN='abc'\nEXISTING=new\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {"EXISTING": "old"}, clear=False):
                self.assertTrue(_load_dotenv_fallback(env_file, override=False))
                self.assertEqual(os.environ["TOKEN"], "abc")
                self.assertEqual(os.environ["EXISTING"], "old")
                self.assertTrue(_load_dotenv_fallback(env_file, override=True))
                self.assertEqual(os.environ["EXISTING"], "new")

    def test_path_helpers_resolve_and_create_parent_dir(self):
        from utils.paths import ensure_parent_dir, resolve_path

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            resolved = resolve_path("nested/file.txt", base)
            ensured = ensure_parent_dir(resolved)

            self.assertEqual(resolved, base / "nested" / "file.txt")
            self.assertTrue(ensured.parent.exists())


if __name__ == "__main__":
    unittest.main()
