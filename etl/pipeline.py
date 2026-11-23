"""Runs the stages in order: extract, transform, load for each source, then quality.

Sellers go first and orders second, because orders need the seller rows
and shipments need the order rows.
"""

import os

from etl import clean, extract, load, quality, runlog, warehouse

# (source name, file name, cleaning function, business key)
SOURCES = [
    ("sellers", "sellers.csv", clean.clean_seller, "seller_id"),
    ("orders", "orders.csv", clean.clean_order, "order_id"),
    ("shipments", "shipments.jsonl", clean.clean_shipment, "shipment_id"),
]


# Extract one file. Counts: rows in the file, rows read.
def extract_stage(path):
    rows = extract.read_source(path)
    return rows, (len(rows), len(rows), 0, 0)


# Clean the rows and save the rejects. Counts: rows read, rows kept, rows rejected.
def transform_stage(conn, run_id, source, rows, cleaner, key):
    kept, rejects = clean.clean_rows(rows, cleaner, key)
    runlog.log_rejects(conn, run_id, source, rejects)
    return kept, (len(rows), len(kept), len(rejects), 0)


# Load the clean rows. Counts: rows in, rows written, rows rejected, rows skipped.
def load_stage(conn, run_id, source, kept):
    written, skipped, rejects = load.load_source(conn, source, kept)
    runlog.log_rejects(conn, run_id, source, rejects)
    return None, (len(kept), written, len(rejects), skipped)


# Run all the quality checks. Counts: checks run, checks passed.
# If any check fails this raises QualityError, and the stage is logged as failed.
def quality_stage(conn, run_id):
    results = quality.run_checks(conn, run_id)
    quality.raise_if_failed(results)
    return results, (len(results), len(results), 0, 0)


# Run the whole pipeline on one batch folder. Returns the run id.
# A failed quality check raises QualityError. The data is already loaded
# at that point, and the run_log line says "failed".
def run_pipeline(batch_dir, db_path):
    conn = warehouse.connect(db_path)
    try:
        run_id = runlog.next_run_id(conn)
        for source, filename, cleaner, key in SOURCES:
            path = os.path.join(batch_dir, filename)
            rows = runlog.run_stage(conn, run_id, "extract", source, lambda: extract_stage(path))
            kept = runlog.run_stage(
                conn, run_id, "transform", source,
                lambda: transform_stage(conn, run_id, source, rows, cleaner, key))
            runlog.run_stage(conn, run_id, "load", source, lambda: load_stage(conn, run_id, source, kept))
        runlog.run_stage(conn, run_id, "quality", "all", lambda: quality_stage(conn, run_id))
        return run_id
    finally:
        conn.close()
