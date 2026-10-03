"""Disney Cruise table app (FastAPI + Jinja2).

Data source: Supabase REST (when SUPABASE_URL and SUPABASE_ANON_KEY are set),
otherwise the bundled results.csv, so the app always has something to show.
"""
import csv
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / "results.csv"
PAGE = 1000          # PostgREST page size
CACHE_SECONDS = 300

# CSV header -> database column
COLUMN_MAP = {
    "Title": "title", "Cruise Name": "cruise_name", "Nights": "nights", "Banner": "banner",
    "Offer": "offer", "Departure Port": "departure_port", "Locations": "locations",
    "Price (INR)": "price_inr", "Price Text": "price_text", "Dates Count": "dates_count",
    "Note": "note",
}
HOLIDAY_BANNERS = {"Very Merrytime", "Halloween on the High Seas"}

app = FastAPI(title="Disney Cruise Data")
templates = Jinja2Templates(directory=str(BASE / "templates"))
_cache = {"at": 0.0, "rows": [], "source": ""}


def supabase_headers(key):
    """New-style keys (sb_...) go in `apikey` only; legacy JWT keys (eyJ...) also need Bearer."""
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def read_supabase(url, key):
    rows, start = [], 0
    with httpx.Client(timeout=30) as client:
        while True:
            r = client.get(
                f"{url.rstrip('/')}/rest/v1/cruises",
                params={"select": "*", "order": "id.asc"},
                headers={**supabase_headers(key), "Range-Unit": "items", "Range": f"{start}-{start + PAGE - 1}"},
            )
            r.raise_for_status()
            chunk = r.json()
            rows += chunk
            if len(chunk) < PAGE:
                return rows
            start += PAGE


def read_csv():
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        out = []
        for r in csv.DictReader(f):
            row = {COLUMN_MAP[k]: v for k, v in r.items()}
            for k in ("nights", "price_inr", "dates_count"):
                row[k] = int(row[k])
            out.append(row)
        return out


def load_rows():
    """Return (rows, source), cached for a few minutes."""
    if _cache["rows"] and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["rows"], _cache["source"]
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
    rows, source = None, "csv"
    if url and key:
        try:
            rows, source = read_supabase(url, key), "supabase"
        except Exception as exc:                      # fall back instead of showing an error page
            print("Supabase read failed, using CSV:", exc)
    if not rows:
        rows, source = read_csv(), "csv"
    _cache.update(at=time.time(), rows=rows, source=source)
    return rows, source


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/cruises")
def api_cruises():
    rows, source = load_rows()
    return JSONResponse({"source": source, "count": len(rows), "cruises": rows})


@app.get("/")
def index(request: Request):
    rows, source = load_rows()
    stats = {
        "cards": len(rows),
        "sailings": sum(r["dates_count"] for r in rows),
        "holiday": sum(r["banner"] in HOLIDAY_BANNERS for r in rows),
        "multi_date": sum(r["dates_count"] > 2 for r in rows),
        "ports": len({r["departure_port"] for r in rows}),
    }
    return templates.TemplateResponse(request, "index.html", {"rows": rows, "stats": stats, "source": source})
