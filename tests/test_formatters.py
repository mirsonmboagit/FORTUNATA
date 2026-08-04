from __future__ import annotations

import unittest

from utils.core.formatters import (
    format_compact_number,
    format_date_dmy,
    format_display_value,
    format_money,
    format_quantity,
    safe_float,
)


class FormatterTests(unittest.TestCase):
    def test_safe_float_returns_default_for_invalid_values(self):
        self.assertEqual(safe_float("bad", 3.5), 3.5)
        self.assertEqual(safe_float("12.5"), 12.5)

    def test_format_money_supports_suffix_and_prefix(self):
        self.assertEqual(format_money(1234.5, "MZN"), "1 234.50 MZN")
        self.assertEqual(format_money(1234.5, "MZN", "prefix"), "MZN 1 234.50")

    def test_format_quantity_handles_units(self):
        self.assertEqual(format_quantity(2.4), "2")
        self.assertEqual(format_quantity(2.4, is_weight=True), "2.40 kg")

    def test_compact_and_display_values(self):
        self.assertEqual(format_compact_number(2.0), "2")
        self.assertEqual(format_compact_number(2.5), "2.5")
        self.assertEqual(format_display_value(None), "--")
        self.assertEqual(format_display_value(2.5), "2.50")

    def test_format_date_dmy_accepts_iso_values(self):
        self.assertEqual(format_date_dmy("2026-07-25"), "25/07/2026")
        self.assertEqual(format_date_dmy("texto"), "texto")


if __name__ == "__main__":
    unittest.main()
