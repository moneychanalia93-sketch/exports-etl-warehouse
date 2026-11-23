"""Stage 2, transform: turn messy text into clean values, or say why a row is bad.

Every cleaning function raises ValueError with a short reason when it cannot
clean a value. clean_rows() catches that and records the row as a reject.
"""

import json
import re
from datetime import date, datetime

COUNTRIES = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany", "FR": "France",
    "IN": "India", "JP": "Japan", "CA": "Canada", "AU": "Australia",
    "BR": "Brazil", "MX": "Mexico", "SG": "Singapore", "AE": "United Arab Emirates",
}
# Other spellings people use, and the code they mean.
ALIASES = {"usa": "US", "u.s.a.": "US", "u.s.": "US", "uk": "GB", "great britain": "GB",
           "deutschland": "DE", "uae": "AE"}
# Full name (lowercase) to code, built once from COUNTRIES.
NAME_TO_CODE = {name.lower(): code for code, name in COUNTRIES.items()}

# The date spellings we accept. A slash date is month/day/year (US style).
DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%b-%Y", "%B %d, %Y"]


# Read a date written in any accepted spelling. Returns it as YYYY-MM-DD.
# Why: the warehouse needs one date format, or dates cannot be compared.
def parse_date(text):
    for form in DATE_FORMATS:
        try:
            return datetime.strptime(text, form).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError("bad date")


# Read money like "$1,200.50" or "USD 99" and return whole cents (120050).
# Why: cents are whole numbers, so adding them never gives 0.1 + 0.2 errors.
# shortcut: only US dollars are understood; real cross-border data needs
# a currency column and exchange rates.
def parse_money(text):
    cleaned = text.upper().replace("USD", "").replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        raise ValueError("bad amount")
    cents = round(float(cleaned) * 100)
    if cents < 0:
        raise ValueError("negative amount")
    return cents


# Turn "usa", "Germany", " de " or "UK" into a two-letter code like "US".
# Why: the same country must have one spelling, or reports split it in pieces.
def standardise_country(text):
    if text.upper() in COUNTRIES:
        return text.upper()
    code = ALIASES.get(text.lower()) or NAME_TO_CODE.get(text.lower())
    if code is None:
        raise ValueError("unknown country")
    return code


# Read the "last changed" time of a row. Returns "YYYY-MM-DD HH:MM:SS".
# Why: the watermark compares these as text, so they must all look the same.
def parse_timestamp(text):
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError("bad timestamp")


# Tidy a category name ("  home & KITCHEN " becomes "Home & Kitchen").
# A missing category becomes "Unknown": we keep the row, since its money is real.
def clean_category(text):
    return (text or "").strip().title() or "Unknown"


# Read one field of a row and run a parser on it. Errors name the field,
# for example "order_date: bad date". Optional fields give None when empty.
def field(row, name, parser, required=True):
    value = row.get(name)
    text = "" if value is None else str(value).strip()
    if text == "":
        if required:
            raise ValueError(f"{name}: missing")
        return None
    try:
        return parser(text)
    except ValueError as error:
        raise ValueError(f"{name}: {error}")


# Clean one raw order row into a dict of proper values.
def clean_order(row):
    return {
        "order_id": field(row, "order_id", str),
        "order_date": field(row, "order_date", parse_date),
        "seller_id": field(row, "seller_id", str),
        "category": clean_category(row.get("category")),
        "country": field(row, "country", standardise_country),
        "amount_cents": field(row, "amount", parse_money),
        "updated_at": field(row, "updated_at", parse_timestamp),
    }


# Clean one raw shipment row. Also works out two facts we will want later:
# days in transit, and whether the delivery was late.
# An undelivered shipment has no delivery date, so both facts stay empty.
def clean_shipment(row):
    if "_raw" in row:
        raise ValueError("invalid json")
    shipped = field(row, "shipped_date", parse_date)
    delivered = field(row, "delivered_date", parse_date, required=False)
    promised = field(row, "promised_date", parse_date)
    if delivered is not None and delivered < shipped:
        raise ValueError("delivered before shipped")
    days = None if delivered is None else (date.fromisoformat(delivered) - date.fromisoformat(shipped)).days
    return {
        "shipment_id": field(row, "shipment_id", str),
        "order_id": field(row, "order_id", str),
        "shipped_date": shipped, "delivered_date": delivered, "promised_date": promised,
        "carrier": field(row, "carrier", str.upper),
        "days_in_transit": days,
        "is_late": None if delivered is None else int(delivered > promised),
        "updated_at": field(row, "updated_at", parse_timestamp),
    }


# Clean one raw seller row.
def clean_seller(row):
    return {
        "seller_id": field(row, "seller_id", str),
        "seller_name": field(row, "seller_name", str),
        "country": field(row, "country", standardise_country),
        "joined_date": field(row, "joined_date", parse_date),
    }


# Clean a whole list of (row_number, raw_row) pairs from the extract stage.
# Returns (kept, rejects). Bad rows are never dropped quietly: each one goes
# into rejects as (row_number, reason, raw_row).
# When two rows share a business key, the one with the later updated_at is
# kept (on a tie, the later row in the file) and the other is a reject.
def clean_rows(rows, cleaner, key):
    kept, rejects = {}, []
    for number, raw in rows:
        try:
            clean = cleaner(raw)
        except ValueError as error:
            rejects.append((number, str(error), raw))
            continue
        clean["_row"] = number
        old = kept.get(clean[key])
        if old is not None:
            loser = old if clean.get("updated_at", "") >= old.get("updated_at", "") else clean
            rejects.append((loser["_row"], "duplicate in batch", loser))
            if loser is clean:
                continue
        kept[clean[key]] = clean
    return list(kept.values()), rejects


# Turn a reject's row into JSON text, so it can be stored and read later.
def raw_text(row):
    return json.dumps(row, default=str)
