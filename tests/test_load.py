import os
import unittest

from etl import clean, extract, load
from tests.helpers import WarehouseTestCase


# Tests for the load stage: facts, upserts, rejects and the watermark.
class LoadTests(WarehouseTestCase):
    def test_day_one_fills_the_facts_and_dimensions(self):
        self.run_batch(self.day1)
        count = lambda table: self.scalar(f"SELECT COUNT(*) FROM {table}")
        self.assertEqual(
            [count(t) for t in ["fact_orders", "fact_shipments", "dim_seller", "dim_country", "dim_category", "dim_date"]],
            [4, 4, 3, 3, 3, 14])

    def test_money_is_stored_as_cents_and_countries_as_one_row_each(self):
        self.run_batch(self.day1)
        self.assertEqual(self.scalar("SELECT amount_cents FROM fact_orders WHERE order_id = 'O-1'"), 120050)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM fact_orders o JOIN dim_country c USING (country_key) WHERE c.country_code = 'DE'"), 2)

    def test_unknown_seller_and_unknown_order_are_rejected_and_logged(self):
        self.run_batch(self.day1)
        row = self.connect().execute("SELECT source, source_row, reason FROM rejects WHERE reason = 'unknown seller'").fetchone()
        self.assertEqual(row, ("orders", 5, "unknown seller"))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM fact_orders WHERE order_id = 'O-5'"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM rejects WHERE reason = 'unknown order'"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM fact_shipments WHERE shipment_id = 'SH-5'"), 0)

    def test_shipment_takes_seller_and_country_from_its_order(self):
        self.run_batch(self.day1)
        same = self.scalar(
            "SELECT COUNT(*) FROM fact_shipments s JOIN fact_orders o USING (order_id)"
            " WHERE s.seller_key = o.seller_key AND s.country_key = o.country_key")
        self.assertEqual(same, 4)

    def test_upsert_changes_rows_but_keeps_their_surrogate_keys(self):
        self.run_batch(self.day1)
        key_before = self.scalar("SELECT order_key FROM fact_orders WHERE order_id = 'O-2'")
        seller_before = self.scalar("SELECT seller_key FROM dim_seller WHERE seller_id = 'S-2'")
        self.run_batch(self.day2)
        row = self.connect().execute("SELECT seller_key, seller_name FROM dim_seller WHERE seller_id = 'S-2'").fetchone()
        self.assertEqual(row, (seller_before, "Birch Trading Ltd"))
        self.assertEqual(self.scalar("SELECT order_key FROM fact_orders WHERE order_id = 'O-2'"), key_before)
        self.assertEqual(self.scalar("SELECT amount_cents FROM fact_orders WHERE order_id = 'O-2'"), 2500)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM fact_orders"), 5)

    def test_an_older_copy_never_overwrites_a_newer_row(self):
        self.run_batch(self.day1)
        self.run_batch(self.day2)
        conn = self.connect()
        conn.execute("DELETE FROM etl_state")  # forget the watermark: everything is looked at again
        old_rows, _ = clean.clean_rows(extract.read_csv(os.path.join(self.day1, "orders.csv")), clean.clean_order, "order_id")
        written, _, _ = load.load_source(conn, "orders", old_rows)
        self.assertEqual(written, 0)
        self.assertEqual(conn.execute("SELECT amount_cents FROM fact_orders WHERE order_id = 'O-2'").fetchone()[0], 2500)

    def test_watermark_is_saved_per_source_and_only_moves_forward(self):
        self.run_batch(self.day1)
        self.assertEqual(load.get_watermark(self.connect(), "orders"), "2026-02-21 08:00:00")
        self.assertEqual(load.get_watermark(self.connect(), "shipments"), "2026-02-28 10:00:00")
        self.assertEqual(load.get_watermark(self.connect(), "nothing"), "")
        self.run_batch(self.day2)
        self.assertEqual(load.get_watermark(self.connect(), "orders"), "2026-03-02 10:00:00")


if __name__ == "__main__":
    unittest.main()
