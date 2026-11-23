import contextlib
import io
import os
import re
import unittest
from unittest import mock

from etl import cli, quality
from tests.helpers import WarehouseTestCase


# Tests for the command line. main() is called directly, and its output is captured.
class CliTests(WarehouseTestCase):
    # Run a command. Returns (exit_code, printed_text, error_text).
    def command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_format_table_aligns_columns_and_shows_none_as_a_dash(self):
        text = cli.format_table(["name", "n"], [("a", 1234), ("bbb", None)])
        self.assertEqual(text.splitlines(), ["name      n", "----  -----", "a     1,234", "bbb       -"])

    def test_seed_command_writes_three_files(self):
        data = os.path.join(self.folder.name, "data")
        code, out, _ = self.command("seed", "--data", data, "--orders", "100")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(os.path.join(data, "day1"))), ["orders.csv", "sellers.csv", "shipments.jsonl"])
        self.assertIn("orders:", out)

    def test_run_command_prints_stages_rejects_and_a_fingerprint(self):
        code, out, _ = self.command("run", "--batch", self.day1, "--db", self.db)
        self.assertEqual(code, 0)
        for text in ["load", "Rejected rows, by reason", "unknown seller", "Warehouse fingerprint:", "Quality checks: all passed"]:
            self.assertIn(text, out)

    def test_running_twice_prints_the_same_fingerprint(self):
        prints = [re.search(r"fingerprint: (\w+)", self.command("run", "--batch", self.day1, "--db", self.db)[1]).group(1)
                  for _ in range(2)]
        self.assertEqual(prints[0], prints[1])

    def test_run_exits_with_1_and_a_message_when_a_check_fails(self):
        with mock.patch.object(quality, "VALUE_CHECKS", [("always bad", "SELECT 1")]):
            code, _, err = self.command("run", "--batch", self.day1, "--db", self.db)
        self.assertEqual(code, 1)
        self.assertIn("FAILED", err)

    def test_missing_files_and_missing_warehouse_exit_with_2(self):
        self.assertEqual(self.command("run", "--batch", os.path.join(self.folder.name, "nope"), "--db", self.db)[0], 2)
        self.assertEqual(self.command("queries", "--db", os.path.join(self.folder.name, "none.db"))[0], 2)

    def test_queries_command_prints_a_table_per_query(self):
        self.command("run", "--batch", self.day1, "--db", self.db)
        code, out, _ = self.command("queries", "--db", self.db)
        self.assertEqual(code, 0)
        self.assertIn("1. Revenue by destination country", out)
        self.assertIn("8. Orders that have a shipment record, by month", out)
        self.assertIn("United States", out)


if __name__ == "__main__":
    unittest.main()
