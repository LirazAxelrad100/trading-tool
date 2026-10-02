"""What a company's insiders did with their own shares over the last 12 months, from SEC Form 4.

Every other opinion in this tool comes from analysts, and Zacks' rank and the Finnhub
consensus are built from the same brokers' analysts, so more of either is not a second view.
Insider filings are a different kind of evidence: legally required reports of what the people
running the company actually did.

Two distinctions decide whether a trade means anything, and Finnhub's free feed has neither
(it drops the trade type and has no "scheduled" flag):

- **Purchases on the open market (code P) are the signal.** Insiders sell for many reasons
  (tax, a house, diversifying); they buy for one.
- **Sales split three ways.** Sales under a Rule 10b5-1 plan were set months in advance and
  say little about today. Sales on the day of an option exercise turn pay into cash. Only the
  rest were timed by the insider, and those are the ones worth reading.

Real case (TOST, 2026-10-01): the Analyze prose called it "the CFO selling massively". The
filings showed every sale by the CEO, CFO and CRO was under a plan adopted 5–9 months earlier.

Access: SEC requires a User-Agent naming a contact email, or it refuses with 403. The address
comes from `SEC_CONTACT_EMAIL` in `.env` and goes nowhere but SEC's servers; never log or print
it. SEC allows 10 requests a second; this stays well under. A Form 4 never changes once filed,
so each is parsed once and cached for good; the list of filings is cached per ticker per day.
"""

import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DATA = Path(__file__).parent / "data"
TICKERS_FILE = DATA / "sec_tickers.json"
FILINGS_CACHE_FILE = DATA / "sec_filings_cache.json"
FORM4_CACHE_FILE = DATA / "form4_cache.json"
TICKERS_REFRESH_DAYS = 30
WINDOW_DAYS = 365
MAX_FILINGS = 150  # a very active company files hundreds; the newest year is what matters
PAUSE_SECONDS = 0.15
PARSE_VERSION = 2  # bump when parse_form4() learns a field, so cached filings are re-read
PAY_DAYS = 3  # a sale this soon after an exercise is the exercise being cashed in


class InsiderError(Exception):
    pass


def _headers() -> dict:
    email = os.environ.get("SEC_CONTACT_EMAIL")
    if not email:
        raise InsiderError("SEC_CONTACT_EMAIL is not set in .env")
    return {"User-Agent": f"trading-tool personal research {email}"}


_last_call = 0.0


def _get(url: str) -> requests.Response:
    global _last_call
    wait = PAUSE_SECONDS - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()
    try:
        res = requests.get(url, headers=_headers(), timeout=20)
        res.raise_for_status()
        return res
    except requests.RequestException as e:
        # The message names the URL only; the header with the email is never included.
        raise InsiderError(f"SEC request failed: {url.split('?')[0]} ({getattr(e.response, 'status_code', 'no response')})") from None


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _cik(ticker: str) -> Optional[int]:
    stored = _load(TICKERS_FILE)
    fresh = stored.get("fetched") and (date.today() - date.fromisoformat(stored["fetched"])).days < TICKERS_REFRESH_DAYS
    if not fresh:
        rows = _get("https://www.sec.gov/files/company_tickers.json").json()
        stored = {"fetched": date.today().isoformat(), "map": {r["ticker"]: r["cik_str"] for r in rows.values()}}
        TICKERS_FILE.write_text(json.dumps(stored))
    return stored["map"].get(ticker.upper())


def _filings(ticker: str, cik: int) -> list:
    """This company's Form 4 filings over the window, newest first."""
    cache = _load(FILINGS_CACHE_FILE)
    today = date.today().isoformat()
    if cache.get(ticker, {}).get("fetched") == today:
        return cache[ticker]["filings"]
    recent = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]["recent"]
    since = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()
    out = []
    for i, form in enumerate(recent["form"]):
        if form == "4" and recent["filingDate"][i] >= since:
            out.append({
                "accession": recent["accessionNumber"][i],
                "filed": recent["filingDate"][i],
                # The primary document is the styled view ("xslF345X06/form4.xml"); the raw XML
                # sits at the same name without the style folder.
                "doc": recent["primaryDocument"][i].split("/")[-1],
            })
    out = out[:MAX_FILINGS]
    cache[ticker] = {"fetched": today, "filings": out}
    FILINGS_CACHE_FILE.write_text(json.dumps(cache))
    return out


def _text(node, path: str) -> Optional[str]:
    found = node.find(path)
    return found.text.strip() if found is not None and found.text else None


def _num(node, path: str) -> Optional[float]:
    try:
        return float(_text(node, path))
    except (TypeError, ValueError):
        return None


def parse_form4(xml: str) -> dict:
    """The parts of one Form 4 that matter here: who, their role, whether the filing is
    marked as made under a 10b5-1 plan, and each share transaction."""
    root = ET.fromstring(xml)
    owners = root.findall("reportingOwner")
    names = [_text(o, "reportingOwnerId/rptOwnerName") for o in owners]
    rel = owners[0].find("reportingOwnerRelationship") if owners else None
    title = None
    if rel is not None:
        title = _text(rel, "officerTitle")
        if not title and _text(rel, "isDirector") in ("1", "true"):
            title = "Director"
        if not title and _text(rel, "isTenPercentOwner") in ("1", "true"):
            title = "10% owner"
    notes = {f.get("id"): " ".join(f.itertext()) for f in root.iter("footnote")}
    # The checkbox exists on filings since April 2023 and covers the filing as a whole; each
    # transaction's own footnotes say which kind it was, so they are read first.
    plan = _text(root, "aff10b5One") in ("1", "true")
    trades = []
    for t in root.iter("nonDerivativeTransaction"):
        text = " ".join(notes.get(ref.get("id"), "") for ref in t.iter("footnoteId")).lower()
        trades.append({
            "date": (_text(t, "transactionDate/value") or "")[:10],
            "code": _text(t, "transactionCoding/transactionCode"),
            "shares": _num(t, "transactionAmounts/transactionShares/value") or 0.0,
            "price": _num(t, "transactionAmounts/transactionPricePerShare/value"),
            "note_plan": "10b5-1" in text,
            # "Sell to cover": shares the company sells automatically to pay the tax due when
            # stock pay vests. Usually the day after vesting, so the same-day rule misses it.
            "note_tax": any(k in text for k in ("tax withholding", "sell-to-cover", "sell to cover",
                                                "cover tax", "not represent a discretionary")),
        })
    return {"v": PARSE_VERSION, "name": " / ".join(n for n in names if n), "title": title, "plan": plan, "trades": trades}


def _form4(cik: int, filing: dict, cache: dict) -> Optional[dict]:
    key = filing["accession"]
    if cache.get(key, {}).get("v") != PARSE_VERSION:
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{key.replace('-', '')}/{filing['doc']}"
        try:
            cache[key] = parse_form4(_get(url).text)
        except (InsiderError, ET.ParseError):
            return None  # one unreadable filing should not cost the whole summary
    return cache[key]


def summary(ticker: str) -> dict:
    """Purchases, then sales split into scheduled / from exercised options / own timing, over
    the last 12 months. Amounts in USD, as filed."""
    ticker = ticker.upper()
    cik = _cik(ticker)
    if cik is None:
        return {"error": f"{ticker} files no insider reports with the SEC (not a US-listed company)."}
    filings = _filings(ticker, cik)
    cache = _load(FORM4_CACHE_FILE)
    before = len(cache)
    since = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()

    bought, own_timing = {}, {}
    # tax: sold automatically to pay the tax on vesting stock pay. scheduled: under a 10b5-1
    # plan. own_timing: everything else, including exercising options and selling at once,
    # since when to exercise is the insider's choice (options_part says how much of it was).
    sold = {"tax": 0.0, "scheduled": 0.0, "own_timing": 0.0}
    options_part = 0.0
    try:
        for f in filings:
            doc = _form4(cik, f, cache)
            if not doc:
                continue
            vested = [date.fromisoformat(t["date"]) for t in doc["trades"] if t["code"] == "M" and t["date"]]
            for t in doc["trades"]:
                if t["date"] < since or t["code"] not in ("P", "S"):
                    continue
                value = t["shares"] * (t["price"] or 0)
                day = date.fromisoformat(t["date"])
                if t["code"] == "P":
                    p = bought.setdefault(doc["name"], {"name": doc["name"], "title": doc["title"], "value": 0.0})
                    p["value"] += value
                elif t["note_tax"]:
                    sold["tax"] += value
                elif t["note_plan"] or doc["plan"]:
                    sold["scheduled"] += value
                else:
                    sold["own_timing"] += value
                    if any(0 <= (day - v).days <= PAY_DAYS for v in vested):
                        options_part += value
                    s = own_timing.setdefault(doc["name"], {"name": doc["name"], "title": doc["title"], "value": 0.0})
                    s["value"] += value
    finally:
        if len(cache) != before:
            FORM4_CACHE_FILE.write_text(json.dumps(cache))

    by_value = lambda d: sorted(d.values(), key=lambda p: -p["value"])
    return {
        "ticker": ticker,
        "since": since,
        "filings": len(filings),
        "bought": by_value(bought),
        "bought_value": sum(p["value"] for p in bought.values()),
        "sold": sold,
        "sold_value": sum(sold.values()),
        "own_timing_from_options": options_part,
        "own_timing": by_value(own_timing)[:3],
    }
