from tests.helpers import TemporaryDatabaseTestCase
from utils.hardware.thermal_printer import format_receipt_text


class ReceiptSellerNameTests(TemporaryDatabaseTestCase):
    def test_full_name_is_stored_separately_from_username(self):
        self.assertTrue(self.db.create_user("vendedor01", "senha-segura", "manager"))
        self.assertTrue(self.db.set_user_full_name("vendedor01", "Maria Fernanda Mboa"))

        self.assertEqual(self.db.get_user_full_name("vendedor01"), "Maria Fernanda Mboa")

    def test_receipt_footer_uses_full_seller_name(self):
        receipt = format_receipt_text(
            {
                "store_name": "Loja Teste",
                "issued_at": "01/09/2026 10:00",
                "operator": "vendedor01",
                "items": [],
                "subtotal": 0,
                "vat_total": 0,
                "total": 0,
                "seller_full_name": "Maria Fernanda Mboa",
            }
        )

        self.assertIn("Atendente:", receipt)
        self.assertIn("Maria Fernanda Mboa", receipt)

    def test_receipt_includes_optional_store_contact_data(self):
        receipt = format_receipt_text(
            {
                "store_name": "Loja Teste",
                "receipt_nuit": "401234567",
                "receipt_address": "Bairro Central, Maputo",
                "receipt_street": "Av. 24 de Julho, 100",
                "receipt_phone": "+258 84 000 0000",
            }
        )

        self.assertIn("NUIT: 401234567", receipt)
        self.assertIn("Endereco: Bairro Central, Maputo", receipt)
        self.assertIn("Av./Rua: Av. 24 de Julho, 100", receipt)
        self.assertIn("Telefone: +258 84 000 0000", receipt)


    def test_receipt_has_one_reference_and_one_tax_breakdown(self):
        for width in (58, 80):
            text = format_receipt_text({
                "receipt_code": "20260914100000", "total": 116,
                "subtotal": 100, "vat_total": 16,
                "vat_summary": [{"label": "IVA 16%", "vat_amount": 16, "gross_total": 116}],
                "paid_amount": 120, "change_amount": 4,
            }, paper_width_mm=width)
            self.assertEqual(text.count("20260914100000"), 1)
            self.assertIn("VD 20260914100000", text)
            self.assertEqual(text.count("IVA"), 1)
            self.assertNotIn("Ref.", text)
            self.assertNotIn("CODIGO DO RECIBO", text)
            self.assertIn("Troco", text)
            self.assertLessEqual(max(map(len, text.splitlines())), 32 if width == 58 else 42)
