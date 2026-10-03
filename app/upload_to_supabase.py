"""Load results.csv into the Supabase `cruises` table.

Run from the app/ folder:   python upload_to_supabase.py
The project URL and the *secret* key are typed at hidden prompts (nothing is
stored or echoed).  The secret key bypasses RLS, so it is only used here and is
never part of the web app.  Re-running replaces the table contents.
"""
import csv
import getpass
import sys
from pathlib import Path

import httpx

CSV_PATH = Path(__file__).resolve().parent / "results.csv"
BATCH = 200
COLUMN_MAP = {
    "Title": "title", "Cruise Name": "cruise_name", "Nights": "nights", "Banner": "banner",
    "Offer": "offer", "Departure Port": "departure_port", "Locations": "locations",
    "Price (INR)": "price_inr", "Price Text": "price_text", "Dates Count": "dates_count",
    "Note": "note",
}
INT_COLUMNS = ("nights", "price_inr", "dates_count")


def headers(key):
    # New-style keys (sb_secret_...) go in `apikey` only; legacy JWT keys also need Bearer.
    h = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        h["Authorization"] = f"Bearer {key}"
    return h


def load_rows():
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = []
        for r in csv.DictReader(f):
            row = {COLUMN_MAP[k]: v for k, v in r.items()}
            for c in INT_COLUMNS:
                row[c] = int(row[c])
            rows.append(row)
    return rows


def main():
    rows = load_rows()
    print(f"Read {len(rows)} rows from {CSV_PATH.name}")
    url = input("Supabase project URL (https://xxxx.supabase.co): ").strip().rstrip("/")
    key = getpass.getpass("Supabase secret key (hidden): ").strip()
    if not url.startswith("https://") or not key:
        sys.exit("URL must start with https:// and the key must not be empty.")
    endpoint = f"{url}/rest/v1/cruises"

    with httpx.Client(timeout=60) as client:
        # Replace existing contents so the script can be re-run safely.
        r = client.delete(endpoint, params={"id": "gt.0"}, headers=headers(key))
        if r.status_code >= 300:
            sys.exit(f"Could not clear table ({r.status_code}): {r.text}\nDid you run schema.sql first?")
        for i in range(0, len(rows), BATCH):
            r = client.post(endpoint, json=rows[i:i + BATCH], headers={**headers(key), "Prefer": "return=minimal"})
            if r.status_code >= 300:
                sys.exit(f"Insert failed ({r.status_code}): {r.text}")
            print(f"  inserted {min(i + BATCH, len(rows))}/{len(rows)}")
        r = client.get(endpoint, params={"select": "id"}, headers={**headers(key), "Prefer": "count=exact", "Range": "0-0"})
        print("Rows now in table:", r.headers.get("content-range", "?"))


if __name__ == "__main__":
    main()
