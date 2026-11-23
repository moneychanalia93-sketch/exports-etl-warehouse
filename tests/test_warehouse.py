import unittest

from etl import warehouse
from tests.helpers import WarehouseTestCase


# Tests for the schema, the dimension keys and the fingerprint.
class WarehouseTests(WarehouseTestCase):
    def test_all_tables_are_created(self):
        names = {row[0] for row in self.connect().execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"dim_date", "dim_country", "dim_category", "dim_seller", "fact_orders",
                         "fact_shipments", "etl_state", "run_log", "rejects"} <= names)

    def test_date_key_is_the_date_as_a_number_and_none_stays_none(self):
        conn = self.connect()
        self.assertEqual(warehouse.date_key(conn, "2026-03-14"), 20260314)
        self.assertIsNone(warehouse.date_key(conn, None))
        row = conn.execute("SELECT full_date, year, month, year_month, weekday FROM dim_date").fetchone()
        self.assertEqual(row, ("2026-03-14", 2026, 3, "2026-03", "Saturday"))

    def test_dimension_keys_are_stable(self):
        conn = self.connect()
        us, de = warehouse.country_key(conn, "US"), warehouse.country_key(conn, "DE")
        self.assertNotEqual(us, de)
        self.assertEqual(warehouse.country_key(conn, "US"), us)
        toys = warehouse.category_key(conn, "Toys")
        self.assertEqual(warehouse.category_key(conn, "Toys"), toys)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM dim_country").fetchone()[0], 2)

    def test_dimension_keys_survive_a_reload(self):
        self.run_batch(self.day1)
        before = self.connect().execute("SELECT * FROM dim_country ORDER BY 1").fetchall()
        self.run_batch(self.day2)
        after = self.connect().execute("SELECT * FROM dim_country ORDER BY 1").fetchall()
        self.assertEqual(before, after)

    def test_fingerprint_is_the_same_for_the_same_data_and_changes_with_data(self):
        self.run_batch(self.day1)
        conn = self.connect()
        counts, first = warehouse.fingerprint(conn)
        self.assertEqual(warehouse.fingerprint(conn), (counts, first))
        conn.execute("UPDATE fact_orders SET amount_cents = amount_cents + 1 WHERE order_id = 'O-1'")
        self.assertNotEqual(warehouse.fingerprint(conn)[1], first)


if __name__ == "__main__":
    unittest.main()
