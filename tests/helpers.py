"""Shared test setup: a tiny hand-written batch whose numbers we know by heart.

Day 1 has 8 order rows: 4 good orders (O-1 to O-4), one repeated row (O-1),
one order with an unknown seller (O-5), one bad date (O-6), one bad amount (O-7).
Shipments: 4 good ones, one for an unknown order, one that "delivered before
shipped", and one line that is not JSON.
Day 2 changes the amount of O-2, adds order O-8, delivers SH-3, adds SH-7,
and renames seller S-2.
"""

import os
import tempfile
import unittest

from etl import pipeline, warehouse

SELLERS = """seller_id,seller_name,country,joined_date
S-1,Acme Goods,US,2025-01-15
S-2,Birch Trading,United Kingdom,03/20/2025
S-3,Cobalt Ltd,de,5-Feb-2025
"""

ORDERS = """order_id,order_date,seller_id,category,country,amount,updated_at
O-1,2026-01-10,S-1,electronics,US,"$1,200.50",2026-01-10 09:00:00
O-2,01/15/2026,S-1,Books,United Kingdom,20.00,2026-01-15 10:00:00
O-3,15-Feb-2026,S-2,books,DE,99.99,2026-02-15 11:00:00
O-4,2026-02-20,S-3,Toys,Germany,USD 50,2026-02-20 12:00:00
O-5,2026-02-21,S-9,Toys,US,10.00,2026-02-21 08:00:00
O-6,2026-13-45,S-1,Toys,US,10.00,2026-02-22 08:00:00
O-7,2026-02-23,S-1,Toys,US,N/A,2026-02-23 08:00:00
O-1,2026-01-10,S-1,electronics,US,"$1,200.50",2026-01-10 09:00:00
"""

SHIPMENTS = "\n".join([
    '{"shipment_id": "SH-1", "order_id": "O-1", "shipped_date": "2026-01-11", "delivered_date": "2026-01-14", "promised_date": "2026-01-16", "carrier": "dhl", "updated_at": "2026-01-14 10:00:00"}',
    '{"shipment_id": "SH-2", "order_id": "O-2", "shipped_date": "01/16/2026", "delivered_date": "01/25/2026", "promised_date": "2026-01-20", "carrier": "UPS", "updated_at": "2026-01-25 10:00:00"}',
    '{"shipment_id": "SH-3", "order_id": "O-3", "shipped_date": "2026-02-16", "delivered_date": null, "promised_date": "2026-02-22", "carrier": "DHL", "updated_at": "2026-02-16 10:00:00"}',
    '{"shipment_id": "SH-4", "order_id": "O-4", "shipped_date": "2026-02-21", "delivered_date": "2026-02-27", "promised_date": "2026-02-25", "carrier": "DHL", "updated_at": "2026-02-27 10:00:00"}',
    '{"shipment_id": "SH-5", "order_id": "O-99", "shipped_date": "2026-02-22", "delivered_date": null, "promised_date": "2026-02-27", "carrier": "DHL", "updated_at": "2026-02-28 10:00:00"}',
    '{"shipment_id": "SH-6", "order_id": "O-1", "shipped_date": "2026-01-20", "delivered_date": "2026-01-18", "promised_date": "2026-01-25", "carrier": "UPS", "updated_at": "2026-01-18 10:00:00"}',
    'this line is not json',
]) + "\n"

DAY2_SELLERS = """seller_id,seller_name,country,joined_date
S-2,Birch Trading Ltd,UK,03/20/2025
"""

DAY2_ORDERS = """order_id,order_date,seller_id,category,country,amount,updated_at
O-2,01/15/2026,S-1,Books,United Kingdom,25.00,2026-03-01 09:00:00
O-8,2026-03-02,S-2,Toys,US,"$300.00",2026-03-02 10:00:00
"""

DAY2_SHIPMENTS = "\n".join([
    '{"shipment_id": "SH-3", "order_id": "O-3", "shipped_date": "2026-02-16", "delivered_date": "2026-02-25", "promised_date": "2026-02-22", "carrier": "DHL", "updated_at": "2026-03-01 11:00:00"}',
    '{"shipment_id": "SH-7", "order_id": "O-8", "shipped_date": "2026-03-03", "delivered_date": null, "promised_date": "2026-03-08", "carrier": "UPS", "updated_at": "2026-03-03 09:00:00"}',
]) + "\n"


# Write the three source files of one batch into a folder.
def write_batch(folder, sellers, orders, shipments):
    os.makedirs(folder, exist_ok=True)
    for name, text in (("sellers.csv", sellers), ("orders.csv", orders), ("shipments.jsonl", shipments)):
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="") as handle:
            handle.write(text)


# Base class for tests that need a warehouse. Every test gets its own
# temporary folder with the tiny day 1 and day 2 batches already written.
class WarehouseTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = os.path.join(self.folder.name, "test.db")
        self.day1 = os.path.join(self.folder.name, "day1")
        self.day2 = os.path.join(self.folder.name, "day2")
        write_batch(self.day1, SELLERS, ORDERS, SHIPMENTS)
        write_batch(self.day2, DAY2_SELLERS, DAY2_ORDERS, DAY2_SHIPMENTS)

    # Open a connection to the test warehouse. It is closed after the test.
    def connect(self):
        conn = warehouse.connect(self.db)
        self.addCleanup(conn.close)
        return conn

    # Run the pipeline on a batch folder and return the run id.
    def run_batch(self, folder):
        return pipeline.run_pipeline(folder, self.db)

    # One value from one SQL query, on a fresh connection.
    def scalar(self, sql, params=()):
        return self.connect().execute(sql, params).fetchone()[0]
