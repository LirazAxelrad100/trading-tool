"""Which holdings move together — concentration by correlation, not just by size.

The % Portfolio column already shows how big each position is. It cannot show that several
positions are really one bet: on 2026-09-05 WDC, NVDA, MU, AMD and NBIS moved as a bloc worth
53.7% of the portfolio, while PLTR — the single largest position at 22% — turned out to
correlate *negatively* with most of them, so the intuitive "three quarters of this is AI" read
was wrong in an important way.

Free. `data/holdings_history.json` already records each holding's value once a day, and while
the share count is unchanged a change in value *is* a change in price, so no price history
needs fetching. That assumption is the one real trap here, and `_changed_shares()` guards it:
a sale or a new lot inside the window moves the value without the price moving, which would
otherwise read as a huge fake one-day return and corrupt every correlation that ticker is in.

Descriptive only — it names the blocs and their combined weight, and never suggests what to
do about them.
"""

import collections
import math
import statistics
from typing import Optional

# n=21 daily returns puts the 5% significance level near r=0.43, so 0.5 asks for a little
# more than "probably not noise" without demanding a relationship this short a window can't
# evidence. Groups also report their own average correlation, since connected-component
# grouping can chain A-B-C together on two edges while A and C barely relate.
CORRELATION_THRESHOLD = 0.5
MIN_RETURNS = 10


def _returns(values: list) -> list:
    return [
        math.log(values[i] / values[i - 1])
        for i in range(1, len(values))
        if values[i - 1] > 0 and values[i] > 0
    ]


def _correlation(a: list, b: list) -> float:
    mean_a, mean_b = statistics.mean(a), statistics.mean(b)
    dev_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    dev_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    if not dev_a or not dev_b:
        return 0.0
    return sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b)) / (dev_a * dev_b)


def _changed_shares(holding: dict, sales: list, since: str) -> bool:
    """Did this position's share count move during the window? Then its recorded value
    changed for a reason other than price, and its returns are unusable."""
    ticker = holding["ticker"]
    # sales_history stores `sell_datetime` ("2026-07-27T16:19"), not `sell_date`; the ISO
    # prefix compares correctly against a plain date string.
    if any(s.get("ticker") == ticker and (s.get("sell_datetime") or "") >= since for s in sales):
        return True
    return any((lot.get("purchase_date") or "") >= since for lot in holding.get("lots") or [])


def _group(tickers: list, correlations: dict) -> list:
    """Connected components over pairs above the threshold: a bloc is a set of holdings
    linked by co-movement, directly or through another member."""
    parent = {t: t for t in tickers}

    def find(t):
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    for (a, b), corr in correlations.items():
        if corr >= CORRELATION_THRESHOLD:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

    blocs = collections.defaultdict(list)
    for t in tickers:
        blocs[find(t)].append(t)
    return [sorted(members) for members in blocs.values()]


# Correlation measured across calm days answers the wrong question. Holdings that trade
# independently day to day often fall together in a genuine shock, which is exactly when the
# diversification was supposed to help — so this reports how each holding actually behaved on
# the portfolio's worst days. A share of days is used rather than a fixed count so it still
# means something as the history grows.
WORST_DAY_SHARE = 0.25
MIN_WORST_DAYS = 4


def _down_day_behaviour(returns_by_ticker: dict, dates: list, portfolio: list) -> Optional[dict]:
    """On the days the whole portfolio fell hardest, what did each holding do? A holding that
    still rose on those days genuinely cushioned; one that fell harder than the portfolio
    amplified the move regardless of how independent it looks on an average day."""
    if len(portfolio) < MIN_WORST_DAYS * 2:
        return None
    count = max(MIN_WORST_DAYS, int(len(portfolio) * WORST_DAY_SHARE))
    worst = sorted(range(len(portfolio)), key=lambda i: portfolio[i])[:count]
    if all(portfolio[i] >= 0 for i in worst):
        return None

    rows = []
    for ticker, series in returns_by_ticker.items():
        picked = [series[i] for i in worst if i < len(series)]
        if not picked:
            continue
        rows.append({
            "ticker": ticker,
            "avg_return_pct": statistics.mean(picked) * 100,
            "fell_on": sum(1 for r in picked if r < 0),
            "of_days": len(picked),
        })
    rows.sort(key=lambda r: r["avg_return_pct"])
    return {
        "days_used": count,
        "portfolio_avg_pct": statistics.mean([portfolio[i] for i in worst]) * 100,
        "holdings": rows,
    }


def analyze(holdings: list, history: list, sales: Optional[list] = None) -> dict:
    sales = sales or []
    if not holdings or not history:
        return {"error": "No holdings history recorded yet."}

    dates = sorted({p["date"] for p in history})
    since = dates[0]
    by_ticker = collections.defaultdict(dict)
    for p in history:
        by_ticker[p["ticker"]][p["date"]] = p["value"]

    held = {h["ticker"]: h for h in holdings}
    total = sum(h["shares"] * h["current_price"] for h in holdings) or 1
    weights = {h["ticker"]: h["shares"] * h["current_price"] / total * 100 for h in holdings}

    usable, excluded = {}, []
    for ticker, holding in held.items():
        points = by_ticker.get(ticker, {})
        if len(points) < len(dates):
            excluded.append({"ticker": ticker, "reason": "not tracked for the whole period"})
            continue
        if _changed_shares(holding, sales, since):
            excluded.append({"ticker": ticker, "reason": "shares bought or sold during the period"})
            continue
        series = _returns([points[d] for d in dates])
        if len(series) < MIN_RETURNS:
            excluded.append({"ticker": ticker, "reason": "not enough days recorded"})
            continue
        usable[ticker] = series

    if len(usable) < 2:
        return {"error": "Not enough recorded history yet to compare holdings against each other."}

    tickers = sorted(usable)
    correlations = {}
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            correlations[(a, b)] = _correlation(usable[a], usable[b])

    groups, singles = [], []
    for members in _group(tickers, correlations):
        weight = sum(weights.get(t, 0) for t in members)
        if len(members) == 1:
            singles.append({"ticker": members[0], "weight_pct": weight})
            continue
        pairs = [
            correlations[(a, b)]
            for i, a in enumerate(members)
            for b in members[i + 1:]
        ]
        groups.append({
            "tickers": members,
            "weight_pct": weight,
            "avg_correlation": statistics.mean(pairs),
            "min_correlation": min(pairs),
        })

    # The portfolio's own daily return, summed across the usable holdings only, so the
    # "worst days" are the ones these holdings actually drove.
    totals = []
    for d in dates:
        totals.append(sum(by_ticker[t][d] for t in usable))
    portfolio_returns = _returns(totals)

    groups.sort(key=lambda g: -g["weight_pct"])
    singles.sort(key=lambda s: -s["weight_pct"])
    return {
        "down_days": _down_day_behaviour(usable, dates, portfolio_returns),
        "days": len(dates),
        "returns": len(next(iter(usable.values()))),
        "from_date": since,
        "to_date": dates[-1],
        "groups": groups,
        "independent": singles,
        "excluded": excluded,
    }
