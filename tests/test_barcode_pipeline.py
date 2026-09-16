import time
import unittest
from contextlib import nullcontext
from threading import Lock

from kivy.clock import Clock

from manager.services.barcode_pipeline import BarcodeScanPipeline
from tests.helpers import TemporaryDatabaseTestCase


class _FakeScannerDatabase:
    def __init__(self):
        self.calls = []
        self._lock = Lock()
        self.concurrent = 0
        self.max_concurrent = 0

    def background_connection(self):
        return nullcontext(self)

    def get_sale_lots_by_barcode_fast(self, barcode):
        with self._lock:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            # Torna visivel qualquer processamento paralelo acidental.
            time.sleep(0.0005)
            with self._lock:
                self.calls.append(barcode)
            return [(1, barcode, 10, 5, barcode, 0, None, "ATIVO", None, 0, "STANDARD")]
        finally:
            with self._lock:
                self.concurrent -= 1


class BarcodeScanPipelineTests(unittest.TestCase):
    def test_keeps_one_thousand_scans_in_order_including_duplicates(self):
        db = _FakeScannerDatabase()
        delivered = []
        pipeline = BarcodeScanPipeline(db, delivered.extend, max_pending=1200, max_results_per_frame=64)
        expected = [f"789{i % 31:04d}" for i in range(1000)]
        for barcode in expected:
            self.assertTrue(pipeline.submit(barcode, "physical"))

        deadline = time.monotonic() + 8
        while len(delivered) < len(expected) and time.monotonic() < deadline:
            Clock.tick()
            time.sleep(0.002)
        pipeline.stop()

        self.assertEqual([result.barcode for result in delivered], expected)
        self.assertEqual(db.calls, expected)
        self.assertEqual(db.max_concurrent, 1)


class BarcodeDatabaseLookupTests(TemporaryDatabaseTestCase):
    def test_normalized_barcode_lookup_returns_only_sale_lots(self):
        self.add_sample_product(barcode=" 789-TEST ", stock=4, expiry_date="2030-01-01")
        self.add_sample_product(barcode="789-test", stock=6, expiry_date="2030-02-01")
        self.add_sample_product(barcode="789-test", stock=0, expiry_date="2030-03-01")

        rows = self.db.get_sale_lots_by_barcode_fast("789-test")

        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row[2] for row in rows), 10)

    def test_public_barcode_lookup_keeps_the_same_sale_result(self):
        product_id = self.add_sample_product(barcode="789-public", stock=4)

        row = self.quiet(self.db.get_product_by_barcode, " 789-PUBLIC ")

        self.assertIsNotNone(row)
        self.assertEqual(row[0], product_id)
