"""Sector relative-strength — ranks the 11 GICS sectors by trailing return (via the
SPDR sector ETFs), so a stock's analysis can be read *in the context of its sector's
current momentum*. Descriptive only ("this sector has been strong/weak lately"),
never a forecast that a sector "will" outperform — same no-directive line as elsewhere.

Cheap and slow-moving: refreshed once a day (sector trends don't move intraday), from
the daily-price cache we already use for charts.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import alpha_vantage
import prices

DATA_DIR = Path(__file__).parent / "data"
SP500_FILE = DATA_DIR / "sp500.json"
STRENGTH_FILE = DATA_DIR / "sector_strength.json"
TICKER_SECTOR_FILE = DATA_DIR / "ticker_sectors.json"

# GICS sector -> its SPDR sector ETF. Keys match the "GICS Sector" strings in sp500.json.
SECTOR_ETF = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}

# Finnhub 'finnhubIndustry' -> GICS sector, for tickers not in the S&P 500 universe.
FINNHUB_TO_GICS = {
    "Semiconductors": "Information Technology",
    "Technology": "Information Technology",
    "Software": "Information Technology",
    "Hardware": "Information Technology",
    "Electronic Equipment": "Information Technology",
    "Pharmaceuticals": "Health Care",
    "Biotechnology": "Health Care",
    "Health Care": "Health Care",
    "Life Sciences Tools & Services": "Health Care",
    "Medical Devices": "Health Care",
    "Banking": "Financials",
    "Financial Services": "Financials",
    "Insurance": "Financials",
    "Energy": "Energy",
    "Oil & Gas": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Chemicals": "Materials",
    "Metals & Mining": "Materials",
    "Media": "Communication Services",
    "Telecommunication": "Communication Services",
    "Communications": "Communication Services",
    "Retail": "Consumer Discretionary",
    "Automobiles": "Consumer Discretionary",
    "Auto Components": "Consumer Discretionary",
    "Textiles Apparel & Luxury Goods": "Consumer Discretionary",
    "Hotels Restaurants & Leisure": "Consumer Discretionary",
    "Food Products": "Consumer Staples",
    "Beverages": "Consumer Staples",
    "Tobacco": "Consumer Staples",
    "Industrial Conglomerates": "Industrials",
    "Machinery": "Industrials",
    "Aerospace & Defense": "Industrials",
    "Airlines": "Industrials",
    "Road & Rail": "Industrials",
    "Logistics & Transportation": "Industrials",
    "Building": "Industrials",
    "Construction": "Industrials",
}

TRADING_DAYS_1M = 21
TRADING_DAYS_3M = 63
# Alpha Vantage free tier is 5 requests/minute — space the 11 ETF pulls out so a
# daily build reliably completes (it's a background/once-a-day job, ~2.5 min).
AV_RATE_SLEEP = 13


def _load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def load_sector_strength() -> dict:
    return _load_json(STRENGTH_FILE, {"generated_at": None, "sectors": {}})


def build_sector_strength() -> dict:
    """Rank the 11 sectors by trailing 3-month return (with 1-month alongside). Uses
    alpha_vantage.fetch_daily_prices, which caches per ETF per day, so a daily refresh
    is 11 calls at most."""
    sectors = {}
    for i, (sector, etf) in enumerate(SECTOR_ETF.items()):
        if i > 0:
            time.sleep(AV_RATE_SLEEP)  # respect Alpha Vantage 5/min
        try:
            hist = alpha_vantage.fetch_daily_prices(etf, days=90)  # [{date, close}], oldest first
        except alpha_vantage.AlphaVantageError:
            continue
        closes = [p["close"] for p in hist]
        if len(closes) < TRADING_DAYS_3M + 1:
            continue
        last = closes[-1]
        sectors[sector] = {
            "etf": etf,
            "ret_1m": (last - closes[-TRADING_DAYS_1M - 1]) / closes[-TRADING_DAYS_1M - 1],
            "ret_3m": (last - closes[-TRADING_DAYS_3M - 1]) / closes[-TRADING_DAYS_3M - 1],
        }

    ranked = sorted(sectors.items(), key=lambda kv: kv[1]["ret_3m"], reverse=True)
    total = len(ranked)
    for i, (_, d) in enumerate(ranked, start=1):
        d["rank"] = i
        d["total"] = total

    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "sectors": sectors}
    STRENGTH_FILE.write_text(json.dumps(out, indent=2))
    return out


def _sp500_sectors() -> dict:
    data = _load_json(SP500_FILE, {"constituents": {}})
    return {t: v.get("sector") for t, v in data.get("constituents", {}).items()}


def ticker_sector(ticker: str) -> Optional[str]:
    """Map a ticker to one of the 11 GICS sectors: S&P 500 membership first, else a
    (cached) Finnhub industry lookup. Returns None if it can't be mapped."""
    ticker = ticker.upper()
    sp = _sp500_sectors()
    if sp.get(ticker) in SECTOR_ETF:
        return sp[ticker]

    cache = _load_json(TICKER_SECTOR_FILE, {})
    if ticker in cache:
        return cache[ticker]

    sector = None
    try:
        sector = FINNHUB_TO_GICS.get(prices.fetch_industry(ticker))
    except prices.PriceError:
        sector = None
    cache[ticker] = sector
    TICKER_SECTOR_FILE.write_text(json.dumps(cache, indent=2))
    return sector


def sector_context(ticker: str) -> Optional[dict]:
    """A ticker's sector plus where that sector currently stands in relative strength —
    for the Analyze/Compare popup. None if the ticker can't be mapped to a sector."""
    sector = ticker_sector(ticker)
    if not sector:
        return None
    strength = load_sector_strength()["sectors"].get(sector)
    if not strength or not strength.get("rank"):
        return {"sector": sector, "rank": None, "total": None, "ret_3m": None, "standing": None}

    rank, total = strength["rank"], strength["total"]
    if rank <= total / 3:
        standing = "leading"
    elif rank <= 2 * total / 3:
        standing = "middle"
    else:
        standing = "lagging"
    return {
        "sector": sector,
        "rank": rank,
        "total": total,
        "ret_1m": strength["ret_1m"],
        "ret_3m": strength["ret_3m"],
        "standing": standing,
    }
