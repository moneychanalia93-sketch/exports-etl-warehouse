"""The run log and the reject table: the pipeline's own record of what it did."""

import time

from etl.clean import raw_text


# The number for the next run: one more than the highest so far.
def next_run_id(conn):
    return conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM run_log").fetchone()[0]


# Write one line to run_log for a finished stage.
def log_stage(conn, run_id, stage, source, counts, seconds, status):
    rows_in, rows_out, rows_rejected, rows_skipped = counts
    conn.execute(
        "INSERT INTO run_log (run_id, stage, source, rows_in, rows_out, rows_rejected,"
        " rows_skipped, seconds, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, stage, source, rows_in, rows_out, rows_rejected, rows_skipped,
         round(seconds, 3), status),
    )
    conn.commit()


# Run one stage and time it. work() returns (result, counts), where counts is
# (rows_in, rows_out, rows_rejected, rows_skipped). The stage is logged as
# "ok", or as "failed" if it raised an error (and then the error goes on).
def run_stage(conn, run_id, stage, source, work):
    started = time.perf_counter()
    try:
        result, counts = work()
    except Exception:
        log_stage(conn, run_id, stage, source, (0, 0, 0, 0), time.perf_counter() - started, "failed")
        raise
    log_stage(conn, run_id, stage, source, counts, time.perf_counter() - started, "ok")
    return result


# Save rejected rows: (row_number, reason, row). Nothing is dropped quietly.
def log_rejects(conn, run_id, source, rejects):
    conn.executemany(
        "INSERT INTO rejects (run_id, source, source_row, reason, raw) VALUES (?, ?, ?, ?, ?)",
        [(run_id, source, number, reason, raw_text(row)) for number, reason, row in rejects],
    )
    conn.commit()
