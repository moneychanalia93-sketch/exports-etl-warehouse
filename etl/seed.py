"""Make fake, messy source files: python -m etl seed [--day 2]

The same seed number always gives the same files. First we build a "true"
world of sellers, orders and shipments (clean, no mistakes). Then we write
what each day's export would look like, with mixed formats and bad rows.
"""

import csv
import json
import os
import random
from datetime import date, timedelta

from etl.clean import ALIASES, COUNTRIES, DATE_FORMATS

DAY1_END = date(2026, 6, 30)   # day 1 holds everything up to this date
DAY2_END = date(2026, 7, 8)    # day 2 holds what changed up to this date
SELLERS = 200                  # sellers in day 1; three more join on day 2
CATEGORIES = ["electronics", "books", "home & kitchen", "toys", "apparel", "beauty", "sports", "garden"]
CARRIERS = {"DHL": 6, "UPS": 7, "FEDEX": 6, "ARAMEX": 8}   # slowest delivery, in days
COUNTRY_WEIGHTS = [30, 15, 12, 8, 8, 7, 7, 5, 3, 2, 2, 1]  # same order as COUNTRIES
SLOW_COUNTRIES = ("BR", "IN", "MX")                        # customs adds a day

ORDER_COLUMNS = ["order_id", "order_date", "seller_id", "category", "country", "amount", "updated_at"]
SELLER_COLUMNS = ["seller_id", "seller_name", "country", "joined_date"]
# Each bad-row recipe is a set of fields to overwrite with a wrong value.
ORDER_MISTAKES = [{"order_id": ""}, {"order_date": "2026-13-45"}, {"order_date": "yesterday"},
                  {"amount": "N/A"}, {"amount": "-12.50"}, {"country": "Atlantis"},
                  {"seller_id": ""}, {"seller_id": "S-9999"}, {"updated_at": ""}]
SHIPMENT_MISTAKES = [{"order_id": ""}, {"order_id": "O-999999"}, {"shipped_date": "not a date"},
                     {"promised_date": "32/13/2026"}, {"delivered_date": "2000-01-01"}, {"carrier": ""}]
SELLER_MISTAKES = [{"country": "Narnia"}, {"seller_name": ""}, {"joined_date": "sometime"}]


# A random day from start to end (both included).
def random_day(rng, start, end):
    return start + timedelta(days=rng.randint(0, (end - start).days))


# A random time of day as text, like "14:05:59".
def clock(rng):
    return f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}"


# One true shipment for an order: shipped 1-3 days after the order, promised
# 5 days after shipping. Each carrier has its own slowest delivery time.
def make_shipment(rng, order):
    carrier = rng.choice(list(CARRIERS))
    shipped = order["date"] + timedelta(days=rng.randint(1, 3))
    days = rng.randint(2, CARRIERS[carrier]) + (order["country"] in SLOW_COUNTRIES)
    return {"id": order["id"].replace("O-", "SH-"), "order_id": order["id"], "carrier": carrier,
            "shipped": shipped, "promised": shipped + timedelta(days=5),
            "delivered": shipped + timedelta(days=days), "clock": clock(rng)}


# Build the true world: sellers, and orders (each with its shipment, or None).
# Orders 1..count are day 1. The extra orders (count // 20) are new on day 2.
def make_world(seed, count):
    rng = random.Random(seed)
    sellers = [{"id": f"S-{n:04d}", "name": f"{rng.choice(['Acme', 'Birch', 'Cobalt', 'Delta', 'Eagle'])} "
                f"{rng.choice(['Goods', 'Trading', 'Supply', 'Direct'])} {n}",
                "country": rng.choice(list(COUNTRIES)), "joined": random_day(rng, date(2024, 1, 1), date(2025, 12, 31))}
               for n in range(1, SELLERS + 4)]
    orders = []
    for n in range(1, count + count // 20 + 1):
        new = n > count
        order = {"id": f"O-{n:06d}", "clock": clock(rng),
                 "date": random_day(rng, date(2026, 7, 1), date(2026, 7, 7)) if new
                 else random_day(rng, date(2026, 1, 1), DAY1_END),
                 "seller": rng.choice(sellers if new else sellers[:SELLERS])["id"],
                 "category": rng.choice(CATEGORIES),
                 "country": rng.choices(list(COUNTRIES), COUNTRY_WEIGHTS)[0],
                 "cents": max(100, round(rng.lognormvariate(4.5, 1.0) * 100))}
        order["shipment"] = make_shipment(rng, order) if rng.random() < 0.9 else None
        orders.append(order)
    return sellers, orders


# How a shipment looked on a given day: not shipped yet gives None; delivered
# only shows if the delivery date has passed. Its updated_at is the last event.
def shipment_as_of(order, day):
    ship = order["shipment"]
    if ship is None or ship["shipped"] > day:
        return None
    delivered = ship["delivered"] if ship["delivered"] <= day else None
    return {**ship, "delivered": delivered, "updated": f"{delivered or ship['shipped']} {ship['clock']}"}


# Write a date in a random accepted spelling (the ISO spelling is the most common).
def messy_date(rng, day):
    return None if day is None else day.strftime(rng.choice(DATE_FORMATS + ["%Y-%m-%d"] * 4))


# Write cents as money in a random style: 1200.5, $1,200.50, 1,200.50 or USD 1200.50.
def messy_money(rng, cents):
    dollars = cents / 100
    return rng.choice([f"{dollars:.2f}", f"${dollars:,.2f}", f"{dollars:,.2f}", f"USD {dollars:.2f}"])


# Write a country code as a code, lowercase code, full name, shouty name or alias.
def messy_country(rng, code):
    aliases = [alias for alias, target in ALIASES.items() if target == code]
    return rng.choice([code, code, code.lower(), COUNTRIES[code], COUNTRIES[code].upper(),
                       f" {COUNTRIES[code]} "] + aliases)


# Turn a true order into a messy raw row. About 4% lose the category.
def order_row(rng, order, cents, updated):
    name = order["category"]
    category = rng.choice([name] * 20 + [name.upper(), f" {name} ", ""])
    return {"order_id": order["id"], "order_date": messy_date(rng, order["date"]), "seller_id": order["seller"],
            "category": category, "country": messy_country(rng, order["country"]),
            "amount": messy_money(rng, cents), "updated_at": updated}


# Turn a true shipment (as seen on one day) into a messy raw row.
def shipment_row(rng, ship):
    return {"shipment_id": ship["id"], "order_id": ship["order_id"], "shipped_date": messy_date(rng, ship["shipped"]),
            "delivered_date": messy_date(rng, ship["delivered"]), "promised_date": messy_date(rng, ship["promised"]),
            "carrier": rng.choice([ship["carrier"], ship["carrier"].lower(), ship["carrier"].title()]),
            "updated_at": ship["updated"]}


# Turn a true seller into a messy raw row.
def seller_row(rng, seller):
    return {"seller_id": seller["id"], "seller_name": seller["name"],
            "country": messy_country(rng, seller["country"]), "joined_date": messy_date(rng, seller["joined"])}


# Add the mess: break some rows (bad_rate of them), repeat some rows
# (1.5%), then shuffle so the order in the file means nothing.
def add_mess(rng, rows, mistakes, bad_rate):
    result = []
    for row in rows:
        if rng.random() < bad_rate:
            row.update(rng.choice(mistakes))
        result.append(row)
        if rng.random() < 0.015:
            result.append(dict(row))
    rng.shuffle(result)
    return result


# Write one batch folder (sellers.csv, orders.csv, shipments.jsonl).
# A few shipment lines are cut in half, so they are not valid JSON.
# Returns how many rows each file holds.
def write_batch(folder, rng, sellers, orders, shipments, seller_bad_rate):
    os.makedirs(folder, exist_ok=True)
    rows = {"sellers": add_mess(rng, [seller_row(rng, s) for s in sellers], SELLER_MISTAKES, seller_bad_rate),
            "orders": add_mess(rng, orders, ORDER_MISTAKES, 0.03),
            "shipments": add_mess(rng, shipments, SHIPMENT_MISTAKES, 0.03)}
    for name, columns in (("sellers", SELLER_COLUMNS), ("orders", ORDER_COLUMNS)):
        with open(os.path.join(folder, name + ".csv"), "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows[name])
    with open(os.path.join(folder, "shipments.jsonl"), "w", encoding="utf-8") as handle:
        for row in rows["shipments"]:
            line = json.dumps(row)
            handle.write((line[: len(line) // 2] if rng.random() < 0.003 else line) + "\n")
    return {name: len(part) for name, part in rows.items()}


# Day 1: all sellers, all orders up to DAY1_END, and the shipments seen by then.
def make_day1(folder, count=20000, seed=42):
    sellers, orders = make_world(seed, count)
    rng = random.Random(seed + 1)
    old = [o for o in orders if o["date"] <= DAY1_END]
    order_rows = [order_row(rng, o, o["cents"], f"{o['date']} {o['clock']}") for o in old]
    ships = [shipment_row(rng, s) for s in (shipment_as_of(o, DAY1_END) for o in old) if s]
    return write_batch(folder, rng, sellers[:SELLERS], order_rows, ships, 0.02)


# Day 2 holds only what is new or changed: three new sellers, five renamed
# sellers, new orders, count // 50 old orders with a corrected amount, and
# every shipment that is new or got delivered since day 1.
def make_day2(folder, count=20000, seed=42):
    sellers, orders = make_world(seed, count)
    rng = random.Random(seed + 2)
    renamed = [dict(s, name=s["name"] + " Ltd") for s in rng.sample(sellers[:SELLERS], 5)]
    new = [o for o in orders if o["date"] > DAY1_END]
    changed = rng.sample([o for o in orders if o["date"] <= DAY1_END], count // 50)
    order_rows = [order_row(rng, o, o["cents"], f"{o['date']} {o['clock']}") for o in new]
    order_rows += [order_row(rng, o, round(o["cents"] * rng.uniform(0.5, 1.5)), f"{DAY2_END} {o['clock']}")
                   for o in changed]
    ships = []
    for order in orders:
        after, before = shipment_as_of(order, DAY2_END), shipment_as_of(order, DAY1_END)
        if after and after != before:
            ships.append(shipment_row(rng, after))
    return write_batch(folder, rng, sellers[SELLERS:] + renamed, order_rows, ships, 0)
