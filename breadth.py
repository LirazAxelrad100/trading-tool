"""Market breadth — how many stocks are actually participating.

Every other signal in this tool looks at one company. This looks at the market underneath
them: the share of US stocks trading above their own long-term (200-day) and short-term
(50-day) averages. A rally where most stocks participate is a different environment from one
carried by a handful of names, and breakout-style setups fail disproportionately in the
second — which is the context the momentum badge can't supply.

Data: TraderMonty's published CSV on GitHub Pages (no key, no login, a dataset deliberately
published for public use — the fit for the project's no-ToS-violating-scraping rule). It is
one person's dataset, so it could move or stop updating; `fetch()` degrades to an error rather
than pretending, and the UI says when the data was last updated so a stale feed is visible
rather than silent.

Cached once per day: the file is ~450 KB and only changes daily.
"""

import csv
import io
import json
from datetime import date
from pathlib import Path
from typing import Optional

import requests

DETAIL_URL = "https://tradermonty.github.io/market-breadth-analysis/market_breadth_data.csv"
CACHE_FILE = Path(__file__).parent / "data" / "breadth_cache.json"
# Enough rows to show where the current reading sits against recent weeks.
HISTORY_ROWS = 60


class BreadthError(Exception):
    pass


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def fetch(force: bool = False) -> dict:
    """Latest breadth reading plus recent history, cached per day."""
    cache = _load_cache()
    today = date.today().isoformat()
    if not force and cache.get("fetched_date") == today and cache.get("rows"):
        return cache

    try:
        res = requests.get(DETAIL_URL, timeout=20)
        res.raise_for_status()
    except requests.RequestException as e:
        if cache.get("rows"):
            return cache  # a stale reading beats none; the UI shows its date
        raise BreadthError(f"Could not fetch market breadth data: {e}") from e

    reader = csv.DictReader(io.StringIO(res.text))
    rows = []
    for row in reader:
        above_200 = _to_float(row.get("Breadth_Index_Raw"))
        above_50 = _to_float(row.get("Breadth_50_Index_Raw"))
        if above_200 is None or above_50 is None:
            continue
        rows.append({
            "date": row.get("Date"),
            "above_200d": above_200 * 100,
            "above_50d": above_50 * 100,
            "trend_200": _to_float(row.get("Breadth_200MA_Trend")),
            "trend_50": _to_float(row.get("Breadth_50_MA_Trend")),
            "bearish_200": (row.get("Bearish_Signal") or "").strip().lower() == "true",
            "bearish_50": (row.get("Bearish_Signal_50") or "").strip().lower() == "true",
        })

    if not rows:
        raise BreadthError("Market breadth data arrived empty or in an unexpected format.")

    cache = {"fetched_date": today, "rows": rows[-HISTORY_ROWS:]}
    CACHE_FILE.write_text(json.dumps(cache, indent=2))
    return cache


def summary() -> dict:
    data = fetch()
    rows = data["rows"]
    latest = rows[-1]
    month_ago = rows[-21] if len(rows) >= 21 else rows[0]
    return {
        "as_of": latest["date"],
        "above_200d": latest["above_200d"],
        "above_50d": latest["above_50d"],
        "above_200d_change": latest["above_200d"] - month_ago["above_200d"],
        "above_50d_change": latest["above_50d"] - month_ago["above_50d"],
        "compared_with": month_ago["date"],
        "bearish_200": latest["bearish_200"],
        "bearish_50": latest["bearish_50"],
        "stale": latest["date"] != date.today().isoformat(),
    }
