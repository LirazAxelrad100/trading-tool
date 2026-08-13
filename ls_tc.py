"""Lang & Schwarz (ls-tc.de) price lookups by ISIN — the actual EUR price Trade
Republic trades against (TR executes US-stock orders via L&S), rather than an
approximation reverse-engineered from a different exchange's price (see
apply_quote in main.py). Public site, no login, robots.txt fully permissive,
and Terms of Use explicitly allow reproduction for personal/private/
non-commercial purposes — the exact shape of this tool. Scoped to holdings
only (a small, user-curated set the user opts into via a manually-entered
ISIN), not to the Opportunities/Opportunities B screening lists — those cover
hundreds of tickers with no reliable free ticker-to-ISIN source, so the
resolve-by-ISIN approach this module depends on doesn't scale there.

Uses ls-tc.de's own internal JSON endpoints (the same ones its own frontend
calls), not HTML scraping.
"""

import json
from pathlib import Path
from typing import Optional

import requests

BASE_URL = "https://www.ls-tc.de"
DATA_DIR = Path(__file__).parent / "data"
CACHE_FILE = DATA_DIR / "ls_tc_cache.json"
# A descriptive, honest User-Agent rather than spoofing a browser.
HEADERS = {"User-Agent": "trading-tool/1.0 (personal, non-commercial portfolio tracker)"}
TIMEOUT = 10


class LsTcError(Exception):
    pass


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    return json.loads(CACHE_FILE.read_text())


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def resolve_instrument_id(isin: str) -> int:
    """ls-tc.de's internal instrumentId for an ISIN, cached since the mapping
    never changes. Raises LsTcError if no matching stock instrument is found —
    ls-tc.de's search only reliably matches by ISIN/WKN, not by ticker or
    company name (both tested unreliable: "AMD" matched "AMDOCS", and the full
    company name matched nothing)."""
    isin = isin.strip().upper()
    cache = _load_cache()
    if isin in cache:
        return cache[isin]["instrument_id"]

    try:
        resp = requests.get(
            f"{BASE_URL}/_rpc/json/.lstc/instrument/search/main",
            params={"q": isin, "localeId": 2},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise LsTcError(f"ls-tc.de search failed for {isin}: {e}")

    match = next(
        (r for r in results if r.get("isin") == isin and r.get("categorySymbol") == "STK"),
        None,
    )
    if not match:
        raise LsTcError(f"No ls-tc.de stock instrument found for ISIN {isin}")

    instrument_id = match["instrumentId"]
    cache[isin] = {"instrument_id": instrument_id, "displayname": match.get("displayname")}
    _save_cache(cache)
    return instrument_id


def fetch_price(isin: str) -> dict:
    """Current mid price in EUR for this ISIN, plus the previous close, both
    straight from Lang & Schwarz so day_change_pct is derived from the same
    source as the price (never mixed with a different exchange's reference
    point). day_change_pct is a ratio (e.g. -0.074), matching prices.py's
    convention. Raises LsTcError if no live intraday tick is available (e.g.
    outside L&S trading hours, ~07:30-23:00 CET)."""
    instrument_id = resolve_instrument_id(isin)

    try:
        resp = requests.get(
            f"{BASE_URL}/_rpc/json/instrument/chart/dataForInstrument",
            params={
                "container": "chart1",
                "instrumentId": instrument_id,
                "marketId": 1,
                "quotetype": "mid",
                "series": "intraday",
                "type": "mini",
                "localeId": 2,
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise LsTcError(f"ls-tc.de price fetch failed for {isin}: {e}")

    intraday = ((data.get("series") or {}).get("intraday") or {}).get("data") or []
    if not intraday:
        raise LsTcError(f"No live intraday price for {isin} (L&S market likely closed)")
    price = intraday[-1][1]

    previous_close = None
    for line in (data.get("info") or {}).get("plotlines") or []:
        if line.get("id") == "previousDay":
            previous_close = line.get("value")

    day_change_pct = (price - previous_close) / previous_close if previous_close else None

    return {
        "price": price,
        "previous_close": previous_close,
        "day_change_pct": day_change_pct,
        "instrument_id": instrument_id,
    }
