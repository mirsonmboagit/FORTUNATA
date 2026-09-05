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

        self.assertIn("Foste ajudado por:", receipt)
        self.assertIn("Maria Fernanda Mboa", receipt)
