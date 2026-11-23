import os
import unittest

from etl import extract
from tests.helpers import WarehouseTestCase


# Tests for reading the source files. Nothing is cleaned or dropped here.
class ExtractTests(WarehouseTestCase):
    def test_csv_rows_are_numbered_from_one_and_stay_raw(self):
        rows = extract.read_csv(os.path.join(self.day1, "orders.csv"))
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[0][1]["amount"], "$1,200.50")
        self.assertEqual(rows[5][1]["order_date"], "2026-13-45")

    def test_jsonl_keeps_a_broken_line_as_raw_text(self):
        rows = extract.read_jsonl(os.path.join(self.day1, "shipments.jsonl"))
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0][1]["shipment_id"], "SH-1")
        self.assertEqual(rows[6], (7, {"_raw": "this line is not json"}))

    def test_jsonl_skips_blank_lines_and_read_source_picks_by_file_ending(self):
        path = os.path.join(self.folder.name, "blank.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"a": 1}\n\n[1, 2]\n')
        self.assertEqual(extract.read_source(path), [(1, {"a": 1}), (2, {"_raw": "[1, 2]"})])
        self.assertEqual(len(extract.read_source(os.path.join(self.day1, "sellers.csv"))), 3)


if __name__ == "__main__":
    unittest.main()
