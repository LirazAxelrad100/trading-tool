import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FRANKFURTER_URL = "https://api.frankfurter.app/latest"


class PriceError(Exception):
    pass


def us_market_open() -> bool:
    """US regular session, 9:30-16:00 ET, Mon-Fri (holidays not accounted for) —
    mirrors usMarketOpen() in static/app.js. While closed, Finnhub freezes on the
    last US close, so day_change_pct reflects an already-fully-realized move, not
    a live one — apply_quote (main.py) must not roll a stored price forward by it,
    or it double-counts a move already baked into a TR-verified anchor."""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def _finnhub_get(path: str, params: dict) -> dict:
    if not FINNHUB_API_KEY:
        raise PriceError("FINNHUB_API_KEY is not set in .env")
    try:
        res = requests.get(
            f"{FINNHUB_BASE_URL}/{path}",
            params={**params, "token": FINNHUB_API_KEY},
            timeout=10,
        )
        res.raise_for_status()
        return res.json()
    except requests.RequestException as e:
        raise PriceError(f"Could not fetch {path} for params {params}: {e}") from e


def fetch_usd_to_eur_rate() -> float:
    try:
        res = requests.get(FRANKFURTER_URL, params={"from": "USD", "to": "EUR"}, timeout=10)
        res.raise_for_status()
        return res.json()["rates"]["EUR"]
    except requests.RequestException as e:
        raise PriceError(f"Could not fetch USD/EUR rate: {e}") from e


def fetch_quote(ticker: str, usd_to_eur_rate: float) -> dict:
    """Current price (EUR) and today's % change vs. Finnhub's previous-close reference,
    from a single /quote call. day_change_pct is a ratio (e.g. -0.074), not a raw percent —
    consistent with trailing_pct/portfolio_pct elsewhere. This is deliberately Finnhub's own
    computed change, not something we derive ourselves (a self-tracked "day open" snapshot
    depends on when we happen to first refresh, which can already be well after a big move —
    see CLAUDE.md)."""
    data = _finnhub_get("quote", {"symbol": ticker})
    price_usd = data.get("c")
    if not price_usd:
        raise PriceError(f"No price found for ticker '{ticker}'")
    dp = data.get("dp")
    return {
        "price": price_usd * usd_to_eur_rate,
        "day_change_pct": dp / 100 if dp is not None else None,
        "previous_close_usd": data.get("pc"),
    }


def fetch_analyst_consensus(ticker: str) -> dict:
    data = _finnhub_get("stock/recommendation", {"symbol": ticker})

    if not data:
        raise PriceError(f"No analyst consensus found for '{ticker}'")

    latest = data[0]
    return {
        "period": latest["period"],
        "strong_buy": latest["strongBuy"],
        "buy": latest["buy"],
        "hold": latest["hold"],
        "sell": latest["sell"],
        "strong_sell": latest["strongSell"],
    }


def fetch_industry(ticker: str) -> Optional[str]:
    """Finnhub's 'finnhubIndustry' label for a ticker (e.g. 'Semiconductors',
    'Banking'), used to map a stock to one of the 11 GICS sectors."""
    data = _finnhub_get("stock/profile2", {"symbol": ticker})
    return (data or {}).get("finnhubIndustry")


def fetch_price_returns(ticker: str) -> dict:
    """Pre-computed trailing price returns (percent) from Finnhub's free metrics —
    5-day (~1 week) and 13-week (~3 months). One call, no daily-price history needed."""
    data = _finnhub_get("stock/metric", {"symbol": ticker, "metric": "all"})
    m = (data or {}).get("metric", {})
    return {"move_1w": m.get("5DayPriceReturnDaily"), "move_3m": m.get("13WeekPriceReturnDaily")}


def fetch_recommendation_history(ticker: str, limit: int = 4) -> list:
    """Raw recommendation counts for the most recent `limit` monthly periods
    (newest first) — Finnhub returns several periods in one call, which is what
    lets us read analyst-opinion drift for free. Each row: strongBuy/buy/hold/sell/
    strongSell/period."""
    data = _finnhub_get("stock/recommendation", {"symbol": ticker})
    if not data:
        raise PriceError(f"No analyst consensus found for '{ticker}'")
    return data[:limit]


def fetch_earnings_history(ticker: str, limit: int = 4) -> list:
    data = _finnhub_get("stock/earnings", {"symbol": ticker})
    return [
        {
            "period": row["period"],
            "quarter": row["quarter"],
            "year": row["year"],
            "estimate": row.get("estimate"),
            "actual": row.get("actual"),
            "surprise_percent": row.get("surprisePercent"),
        }
        for row in data[:limit]
    ]


def fetch_earnings_calendar(ticker: str) -> dict:
    today = date.today()
    data = _finnhub_get(
        "calendar/earnings",
        {"symbol": ticker, "from": today.isoformat(), "to": (today + timedelta(days=120)).isoformat()},
    )
    upcoming = data.get("earningsCalendar") or []
    if not upcoming:
        return {}
    next_event = upcoming[0]
    return {
        "date": next_event.get("date"),
        "hour": next_event.get("hour"),
        "eps_estimate": next_event.get("epsEstimate"),
    }


def fetch_insider_transactions(ticker: str, limit: int = 5) -> list:
    data = _finnhub_get("stock/insider-transactions", {"symbol": ticker})
    rows = data.get("data") or []
    return [
        {
            "name": row.get("name"),
            "shares": row.get("share"),
            "change": row.get("change"),
            "transaction_date": row.get("transactionDate"),
            "transaction_price": row.get("transactionPrice"),
        }
        for row in rows[:limit]
    ]


def fetch_company_news(ticker: str, days: int = 7, limit: int = 8) -> list:
    today = date.today()
    data = _finnhub_get(
        "company-news",
        {"symbol": ticker, "from": (today - timedelta(days=days)).isoformat(), "to": today.isoformat()},
    )
    return [
        {"headline": row.get("headline"), "source": row.get("source"), "datetime": row.get("datetime")}
        for row in data[:limit]
    ]
