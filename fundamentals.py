"""Price vs. fundamentals — the lens the rest of the tool structurally lacks.

Zacks rank, Opportunities B, momentum and sentiment are all trend-following: they ask
"is this working right now". A recovery thesis says "it isn't, and that's the point", so
those signals will always read bearish on one, which tells the user nothing they didn't
already know. This asks a different question — did the *price* fall while the *business*
kept growing, or did both deteriorate together? The first is the setup a recovery thesis
needs; the second is the shape of a value trap.

Descriptive only, and kept out of synthesis.py's SYSTEM_PROMPT for the same reason as
risk.py and momentum.py: naming a quadrant is a fact, but an LLM narrating "the business
is intact while the price has fallen" slides into a recommendation without ever using a
banned word.

Honest limit: this identifies the *entry condition* for a recovery thesis, never the
timing. Nothing here can say a decline is over.

Free — both inputs are already fetched for the Analyze popup.
"""

from typing import Optional

import momentum

# Finnhub's growth figures are trailing-twelve-month year-over-year, so the price side
# must use the matching 12-month window or the comparison is meaningless. Shorter windows
# are available for price but have no EPS counterpart on the free tier.
#
# That window is right but blind on its own: live-tested across STRL, AMD, NEM and FN
# (2026-09-05), every one came out "in_line" — including STRL, whose 52% fall since June
# sits inside a 12-month period that was still net positive. So the recent drawdown is
# reported alongside as its own fact. The pairing is what carries the meaning: a flat
# multiple with a deep drawdown says the earlier peak was the anomaly, while a still-
# expanded multiple after a fall says the re-rating may not be finished.
PRICE_FIELD = "52WeekPriceReturnDaily"

QUADRANTS = {
    (True, True): "in_line",
    (False, True): "divergence",
    (True, False): "multiple_expansion",
    (False, False): "both_falling",
}


# Above this, year-over-year profit growth is almost always a recovery from a near-zero or
# depressed base rather than real expansion, and the derived valuation change becomes
# meaningless. Live case (GEV, 2026-09-05): profit per share +744% produced "investors pay
# 81% less for the same profit" — arithmetically correct, practically nonsense.
EPS_BASE_DISTORTION_PCT = 200


def _multiple_change_pct(price_pct: float, eps_pct: float) -> Optional[float]:
    """How much the market's willingness to pay per dollar of earnings moved, derived
    rather than measured: price and earnings growth are both known, and P/E is their
    ratio, so (1+price)/(1+eps)-1 recovers the change without any historical-P/E data
    (which no free source provides). Meaningless once earnings cross zero — a swing from
    profit to loss isn't a multiple change — so that returns None."""
    if eps_pct <= -100:
        return None
    return ((1 + price_pct / 100) / (1 + eps_pct / 100) - 1) * 100


def analyze(metrics: dict, earnings_history: Optional[list] = None,
            current_price_usd: Optional[float] = None) -> dict:
    """`metrics` is prices.fetch_metrics() output; `earnings_history` is
    prices.fetch_earnings_history() (optional, adds the beat record);
    `current_price_usd` enables the drawdown reading (optional)."""
    m = metrics or {}
    price_pct = m.get(PRICE_FIELD)
    eps_pct = m.get("epsGrowthTTMYoy")

    if not isinstance(price_pct, (int, float)) or not isinstance(eps_pct, (int, float)):
        return {"error": "Not enough data to compare this company's share price against its profits."}

    quadrant = QUADRANTS[(price_pct >= 0, eps_pct >= 0)]

    beats = misses = None
    if isinstance(earnings_history, list):
        surprises = [
            r.get("surprise_percent")
            for r in earnings_history
            if isinstance(r, dict) and isinstance(r.get("surprise_percent"), (int, float))
        ]
        if surprises:
            beats = sum(1 for s in surprises if s > 0)
            misses = len(surprises) - beats

    return {
        "quadrant": quadrant,
        "price_12m_pct": price_pct,
        "price_3m_pct": m.get("13WeekPriceReturnDaily"),
        # Shares momentum.py's guard against Finnhub returning a different listing's range
        # than its own quote (the TSM ADR-vs-Taiwan case documented there).
        "pct_from_52w_high": momentum.pct_from_52w_high(
            current_price_usd, m.get("52WeekHigh"), m.get("52WeekLow")
        ),
        "eps_growth_pct": eps_pct,
        "revenue_growth_pct": m.get("revenueGrowthTTMYoy"),
        "multiple_change_pct": _multiple_change_pct(price_pct, eps_pct),
        "eps_base_distorted": eps_pct > EPS_BASE_DISTORTION_PCT,
        "pe_ttm": m.get("peTTM"),
        "roe_ttm": m.get("roeTTM"),
        "debt_to_equity": m.get("totalDebt/totalEquityAnnual"),
        "beats": beats,
        "misses": misses,
    }
