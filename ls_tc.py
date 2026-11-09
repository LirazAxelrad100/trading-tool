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
import re
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


# --- Finding an ISIN from a ticker (2026-11-09) -----------------------------------------
# Trade Republic's trade screens never show the ISIN, so a purchase recorded from them
# came in without one and was priced from the Finnhub approximation (LLY and MSFT, the day
# this was written). L&S's search does not match tickers ("AMD" finds AMDOCS, "DK" finds
# Danish shares) and matches full company names poorly ("Microsoft Corporation" finds
# nothing, "Microsoft" does), so the name is cleaned and shortened word by word. Shortening
# makes it noisy ("West" for West Pharmaceutical also finds Western Digital), so a candidate
# is accepted only when its L&S price agrees with the US price converted to EUR. That also
# rejects CDRs and ADRs with a share ratio, whose prices are a fraction or a multiple.

LOOKUP_CACHE_FILE = DATA_DIR / "isin_lookup_cache.json"
PRICE_TOLERANCE = 0.06  # FX timing and L&S's own quote; real mismatches are far larger
MAX_CANDIDATES = 6
_NAME_NOISE = re.compile(
    r"\b(inc|incorporated|corp|corporation|company|co|ltd|limited|plc|holdings?|group|"
    r"sa|nv|ag|se|the|and|class [a-c])\b\.?",
    re.I,
)


def _search(query: str) -> list:
    resp = requests.get(
        f"{BASE_URL}/_rpc/json/.lstc/instrument/search/main",
        params={"q": query, "localeId": 2},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return [r for r in resp.json() if r.get("categorySymbol") == "STK" and r.get("isin")]


def _last_price(instrument_id: int) -> Optional[float]:
    """The live mid price, or the last daily close outside L&S's trading hours."""
    for series, kind in (("intraday", "mini"), ("history", "mini")):
        try:
            resp = requests.get(
                f"{BASE_URL}/_rpc/json/instrument/chart/dataForInstrument",
                params={
                    "container": "chart1",
                    "instrumentId": instrument_id,
                    "marketId": 1,
                    "quotetype": "mid",
                    "series": series,
                    "type": kind,
                    "localeId": 2,
                },
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            points = ((resp.json().get("series") or {}).get(series) or {}).get("data") or []
        except (requests.RequestException, ValueError):
            continue
        if points:
            return points[-1][1]
    return None


def _name_queries(company: str) -> list:
    """Longest first: the full cleaned name, then one word fewer each time, then the first
    word's first four letters, because L&S abbreviates ("WESTN DIGITAL", "WEST PHARM.SVCS")."""
    words = _NAME_NOISE.sub(" ", re.sub(r"[,.()&+]", " ", company)).split()
    queries = []
    for k in range(len(words), 0, -1):
        queries.append(" ".join(words[:k]))
        if len(words[k - 1]) > 4:  # "Meta Plat" finds "META PLATF.", "Meta Platforms" doesn't
            queries.append(" ".join(words[: k - 1] + [words[k - 1][:4]]))
    return list(dict.fromkeys(queries))


def _name_score(company_words: list, displayname: str) -> int:
    """How many of the company's words L&S's abbreviated name starts the same way (4 letters)."""
    tokens = re.split(r"[\s.,+/-]+", displayname.upper())
    return sum(any(t.startswith(w[:4].upper()) for t in tokens if t) for w in company_words)


def find_isin(ticker: str, company: str, expected_eur: float) -> Optional[dict]:
    """The ISIN of the L&S share whose price matches `expected_eur`, or None. Searches the
    company name from longest to shortest; within one search, candidates are tried in order
    of how well the name fits, and the closest price wins. Share classes of one company
    (Alphabet A and C) are priced almost alike, so any other match is returned as `others`
    for her to compare with what Trade Republic shows."""
    ticker = ticker.strip().upper()
    cache = json.loads(LOOKUP_CACHE_FILE.read_text()) if LOOKUP_CACHE_FILE.exists() else {}
    if ticker in cache:
        return cache[ticker]
    words = _NAME_NOISE.sub(" ", re.sub(r"[,.()&+]", " ", company or "")).split()
    seen = set()
    for query in _name_queries(company or ""):
        try:
            results = _search(query)
        except (requests.RequestException, ValueError):
            continue
        results = [r for r in results if r["isin"] not in seen]
        results.sort(key=lambda r: -_name_score(words, r.get("displayname", "")))
        matches = []
        for r in results[:MAX_CANDIDATES]:
            seen.add(r["isin"])
            price = _last_price(r["instrumentId"])
            if price and abs(price / expected_eur - 1) <= PRICE_TOLERANCE:
                name = re.sub(r"\s+(DL|EO)-.*$|\s{2,}.*$", "", r.get("displayname", "")).strip()
                matches.append({"isin": r["isin"], "name": name, "ls_price": price})
        if matches:
            matches.sort(key=lambda m: abs(m["ls_price"] / expected_eur - 1))
            found = dict(matches[0], others=[{"isin": m["isin"], "name": m["name"]} for m in matches[1:]])
            cache[ticker] = found
            LOOKUP_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
            return found
    return None
