import math
import statistics

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
