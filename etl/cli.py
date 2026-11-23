"""The command line: python -m etl seed | run | queries"""

import argparse
import os
import sys

from etl import pipeline, queries, runlog, seed, warehouse
from etl.quality import QualityError

STAGE_SQL = ("SELECT stage, source, rows_in, rows_out, rows_rejected, rows_skipped, seconds, status"
             " FROM run_log WHERE run_id = ? ORDER BY log_id")
REJECT_SQL = ("SELECT source, reason, COUNT(*) AS rows FROM rejects WHERE run_id = ?"
              " GROUP BY source, reason ORDER BY source, rows DESC")


# One value as text: None is "-", whole numbers get commas, decimals show 2 places.
def show(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


# Lay out rows as aligned text. Columns that hold numbers are right-aligned.
def format_table(columns, rows):
    text = [[show(v) for v in row] for row in rows]
    numeric = [any(isinstance(row[i], (int, float)) for row in rows) for i in range(len(columns))]
    widths = [max([len(col)] + [len(row[i]) for row in text]) for i, col in enumerate(columns)]
    align = lambda cell, i: cell.rjust(widths[i]) if numeric[i] else cell.ljust(widths[i])
    lines = ["  ".join(align(col, i) for i, col in enumerate(columns)),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(align(cell, i) for i, cell in enumerate(row)) for row in text]
    return "\n".join(lines)


# Command "seed": write fake source files for day 1 or day 2.
def cmd_seed(args):
    folder = f"{args.data}/day{args.day}"
    counts = (seed.make_day1 if args.day == 1 else seed.make_day2)(folder, args.orders, args.seed)
    print(f"Wrote {folder}")
    for name, rows in counts.items():
        print(f"  {name}: {rows:,} rows")
    return 0


# Command "run": run the pipeline, then print what happened. The exit code
# is 0 when all is well, 1 when a quality check failed, 2 for a missing file.
def cmd_run(args):
    error = None
    try:
        pipeline.run_pipeline(args.batch, args.db)
    except QualityError as problem:
        error = problem
    except FileNotFoundError as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    conn = warehouse.connect(args.db)
    run_id = runlog.next_run_id(conn) - 1
    print(f"Run {run_id}: {args.batch} -> {args.db}\n")
    cursor = conn.execute(STAGE_SQL, (run_id,))
    print(format_table([col[0] for col in cursor.description], cursor.fetchall()))
    cursor = conn.execute(REJECT_SQL, (run_id,))
    print("\nRejected rows, by reason:")
    print(format_table([col[0] for col in cursor.description], cursor.fetchall()))
    counts, digest = warehouse.fingerprint(conn)
    print("\nWarehouse rows:", ", ".join(f"{table} {n:,}" for table, n in counts.items()))
    print("Warehouse fingerprint:", digest[:16])
    conn.close()
    if error:
        print(f"\nFAILED: {error}", file=sys.stderr)
        return 1
    print("Quality checks: all passed")
    return 0


# Command "queries": run queries.sql and print one table per query.
def cmd_queries(args):
    if not os.path.exists(args.db):
        print(f"error: {args.db} not found. Run: python -m etl run", file=sys.stderr)
        return 2
    conn = warehouse.connect(args.db)
    for title, columns, rows in queries.run_queries(conn, args.file):
        print(f"\n{title}\n{format_table(columns, rows)}")
    conn.close()
    return 0


# Read the command line and run the chosen command. Returns the exit code.
def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m etl", description="Fake order data into a star schema")
    commands = parser.add_subparsers(dest="command", required=True)
    seed_cmd = commands.add_parser("seed", help="write fake source files")
    seed_cmd.add_argument("--day", type=int, choices=[1, 2], default=1)
    seed_cmd.add_argument("--data", default="data")
    seed_cmd.add_argument("--orders", type=int, default=20000)
    seed_cmd.add_argument("--seed", type=int, default=42)
    run_cmd = commands.add_parser("run", help="load one batch into the warehouse")
    run_cmd.add_argument("--batch", default="data/day1")
    run_cmd.add_argument("--db", default="warehouse.db")
    queries_cmd = commands.add_parser("queries", help="run the analytic queries")
    queries_cmd.add_argument("--db", default="warehouse.db")
    queries_cmd.add_argument("--file", default=queries.DEFAULT_FILE)
    args = parser.parse_args(argv)
    return {"seed": cmd_seed, "run": cmd_run, "queries": cmd_queries}[args.command](args)
