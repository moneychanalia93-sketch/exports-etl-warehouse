"""Stage 3, load: write clean rows into the star schema.

Upsert = "update the row if it exists, insert it if it does not". Because of
the upsert, loading the same rows twice leaves the warehouse the same. That is
idempotent. We use ON CONFLICT ... DO UPDATE, not INSERT OR REPLACE: REPLACE
deletes the old row and makes a new one with a new surrogate key.

Watermark = the newest updated_at we have loaded for a source. The next run
only looks at rows at or after it. The "or" matters: rows that share the
last timestamp are looked at again, and the upsert ignores them harmlessly.
"""

from etl.warehouse import category_key, country_key, date_key

UPSERT_SELLER = """
INSERT INTO dim_seller (seller_id, seller_name, country_key, joined_date)
VALUES (?, ?, ?, ?)
ON CONFLICT(seller_id) DO UPDATE SET seller_name = excluded.seller_name,
    country_key = excluded.country_key, joined_date = excluded.joined_date
"""

# The WHERE keeps an older copy of a row from overwriting a newer one.
UPSERT_ORDER = """
INSERT INTO fact_orders (order_id, order_date_key, seller_key, country_key,
    category_key, amount_cents, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(order_id) DO UPDATE SET order_date_key = excluded.order_date_key,
    seller_key = excluded.seller_key, country_key = excluded.country_key,
    category_key = excluded.category_key, amount_cents = excluded.amount_cents,
    updated_at = excluded.updated_at
WHERE excluded.updated_at > fact_orders.updated_at
"""

UPSERT_SHIPMENT = """
INSERT INTO fact_shipments (shipment_id, order_id, seller_key, country_key,
    ship_date_key, delivered_date_key, promised_date_key, carrier,
    days_in_transit, is_late, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(shipment_id) DO UPDATE SET order_id = excluded.order_id,
    seller_key = excluded.seller_key, country_key = excluded.country_key,
    ship_date_key = excluded.ship_date_key,
    delivered_date_key = excluded.delivered_date_key,
    promised_date_key = excluded.promised_date_key, carrier = excluded.carrier,
    days_in_transit = excluded.days_in_transit, is_late = excluded.is_late,
    updated_at = excluded.updated_at
WHERE excluded.updated_at > fact_shipments.updated_at
"""


# The watermark of a source. Empty text if the source was never loaded;
# empty text sorts before every timestamp, so every row passes.
def get_watermark(conn, source):
    row = conn.execute("SELECT watermark FROM etl_state WHERE source = ?", (source,)).fetchone()
    return row[0] if row else ""


# Remember the new watermark of a source.
def set_watermark(conn, source, value):
    conn.execute(
        "INSERT INTO etl_state (source, watermark) VALUES (?, ?)"
        " ON CONFLICT(source) DO UPDATE SET watermark = excluded.watermark",
        (source, value),
    )


# Load sellers into dim_seller. Sellers are few, so every run upserts all of them.
# Every load function returns (rows_written, rows_skipped, rejects).
def load_sellers(conn, rows):
    for row in rows:
        conn.execute(UPSERT_SELLER, (row["seller_id"], row["seller_name"],
                                     country_key(conn, row["country"]), row["joined_date"]))
    return len(rows), 0, []


# Load orders into fact_orders. An order whose seller is not in dim_seller is
# rejected. We look the seller up first, so a rejected order adds nothing
# to the other dimensions.
# rowcount is 1 when the upsert wrote a row, and 0 when its WHERE said "not newer".
def load_orders(conn, rows):
    written, rejects = 0, []
    for row in rows:
        seller = conn.execute(
            "SELECT seller_key FROM dim_seller WHERE seller_id = ?", (row["seller_id"],)
        ).fetchone()
        if seller is None:
            rejects.append((row["_row"], "unknown seller", row))
            continue
        written += conn.execute(UPSERT_ORDER, (
            row["order_id"], date_key(conn, row["order_date"]), seller[0],
            country_key(conn, row["country"]), category_key(conn, row["category"]),
            row["amount_cents"], row["updated_at"])).rowcount
    return written, len(rows) - written - len(rejects), rejects


# Load shipments into fact_shipments. The seller and country come from the
# order, so a shipment for an unknown order is rejected.
def load_shipments(conn, rows):
    written, rejects = 0, []
    for row in rows:
        order = conn.execute(
            "SELECT seller_key, country_key FROM fact_orders WHERE order_id = ?", (row["order_id"],)
        ).fetchone()
        if order is None:
            rejects.append((row["_row"], "unknown order", row))
            continue
        written += conn.execute(UPSERT_SHIPMENT, (
            row["shipment_id"], row["order_id"], order[0], order[1],
            date_key(conn, row["shipped_date"]), date_key(conn, row["delivered_date"]),
            date_key(conn, row["promised_date"]), row["carrier"], row["days_in_transit"],
            row["is_late"], row["updated_at"])).rowcount
    return written, len(rows) - written - len(rejects), rejects


LOADERS = {"sellers": load_sellers, "orders": load_orders, "shipments": load_shipments}


# Load the clean rows of one source. Steps: drop rows older than the watermark,
# upsert the rest, and save the new watermark. All of it is one transaction,
# so the data and the watermark cannot disagree after a crash.
# Returns (rows_written, rows_skipped, rejects).
# shortcut: a row rejected here (unknown seller) still moves the watermark,
# so it is not retried tomorrow. Real pipelines park such rows and retry.
def load_source(conn, source, rows):
    skipped = 0
    if source != "sellers":
        mark = get_watermark(conn, source)
        fresh = [row for row in rows if row["updated_at"] >= mark]
        skipped, rows = len(rows) - len(fresh), fresh
    with conn:
        written, blocked, rejects = LOADERS[source](conn, rows)
        if source != "sellers" and rows:
            set_watermark(conn, source, max(row["updated_at"] for row in rows))
    return written, skipped + blocked, rejects
