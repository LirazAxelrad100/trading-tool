import math
import statistics
from datetime import date

import alpha_vantage

# Rough bands for annualized volatility of an individual stock (broad market ~15-20%).
VOL_BANDS = [
    (20, "Low"),
    (35, "Moderate"),
    (55, "High"),
]


def compute_volatility(ticker: str, days: int = 90) -> dict:
    """Historical (realized) volatility from daily closes — how much the price has
    actually swung day to day, annualized. Purely descriptive, backward-looking:
    not a forecast of future moves. Reuses alpha_vantage's per-ticker-per-day price
    cache, so it costs nothing extra if the ticker's chart was already viewed today."""
    prices = alpha_vantage.fetch_daily_prices(ticker, days=days)
    closes = [p["close"] for p in prices]
    if len(closes) < 10:
        return {"error": "Not enough price history to estimate volatility."}

    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    daily_std = statistics.pstdev(returns)
    annualized_pct = daily_std * math.sqrt(252) * 100

    label = next((lbl for cutoff, lbl in VOL_BANDS if annualized_pct < cutoff), "Very high")
    return {
        "annualized_pct": annualized_pct,
        "label": label,
        "days_used": len(closes),
    }


STOP_WIDTHS = [10, 15, 20, 25]


def stop_history(ticker: str, cached_only: bool = False) -> dict:
    """How often a trailing stop of each width would have sold this stock over the last
    ~100 trading days. Motivated by HPE (2026-08): a default 10% stop fired five days after
    buying, on a stock whose ordinary week moves about that much — the stop was measuring
    noise, not the thesis. Descriptive only: it shows how the stock has behaved, and the
    stop level stays the user's choice.

    The peak follows closing prices (as the tool's own reference_high does), but the trigger
    reads each day's low, because a broker's stop order fires during the day. After a stop
    fires the peak re-arms at that day's close, so the count answers "how many times would
    this have shaken me out", not just "did it ever".

    cached_only returns {"cached": False} instead of spending an Alpha Vantage call, so the
    pre-buy modal can show this for free whenever Analyze or Check already fetched today."""
    if cached_only:
        cached = alpha_vantage._load_price_history_cache().get(ticker)
        if not cached or cached.get("fetched_date") != date.today().isoformat():
            return {"cached": False}
    bars = alpha_vantage.fetch_daily_prices(ticker, days=100)
    closes = [b["close"] for b in bars]
    if len(closes) < 20:
        return {"error": "Not enough price history."}

    fires = {}
    for width in STOP_WIDTHS:
        peak, count = closes[0], 0
        for b in bars:
            low = b.get("low", b["close"])
            if low <= peak * (1 - width / 100):
                count += 1
                peak = b["close"]
            else:
                peak = max(peak, b["close"])
        fires[width] = count

    moves = sorted(abs(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes)))
    return {
        "cached": True,
        "days": len(closes),
        "typical_daily_move_pct": moves[len(moves) // 2],
        "fires": fires,
    }
