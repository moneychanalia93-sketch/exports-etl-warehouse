# exports-etl-warehouse

A small command-line ETL pipeline. It reads three messy files of fake cross-border order data, cleans them, and loads them into a star-schema warehouse in SQLite. A second "day 2" batch is loaded without redoing day 1, and running any batch twice leaves the warehouse unchanged.

It uses only the Python standard library (`csv`, `json`, `sqlite3`, `hashlib`, `datetime`, `argparse`, `unittest`). There is nothing to install. Python 3.13 was used (it came with SQLite 3.49). The code needs SQLite 3.25 or newer, for upserts and window functions.

> Built with AI assistance (Kiro). I designed the rules, reviewed the code, and ran the tests.
> This is a learning project with fake data. It has not been used in production.

## What it does

- **Seed:** writes fake source files, the same ones every time (fixed random seed): about 20,000 orders (CSV), their shipments (JSON lines) and 200 sellers (CSV). The files are messy on purpose: five date spellings, money like `$1,200.50`, countries as codes, names and nicknames, repeated rows, missing values, impossible values and a few broken JSON lines.
- **Extract:** reads each file as it is and counts the rows.
- **Transform:** parses dates and money, standardises countries, tidies categories. A bad row is not dropped quietly: it goes into a `rejects` table with the row number, a reason and the raw row.
- **Load:** upserts into a star schema (`fact_orders`, `fact_shipments`, `dim_date`, `dim_country`, `dim_seller`, `dim_category`). Each source has a watermark, so a later batch only touches new or changed rows.
- **Check:** after the load, 16 data quality checks run. If one finds a problem, the run fails with a clear message and exit code 1.
- **Log:** every stage of every run writes a line to a `run_log` table (run id, stage, rows in, rows out, rows rejected, rows skipped, seconds, status).
- **Query:** `queries.sql` holds 8 analytic queries. One command runs them and prints the tables.

## Run it (3 commands)

Run these from the project folder. If `python` is not on your PATH, use `py` or the full path to `python.exe`.

```powershell
python -m etl seed       # writes data/day1/ (about 20,000 fake orders)
python -m etl run        # loads day 1 into warehouse.db
python -m etl queries    # runs the 8 queries in queries.sql
```

Then load the second day, and run it again to see that nothing changes:

```powershell
python -m etl seed --day 2                # writes data/day2/ (new and changed rows only)
python -m etl run --batch data/day2       # loads it
python -m etl run --batch data/day2       # same batch again: the warehouse does not change
```

Run the tests with `python -m unittest discover -s tests -t .`. Options: `--db other.db`, `--data folder`, `--orders 5000`, `--seed 7`. Delete `warehouse.db` and `data/` to start fresh.

## The pipeline

```
 sellers.csv ----+
 orders.csv -----+--> EXTRACT --> TRANSFORM --> LOAD --> QUALITY CHECKS
 shipments.jsonl-+    read rows    clean rows    upsert    16 checks, all
                      count them   or reject     + new     must find 0 bad
                                      |          watermark rows
                                      v
                                 rejects table          run_log table
                                 (row, reason, raw)     (one line per stage)
```

The source files, the stage modules and the tables line up:

| Stage | Code | What it reads | What it writes |
|---|---|---|---|
| Extract | `etl/extract.py` | the three files | rows in memory |
| Transform | `etl/clean.py` | raw rows | clean rows, plus `rejects` |
| Load | `etl/load.py`, `etl/warehouse.py` | clean rows | dimensions, facts, watermark |
| Check | `etl/quality.py` | the warehouse | pass, or `QualityError` |
| Bookkeeping | `etl/runlog.py`, `etl/pipeline.py` | | `run_log`, `rejects` |

## The star schema

A fact table holds one row per event, with numbers to add up. Dimension tables describe the who, what, where and when. Facts point to dimensions with small whole-number keys ("surrogate keys") that the warehouse makes up.

```
                       dim_date
                       date_key (20260314), full_date, year,
                       month, year_month, weekday
                          ^
                          | order_date_key, ship_date_key,
                          | delivered_date_key, promised_date_key
                          |
 dim_seller <-- fact_orders ---------> dim_category
 seller_key     order_key (surrogate)   category_key
 seller_id      order_id  (business)    category_name
 seller_name    amount_cents
 country_key    updated_at
 joined_date        |
     |              | country_key
     v              v
 dim_country <--- fact_shipments
 country_key      shipment_key (surrogate)
 country_code     shipment_id  (business), order_id
 country_name     seller_key, carrier, days_in_transit,
                  is_late (1 / 0 / empty = not delivered yet)
```

Money is stored as whole cents (`amount_cents`), so sums never show tiny rounding errors. The queries divide by 100.

## Cleaning rules

| Field | Rule |
|---|---|
| Dates | Accepted: `2026-03-14`, `2026/03/14`, `03/14/2026` (month first), `14-Mar-2026`, `March 14, 2026`. Anything else, or a day that does not exist, is rejected. |
| Money | `1200.5`, `$1,200.50`, `1,200.50` and `USD 1200.50` all become `120050` cents. `N/A` is rejected as a bad amount. A negative amount is rejected as a negative amount. |
| Countries | `US`, `us`, `United States`, `USA` all become `US`. A name not in the list of 12 countries is rejected. |
| Category | Trimmed and title-cased. An empty category becomes `Unknown` (the row is kept, because its money is real). |
| Timestamps | `updated_at` must be a valid date and time. It drives the watermark. |
| Shipments | Delivered before shipped is rejected. `is_late` is 1 if delivered after the promised date, 0 if not, and empty if not delivered yet. |
| Repeats | If two rows have the same business key in one batch, the one with the later `updated_at` is kept (on a tie, the later row in the file). The other is logged as `duplicate in batch`. |
| Missing parents | An order whose seller is not in `dim_seller` is rejected as `unknown seller`. A shipment whose order is not in `fact_orders` is rejected as `unknown order`. |

## Incremental load, upsert and idempotency

- **Watermark.** For orders and shipments, the pipeline stores the newest `updated_at` it has loaded. The next run only looks at rows at or after it. The watermark is saved in the same transaction as the data.
- **Upsert.** Each row is written with `INSERT ... ON CONFLICT(business key) DO UPDATE`. A new row is inserted. An existing row is changed in place and keeps its surrogate key. The update only happens if the incoming row is newer, so an old copy cannot overwrite a newer one.
- **Idempotent.** Running the same batch twice gives the same warehouse. Two things make that true: the watermark skips rows already loaded, and, even if the watermark were lost, the upsert would write the same values again. The tests check both.
- **Proof.** After every run the tool prints the row counts and a **fingerprint**: a SHA-256 hash of the contents of all six warehouse tables. The same data gives the same fingerprint.

Day 1, from a fresh start (real output, Python 3.13 on a Windows laptop; times vary):

```
$ python -m etl seed
Wrote data/day1
  sellers: 206 rows
  orders: 20,273 rows
  shipments: 18,148 rows

$ python -m etl run
Run 1: data/day1 -> warehouse.db

stage      source     rows_in  rows_out  rows_rejected  rows_skipped  seconds  status
---------  ---------  -------  --------  -------------  ------------  -------  ------
extract    sellers        206       206              0             0     0.00  ok    
transform  sellers        206       195             11             0     0.01  ok    
load       sellers        195       195              0             0     0.01  ok    
extract    orders      20,273    20,273              0             0     0.03  ok    
transform  orders      20,273    19,438            835             0     0.30  ok    
load       orders      19,438    18,890            548             0     0.27  ok    
extract    shipments   18,148    18,148              0             0     0.04  ok    
transform  shipments   18,148    17,383            765             0     0.56  ok    
load       shipments   17,383    16,324          1,059             0     0.34  ok    
quality    all             16        16              0             0     0.03  ok    

Rejected rows, by reason:
source     reason                     rows
---------  ------------------------  -----
orders     unknown seller              548
orders     duplicate in batch          266
orders     order_date: bad date        145
orders     seller_id: missing           83
orders     updated_at: missing          75
orders     country: unknown country     75
orders     amount: bad amount           67
orders     amount: negative amount      65
orders     order_id: missing            59
sellers    duplicate in batch            6
sellers    seller_name: missing          2
sellers    joined_date: bad date         2
sellers    country: unknown country      1
shipments  unknown order             1,059
shipments  duplicate in batch          293
shipments  carrier: missing             93
shipments  promised_date: bad date      84
shipments  order_id: missing            82
shipments  delivered before shipped     80
shipments  shipped_date: bad date       75
shipments  invalid json                 58

Warehouse rows: dim_date 186, dim_country 12, dim_category 9, dim_seller 195, fact_orders 18,890, fact_shipments 16,324
Warehouse fingerprint: d6140d30f8e334ce
Quality checks: all passed
```

How to read it: 206 seller rows were read. 11 were rejected (6 repeats and 5 with a bad field), so 195 were loaded. The 5 sellers lost to bad rows are behind most of the 548 orders with an `unknown seller`, and the lost orders in turn explain most of the 1,059 shipments with an `unknown order`. A bad row in one file spreads to the files that depend on it.

Run it again (same batch). Only the lines that differ from the first run are shown:

```
$ python -m etl run
Run 2: data/day1 -> warehouse.db
...
load       orders      19,438         0              0        19,438     0.00  ok    
...
load       shipments   17,383         0              0        17,383     0.00  ok    
...
Warehouse rows: dim_date 186, dim_country 12, dim_category 9, dim_seller 195, fact_orders 18,890, fact_shipments 16,324
Warehouse fingerprint: d6140d30f8e334ce
Quality checks: all passed
```

Every row was skipped, nothing was written, and the fingerprint is the same `d6140d30f8e334ce`.

Day 2 holds only new and changed rows: 3 new sellers, 5 renamed sellers, about 1,000 new orders, about 400 old orders with a corrected amount, and every shipment that is new or was delivered since day 1.

```
$ python -m etl seed --day 2
Wrote data/day2
  sellers: 8 rows
  orders: 1,421 rows
  shipments: 1,435 rows

$ python -m etl run --batch data/day2
Run 3: data/day2 -> warehouse.db

stage      source     rows_in  rows_out  rows_rejected  rows_skipped  seconds  status
---------  ---------  -------  --------  -------------  ------------  -------  ------
extract    sellers          8         8              0             0     0.00  ok    
transform  sellers          8         8              0             0     0.00  ok    
load       sellers          8         8              0             0     0.01  ok    
extract    orders       1,421     1,421              0             0     0.00  ok    
transform  orders       1,421     1,360             61             0     0.03  ok    
load       orders       1,360     1,326             34             0     0.05  ok    
extract    shipments    1,435     1,435              0             0     0.00  ok    
transform  shipments    1,435     1,389             46             0     0.06  ok    
load       shipments    1,389     1,304             85             0     0.06  ok    
quality    all             16        16              0             0     0.03  ok    
...
Warehouse rows: dim_date 194, dim_country 12, dim_category 9, dim_seller 198, fact_orders 19,853, fact_shipments 17,214
Warehouse fingerprint: fb90b5ea217506fc
Quality checks: all passed
```

`fact_orders` grew from 18,890 to 19,853 rows: 963 inserted, and 363 of the 1,326 written rows were updates of existing orders. Running the same day 2 batch again gives the same fingerprint, `fb90b5ea217506fc`, with every row skipped.

## Data quality checks

Run after the load. Each check counts bad rows, and the count must be 0.

| Check | What it looks for |
|---|---|
| Reconcile (3 checks, one per source) | rows read = rows written + rows skipped + rows in `rejects`. The rejects are counted from the table itself, so a row that vanished without a log line shows up as a difference. |
| Orphan keys (8 checks) | a key in a fact or a dimension that has no row in the table it points to |
| Duplicate business keys (3 checks) | `order_id`, `shipment_id` or `seller_id` appearing twice |
| Amounts (1 check) | a negative order amount |
| Dates (1 check) | negative days in transit |

If any check finds a problem, the run stops with exit code 1 and a message. To see it, the warehouse was damaged on purpose (one order amount set to -500, and the France row removed from `dim_country`) and the day 2 batch was run again (real output, last lines):

```
Warehouse fingerprint: 3bb5f9eca260da6e
FAILED: quality checks failed: orphans: fact_orders.country_key has no row in dim_country (1633); orphans: dim_seller.country_key has no row in dim_country (17); amounts: negative order amount (1)
```

The `quality` line in `run_log` for that run says `failed`. The data of a failed run stays in the warehouse (see the limits below).

## Analytic queries

`python -m etl queries` runs the 8 queries in `queries.sql` and prints a table for each: revenue by country, revenue by month and country, top sellers, revenue share by category, month-over-month change (`LAG`), late shipment rate by carrier, late rate and transit days by country, and the share of orders that have a shipment record (`LEFT JOIN`). Real output for four of them, run after day 1 and day 2 were loaded:

```
1. Revenue by destination country
country               orders  revenue_usd  avg_order_usd
--------------------  ------  -----------  -------------
United States          5,996   900,225.39         150.14
United Kingdom         2,935   430,978.88         146.84
Germany                2,342   352,194.94         150.38
India                  1,619   243,015.08         150.10
France                 1,633   229,478.70         140.53
Japan                  1,432   208,378.16         145.52
Canada                 1,365   201,376.80         147.53
Australia                928   136,238.17         146.81
Brazil                   572    83,235.47         145.52
Singapore                398    65,140.34         163.67
Mexico                   430    63,731.03         148.21
United Arab Emirates     203    32,847.71         161.81

5. Monthly revenue and change from the month before
month    revenue_usd  change_pct
-------  -----------  ----------
2026-01   504,925.76           -
2026-02   442,027.44      -12.50
2026-03   455,131.97        3.00
2026-04   455,558.48        0.10
2026-05   476,187.41        4.50
2026-06   470,375.70       -1.20
2026-07   142,633.91      -69.70

6. Late shipment rate by carrier (delivered shipments only)
carrier  delivered   late  late_pct
-------  ---------  -----  --------
ARAMEX       4,155  1,855     44.60
UPS          4,242  1,479     34.90
DHL          4,200    946     22.50
FEDEX        4,102    861     21.00

7. Late rate and average days in transit by destination country
country               delivered  late_pct  avg_days
--------------------  ---------  --------  --------
Mexico                      365     47.90      5.40
Brazil                      467     47.80      5.40
India                     1,371     46.80      5.40
United Arab Emirates        172     33.10      4.40
Germany                   1,972     29.10      4.40
Canada                    1,137     29.10      4.40
United States             5,066     28.70      4.30
Japan                     1,188     28.00      4.30
France                    1,378     27.90      4.40
Australia                928   136,238.17         146.81 Australia                   784     27.60      4.30
United Kingdom            2,465     27.00      4.30
Singapore                   334     25.70      4.30
```

July is a partial month (day 2 only covers 1 to 7 July), so its -69.70% change is not a real drop. The fake data was built so that some carriers and slow-customs countries are later; that is why those rows stand out. These numbers describe fake data and mean nothing about real trade.

## How this would map to AWS (a sketch; this project does not run on AWS)

I have not built or run anything on AWS. This table is only my understanding of where each local piece would live in a cloud version.

| This project | A possible AWS equivalent | Note |
|---|---|---|
| `data/day1/`, `data/day2/` folders | S3 "landing zone" bucket, with a prefix per day, such as `landing/orders/2026-07-08/` | A landing zone is where raw files arrive, untouched. |
| Running `python -m etl run` by hand | A Lambda function (or EventBridge schedule) that starts the job when a new file lands | Lambda runs short jobs. Long ones go to Glue. |
| `extract.py` + `clean.py` + `load.py` | A Glue job (Spark or Python) | Glue is the managed ETL service. |
| `warehouse.db` (SQLite) | Redshift tables, or S3 files queried with Athena | Redshift is a real warehouse. Athena queries files in S3 with SQL. |
| Day folders as partitions | S3 prefixes or table partitions by date | A partition is a slice of a table, so a query reads only the days it needs. |
| `rejects` table | A rejects prefix in S3, or a rejects table | Keeps bad rows for later review. |
| `run_log` table, `QualityError` | CloudWatch logs and metrics, plus an alarm | The alarm would tell a person when a run fails. |
| Who may read or write what | IAM roles with narrow permissions per job | Least privilege: each job gets only the access it needs. |

Two points from my reading that I have not tested: Redshift treats primary and foreign keys as hints and does not enforce them, which is why this project checks for orphans and duplicates itself; and a real upsert in Redshift is usually a staging table plus a merge, not `ON CONFLICT`.

## What it does not do

- **The data is fake.** It was made by a script. No real orders, sellers or customers are in it.
- **SQLite is not a warehouse.** It is one file on one machine, with no parallel load, no columnar storage and no concurrent users. The star schema is the real idea. The engine is a stand-in.
- **No AWS.** Nothing here calls AWS. See the sketch above.
- **One currency.** All amounts are treated as US dollars. Real cross-border data needs a currency column and exchange rates.
- **A failed quality check does not roll back.** The data is already in the warehouse when the checks run, and the run is marked `failed`. A better design loads to a staging table and publishes only after the checks pass.
- **Rejected rows are not retried.** An order rejected for an unknown seller is logged, and the watermark moves past it. When the seller arrives later, the order is not picked up again unless it is changed and re-sent.
- **Rows with the same timestamp.** The upsert only updates when `updated_at` is strictly newer. Two versions of a row with the same timestamp and different content would keep the first.
- **Sellers are loaded in full every run.** The sellers file is small and has no `updated_at`, so there is no watermark for it. Seller changes overwrite (there is no history of old names).
- **No deletes.** If an order disappears from the source, it stays in the warehouse.
- **A shipment copies the seller and country of its order when it loads.** If the order's country changed later, old shipments would keep the old one.
- **Everything is held in memory** during a run. That is fine for 20,000 rows, not for 200 million.
- **No scheduling, no alerts, no permissions, no encryption.**
- Tested only on Python 3.13 on Windows.

## Run the tests

```powershell
python -m unittest discover -s tests -t .
```

Real result: `Ran 60 tests ... OK` (about 13 seconds). The tests cover the repeatable seed, every cleaning function (dates, money, countries, timestamps, categories), reject logging, duplicate handling, stable dimension keys, the fact load, the upsert and watermark, idempotent reruns (with and without the watermark), the quality checks failing on damaged data, the queries on a tiny hand-made dataset with known answers, and the command line.

## Files

```
etl/seed.py       makes the fake source files (day 1 and day 2)
etl/extract.py    stage 1: reads the files
etl/clean.py      stage 2: cleaning functions, rejects, duplicate handling
etl/warehouse.py  the star schema, dimension keys, the fingerprint
etl/load.py       stage 3: upserts and the watermark
etl/quality.py    stage 4: the data quality checks
etl/runlog.py     the run log and the rejects table
etl/pipeline.py   runs the stages in order
etl/queries.py    runs queries.sql
etl/cli.py        the commands: seed, run, queries
queries.sql       the 8 analytic queries
tests/            unittest tests
```

## License

MIT. See `LICENSE`.
