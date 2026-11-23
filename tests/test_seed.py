import csv
import os
import re
import tempfile
import unittest

from etl import seed


# Read a whole file as text.
def read(folder, name):
    with open(os.path.join(folder, name), encoding="utf-8") as handle:
        return handle.read()


# Tests for the fake data generator. A small count keeps them quick.
class SeedTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    # Make a batch in a subfolder and return its path.
    def make(self, name, day=1, count=400, seed_number=42):
        path = os.path.join(self.folder.name, name)
        (seed.make_day1 if day == 1 else seed.make_day2)(path, count, seed_number)
        return path

    def test_same_seed_gives_identical_files(self):
        first, second = self.make("a"), self.make("b")
        for name in ["sellers.csv", "orders.csv", "shipments.jsonl"]:
            self.assertEqual(read(first, name), read(second, name), name)

    def test_a_different_seed_gives_different_files(self):
        self.assertNotEqual(read(self.make("a"), "orders.csv"), read(self.make("b", seed_number=7), "orders.csv"))

    def test_day_one_has_about_the_asked_number_of_orders_plus_repeats(self):
        folder = self.make("a")
        with open(os.path.join(folder, "orders.csv"), newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        ids = {row["order_id"] for row in rows}
        self.assertTrue(400 <= len(rows) <= 440, len(rows))
        self.assertLess(len(ids), len(rows))  # repeated rows are in there on purpose

    def test_the_files_are_messy_on_purpose(self):
        folder = self.make("a", count=2000)
        orders, shipments = read(folder, "orders.csv"), read(folder, "shipments.jsonl")
        self.assertRegex(orders, r"\d\d/\d\d/\d{4}")   # a slash date
        self.assertIn("$", orders)                      # a money string
        self.assertIn("N/A", orders)                    # a bad amount
        self.assertRegex(orders, r"United States|UNITED STATES")  # a country name, not a code
        self.assertTrue(any(not line.rstrip().endswith("}") for line in shipments.splitlines()))  # cut JSON

    def test_day_two_has_new_and_changed_orders_and_is_repeatable(self):
        self.make("day1")
        first, second = self.make("a", day=2), self.make("b", day=2)
        self.assertEqual(read(first, "orders.csv"), read(second, "orders.csv"))
        numbers = [int(n) for n in re.findall(r"^O-(\d{6})", read(first, "orders.csv"), re.M)]
        self.assertGreaterEqual(sum(1 for n in numbers if n > 400), 15)   # new orders (20 made)
        self.assertGreaterEqual(sum(1 for n in numbers if n <= 400), 5)   # changed old orders (8 made)
        self.assertGreaterEqual(len(read(first, "sellers.csv").splitlines()), 9)  # header + 3 new + 5 renamed


if __name__ == "__main__":
    unittest.main()
