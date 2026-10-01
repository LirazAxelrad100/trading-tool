import json
import os
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY")
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
PRICE_HISTORY_CACHE_FILE = Path(__file__).parent / "data" / "price_history_cache.json"
NEWS_SENTIMENT_CACHE_FILE = Path(__file__).parent / "data" / "news_sentiment_cache.json"


class AlphaVantageError(Exception):
    pass


def _load_news_sentiment_cache() -> dict:
    if not NEWS_SENTIMENT_CACHE_FILE.exists():
        return {}
    return json.loads(NEWS_SENTIMENT_CACHE_FILE.read_text())


def _save_news_sentiment_cache(cache: dict) -> None:
    NEWS_SENTIMENT_CACHE_FILE.write_text(json.dumps(cache, indent=2))


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
_last_dividend_call = 0.0


def fetch_dividends(ticker: str, cached_only: bool = False) -> list:
    """Every dividend Alpha Vantage knows for a ticker, newest first: payment date, ex-date
    and amount per share in USD. It includes ones already declared but not yet paid.
    Finnhub's equivalent is paid-tier (403, live-tested 2026-10-01).

    Cached a week per ticker: the list only changes when a new dividend is declared, and the
    free key's 25 calls a day are shared with price history and sentiment. A failed fetch
    falls back to whatever is cached, however old, since a dividend paid stays paid."""
    global _last_dividend_call
    cache = json.loads(DIVIDENDS_CACHE_FILE.read_text()) if DIVIDENDS_CACHE_FILE.exists() else {}
    cached = cache.get(ticker)
    fresh = cached and (date.today() - date.fromisoformat(cached["fetched_date"])).days < DIVIDENDS_REFRESH_DAYS
    if fresh or (cached and cached_only):
        return cached["dividends"]
    if cached_only:
        raise AlphaVantageError(f"No dividends cached for '{ticker}'")
    if not ALPHA_VANTAGE_API_KEY:
        raise AlphaVantageError("ALPHA_VANTAGE_API_KEY is not set in .env")

    # The free key also refuses bursts faster than about one call a second.
    wait = 1.5 - (time.time() - _last_dividend_call)
    if wait > 0:
        time.sleep(wait)
    _last_dividend_call = time.time()
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
    DIVIDENDS_CACHE_FILE.write_text(json.dumps(cache, indent=2))
    return cache[ticker]["dividends"]


def _load_price_history_cache() -> dict:
    if not PRICE_HISTORY_CACHE_FILE.exists():
        return {}
    return json.loads(PRICE_HISTORY_CACHE_FILE.read_text())


def _save_price_history_cache(cache: dict) -> None:
    PRICE_HISTORY_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def fetch_daily_prices(ticker: str, days: int = 30) -> list:
    """Daily OHLCV bars for a ticker, oldest first, in USD. Cached per ticker per day
    since this shares Alpha Vantage's 25-requests/day free-tier cap with sentiment.

    Alpha Vantage returns open/high/low/volume in the same response as the close, so
    keeping them costs no extra call — momentum.py reads them for burst signals. Entries
    cached earlier under the close-only format have no OHLC keys; callers that need them
    must degrade rather than assume (self-heals on the next day's refetch)."""
    cache = _load_price_history_cache()
    today = date.today().isoformat()
    cached = cache.get(ticker)
    if cached and cached.get("fetched_date") == today:
        return cached["prices"][-days:]

    if not ALPHA_VANTAGE_API_KEY:
        raise AlphaVantageError("ALPHA_VANTAGE_API_KEY is not set in .env")
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
    return prices[-days:]
