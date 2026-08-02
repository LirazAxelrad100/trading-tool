import json
import os
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY")
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
PRICE_HISTORY_CACHE_FILE = Path(__file__).parent / "data" / "price_history_cache.json"


class AlphaVantageError(Exception):
    pass


def fetch_news_sentiment(ticker: str, limit: int = 10) -> dict:
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
    return {
        "average_score": average_score,
        "article_count": len(articles),
        "articles": articles,
    }


def _load_price_history_cache() -> dict:
    if not PRICE_HISTORY_CACHE_FILE.exists():
        return {}
    return json.loads(PRICE_HISTORY_CACHE_FILE.read_text())


def _save_price_history_cache(cache: dict) -> None:
    PRICE_HISTORY_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def fetch_daily_prices(ticker: str, days: int = 30) -> list:
    """Daily closes for a ticker, oldest first, in USD. Cached per ticker per day
    since this shares Alpha Vantage's 25-requests/day free-tier cap with sentiment."""
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
        ({"date": d, "close": float(row["4. close"])} for d, row in series.items()),
        key=lambda r: r["date"],
    )

    cache[ticker] = {"fetched_date": today, "prices": prices}
    _save_price_history_cache(cache)
    return prices[-days:]
