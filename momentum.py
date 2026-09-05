"""Momentum-burst signals — descriptive only, in the same spirit as risk.py.

Reports what a stock's price and volume have *just done* (a sharp up-day, an already-
extended run, a close near the day's high) using thresholds from Pradeep Bonde's
"momentum burst" screening rules. It states facts and never grades a setup: no A/B/C
rating, no score, no entry/stop/size. Like risk.py, this is deliberately kept out of
synthesis.py's SYSTEM_PROMPT — words like "breakout" read as a recommendation once an
LLM narrates them, whereas a badge showing "+22% over 5 days, closed mid-range" leaves
the reading to the user.

Reads today's live quote plus Finnhub's trailing metrics — both already fetched where it
is used, so it costs nothing extra. An earlier Alpha Vantage daily-bars tier added volume
vs. the 50-day average and range expansion, but those bars lag a day, so the badge kept
describing yesterday while calling it today; it was dropped in favour of one live read.
"""

from typing import Optional

# Bonde's third trigger, a "dollar breakout" (close - open >= $0.90), is deliberately not
# implemented: it was written for low-priced stocks, and on the high-priced US names in this
# portfolio it clears trivially — live-tested on AMD ($473), it fired on a day the stock
# closed *down* 0.2%, which reads as bullish while being nothing of the sort.
BREAKOUT_PCT = 4.0        # Bonde's "4% breakout" day
EXTENDED_5D_PCT = 20.0    # Bonde's "5 days, +20%" already-moved marker
VOLUME_LOOKBACK = 50
RANGE_LOOKBACK = 3

# Trend context. Bonde's burst setups assume the stock is already in an uptrend (his method
# pairs them with a trend filter; Minervini calls the same idea "Stage 2"). Without that
# context a burst label is ambiguous: STRL rose 5% on 2026-09-04 while sitting 52% below its
# June high, which is a bounce inside a decline, not a breakout — the case Bonde's own
# failure filters exist to be wary of. Two plain conditions, so the label can say which it is.
NEAR_HIGH_PCT = 15.0      # within this % of the 52-week high counts as "near its highs"


def _close_location(close, high, low) -> Optional[float]:
    """Where in the day's range the price sits: 1.0 = closed at the high, 0.0 = at the low.
    A strong up-day that closes mid-range means sellers met the buying."""
    if close is None or high is None or low is None or high <= low:
        return None
    return (close - low) / (high - low)


def _state(breakout: bool, extended: bool, day_change: Optional[float] = None) -> str:
    """A neutral one-word summary. 'extended' wins when both are true: a stock that has
    already run 20% in a week is a different situation from a fresh move, and that is the
    part the user is most at risk of missing. A sharp fall gets its own label rather than
    'quiet' — a -5% day is many things, but quiet is not one of them."""
    if extended:
        return "extended"
    if breakout:
        return "burst"
    if day_change is not None and day_change <= -BREAKOUT_PCT:
        return "sharp drop"
    return "quiet"


def pct_from_52w_high(close, high_52w, low_52w) -> Optional[float]:
    """Distance from the 52-week high, or None when Finnhub's range clearly describes a
    different instrument than its own /quote. Real case: for TSM, /quote returns the US ADR
    (~$427) while stock/metric returns the Taiwan listing's range (high 2535, low 1145 TWD),
    which rendered as "-83% from its 52-week high". A price sitting far outside its own
    52-week range is impossible for one instrument, so treat it as a currency/listing
    mismatch. The band is loose because the metric is daily and a live price can genuinely
    poke through a stale high or low."""
    if not close or not high_52w:
        return None
    if close > high_52w * 1.15:
        return None
    if low_52w and close < low_52w * 0.85:
        return None
    return (close / high_52w - 1) * 100


def _trend(ret_3m: Optional[float], pct_from_high: Optional[float]) -> Optional[str]:
    """Is the stock climbing or falling underneath today's move? Judged on two facts a
    reader can check: whether it is up over the last 3 months, and whether it trades near
    its 52-week high. Both true = uptrend, both false = downtrend, one of each = mixed.
    Returns None when neither is known, so the caller can omit the context rather than
    guess at it."""
    up_3m = None if ret_3m is None else ret_3m > 0
    near_high = None if pct_from_high is None else pct_from_high >= -NEAR_HIGH_PCT
    known = [v for v in (up_3m, near_high) if v is not None]
    if not known:
        return None
    if all(known):
        return "uptrend"
    if not any(known):
        return "downtrend"
    return "mixed"


def from_finnhub(shape: dict, metrics: dict) -> dict:
    """Watch List tier. `shape` is prices.fetch_quote_shape(), `metrics` is
    prices.fetch_metrics() — both already fetched during a watchlist refresh."""
    close = shape.get("close")
    day_change = shape.get("day_change_pct")
    run_up_5d = metrics.get("5DayPriceReturnDaily")
    high_52w = metrics.get("52WeekHigh")

    vol_10d = metrics.get("10DayAverageTradingVolume")
    vol_3m = metrics.get("3MonthAverageTradingVolume")
    vol_elevation = vol_10d / vol_3m if vol_10d and vol_3m else None

    pct_from_high = pct_from_52w_high(close, high_52w, metrics.get("52WeekLow"))

    ret_3m = metrics.get("13WeekPriceReturnDaily")

    breakout = day_change is not None and day_change >= BREAKOUT_PCT
    extended = run_up_5d is not None and run_up_5d >= EXTENDED_5D_PCT

    return {
        "source": "finnhub",
        "state": _state(breakout, extended, day_change),
        "trend": _trend(ret_3m, pct_from_high),
        "day_change_pct": day_change,
        "close_location": _close_location(close, shape.get("high"), shape.get("low")),
        "run_up_5d_pct": run_up_5d,
        "ret_3m_pct": ret_3m,
        "volume_elevation": vol_elevation,
        "pct_from_52w_high": pct_from_high,
    }
