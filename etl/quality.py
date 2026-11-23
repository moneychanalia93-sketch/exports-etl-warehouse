"""Stage 4, data quality checks, run after the load.

Every check is a question with one right answer: "how many bad rows are
there?" The answer must be 0. If any answer is not 0, the run fails loudly.
"""


# Raised when at least one quality check finds a problem.
class QualityError(Exception):
    pass


# Rows read from a file must be fully accounted for. For each source:
# rows read = rows written + rows skipped + rows in the rejects table.
# The rejects are counted from the table itself, not from a counter, so a
# row that vanished without being logged shows up as a difference here.
RECONCILE_SQL = """
SELECT source,
       SUM(CASE WHEN stage = 'extract' THEN rows_out ELSE 0 END)
     - SUM(CASE WHEN stage = 'load' THEN rows_out + rows_skipped ELSE 0 END)
     - (SELECT COUNT(*) FROM rejects r WHERE r.run_id = l.run_id AND r.source = l.source)
FROM run_log l
WHERE run_id = ? AND stage IN ('extract', 'load')
GROUP BY source ORDER BY source
"""

# Orphan check: every key in a fact (or dimension) must exist in the table it
# points to. (table, key column, parent table, parent key column)
# A NULL key (a shipment not delivered yet) is not counted: NULL NOT IN (...) is not true.
RELATIONSHIPS = [
    ("fact_orders", "order_date_key", "dim_date", "date_key"),
    ("fact_orders", "seller_key", "dim_seller", "seller_key"),
    ("fact_orders", "country_key", "dim_country", "country_key"),
    ("fact_orders", "category_key", "dim_category", "category_key"),
    ("fact_shipments", "order_id", "fact_orders", "order_id"),
    ("fact_shipments", "ship_date_key", "dim_date", "date_key"),
    ("fact_shipments", "delivered_date_key", "dim_date", "date_key"),
    ("dim_seller", "country_key", "dim_country", "country_key"),
]

# Duplicate check: a business key must appear once. (table, business key)
BUSINESS_KEYS = [("fact_orders", "order_id"), ("fact_shipments", "shipment_id"), ("dim_seller", "seller_id")]

# Value checks: SQL that counts rows with a bad value.
VALUE_CHECKS = [
    ("amounts: negative order amount", "SELECT COUNT(*) FROM fact_orders WHERE amount_cents < 0"),
    ("dates: negative days in transit", "SELECT COUNT(*) FROM fact_shipments WHERE days_in_transit < 0"),
]


# Build every check as (name, SQL that counts bad rows). All names in the
# SQL come from the fixed lists above, never from a user.
def all_checks():
    checks = [(f"orphans: {t}.{c} has no row in {p}",
               f"SELECT COUNT(*) FROM {t} WHERE {c} NOT IN (SELECT {pc} FROM {p})")
              for t, c, p, pc in RELATIONSHIPS]
    checks += [(f"duplicates: {t}.{k} appears twice",
                f"SELECT COUNT(*) FROM (SELECT {k} FROM {t} GROUP BY {k} HAVING COUNT(*) > 1)")
               for t, k in BUSINESS_KEYS]
    return checks + VALUE_CHECKS


# Run every check for one run. Returns a list of (name, bad_count).
def run_checks(conn, run_id):
    results = [(f"reconcile: {source} rows read = written + skipped + rejected", gap)
               for source, gap in conn.execute(RECONCILE_SQL, (run_id,))]
    return results + [(name, conn.execute(sql).fetchone()[0]) for name, sql in all_checks()]


# Stop with an error that lists every failed check. Does nothing if all pass.
def raise_if_failed(results):
    failed = [f"{name} ({count})" for name, count in results if count != 0]
    if failed:
        raise QualityError("quality checks failed: " + "; ".join(failed))
