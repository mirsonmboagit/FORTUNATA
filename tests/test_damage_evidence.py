from __future__ import annotations

from io import BytesIO
from unittest import mock

from tests.helpers import ProjectTestCase, TemporaryDatabaseTestCase


class DamageEvidenceDatabaseTests(TemporaryDatabaseTestCase):
    def _attached_evidence(self, evidence_id="evidence-ok", user="maria"):
        analysis = {
            "attached": True,
            "source": "OPERATOR",
            "summary": "Foto anexada pelo atendente.",
        }
        self.assertTrue(self.db.create_damage_evidence(
            evidence_id, f"data/evidence/losses/{evidence_id}.jpg", "a" * 64,
            "image/jpeg", 100, analysis, created_by=user,
        ))
        return evidence_id

    def test_all_loss_types_require_a_non_blank_reason(self):
        product_id = self.add_sample_product(stock=4)
        for loss_type in ("EXPIRED", "THEFT", "ADJUSTMENT"):
            movement = self.db.record_stock_movement(
                product_id, loss_type, 1, "OUT", reason="   ", created_by="maria",
            )
            self.assertIsNone(movement)
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (product_id,)), 4.0)

    def test_damage_needs_an_attached_unused_photo_and_binds_atomically(self):
        product_id = self.add_sample_product(stock=4)
        self.assertIsNone(self.db.record_stock_movement(
            product_id, "DAMAGE", 1, "OUT", reason="Frasco rachado", created_by="maria",
        ))

        evidence_id = self._attached_evidence()
        movement_id = self.db.record_stock_movement(
            product_id, "DAMAGE", 1, "OUT", reason="Frasco rachado",
            created_by="maria", evidence_id=evidence_id,
        )
        self.assertIsNotNone(movement_id)
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (product_id,)), 3.0)
        self.assertEqual(
            self.fetch_scalar("SELECT movement_id FROM damage_evidence WHERE id=?", (evidence_id,)),
            movement_id,
        )
        self.assertEqual(
            self.fetch_scalar("SELECT analysis_status FROM damage_evidence WHERE id=?", (evidence_id,)),
            "ATTACHED",
        )
        self.assertIsNone(self.db.record_stock_movement(
            product_id, "DAMAGE", 1, "OUT", reason="Outra perda",
            created_by="maria", evidence_id=evidence_id,
        ))
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id=?", (product_id,)), 3.0)

    def test_damage_evidence_cannot_cross_data_owner_and_expired_unbound_entries_are_cleaned(self):
        product_id = self.add_sample_product(stock=4)
        evidence_id = self._attached_evidence("evidence-bob", user="bob")
        self.assertIsNone(self.db.record_stock_movement(
            product_id, "DAMAGE", 1, "OUT", reason="Caixa partida",
            created_by="maria", evidence_id=evidence_id,
        ))
        self.db.cursor.execute(
            "UPDATE damage_evidence SET created_at='2000-01-01T00:00:00' WHERE id=?", (evidence_id,)
        )
        self.db.conn.commit()
        paths = self.db.cleanup_unbound_damage_evidence(hours=24)
        self.assertEqual(paths, [f"data/evidence/losses/{evidence_id}.jpg"])
        self.assertIsNone(self.db.get_damage_evidence(evidence_id))


class DamageEvidenceServiceTests(ProjectTestCase):
    def _jpeg_bytes(self):
        from PIL import Image

        image = Image.new("RGB", (120, 120), color=(180, 30, 30))
        output = BytesIO()
        image.save(output, format="JPEG")
        return output.getvalue()

    def test_prepare_image_accepts_jpeg_and_strips_to_supported_bytes(self):
        from utils.business.damage_evidence import prepare_damage_image

        prepared = prepare_damage_image(self._jpeg_bytes(), "damage.jpg")
        self.assertEqual(prepared["mime_type"], "image/jpeg")
        self.assertTrue(prepared["sha256"])
        self.assertLessEqual(prepared["file_size"], 10 * 1024 * 1024)

    def test_photo_is_stored_without_contacting_an_external_model(self):
        from utils.business import damage_evidence

        database = mock.Mock()
        database.cleanup_unbound_damage_evidence.return_value = []
        database.create_damage_evidence.return_value = True
        prepared = {
            "data": self._jpeg_bytes(), "mime_type": "image/jpeg",
            "extension": ".jpg", "sha256": "a" * 64, "file_size": 120,
        }
        with mock.patch.object(damage_evidence, "store_prepared_evidence", return_value=("photo-1", "data/evidence/losses/photo-1.jpg")):
            result = damage_evidence.create_damage_evidence_from_image(
                database, prepared, created_by="maria"
            )

        self.assertTrue(result["attached"])
        self.assertEqual(result["evidence_id"], "photo-1")
        self.assertEqual(database.create_damage_evidence.call_args.kwargs["analysis"]["source"], "OPERATOR")
