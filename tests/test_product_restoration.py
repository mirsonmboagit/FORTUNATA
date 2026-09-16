from tests.helpers import TemporaryDatabaseTestCase


class ProductRestorationTests(TemporaryDatabaseTestCase):
    def test_restore_removed_product_preserves_fields_and_records_history(self):
        product = self.add_sample_product(barcode="restore-1", stock=7)
        before = self.db.cursor.execute("SELECT * FROM products WHERE id = ?", (product,)).fetchone()
        self.assertTrue(self.db.delete_product(product))
        self.assertEqual(self.db.get_archived_products()[0]["archive_source"], "archive")
        result = self.db.restore_archived_product(product, "archive", "admin")
        self.assertTrue(result["ok"], result)
        after = self.db.cursor.execute("SELECT * FROM products WHERE id = ?", (product,)).fetchone()
        self.assertEqual(before[:14], after[:14])
        self.assertFalse(self.db.get_archived_products())
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM product_status_history WHERE product_id = ?", (product,)), 1)
        self.assertFalse(self.db.restore_archived_product(product, "archive")["ok"])

    def test_restore_product_with_sales_keeps_sales_and_stock(self):
        product = self.add_sample_product(stock=4)
        sale = self.db.add_sale(product, 1, 116, username="maria", role="manager")
        self.assertIsNotNone(sale)
        self.assertTrue(self.db.delete_product(product))
        self.assertEqual(self.db.get_archived_products()[0]["archive_source"], "catalog")
        self.assertTrue(self.db.restore_archived_product(product, "catalog")["ok"])
        self.assertEqual(self.fetch_scalar("SELECT existing_stock FROM products WHERE id = ?", (product,)), 3)
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM sales WHERE product_id = ?", (product,)), 1)

    def test_expired_product_stays_expired(self):
        product = self.add_sample_product(expiry_date="2020-01-01")
        self.assertTrue(self.db.delete_product(product))
        result = self.db.restore_archived_product(product, "archive")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.fetch_scalar("SELECT status FROM products WHERE id = ?", (product,)), "EXPIRADO")

    def test_conflicting_id_preserves_both_records(self):
        product = self.add_sample_product(description="Antigo")
        self.assertTrue(self.db.delete_product(product))
        replacement = self.add_sample_product(description="Novo")
        self.db.cursor.execute("UPDATE products SET id = ? WHERE id = ?", (product, replacement))
        self.db.conn.commit()
        self.assertFalse(self.db.restore_archived_product(product, "archive")["ok"])
        self.assertEqual(self.fetch_scalar("SELECT description FROM products_archive WHERE id = ?", (product,)), "Antigo")
        self.assertEqual(self.fetch_scalar("SELECT description FROM products WHERE id = ?", (product,)), "Novo")

    def test_duplicate_batch_is_not_restored(self):
        product = self.add_sample_product(barcode="same-batch")
        self.assertTrue(self.db.delete_product(product))
        self.add_sample_product(barcode="same-batch")
        result = self.db.restore_archived_product(product, "archive")
        self.assertFalse(result["ok"])
        self.assertIn("mesmo codigo", result["message"])
        self.assertEqual(len(self.db.get_archived_products()), 1)

    def test_insert_conflict_rolls_back_archive_removal(self):
        product = self.add_sample_product()
        self.assertTrue(self.db.delete_product(product))
        replacement = self.add_sample_product(description="Outro")
        sku = self.fetch_scalar("SELECT sku FROM products WHERE id = ?", (replacement,))
        self.db.cursor.execute("UPDATE products_archive SET sku = ? WHERE id = ?", (sku, product))
        self.db.conn.commit()
        self.assertFalse(self.db.restore_archived_product(product, "archive")["ok"])
        self.assertEqual(len(self.db.get_archived_products()), 1)
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM product_status_history WHERE product_id = ?", (product,)), 0)

    def test_owner_scope_and_manager_restriction(self):
        product = self.add_sample_product()
        self.db.cursor.execute("UPDATE products SET owner_username = 'alice' WHERE id = ?", (product,))
        self.db.conn.commit()
        self.assertTrue(self.db.delete_product(product))
        self.db.current_user = "bob"
        self.db.current_data_owner = "bob"
        self.db.current_role = "admin"
        self.assertEqual(self.db.get_archived_products(), [])
        self.assertFalse(self.db.restore_archived_product(product, "archive")["ok"])
        self.db.current_data_owner = "alice"
        self.db.current_role = "manager"
        self.assertFalse(self.db.restore_archived_product(product, "archive")["ok"])
        self.db.current_role = "admin"
        self.assertTrue(self.db.restore_archived_product(product, "archive")["ok"])
