"""Generate notebooks/disney_cruise_colab.ipynb from the scraper source + data/raw.json.

The notebook embeds the locally scraped raw.json (gzip + base64) and runs the
*same* cleaning/answer code that lives in src/disney_cruise_scraper.py (it is
sliced out of that file, so the two can never drift apart).
"""
import base64
import gzip
import hashlib
import json
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "src" / "disney_cruise_scraper.py").read_text(encoding="utf-8")
RAW = (ROOT / "data" / "raw.json").read_bytes()
CSV = (ROOT / "data" / "results.csv").read_bytes()

# Slice the shared code out of the scraper module.
columns = SRC[SRC.index("COLUMNS = ["):SRC.index("# JavaScript run inside")]
holiday = SRC[SRC.index("HOLIDAY_BANNERS ="):SRC.index("COLUMNS = [")]
cleaning = SRC[SRC.index("# " + "-" * 74 + "\n# Cleaning"):SRC.index("def cross_check")]
scrape_src = SRC[SRC.index("def scrape():"):SRC.index("# " + "-" * 74 + "\n# Cleaning")]

blob = base64.b64encode(gzip.compress(RAW, 9)).decode()
chunks = "\n".join(f'    "{blob[i:i + 100]}"' for i in range(0, len(blob), 100))

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s))
code = lambda s: cells.append(nbf.v4.new_code_cell(s))

md("""# Disney Cruise Line (India) - scrape, clean, answer

**Please read - how this notebook works (honest note).**
`disneycruise.disney.go.com` blocks datacenter IPs (Google Colab included) with an *Access Denied* page,
so the live scraper **cannot run inside Colab**. I ran it on my own machine with Playwright + Microsoft Edge
(`src/disney_cruise_scraper.py`): accept consent -> click **View Dates** -> scroll until all **171 cards / 35 pages** loaded.

The raw output of that run (`raw.json`) is embedded below (gzip + base64). Everything after that - the cleaning rules,
`results.csv` and the five answers - is the **same code** as in the `.py` file and runs here for real.

Run all cells: *Runtime -> Run all*.""")

md("## 1. Scraper code (reference only - runs locally, not in Colab)\n\n```python\n"
   + scrape_src.rstrip() + "\n```")

md("## 2. Raw data scraped locally (embedded)")
code(f"""import base64, gzip, hashlib, json, re
import pandas as pd

RAW_B64 = (
{chunks}
)
raw = json.loads(gzip.decompress(base64.b64decode(RAW_B64)).decode("utf-8"))
print(len(raw), "raw cards loaded  (171 cards = 35 pages x 5 cards)")
raw[:2]""")

md("## 3. Cleaning rules and answers (identical to the `.py` file)")
code(holiday + columns + "\n" + cleaning.rstrip() + "\n")

md("## 4. Clean, save `results.csv`, print the answers")
code(f"""df = clean(raw)
df.to_csv("results.csv", index=False, encoding="utf-8-sig")
print(f"Cleaned: {{len(raw)}} raw -> {{len(df)}} rows -> results.csv")
print("Empty cells:", int((df.astype(str).apply(lambda c: c.str.strip()) == "").sum().sum()),
      "| NaN:", int(df.isna().sum().sum()), "| duplicates:", int(df.duplicated().sum()))
ans = answers(df)
df.head(10)""")

md("## 5. Check against the file produced locally")
code(f"""EXPECTED_SHA256 = "{hashlib.sha256(CSV).hexdigest()}"   # sha256 of the results.csv produced on my machine
actual = hashlib.sha256(open("results.csv", "rb").read()).hexdigest()
print("results.csv identical to the locally generated file:", actual == EXPECTED_SHA256)""")

md("## 6. Download `results.csv` (optional)")
code("""try:
    from google.colab import files
    files.download("results.csv")
except ImportError:
    print("Not running in Colab - results.csv is in the working directory.")""")

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nb.metadata["colab"] = {"name": "disney_cruise_colab.ipynb", "provenance": []}
out = ROOT / "notebooks" / "disney_cruise_colab.ipynb"
nbf.write(nb, out)
print("Wrote", out, f"({out.stat().st_size // 1024} KB)")
