import unittest

from etl import clean


# Tests for the cleaning functions alone (no files, no database).
class ParseTests(unittest.TestCase):
    def test_dates_in_every_accepted_spelling_become_iso_and_bad_dates_are_refused(self):
        for text in ["2026-03-14", "2026/03/14", "03/14/2026", "14-Mar-2026", "March 14, 2026"]:
            self.assertEqual(clean.parse_date(text), "2026-03-14", text)
        for text in ["2026-13-45", "yesterday", "14/03/2026", "2025-02-29"]:
            with self.assertRaises(ValueError, msg=text):
                clean.parse_date(text)

    def test_money_in_every_style_becomes_cents(self):
        for text in ["1200.5", "$1,200.50", "1,200.50", "USD 1200.50", "usd1200.50"]:
            self.assertEqual(clean.parse_money(text), 120050, text)
        self.assertEqual(clean.parse_money("19.99"), 1999)  # rounded, not cut

    def test_bad_and_negative_money_are_refused_with_their_own_reasons(self):
        for text in ["N/A", "abc", "nan", "1.2.3"]:
            with self.assertRaisesRegex(ValueError, "bad amount"):
                clean.parse_money(text)
        with self.assertRaisesRegex(ValueError, "negative amount"):
            clean.parse_money("-12.50")

    def test_countries_by_code_name_and_alias_become_codes_and_unknown_is_refused(self):
        for text in ["US", "us", "United States", "UNITED STATES", "usa", "U.S.A."]:
            self.assertEqual(clean.standardise_country(text), "US", text)
        self.assertEqual(clean.standardise_country("UK"), "GB")
        self.assertEqual(clean.standardise_country("germany"), "DE")
        with self.assertRaisesRegex(ValueError, "unknown country"):
            clean.standardise_country("Atlantis")

    def test_timestamps_are_written_one_way_and_categories_are_tidied(self):
        self.assertEqual(clean.parse_timestamp("2026-03-14T09:30:00"), "2026-03-14 09:30:00")
        with self.assertRaises(ValueError):
            clean.parse_timestamp("later")
        self.assertEqual(clean.clean_category("  home & KITCHEN "), "Home & Kitchen")
        self.assertEqual(clean.clean_category(""), "Unknown")
        self.assertEqual(clean.clean_category(None), "Unknown")


# Tests for cleaning whole rows.
class RowTests(unittest.TestCase):
    ORDER = {"order_id": " O-1 ", "order_date": "03/14/2026", "seller_id": "S-1", "category": "toys",
             "country": "usa", "amount": "$10.50", "updated_at": "2026-03-14 08:00:00"}
    SHIPMENT = {"shipment_id": "SH-1", "order_id": "O-1", "shipped_date": "2026-03-01",
                "delivered_date": "2026-03-05", "promised_date": "2026-03-04", "carrier": "dhl",
                "updated_at": "2026-03-05 10:00:00"}

    def test_good_order_is_cleaned(self):
        self.assertEqual(clean.clean_order(self.ORDER), {
            "order_id": "O-1", "order_date": "2026-03-14", "seller_id": "S-1", "category": "Toys",
            "country": "US", "amount_cents": 1050, "updated_at": "2026-03-14 08:00:00"})

    def test_reason_names_the_field(self):
        for change, reason in [({"order_id": ""}, "order_id: missing"),
                               ({"order_date": "soon"}, "order_date: bad date"),
                               ({"amount": "-1"}, "amount: negative amount"),
                               ({"country": "Mars"}, "country: unknown country"),
                               ({"updated_at": None}, "updated_at: missing")]:
            with self.assertRaisesRegex(ValueError, reason):
                clean.clean_order({**self.ORDER, **change})

    def test_late_on_time_and_in_transit_shipments(self):
        ship = clean.clean_shipment(self.SHIPMENT)
        self.assertEqual((ship["is_late"], ship["days_in_transit"], ship["carrier"]), (1, 4, "DHL"))
        on_time = clean.clean_shipment({**self.SHIPMENT, "delivered_date": "2026-03-04"})
        self.assertEqual(on_time["is_late"], 0)
        moving = clean.clean_shipment({**self.SHIPMENT, "delivered_date": None})
        self.assertEqual((moving["is_late"], moving["days_in_transit"]), (None, None))

    def test_shipment_problems_are_refused(self):
        with self.assertRaisesRegex(ValueError, "delivered before shipped"):
            clean.clean_shipment({**self.SHIPMENT, "delivered_date": "2026-02-01"})
        with self.assertRaisesRegex(ValueError, "invalid json"):
            clean.clean_shipment({"_raw": "{broken"})


# Tests for clean_rows: rejects and duplicates.
class CleanRowsTests(unittest.TestCase):
    def order(self, order_id, amount="1.00", stamp="2026-03-14 08:00:00"):
        return {**RowTests.ORDER, "order_id": order_id, "amount": amount, "updated_at": stamp}

    def test_bad_rows_are_logged_with_row_number_and_reason(self):
        rows = [(1, self.order("O-1")), (2, self.order("O-2", amount="oops")), (3, self.order(""))]
        kept, rejects = clean.clean_rows(rows, clean.clean_order, "order_id")
        self.assertEqual([row["order_id"] for row in kept], ["O-1"])
        self.assertEqual([(n, why) for n, why, _ in rejects],
                         [(2, "amount: bad amount"), (3, "order_id: missing")])

    def test_duplicate_keeps_the_newest_copy(self):
        rows = [(1, self.order("O-1", "1.00", "2026-03-14 09:00:00")),
                (2, self.order("O-1", "2.00", "2026-03-14 08:00:00"))]
        kept, rejects = clean.clean_rows(rows, clean.clean_order, "order_id")
        self.assertEqual([row["amount_cents"] for row in kept], [100])
        self.assertEqual([(n, why) for n, why, _ in rejects], [(2, "duplicate in batch")])

    def test_on_a_tie_the_later_row_wins(self):
        rows = [(1, self.order("O-1", "1.00")), (2, self.order("O-1", "2.00"))]
        kept, rejects = clean.clean_rows(rows, clean.clean_order, "order_id")
        self.assertEqual([row["amount_cents"] for row in kept], [200])
        self.assertEqual(rejects[0][0], 1)


if __name__ == "__main__":
    unittest.main()
