import os
import unittest

from etl import warehouse
from tests.helpers import WarehouseTestCase

STAGE_SQL = ("SELECT stage, source, rows_in, rows_out, rows_rejected, rows_skipped, status"
             " FROM run_log WHERE run_id = ? ORDER BY log_id")


# Tests for the whole pipeline: run log, incremental loads and idempotency.
class PipelineTests(WarehouseTestCase):
    def stages(self, run_id):
        return self.connect().execute(STAGE_SQL, (run_id,)).fetchall()

    def fingerprint(self):
        return warehouse.fingerprint(self.connect())

    def test_run_log_has_one_line_per_stage_and_source(self):
        run_id = self.run_batch(self.day1)
        names = [(row[0], row[1]) for row in self.stages(run_id)]
        self.assertEqual(names, [("extract", "sellers"), ("transform", "sellers"), ("load", "sellers"),
                                 ("extract", "orders"), ("transform", "orders"), ("load", "orders"),
                                 ("extract", "shipments"), ("transform", "shipments"), ("load", "shipments"),
                                 ("quality", "all")])
        self.assertTrue(all(row[6] == "ok" for row in self.stages(run_id)))

    def test_day_one_counts_for_orders_and_shipments(self):
        stages = {(row[0], row[1]): row[2:6] for row in self.stages(self.run_batch(self.day1))}
        # (rows_in, rows_out, rows_rejected, rows_skipped)
        self.assertEqual(stages[("extract", "orders")], (8, 8, 0, 0))
        self.assertEqual(stages[("transform", "orders")], (8, 5, 3, 0))
        self.assertEqual(stages[("load", "orders")], (5, 4, 1, 0))
        self.assertEqual(stages[("transform", "shipments")], (7, 5, 2, 0))
        self.assertEqual(stages[("load", "shipments")], (5, 4, 1, 0))

    def test_every_reject_has_a_reason_and_the_raw_row(self):
        run_id = self.run_batch(self.day1)
        rows = self.connect().execute(
            "SELECT source, source_row, reason FROM rejects WHERE run_id = ? ORDER BY source, source_row", (run_id,)).fetchall()
        self.assertEqual(len(rows), 7)
        self.assertIn(("orders", 6, "order_date: bad date"), rows)
        self.assertIn(("orders", 7, "amount: bad amount"), rows)
        self.assertIn(("orders", 1, "duplicate in batch"), rows)
        self.assertIn(("shipments", 7, "invalid json"), rows)
        self.assertIn("2026-13-45", self.scalar("SELECT raw FROM rejects WHERE source_row = 6 AND source = 'orders'"))

    def test_rerunning_the_same_batch_changes_nothing(self):
        self.assertEqual(self.run_batch(self.day1), 1)
        first = self.fingerprint()
        run_id = self.run_batch(self.day1)
        self.assertEqual(run_id, 2)
        self.assertEqual(self.fingerprint(), first)
        stages = {(row[0], row[1]): row[2:6] for row in self.stages(run_id)}
        self.assertEqual(stages[("load", "orders")][1], 0)
        self.assertEqual(stages[("load", "shipments")][1], 0)

    def test_rerun_is_still_safe_when_the_watermark_is_lost(self):
        self.run_batch(self.day1)
        first = self.fingerprint()
        conn = self.connect()
        conn.execute("DELETE FROM etl_state")
        conn.commit()
        self.run_batch(self.day1)
        self.assertEqual(self.fingerprint(), first)

    def test_day_two_adds_new_rows_and_changes_old_ones(self):
        self.run_batch(self.day1)
        first = self.fingerprint()
        stages = {(row[0], row[1]): row[2:6] for row in self.stages(self.run_batch(self.day2))}
        self.assertEqual(stages[("load", "orders")], (2, 2, 0, 0))
        self.assertEqual(stages[("load", "shipments")], (2, 2, 0, 0))
        counts, digest = self.fingerprint()
        self.assertNotEqual(digest, first[1])
        self.assertEqual((counts["fact_orders"], counts["fact_shipments"]), (5, 5))
        self.assertEqual(self.scalar("SELECT is_late FROM fact_shipments WHERE shipment_id = 'SH-3'"), 1)

    def test_day_two_twice_is_the_same_as_day_two_once(self):
        self.run_batch(self.day1)
        self.run_batch(self.day2)
        first = self.fingerprint()
        self.run_batch(self.day2)
        self.assertEqual(self.fingerprint(), first)

    def test_a_missing_file_is_logged_as_failed(self):
        empty = os.path.join(self.folder.name, "empty")
        os.makedirs(empty)
        with self.assertRaises(FileNotFoundError):
            self.run_batch(empty)
        self.assertEqual(self.stages(1), [("extract", "sellers", 0, 0, 0, 0, "failed")])


if __name__ == "__main__":
    unittest.main()
