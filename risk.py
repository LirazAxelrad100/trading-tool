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


# Windows for the typical daily move, in trading days. Stops at ~5 months because Alpha
# Vantage's free tier returns 100 trading days; 6 months would need the paid `full` output.
MOVE_WINDOWS = [("1m", 21), ("3m", 63), ("5m", 100)]


def typical_moves(closes: list) -> list:
    """The median absolute daily move over each window, newest days last. Median rather than
    average, so one earnings-day jump doesn't set the figure for a whole month. Side by side
    they show whether a stock is swinging more or less lately than it used to — which the
    single annualized figure blends into one number."""
    out = []
    for key, n in MOVE_WINDOWS:
        window = closes[-(n + 1):]
        if len(window) < n * 0.8:
            continue
        moves = sorted(abs(window[i] / window[i - 1] - 1) * 100 for i in range(1, len(window)))
        out.append({"window": key, "days": len(moves), "pct": moves[len(moves) // 2]})
    return out


def compute_volatility(ticker: str, days: int = 90) -> dict:
    """Historical (realized) volatility from daily closes — how much the price has
    actually swung day to day, annualized. Purely descriptive, backward-looking:
    not a forecast of future moves. Reuses alpha_vantage's per-ticker-per-day price
    cache, so it costs nothing extra if the ticker's chart was already viewed today."""
    all_closes = [p["close"] for p in alpha_vantage.fetch_daily_prices(ticker, days=100)]
    closes = all_closes[-days:]
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
        "typical_moves": typical_moves(all_closes),
    }


STOP_WIDTHS = [10, 15, 20, 25]

# The user's own rule (2026-10-05), not the tool's: the stop width she wants by default for a
# new holding at each volatility level. The tool never picks a width — it applies hers, the
# same way it applies her minimum position size, and she can type over it. It came from RDDT,
# bought with the 10% default when a 10% stop would have sold it 10 times in 100 days.
STOP_BY_LEVEL = {"Low": 10, "Moderate": 15, "High": 20, "Very high": 25}


def stop_default(ticker: str) -> dict:
    """Volatility level, the user's stop width for it, and how often that width would have
    fired. Both readings share alpha_vantage's per-ticker-per-day cache, so this is one call
    the first time a ticker is looked at each day and free after that."""
    vol = compute_volatility(ticker)
    if vol.get("error"):
        return vol
    width = STOP_BY_LEVEL[vol["label"]]
    stops = stop_history(ticker)
    return {
        "level": vol["label"],
        "annualized_pct": vol["annualized_pct"],
        "typical_daily_move_pct": stops.get("typical_daily_move_pct"),
        "width": width,
        "fires": (stops.get("fires") or {}).get(width),
        "days": stops.get("days"),
    }


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
        "typical_moves": typical_moves(closes),
        "fires": fires,
    }
