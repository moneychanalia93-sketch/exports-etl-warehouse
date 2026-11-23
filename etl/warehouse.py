"""The warehouse: the star schema, and how dimension rows get their keys.

Star schema = fact tables in the middle (one row per event, with numbers)
and dimension tables around them (who, what, where, when).

Surrogate key = a number the warehouse makes up for each dimension row
(1, 2, 3...). Facts store that number, not the text. A business key is the
id that comes from the source ("O-000123").
"""

import hashlib
import sqlite3
from datetime import date

from etl.clean import COUNTRIES

# REFERENCES shows which table a key points to. SQLite does not check it
# unless asked, and many warehouses treat it as a hint only, so quality.py
# looks for orphans itself. The UNIQUE indexes are enforced: the upserts in
# load.py depend on them.
SCHEMA = """
CREATE TABLE IF NOT EXISTS dim_date (date_key INTEGER PRIMARY KEY, full_date TEXT NOT NULL,
    year INTEGER NOT NULL, month INTEGER NOT NULL, year_month TEXT NOT NULL, weekday TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dim_country (country_key INTEGER PRIMARY KEY,
    country_code TEXT NOT NULL, country_name TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_country ON dim_country(country_code);
CREATE TABLE IF NOT EXISTS dim_category (category_key INTEGER PRIMARY KEY, category_name TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_category ON dim_category(category_name);
CREATE TABLE IF NOT EXISTS dim_seller (seller_key INTEGER PRIMARY KEY, seller_id TEXT NOT NULL,
    seller_name TEXT NOT NULL, country_key INTEGER NOT NULL REFERENCES dim_country,
    joined_date TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_seller ON dim_seller(seller_id);

CREATE TABLE IF NOT EXISTS fact_orders (order_key INTEGER PRIMARY KEY, order_id TEXT NOT NULL,
    order_date_key INTEGER NOT NULL REFERENCES dim_date,
    seller_key INTEGER NOT NULL REFERENCES dim_seller,
    country_key INTEGER NOT NULL REFERENCES dim_country,
    category_key INTEGER NOT NULL REFERENCES dim_category,
    amount_cents INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_order ON fact_orders(order_id);
CREATE TABLE IF NOT EXISTS fact_shipments (shipment_key INTEGER PRIMARY KEY,
    shipment_id TEXT NOT NULL, order_id TEXT NOT NULL,
    seller_key INTEGER NOT NULL REFERENCES dim_seller,
    country_key INTEGER NOT NULL REFERENCES dim_country,
    ship_date_key INTEGER NOT NULL REFERENCES dim_date,
    delivered_date_key INTEGER REFERENCES dim_date,
    promised_date_key INTEGER NOT NULL REFERENCES dim_date,
    carrier TEXT NOT NULL, days_in_transit INTEGER, is_late INTEGER, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_shipment ON fact_shipments(shipment_id);

CREATE TABLE IF NOT EXISTS etl_state (source TEXT PRIMARY KEY, watermark TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_log (log_id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
    stage TEXT NOT NULL, source TEXT NOT NULL, rows_in INTEGER, rows_out INTEGER,
    rows_rejected INTEGER, rows_skipped INTEGER, seconds REAL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rejects (reject_id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
    source TEXT NOT NULL, source_row INTEGER, reason TEXT NOT NULL, raw TEXT);
"""

# The tables that hold the business data. run_log, rejects and etl_state are
# bookkeeping, so they are left out of the fingerprint.
DATA_TABLES = ["dim_date", "dim_country", "dim_category", "dim_seller",
               "fact_orders", "fact_shipments"]


# Open the warehouse file (it is created if missing) and make sure the tables exist.
# Safe to run every time.
def connect(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


# Get the key of a date row, adding the row if it is new. Date keys are the
# date as a number (2026-03-14 becomes 20260314), so they are easy to read.
# Returns None for None, because a shipment may have no delivery date yet.
def date_key(conn, iso_date):
    if iso_date is None:
        return None
    day = date.fromisoformat(iso_date)
    key = int(iso_date.replace("-", ""))
    conn.execute(
        "INSERT OR IGNORE INTO dim_date VALUES (?, ?, ?, ?, ?, ?)",
        (key, iso_date, day.year, day.month, iso_date[:7], day.strftime("%A")),
    )
    return key


# Get the key of a country row, adding the row if it is new.
# INSERT OR IGNORE does nothing when the code exists, so keys never change.
def country_key(conn, code):
    conn.execute(
        "INSERT OR IGNORE INTO dim_country (country_code, country_name) VALUES (?, ?)",
        (code, COUNTRIES[code]),
    )
    return conn.execute(
        "SELECT country_key FROM dim_country WHERE country_code = ?", (code,)
    ).fetchone()[0]


# Get the key of a category row, adding the row if it is new.
def category_key(conn, name):
    conn.execute("INSERT OR IGNORE INTO dim_category (category_name) VALUES (?)", (name,))
    return conn.execute(
        "SELECT category_key FROM dim_category WHERE category_name = ?", (name,)
    ).fetchone()[0]


# Count the rows of every data table and make one fingerprint (a SHA-256 hash)
# of all their contents. Same data gives the same fingerprint, so two warehouses
# can be compared with one short string. Used to prove a rerun changes nothing.
# The table names come from the fixed list above, never from a user.
def fingerprint(conn):
    digest = hashlib.sha256()
    counts = {}
    for table in DATA_TABLES:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        counts[table] = len(rows)
        digest.update(repr(rows).encode())
    return counts, digest.hexdigest()
