import unittest
from unittest import mock

from etl import quality
from tests.helpers import WarehouseTestCase


# Tests for the data quality checks. Each test breaks the warehouse on
# purpose and checks that the right check notices.
class QualityTests(WarehouseTestCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.run_batch(self.day1)
        self.conn = self.connect()

    # Names of the checks that found a problem right now.
    def failed(self):
        return [name for name, count in quality.run_checks(self.conn, self.run_id) if count != 0]

    def test_a_good_load_passes_every_check(self):
        results = quality.run_checks(self.conn, self.run_id)
        self.assertEqual(len(results), 3 + 8 + 3 + 2)
        self.assertEqual(self.failed(), [])

    def test_reconcile_fails_when_a_reject_goes_missing(self):
        self.conn.execute("DELETE FROM rejects WHERE rowid = (SELECT MIN(rowid) FROM rejects WHERE source = 'orders')")
        self.assertEqual(self.failed(), ["reconcile: orders rows read = written + skipped + rejected"])

    def test_reconcile_fails_when_rows_vanish_from_the_load_count(self):
        self.conn.execute("UPDATE run_log SET rows_out = rows_out - 1 WHERE stage = 'load' AND source = 'shipments'")
        self.assertEqual(self.failed(), ["reconcile: shipments rows read = written + skipped + rejected"])

    def test_orphan_key_is_found(self):
        self.conn.execute("DELETE FROM dim_country WHERE country_code = 'DE'")
        failed = self.failed()
        self.assertIn("orphans: fact_orders.country_key has no row in dim_country", failed)
        self.assertIn("orphans: dim_seller.country_key has no row in dim_country", failed)

    def test_duplicate_business_key_is_found(self):
        self.conn.execute("DROP INDEX ux_order")  # the unique index would stop the duplicate
        self.conn.execute(
            "INSERT INTO fact_orders (order_id, order_date_key, seller_key, country_key, category_key,"
            " amount_cents, updated_at) SELECT order_id, order_date_key, seller_key, country_key,"
            " category_key, amount_cents, updated_at FROM fact_orders WHERE order_id = 'O-1'")
        self.assertEqual(self.failed(), ["duplicates: fact_orders.order_id appears twice"])

    def test_negative_amount_is_found(self):
        self.conn.execute("UPDATE fact_orders SET amount_cents = -5 WHERE order_id = 'O-1'")
        self.assertEqual(self.failed(), ["amounts: negative order amount"])

    def test_raise_if_failed_names_every_failed_check(self):
        with self.assertRaisesRegex(quality.QualityError, r"a \(2\); b \(1\)"):
            quality.raise_if_failed([("a", 2), ("ok", 0), ("b", 1)])
        quality.raise_if_failed([("ok", 0)])

    def test_the_pipeline_fails_loudly_and_logs_the_failure(self):
        bad = [("always bad", "SELECT 1")]
        with mock.patch.object(quality, "VALUE_CHECKS", bad):
            with self.assertRaisesRegex(quality.QualityError, "always bad"):
                self.run_batch(self.day1)
        status = self.scalar("SELECT status FROM run_log WHERE run_id = 2 AND stage = 'quality'")
        self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
