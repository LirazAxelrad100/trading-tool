import json
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY")
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
PRICE_HISTORY_CACHE_FILE = Path(__file__).parent / "data" / "price_history_cache.json"
NEWS_SENTIMENT_CACHE_FILE = Path(__file__).parent / "data" / "news_sentiment_cache.json"


class AlphaVantageError(Exception):
    """Its message reaches the screen (the Add form's stop hint, Analyze), and Alpha Vantage's
    own rate-limit text quotes the API key back, as does a requests error's URL. So the key
    is masked here, once, rather than at every raise (2026-11-09: seen on the Add form)."""

    def __init__(self, message: str = ""):
        message = str(message)
        if ALPHA_VANTAGE_API_KEY:
            message = message.replace(ALPHA_VANTAGE_API_KEY, "[your key]")
        super().__init__(message)


# The free key refuses bursts faster than about one call a second, and the web server answers
# requests in parallel threads. Six stop-hit panels asking at once on page load lost five of
# their six answers (2026-11-07). Every call takes the next free slot, so a burst just waits.
MIN_CALL_GAP_SECONDS = 1.5
_slot_lock = threading.Lock()
_next_slot = 0.0


def _wait_for_slot() -> None:
    global _next_slot
    with _slot_lock:
        now = time.time()
        slot = max(now, _next_slot)
        _next_slot = slot + MIN_CALL_GAP_SECONDS
    if slot > now:
        time.sleep(slot - now)


def _write_json(path: Path, data) -> None:
    """Write to a temp file and swap it in. Two charts opened at once run in parallel
    threads; a plain write_text from both left the longer write's tail after the shorter
    one, and the cache stopped parsing (2026-11-01)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _load_news_sentiment_cache() -> dict:
    if not NEWS_SENTIMENT_CACHE_FILE.exists():
        return {}
    return json.loads(NEWS_SENTIMENT_CACHE_FILE.read_text())


def _save_news_sentiment_cache(cache: dict) -> None:
    _write_json(NEWS_SENTIMENT_CACHE_FILE, cache)


def fetch_news_sentiment(ticker: str, limit: int = 10) -> dict:
    """Cached per ticker per day, same as fetch_daily_prices — Analyze can be clicked on the
    same ticker more than once in a day, and this shares Alpha Vantage's 25-requests/day
    free-tier cap with price history."""
    cache = _load_news_sentiment_cache()
    today = date.today().isoformat()
    cached = cache.get(ticker)
    if cached and cached.get("fetched_date") == today:
        return cached["result"]

    if not ALPHA_VANTAGE_API_KEY:
        raise AlphaVantageError("ALPHA_VANTAGE_API_KEY is not set in .env")
    _wait_for_slot()
    try:
        res = requests.get(
            ALPHA_VANTAGE_URL,
            params={"function": "NEWS_SENTIMENT", "tickers": ticker, "apikey": ALPHA_VANTAGE_API_KEY},
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
    except requests.RequestException as e:
        raise AlphaVantageError(f"Could not fetch news sentiment for '{ticker}': {e}") from e

    if "feed" not in data:
        message = data.get("Information") or data.get("Note") or data.get("Error Message") or "Unknown error"
        raise AlphaVantageError(f"Alpha Vantage did not return sentiment data for '{ticker}': {message}")

    articles = []
    scores = []
    for item in data["feed"]:
        ticker_entries = [t for t in item.get("ticker_sentiment", []) if t.get("ticker") == ticker]
        if not ticker_entries:
            continue
        entry = ticker_entries[0]
        try:
            score = float(entry["ticker_sentiment_score"])
        except (KeyError, ValueError):
            continue
        articles.append(
            {
                "title": item.get("title"),
                "source": item.get("source"),
                "time_published": item.get("time_published"),
                "sentiment_label": entry.get("ticker_sentiment_label"),
                "sentiment_score": score,
            }
        )
        scores.append(score)
        if len(articles) >= limit:
            break

    average_score = sum(scores) / len(scores) if scores else None
    result = {
        "average_score": average_score,
        "article_count": len(articles),
        "articles": articles,
    }
    cache[ticker] = {"fetched_date": today, "result": result}
    _save_news_sentiment_cache(cache)
    return result


DIVIDENDS_CACHE_FILE = Path(__file__).parent / "data" / "dividends_cache.json"
DIVIDENDS_REFRESH_DAYS = 7  # dividends are declared ~2 weeks ahead and paid quarterly


def fetch_dividends(ticker: str, cached_only: bool = False) -> list:
    """Every dividend Alpha Vantage knows for a ticker, newest first: payment date, ex-date
    and amount per share in USD. It includes ones already declared but not yet paid.
    Finnhub's equivalent is paid-tier (403, live-tested 2026-10-01).

    Cached a week per ticker: the list only changes when a new dividend is declared, and the
    free key's 25 calls a day are shared with price history and sentiment. A failed fetch
    falls back to whatever is cached, however old, since a dividend paid stays paid."""
    cache = json.loads(DIVIDENDS_CACHE_FILE.read_text()) if DIVIDENDS_CACHE_FILE.exists() else {}
    cached = cache.get(ticker)
    fresh = cached and (date.today() - date.fromisoformat(cached["fetched_date"])).days < DIVIDENDS_REFRESH_DAYS
    if fresh or (cached and cached_only):
        return cached["dividends"]
    if cached_only:
        raise AlphaVantageError(f"No dividends cached for '{ticker}'")
    if not ALPHA_VANTAGE_API_KEY:
        raise AlphaVantageError("ALPHA_VANTAGE_API_KEY is not set in .env")

    _wait_for_slot()
    try:
        res = requests.get(
            ALPHA_VANTAGE_URL,
            params={"function": "DIVIDENDS", "symbol": ticker, "apikey": ALPHA_VANTAGE_API_KEY},
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
    except requests.RequestException as e:
        if cached:
            return cached["dividends"]
        raise AlphaVantageError(f"Could not fetch dividends for '{ticker}': {e}") from e

    rows = data.get("data")
    if not isinstance(rows, list):
        if cached:
            return cached["dividends"]
        message = data.get("Information") or data.get("Note") or data.get("Error Message") or "Unknown error"
        raise AlphaVantageError(f"Alpha Vantage did not return dividends for '{ticker}': {message}")

    dividends = []
    for r in rows:
        try:
            dividends.append({
                "payment_date": r["payment_date"],
                "ex_dividend_date": r["ex_dividend_date"],
                "amount": float(r["amount"]),
            })
        except (KeyError, ValueError, TypeError):
            continue  # "None" dates on very old rows
    dividends = [d for d in dividends if d["payment_date"][:1].isdigit()]
    dividends.sort(key=lambda d: d["payment_date"], reverse=True)
    cache[ticker] = {"fetched_date": date.today().isoformat(), "dividends": dividends[:12]}
    _write_json(DIVIDENDS_CACHE_FILE, cache)
    return cache[ticker]["dividends"]


def _load_price_history_cache() -> dict:
    if not PRICE_HISTORY_CACHE_FILE.exists():
        return {}
    return json.loads(PRICE_HISTORY_CACHE_FILE.read_text())


def _save_price_history_cache(cache: dict) -> None:
    _write_json(PRICE_HISTORY_CACHE_FILE, cache)


def prices_cached_today(ticker: str) -> bool:
    """Whether fetch_daily_prices() would answer from cache, i.e. without spending a call."""
    cached = _load_price_history_cache().get(ticker)
    return bool(cached) and cached.get("fetched_date") == date.today().isoformat()


def cached_closes(ticker: str) -> dict:
    """{date: close} from whatever this ticker's cache holds, however old. Never fetches —
    for readings that should cost nothing and can live with history that stops a few days
    back. Corrected for splits already known; see _apply_splits()."""
    cached = _load_price_history_cache().get(ticker) or {}
    bars = _apply_splits(cached.get("prices", []), _cached_splits(ticker))
    return {p["date"]: p["close"] for p in bars}


# TIME_SERIES_DAILY is not adjusted for splits, and its adjusted twin is paid-tier. APH's 2-for-1
# on 2026-09-03 read as a one-day fall of 48,7%, which took its yearly swing figure to 119% and
# its level to "Very high". So the raw bars stay in the cache and every read divides the bars
# before a split by its factor.
#
# Asking for splits costs a call, so it is asked only when the bars show a one-day move big
# enough to be one. 5-for-4 is about the smallest split in practice, and it reads as -20%.
SPLITS_CACHE_FILE = Path(__file__).parent / "data" / "splits_cache.json"
SPLIT_SUSPECT_DOWN = 0.82
SPLIT_SUSPECT_UP = 1.2


def _load_splits_cache() -> dict:
    if not SPLITS_CACHE_FILE.exists():
        return {}
    return json.loads(SPLITS_CACHE_FILE.read_text())


def _cached_splits(ticker: str) -> list:
    return (_load_splits_cache().get(ticker) or {}).get("splits", [])


def _latest_suspect_day(bars: list) -> Optional[str]:
    """The newest day whose close moved enough, against the day before, to possibly be a split."""
    latest = None
    for i in range(1, len(bars)):
        ratio = bars[i]["close"] / bars[i - 1]["close"]
        if ratio < SPLIT_SUSPECT_DOWN or ratio > SPLIT_SUSPECT_UP:
            latest = bars[i]["date"]
    return latest


def _refresh_splits(ticker: str, bars: list) -> list:
    """Splits for a ticker, asking Alpha Vantage only if a suspect day is newer than the last
    time it was asked. Strictly newer, so a split the feed hadn't listed yet on its own day is
    asked about again the next day. A real move (RDDT -29%) costs one call and is then settled.
    A failed call changes nothing and is tried again on the next day's fetch."""
    cache = _load_splits_cache()
    cached = cache.get(ticker)
    suspect = _latest_suspect_day(bars)
    if not suspect or (cached and cached["fetched_date"] > suspect):
        return (cached or {}).get("splits", [])

    _wait_for_slot()
    try:
        res = requests.get(
            ALPHA_VANTAGE_URL,
            params={"function": "SPLITS", "symbol": ticker, "apikey": ALPHA_VANTAGE_API_KEY},
            timeout=15,
        )
        res.raise_for_status()
        rows = res.json().get("data")
    except (requests.RequestException, ValueError):
        return (cached or {}).get("splits", [])
    if not isinstance(rows, list):
        return (cached or {}).get("splits", [])

    splits = []
    for r in rows:
        try:
            splits.append({"date": r["effective_date"], "factor": float(r["split_factor"])})
        except (KeyError, ValueError, TypeError):
            continue
    cache[ticker] = {"fetched_date": date.today().isoformat(), "splits": splits}
    _write_json(SPLITS_CACHE_FILE, cache)
    return splits


def _apply_splits(bars: list, splits: list) -> list:
    """New bars in today's share terms. A split's date is its first day at the new price, so
    only earlier bars change. Never edits the bars passed in: those are the cache's raw record."""
    usable = [s for s in splits if s["factor"] > 0 and s["factor"] != 1]
    if not usable:
        return bars
    out = []
    for bar in bars:
        factor = 1.0
        for s in usable:
            if bar["date"] < s["date"]:
                factor *= s["factor"]
        if factor == 1.0:
            out.append(bar)
            continue
        fixed = dict(bar)
        for key in ("open", "high", "low", "close"):
            if key in fixed:
                fixed[key] = fixed[key] / factor
        if "volume" in fixed:
            fixed["volume"] = fixed["volume"] * factor
        out.append(fixed)
    return out


WEEKLY_CACHE_FILE = Path(__file__).parent / "data" / "weekly_prices_cache.json"
WEEKLY_REFRESH_DAYS = 7


def fetch_weekly_prices(ticker: str, cached_only: bool = False) -> Optional[list]:
    """One close per week for the whole history, oldest first, in USD. Daily history stops at
    100 trading days on the free key, and this is the free way to see years (live-tested
    2026-11-07: APH back to 1999). The closes are the feed's adjusted ones, so splits and
    dividends are already accounted for.

    Cached a week per ticker: one more week changes little on a chart of years, and the free
    key's 25 calls a day are shared. cached_only returns None rather than spending a call. A
    failed fetch falls back to whatever is cached, however old."""
    cache = json.loads(WEEKLY_CACHE_FILE.read_text()) if WEEKLY_CACHE_FILE.exists() else {}
    cached = cache.get(ticker)
    fresh = cached and (date.today() - date.fromisoformat(cached["fetched_date"])).days < WEEKLY_REFRESH_DAYS
    if fresh or (cached and cached_only):
        return cached["prices"]
    if cached_only:
        return None
    if not ALPHA_VANTAGE_API_KEY:
        raise AlphaVantageError("ALPHA_VANTAGE_API_KEY is not set in .env")
    _wait_for_slot()
    try:
        res = requests.get(
            ALPHA_VANTAGE_URL,
            params={"function": "TIME_SERIES_WEEKLY_ADJUSTED", "symbol": ticker, "apikey": ALPHA_VANTAGE_API_KEY},
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
    except (requests.RequestException, ValueError) as e:
        if cached:
            return cached["prices"]
        raise AlphaVantageError(f"Could not fetch weekly prices for '{ticker}'") from e

    series = data.get("Weekly Adjusted Time Series")
    if not series:
        if cached:
            return cached["prices"]
        message = data.get("Information") or data.get("Note") or data.get("Error Message") or "Unknown error"
        raise AlphaVantageError(f"Alpha Vantage did not return weekly prices for '{ticker}': {message}")

    prices = sorted(
        ({"date": d, "close": float(row["5. adjusted close"])} for d, row in series.items()),
        key=lambda r: r["date"],
    )
    cache[ticker] = {"fetched_date": date.today().isoformat(), "prices": prices}
    _write_json(WEEKLY_CACHE_FILE, cache)
    return prices


def fetch_daily_prices(ticker: str, days: int = 30) -> list:
    """Daily OHLCV bars for a ticker, oldest first, in USD. Cached per ticker per day
    since this shares Alpha Vantage's 25-requests/day free-tier cap with sentiment.

    Alpha Vantage returns open/high/low/volume in the same response as the close, so
    keeping them costs no extra call — momentum.py reads them for burst signals. Entries
    cached earlier under the close-only format have no OHLC keys; callers that need them
    must degrade rather than assume (self-heals on the next day's refetch).

    Prices are in today's share terms: see _apply_splits()."""
    cache = _load_price_history_cache()
    today = date.today().isoformat()
    cached = cache.get(ticker)
    if cached and cached.get("fetched_date") == today:
        return _apply_splits(cached["prices"], _cached_splits(ticker))[-days:]

    if not ALPHA_VANTAGE_API_KEY:
        raise AlphaVantageError("ALPHA_VANTAGE_API_KEY is not set in .env")
    _wait_for_slot()
    try:
        res = requests.get(
            ALPHA_VANTAGE_URL,
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker,
                "outputsize": "compact",
                "apikey": ALPHA_VANTAGE_API_KEY,
            },
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
    except requests.RequestException as e:
        raise AlphaVantageError(f"Could not fetch price history for '{ticker}': {e}") from e

    series = data.get("Time Series (Daily)")
    if not series:
        message = data.get("Information") or data.get("Note") or data.get("Error Message") or "Unknown error"
        raise AlphaVantageError(f"Alpha Vantage did not return price history for '{ticker}': {message}")

    prices = sorted(
        (
            {
                "date": d,
                "open": float(row["1. open"]),
                "high": float(row["2. high"]),
                "low": float(row["3. low"]),
                "close": float(row["4. close"]),
                "volume": float(row["5. volume"]),
            }
            for d, row in series.items()
        ),
        key=lambda r: r["date"],
    )

    cache[ticker] = {"fetched_date": today, "prices": prices}
    _save_price_history_cache(cache)
    return _apply_splits(prices, _refresh_splits(ticker, prices))[-days:]
