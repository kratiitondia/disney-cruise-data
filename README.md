# Disney Cruise Line (India) - scraper, analysis and web app

Scrapes every cruise card from <https://disneycruise.disney.go.com/en-in/>, cleans the data,
writes `results.csv`, answers the five questions, and (bonus) serves the table from Supabase on Render.

## Results

| # | Question | Answer |
|---|----------|--------|
| i | Cruises with Pacific as destination | **5** (2 "Pacific Coast" cards with 3 + 2 dates; the site's *Pacific Coast Cruises* filter shows "5 Cruises") |
| ii | Total cruises | **948** (the site header counts sailings; they come from **171** distinct cruise cards over 35 pages) |
| iii | Holiday cruises | **71** (banners *Very Merrytime* 44 + *Halloween on the High Seas* 27) |
| iv | Cruises with more than 2 dates | **67** |
| v | Miami + London as departure ports | **0** (neither is a departure port on this site) |

Cross-check: the site's own JSON feed (`available-products`) reports 35 pages, 171 products and 948 sailings - identical to the scraped data.

## Layout

```
src/disney_cruise_scraper.py   scrape + clean + answers   (--clean reuses data/raw.json)
data/                          raw.json, raw_api.json, results.csv
notebooks/                     Colab notebook (built by tools/build_notebook.py)
app/                           FastAPI + Jinja2 table page, schema.sql, upload_to_supabase.py
render.yaml                    Render blueprint (rootDir: app, free plan)
```

## Run it

```bash
pip install -r requirements.txt
python -m playwright install msedge          # only if Edge is missing
python src/disney_cruise_scraper.py          # opens Edge, scrapes, cleans, prints answers
python src/disney_cruise_scraper.py --clean  # skip scraping, reuse data/raw.json
```

Why Edge and a visible window: the site's bot protection returns *Access Denied* to datacenter IPs (Colab, cloud VMs)
and to headless browsers. Scraping therefore runs locally with `channel="msedge", headless=False`.
The Colab notebook embeds the locally scraped `raw.json` and runs the same cleaning/answer code on it - it does **not** scrape live.

## Cleaning rules

* No empty cells: placeholders `No Banner`, `No Offer`, `No Note` (never blank, never the string `None`).
* Cards with no "Sailing to" block get the departure port as `Locations`.
* `ending in X` / `with N stops` are split off the departure port into `Note`.
* Exact duplicates dropped (none found - 171 raw cards -> 171 rows).
* `Price (INR)` is the numeric price, `Price Text` the text as shown on the site.

## Web app

```bash
cd app
pip install -r requirements.txt
uvicorn main:app --reload                       # uses bundled results.csv
# with Supabase:
$env:SUPABASE_URL="https://xxxx.supabase.co"; $env:SUPABASE_ANON_KEY="sb_publishable_..."; uvicorn main:app
```

Routes: `/` (table with search, sortable columns, stat tiles), `/api/cruises` (JSON), `/health`.

## Deploy walkthrough (steps only you can do)

### 1. Supabase
1. <https://supabase.com> -> sign in -> **New project** -> name `disney-cruise-data`, set a database password, pick a nearby region -> **Create new project** (wait ~2 min).
2. **SQL Editor** -> **New query** -> paste all of `app/schema.sql` -> **Run**. (Creates table `cruises`, RLS, public read policy, `GRANT SELECT` to `anon`.)
3. **Project Settings -> API Keys**: note the **Project URL**, the **publishable** key (`sb_publishable_...`, used by the app) and the **secret** key (`sb_secret_...`, used only for the upload - click the eye icon to reveal).
4. In a terminal: `cd app` then `python upload_to_supabase.py`. Paste the URL, then the secret key at the hidden prompt. Expect `Rows now in table: 0-0/171`.
5. **Table Editor -> cruises** should show 171 rows.

### 2. GitHub
1. <https://github.com/new> -> repository name `disney-cruise-data` -> Public -> **do not** add README/.gitignore -> **Create repository**.
2. Push the prepared local commit (needs git installed):
   ```bash
   git remote add origin https://github.com/<your-username>/disney-cruise-data.git
   git branch -M main
   git push -u origin main
   ```
   No git? On the new repo page click **uploading an existing file** and drag in the contents of this folder.

### 3. Render
1. <https://render.com> -> sign in with GitHub -> **New +** -> **Blueprint** -> pick `disney-cruise-data` -> it reads `render.yaml` (service name `disney-cruise-data`, free plan, root dir `app`).
   *(Or **New + -> Web Service**, root directory `app`, build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`, instance type **Free**, health check path `/health`.)*
2. When asked for environment variables set `SUPABASE_URL` and `SUPABASE_ANON_KEY` (the **publishable** key, never the secret key).
3. **Apply / Create** -> wait for *Live*. Open the `https://disney-cruise-data.onrender.com` URL; the page subtitle should say `data source: supabase`.
   Free services sleep after 15 min idle, so the first visit can take ~50 s.

### 4. Google Colab
1. <https://colab.research.google.com> -> **File -> Upload notebook** -> choose `notebooks/disney_cruise_colab.ipynb`.
2. **Runtime -> Run all** (no internet access to Disney is needed).
3. **Share** (top right) -> General access: **Anyone with the link** -> Viewer -> **Copy link**.
