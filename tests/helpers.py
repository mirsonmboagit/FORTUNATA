from __future__ import annotations

import contextlib
import shutil
import sqlite3
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@contextlib.contextmanager
def suppress_project_output():
    with contextlib.redirect_stdout(StringIO()), contextlib.redirect_stderr(StringIO()):
        yield


class ProjectTestCase(unittest.TestCase):
    def quiet(self, func, *args, **kwargs):
        with suppress_project_output():
            return func(*args, **kwargs)


class TemporaryDatabaseTestCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        from database.database import Database

        self._tmp_dir = Path(tempfile.mkdtemp(prefix="loja_unit_"))
        self.db_path = self._tmp_dir / "inventory_test.sqlite3"
        self.db = self.quiet(Database, db_path=str(self.db_path))

    def tearDown(self):
        try:
            if getattr(self, "db", None) is not None:
                self.quiet(self.db.close)
        finally:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        super().tearDown()

    def add_sample_product(
        self,
        *,
        description="Arroz",
        category="Mercearia",
        stock=10.0,
        sold_stock=0.0,
        sale_price=116.0,
        unit_purchase_price=80.0,
        barcode=None,
        expiry_date="2030-01-01",
        is_sold_by_weight=False,
        package_quantity="1 un",
        units_per_package=None,
        allow_pack_sale=False,
        vat_rule_code="STANDARD",
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
            vat_rule_code=vat_rule_code,
        )
        self.assertIsNotNone(product_id)
        return product_id

    def fetch_one(self, query, params=()):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, tuple(params))
            return cur.fetchone()

    def fetch_scalar(self, query, params=()):
        row = self.fetch_one(query, params)
        return row[0] if row else None

