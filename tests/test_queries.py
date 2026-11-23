import unittest

from etl import queries
from tests.helpers import WarehouseTestCase


# Tests for queries.sql, run on the tiny day 1 data where every answer is known.
class QueryTests(WarehouseTestCase):
    # Run all queries and return {number: (columns, rows)}, e.g. results["3"].
    def results(self):
        found = queries.run_queries(self.connect())
        return {title.split(".")[0]: (columns, rows) for title, columns, rows in found}

    def test_the_file_holds_eight_numbered_queries_and_every_one_runs(self):
        found = queries.load_queries()
        self.assertEqual([title.split(".")[0] for title, _ in found], [str(n) for n in range(1, 9)])
        self.run_batch(self.day1)
        results = self.results()
        self.assertEqual(len(results), 8)
        for columns, rows in results.values():
            self.assertGreaterEqual(len(columns), 3)
            self.assertGreater(len(rows), 0)

    def test_revenue_by_country(self):
        self.run_batch(self.day1)
        columns, rows = self.results()["1"]
        self.assertEqual(columns, ["country", "orders", "revenue_usd", "avg_order_usd"])
        self.assertEqual([row[:3] for row in rows],
                         [("United States", 1, 1200.5), ("Germany", 2, 149.99), ("United Kingdom", 1, 20.0)])

    def test_top_seller_and_month_over_month_change(self):
        self.run_batch(self.day1)
        results = self.results()
        self.assertEqual(results["3"][1][0], ("Acme Goods", "US", 2, 1220.5))
        self.assertEqual(results["5"][1], [("2026-01", 1220.5, None), ("2026-02", 149.99, -87.7)])

    def test_late_rate_counts_only_delivered_shipments(self):
        self.run_batch(self.day1)
        results = self.results()
        self.assertEqual(results["6"][1], [("UPS", 1, 1, 100.0), ("DHL", 2, 1, 50.0)])
        by_country = {row[0]: row[1:] for row in results["7"][1]}
        self.assertEqual(by_country, {"United States": (1, 0.0, 3.0), "United Kingdom": (1, 100.0, 9.0),
                                      "Germany": (1, 100.0, 6.0)})

    def test_day_two_shows_up_in_the_monthly_pivot(self):
        self.run_batch(self.day1)
        self.run_batch(self.day2)
        columns, rows = self.results()["2"]
        self.assertEqual(columns, ["month", "US", "GB", "DE", "IN", "other"])
        self.assertEqual(rows, [("2026-01", 1200.5, 25.0, 0.0, 0.0, 0.0),
                                ("2026-02", 0.0, 0.0, 149.99, 0.0, 0.0),
                                ("2026-03", 300.0, 0.0, 0.0, 0.0, 0.0)])


if __name__ == "__main__":
    unittest.main()
