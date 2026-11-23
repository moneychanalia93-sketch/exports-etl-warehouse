"""Run the analytic queries in queries.sql against the warehouse."""

import os

DEFAULT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "queries.sql")


# Read queries.sql. Each query starts with a line "-- name: Some title".
# Returns a list of (title, sql).
def load_queries(path=DEFAULT_FILE):
    with open(path, encoding="utf-8") as handle:
        parts = handle.read().split("-- name:")[1:]
    return [tuple(part.strip().split("\n", 1)) for part in parts]


# Run every query. Returns a list of (title, column_names, rows).
def run_queries(conn, path=DEFAULT_FILE):
    results = []
    for title, sql in load_queries(path):
        cursor = conn.execute(sql)
        results.append((title, [col[0] for col in cursor.description], cursor.fetchall()))
    return results
