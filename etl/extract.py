"""Stage 1, extract: read a source file as it is. No cleaning happens here.

Every reader returns a list of (row_number, row) pairs. Row 1 is the first
data row (the CSV header is not counted). The row is a dict of raw text.
"""

import csv
import json


# Read a CSV file. The first line holds the column names.
def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(enumerate(csv.DictReader(handle), start=1))


# Read a JSON-lines file: one JSON object per line.
# A line that is not a JSON object is kept as {"_raw": line}, so the clean
# stage can reject it and log it. Blank lines are skipped.
def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]
    rows = []
    for number, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        rows.append((number, row if isinstance(row, dict) else {"_raw": line}))
    return rows


# Read any source file. The file ending decides the format.
def read_source(path):
    return read_jsonl(path) if path.endswith(".jsonl") else read_csv(path)
