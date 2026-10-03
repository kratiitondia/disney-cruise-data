"""Disney Cruise Line (India) scraper: scrape -> clean -> results.csv -> answers.

Usage
    python src/disney_cruise_scraper.py            # scrape with Edge, then clean
    python src/disney_cruise_scraper.py --clean    # skip scraping, reuse data/raw.json

The site's bot protection blocks datacenter IPs (Colab, cloud VMs), so the
scraping step must run on a normal machine with a visible browser window
(Playwright + Microsoft Edge, headless=False).  The cleaning and answer code
below is plain pandas and runs anywhere.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

BASE_URL = "https://disneycruise.disney.go.com/en-in/"
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_JSON = DATA_DIR / "raw.json"
RAW_API_JSON = DATA_DIR / "raw_api.json"
RESULTS_CSV = DATA_DIR / "results.csv"

MIN_PAGES = 35          # the task asks for at least 35 pages of results
CARDS_PER_PAGE = 5      # the site loads 5 cards per scroll "page"
HOLIDAY_BANNERS = {"Very Merrytime", "Halloween on the High Seas"}

COLUMNS = [
    "Title", "Cruise Name", "Nights", "Banner", "Offer", "Departure Port",
    "Locations", "Price (INR)", "Price Text", "Dates Count", "Note",
]

# JavaScript run inside the page: pulls the raw text of every loaded card.
EXTRACT_JS = """
() => [...document.querySelectorAll('dcl-product-card')].map(card => {
  const txt = (sel) => {
    const el = card.querySelector(sel);
    return el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
  };
  const chip = card.querySelector('.chip-label');
  let offer = '';
  if (chip) {
    const c = chip.cloneNode(true);
    c.querySelectorAll('dcl-ui-global-popover').forEach(n => n.remove());
    offer = c.textContent.replace(/\\s+/g, ' ').trim();
  }
  return {
    title: txt('h2.product-card-content__name'),
    banner: txt('.product-card__banner'),
    offer: offer,
    locations: [...card.querySelectorAll('ul.ul-port-list li')]
                 .map(li => li.textContent.replace(/\\s+/g, ' ').trim()),
    price: txt('.wrapper-price__pricing'),
    currency: txt('.wrapper-price__currency'),
    dates_button: txt('.product-card-footer-wrapper__btn'),
  };
})
"""


# --------------------------------------------------------------------------
# Scraping
# --------------------------------------------------------------------------
def scrape():
    """Open the site, accept consent, click View Dates, scroll, collect cards."""
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

    api_payloads = []

    with sync_playwright() as p:
        # Edge + visible window: the only combination that passes bot protection.
        browser = p.chromium.launch(channel="msedge", headless=False)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()

        # Keep the site's own JSON feed as a cross-check (totalPages, totals).
        def on_response(resp):
            if "available-products" in resp.url:
                try:
                    api_payloads.append({"url": resp.url, "body": resp.json()})
                except Exception:
                    pass
        page.on("response", on_response)

        # Step 1: open the home page and accept the cookie/consent banner.
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.locator("#onetrust-accept-btn-handler").click(timeout=20_000)
            print("Consent accepted")
        except PWTimeout:
            print("No consent banner shown")

        # Step 2: "View Dates" with the default filters (any date / any
        # destination / any port / 2 guests) which lists every cruise.
        page.locator(".view-cruises-button").first.click(timeout=30_000)

        # Step 3: wait for the first cards to render.
        page.wait_for_selector("dcl-product-card", timeout=60_000)
        header = page.locator("body").inner_text()
        m = re.search(r"([\d,]+)\s+Cruises", header)
        print("Header says:", m.group(0) if m else "n/a")

        # Step 4: scroll until no new cards appear.
        cards = page.locator("dcl-product-card")
        count, stalled = 0, 0
        while stalled < 6:
            page.mouse.wheel(0, 20_000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            now = cards.count()
            if now > count:
                count, stalled = now, 0
                print(f"  loaded {count} cards (~{count // CARDS_PER_PAGE} pages)", end="\r")
            else:
                stalled += 1
        print(f"\nFinished scrolling: {count} cards")

        raw = page.evaluate(EXTRACT_JS)
        browser.close()

    pages = -(-len(raw) // CARDS_PER_PAGE)
    if pages < MIN_PAGES:
        print(f"WARNING: only {pages} pages loaded, expected >= {MIN_PAGES}")

    DATA_DIR.mkdir(exist_ok=True)
    RAW_JSON.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    RAW_API_JSON.write_text(json.dumps(api_payloads, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Saved {len(raw)} raw cards -> {RAW_JSON}")
    return raw


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------
# "4-Night Langkawi Cruise from Singapore ending in Hong Kong with 2 stops"
TITLE_RE = re.compile(r"^(?P<nights>\d+)-Night\s+(?P<name>.*?)\s+from\s+(?P<port>.+)$", re.I)
# Extras glued onto the departure port: "ending in X", "ending X",
# "with 2 Stops at Castaway Cay".
NOTE_RE = re.compile(r"\s+(ending(?:\s+in)?\s+.+?|with\s+\d+\s+stops?(?:\s+at\s+.+?)?)\s*$", re.I)


def parse_title(title):
    """Split a card title into (nights, cruise name, departure port, note)."""
    m = TITLE_RE.match(title)
    if not m:
        return "", title, title, "No Note"
    port, notes = m.group("port").strip(), []
    # Peel "ending in X" / "with N stops" off the end (they can be stacked).
    while True:
        n = NOTE_RE.search(port)
        if not n:
            break
        notes.insert(0, n.group(1).strip())
        port = port[:n.start()].strip()
    name = re.sub(r"\s*\bCruise$", "", m.group("name").strip(), flags=re.I) or "Standard"
    return m.group("nights"), name, port, "; ".join(notes) or "No Note"


def clean(raw):
    """Turn raw card dicts into a clean, duplicate-free DataFrame with no empty cells."""
    rows = []
    for r in raw:
        title = r.get("title", "").strip()
        if not title:
            continue
        nights, name, port, note = parse_title(title)
        locs = [x for x in (l.strip() for l in r.get("locations", [])) if x]
        locs = list(dict.fromkeys(locs))                 # de-dupe within a card
        # Cards without a "Sailing to" block: location = departure port.
        locations = "; ".join(locs) if locs else port
        digits = re.sub(r"[^\d]", "", r.get("price", ""))
        dates = re.search(r"(\d+)", r.get("dates_button", ""))
        rows.append({
            "Title": title,
            "Cruise Name": name,
            "Nights": int(nights) if nights else 0,
            "Banner": r.get("banner", "").strip() or "No Banner",
            "Offer": r.get("offer", "").strip() or "No Offer",
            "Departure Port": port,
            "Locations": locations,
            "Price (INR)": int(digits) if digits else 0,
            "Price Text": (f'{r.get("price", "")} {r.get("currency", "")}').strip() or "Price Unavailable",
            "Dates Count": int(dates.group(1)) if dates else 1,
            "Note": note,
        })
    df = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates().reset_index(drop=True)
    assert not df.isna().any().any(), "NaN found after cleaning"
    assert not (df.astype(str).apply(lambda c: c.str.strip()) == "").any().any(), "empty cell found"
    return df


# --------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------
def answers(df, api=None):
    """Compute and print the five required answers; return them as a dict."""
    # (i) The site's "Pacific Coast Cruises" destination filter returns the
    # cards titled "Pacific Coast". Like the "948 Cruises" header it counts
    # sailings (dates), so we sum the date counts of those cards.
    pacific = df["Title"].str.contains("Pacific Coast", case=False)
    holiday = df["Banner"].isin(HOLIDAY_BANNERS)
    departs = df["Departure Port"].str.contains("Miami|London", case=False, regex=True)
    out = {
        "i_pacific": int(df.loc[pacific, "Dates Count"].sum()),
        "i_pacific_cards": int(pacific.sum()),
        "ii_total_sailings": int(df["Dates Count"].sum()),
        "ii_distinct_cards": len(df),
        "iii_holiday": int(holiday.sum()),
        "iv_more_than_2_dates": int((df["Dates Count"] > 2).sum()),
        "v_miami_london_departures": int(departs.sum()),
    }
    print("\n=========== ANSWERS ===========")
    print(f"(i)   Cruises with Pacific as destination : {out['i_pacific']}"
          f"   ({out['i_pacific_cards']} Pacific Coast cards; the site's Pacific Coast filter shows {out['i_pacific']} Cruises)")
    print(f"(ii)  Total cruises                       : {out['ii_total_sailings']}"
          f"   ({out['ii_distinct_cards']} distinct cruise cards; site header counts sailings/dates)")
    print(f"(iii) Holiday cruises                     : {out['iii_holiday']}")
    print(f"(iv)  Cruises offering more than 2 dates  : {out['iv_more_than_2_dates']}")
    print(f"(v)   Miami / London departure ports      : {out['v_miami_london_departures']}")
    print("===============================")
    return out


def cross_check(df):
    """Compare the CSV against the site's own JSON feed (if it was captured)."""
    if not RAW_API_JSON.exists():
        return
    feeds = json.loads(RAW_API_JSON.read_text(encoding="utf-8"))
    if not feeds:
        return
    body = feeds[0]["body"]
    products = [p for f in feeds for p in f["body"].get("products", [])]
    sailings = sum(i["numberOfSailings"] for p in products for i in p["itineraries"])
    print(f"Cross-check vs site feed: pages={len(feeds)}/{body['totalPages']}, "
          f"products={len(products)}, sailings={sailings} (site total {body['totalAvailableCruises']}) "
          f"| CSV rows={len(df)}, sum of dates={int(df['Dates Count'].sum())}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="store_true", help="skip scraping; reuse data/raw.json")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = json.loads(RAW_JSON.read_text(encoding="utf-8")) if args.clean else scrape()
    df = clean(raw)
    df.to_csv(RESULTS_CSV, index=False, encoding="utf-8-sig")   # BOM so Excel shows the rupee sign
    print(f"Cleaned: {len(raw)} raw -> {len(df)} rows -> {RESULTS_CSV}")
    cross_check(df)
    answers(df)


if __name__ == "__main__":
    main()
