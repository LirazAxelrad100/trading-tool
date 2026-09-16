"""Which holdings move together — concentration by correlation, not just by size.

The % Portfolio column already shows how big each position is. It cannot show that several
positions are really one bet: on 2026-09-05 WDC, NVDA, MU, AMD and NBIS moved as a bloc worth
53.7% of the portfolio, while PLTR — the single largest position at 22% — turned out to
correlate *negatively* with most of them, so the intuitive "three quarters of this is AI" read
was wrong in an important way.

Free. `data/holdings_history.json` already records each holding's value once a day, and while
the share count is unchanged a change in value *is* a change in price, so no price history
needs fetching. That assumption is the one real trap here, and `_changed_dates()` guards it:
a sale or a new lot moves the value without the price moving, which would otherwise read as a
huge fake one-day return and corrupt every correlation that ticker is in.

The guard used to drop the whole holding, and the window started at the first day ever
recorded. Together those made the panel accumulate rather than refresh: by 2026-09-16 it was
measuring 33 days from 2026-08-15 with that start date frozen for good, so VLO, LNVGY and DK
were excluded permanently for lots bought on 2026-08-18, and TSM and DELL joined them the day
they were bought. A holding that changes shares once would never be seen again.

Two changes fix that. The window is the last `WINDOW_DAYS` days, so old behaviour falls off
the back. And a share change now masks **only the days it touches** — a new lot spoils the
return into that day and the one out of it, not the other eighty-eight — leaving every clean
day in the series. Days are therefore masked per ticker, so a pair is correlated over the days
both of them can vouch for, and a pair needs `MIN_RETURNS` shared days to be compared at all.
The same mask covers a holding bought mid-window, which simply has no value recorded on the
earlier days: it joins the panel on its own once it has enough days, instead of being excluded
by a rule it can never satisfy.

Descriptive only — it names the blocs and their combined weight, and never suggests what to
do about them.
"""

import collections
import datetime
import math
import statistics
from typing import Optional

# n=21 daily returns puts the 5% significance level near r=0.43, so 0.5 asks for a little
# more than "probably not noise" without demanding a relationship this short a window can't
# evidence. Groups also report their own average correlation, since connected-component
# grouping can chain A-B-C together on two edges while A and C barely relate.
CORRELATION_THRESHOLD = 0.5
MIN_RETURNS = 10

# Only the last three months are measured. Without this the window started at the first day
# ever recorded and never moved, so the panel would eventually be describing last August
# alongside last week and calling the mixture "now".
WINDOW_DAYS = 90


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


def _pair_correlation(a: list, b: list) -> Optional[float]:
    """Correlate two masked series over the days both can vouch for. None when they don't
    share enough of them — a number from four days is not a weaker answer, it is a different
    question."""
    both = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(both) < MIN_RETURNS:
        return None
    return _correlation([x for x, _ in both], [y for _, y in both])


def _changed_dates(holding: dict, sales: list) -> set:
    """The dates this position's share count moved. On those days its recorded value changed
    for a reason other than price."""
    ticker = holding["ticker"]
    dates = {(lot.get("purchase_date") or "")[:10] for lot in holding.get("lots") or []}
    # sales_history stores `sell_datetime` ("2026-07-27T16:19"), not `sell_date`.
    dates |= {
        (s.get("sell_datetime") or s.get("sell_date") or "")[:10]
        for s in sales if s.get("ticker") == ticker
    }
    return {d for d in dates if d}


def _masked_returns(values: list, dirty: list) -> list:
    """Daily log returns aligned to the dates that produced `values`, with None wherever the
    number would not be a clean price move: a missing snapshot, or a day the share count
    changed. Both ends of a change are dropped — the snapshot is taken at one moment in the
    day, so a purchase can land either side of it, and one extra day out of ninety is a
    cheaper mistake than one fabricated 300% return."""
    out = []
    for i in range(1, len(values)):
        before, after = values[i - 1], values[i]
        if before is None or after is None or before <= 0 or after <= 0:
            out.append(None)
        elif dirty[i] or dirty[i - 1]:
            out.append(None)
        else:
            out.append(math.log(after / before))
    return out


def _series_by_ticker(holdings: list, by_ticker: dict, sales: list, dates: list) -> dict:
    """Masked return series per held ticker, all aligned to the same date list."""
    series = {}
    for holding in holdings:
        ticker = holding["ticker"]
        points = by_ticker.get(ticker, {})
        changed = _changed_dates(holding, sales)
        values = [points.get(d) for d in dates]
        dirty = [d in changed for d in dates]
        series[ticker] = _masked_returns(values, dirty)
    return series


def _usable_days(series: list) -> int:
    return sum(1 for r in series if r is not None)


def _window(dates: list) -> list:
    """The last WINDOW_DAYS of recorded dates, so the panel describes now rather than
    everything since recording began."""
    if not dates:
        return dates
    cutoff = datetime.date.fromisoformat(dates[-1]) - datetime.timedelta(days=WINDOW_DAYS)
    return [d for d in dates if d >= cutoff.isoformat()]


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
        if corr is not None and corr >= CORRELATION_THRESHOLD:
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


def _down_day_behaviour(returns_by_ticker: dict, portfolio: list) -> Optional[dict]:
    """On the days the whole portfolio fell hardest, what did each holding do? A holding that
    still rose on those days genuinely cushioned; one that fell harder than the portfolio
    amplified the move regardless of how independent it looks on an average day."""
    days = [i for i, r in enumerate(portfolio) if r is not None]
    if len(days) < MIN_WORST_DAYS * 2:
        return None
    count = max(MIN_WORST_DAYS, int(len(days) * WORST_DAY_SHARE))
    worst = sorted(days, key=lambda i: portfolio[i])[:count]
    if all(portfolio[i] >= 0 for i in worst):
        return None

    rows = []
    for ticker, series in returns_by_ticker.items():
        picked = [series[i] for i in worst if i < len(series) and series[i] is not None]
        # "fell on 2 of 8" from a holding that was only there for two of them is noise
        # dressed as a finding; the row is left out rather than shown with a caveat.
        if len(picked) < MIN_WORST_DAYS:
            continue
        rows.append({
            "ticker": ticker,
            "avg_return_pct": statistics.mean(picked) * 100,
            "fell_on": sum(1 for r in picked if r < 0),
            "of_days": len(picked),
        })
    if not rows:
        return None
    rows.sort(key=lambda r: r["avg_return_pct"])
    return {
        "days_used": count,
        "portfolio_avg_pct": statistics.mean([portfolio[i] for i in worst]) * 100,
        "holdings": rows,
    }


def compare_candidate(ticker: str, holdings: list, history: list, sales: Optional[list] = None,
                      watchlist_history: Optional[list] = None) -> dict:
    """Would buying this add to an existing bloc, or genuinely diversify?

    `analyze()` can only group things already held, because holdings_history records only
    holdings. A candidate needs its own daily series, so this fetches one from Alpha Vantage
    (cached per ticker per day) and lines it up against the recorded values.

    Sector is deliberately not used: GICS files the user's own AI bloc under two different
    sectors and leaves one member unclassified, so it answers a different question than
    "do these move together".

    Caveat carried through to the UI: recorded holding values are EUR while the candidate's
    closes are USD, so currency movement leaks into the comparison. Small against three weeks
    of equity moves, but not nothing."""
    import alpha_vantage  # local import: only this path needs it, and it costs API budget
    import breadth

    ticker = ticker.upper()
    if any(h["ticker"] == ticker for h in holdings):
        return {"error": f"You already hold {ticker}."}

    base = analyze(holdings, history, sales)
    if base.get("error"):
        return base

    dates = _window(sorted({p["date"] for p in history}))
    by_ticker = collections.defaultdict(dict)
    for p in history:
        by_ticker[p["ticker"]][p["date"]] = p["value"]

    # Prefer the series this tool records itself: Finnhub's free tier serves no price history
    # (candles 403), so the fallback is Alpha Vantage against a 25/day cap. Once the watch list
    # has been refreshed on enough days, the comparison costs nothing.
    closes = {p["date"]: p["price"] for p in (watchlist_history or []) if p["ticker"] == ticker}
    source = "recorded"
    if len({d for d in dates if d in closes}) < MIN_WORST_DAYS * 2:
        bars = alpha_vantage.fetch_daily_prices(ticker, days=len(dates) + 40)
        closes = {b["date"]: b["close"] for b in bars}
        source = "alpha vantage"

    # Market series first: if it's available, restrict to days all three cover rather than
    # requiring the market to have every date — that feed lags a day or two, so demanding a
    # full overlap silently disabled the adjustment.
    market = {}
    try:
        market = breadth.market_series()
    except Exception:
        market = {}

    shared = [d for d in dates if d in closes and (not market or d in market)]
    if len(shared) < MIN_WORST_DAYS * 2:
        return {"error": f"Not enough overlapping days to compare {ticker} against your holdings."}

    # Masked rather than filtered, so it stays index-aligned with the holdings' own series —
    # a silently dropped day would shift every comparison by one.
    candidate = _masked_returns([closes[d] for d in shared], [False] * len(shared))
    # Subtract the market's own move from every series. Raw correlation over a few weeks is
    # inflated by the fact that most stocks fall on the days the market falls, so a candidate
    # can score ~0.5 against a bloc simply for being a normal risky US stock. Measured live
    # (2026-09-05): AMD/WDC held at +0.62 -> +0.64 through the adjustment (genuinely linked)
    # while NBIS/NVDA fell +0.42 -> +0.28 (a third of it was just the market).
    market_returns = (
        _masked_returns([market[d] for d in shared], [False] * len(shared)) if market else None
    )
    if market_returns and any(m is None for m in market_returns):
        market_returns = None
    if market_returns:
        candidate = [
            r - m if r is not None else None
            for r, m in zip(candidate, market_returns)
        ]

    sales = sales or []

    pairs = []
    for other, series in sorted(_series_by_ticker(holdings, by_ticker, sales, shared).items()):
        if market_returns:
            series = [
                r - m if r is not None else None
                for r, m in zip(series, market_returns)
            ]
        corr = _pair_correlation(candidate, series)
        if corr is None:
            continue
        pairs.append({"ticker": other, "correlation": corr})

    if not pairs:
        return {"error": f"No holding has a comparable run of days against {ticker}."}

    pairs.sort(key=lambda p: -p["correlation"])
    linked = [p["ticker"] for p in pairs if p["correlation"] >= CORRELATION_THRESHOLD]
    joins = next(
        (g for g in base["groups"] if any(t in linked for t in g["tickers"])),
        None,
    )
    return {
        "ticker": ticker,
        "days": _usable_days(candidate),
        "pairs": pairs,
        "linked": linked,
        "joins_group": joins["tickers"] if joins else None,
        "joins_group_weight_pct": joins["weight_pct"] if joins else None,
        "market_adjusted": bool(market_returns),
        "source": source,
    }


def analyze(holdings: list, history: list, sales: Optional[list] = None) -> dict:
    sales = sales or []
    if not holdings or not history:
        return {"error": "No holdings history recorded yet."}

    recorded = sorted({p["date"] for p in history})
    dates = _window(recorded)
    since = dates[0]
    by_ticker = collections.defaultdict(dict)
    for p in history:
        by_ticker[p["ticker"]][p["date"]] = p["value"]

    total = sum(h["shares"] * h["current_price"] for h in holdings) or 1
    weights = {h["ticker"]: h["shares"] * h["current_price"] / total * 100 for h in holdings}

    all_series = _series_by_ticker(holdings, by_ticker, sales, dates)
    usable, excluded = {}, []
    for ticker, series in sorted(all_series.items()):
        days = _usable_days(series)
        if days < MIN_RETURNS:
            excluded.append({
                "ticker": ticker,
                "days": days,
                "reason": (
                    "no full day recorded yet" if not days
                    else "only %d clean days so far, %d are needed" % (days, MIN_RETURNS)
                ),
            })
            continue
        usable[ticker] = series

    if len(usable) < 2:
        return {"error": "Not enough recorded history yet to compare holdings against each other."}

    tickers = sorted(usable)
    correlations = {}
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            correlations[(a, b)] = _pair_correlation(usable[a], usable[b])

    groups, singles = [], []
    for members in _group(tickers, correlations):
        weight = sum(weights.get(t, 0) for t in members)
        if len(members) == 1:
            singles.append({"ticker": members[0], "weight_pct": weight})
            continue
        pairs = [
            (correlations[(a, b)], a, b)
            for i, a in enumerate(members)
            for b in members[i + 1:]
            if correlations[(a, b)] is not None
        ]
        if not pairs:
            continue
        weakest = min(pairs)
        groups.append({
            "tickers": members,
            "weight_pct": weight,
            "avg_correlation": statistics.mean(p[0] for p in pairs),
            "min_correlation": weakest[0],
            # Connected components chain A-B-C together on two edges even when A and C barely
            # relate, so the weakest pair is named: a six-name bloc can be one borderline link
            # away from being two, and "48% of the portfolio is one bet" is too big a claim to
            # make without showing what holds it together.
            "weakest_pair": [weakest[1], weakest[2]],
        })

    # The portfolio's own daily return: each holding's return weighted by its share of the
    # portfolio, over whichever holdings have a clean number that day. Summing the recorded
    # values instead would make the basket's own composition move the total — a holding
    # dropping out for a masked day would read as a crash.
    portfolio_returns = []
    for i in range(len(dates) - 1):
        parts = [(weights.get(t, 0), s[i]) for t, s in usable.items() if s[i] is not None]
        carried = sum(w for w, _ in parts)
        portfolio_returns.append(
            sum(w * r for w, r in parts) / carried if carried else None
        )

    groups.sort(key=lambda g: -g["weight_pct"])
    singles.sort(key=lambda s: -s["weight_pct"])
    return {
        "down_days": _down_day_behaviour(usable, portfolio_returns),
        "days": len(dates),
        "window_days": WINDOW_DAYS,
        # Only worth telling her about the cap once it is actually throwing days away;
        # until then "32 days, the last 90 days only" is two numbers explaining nothing.
        "window_trimmed": len(dates) < len(recorded),
        "returns": max(_usable_days(s) for s in usable.values()),
        "from_date": since,
        "to_date": dates[-1],
        "groups": groups,
        "independent": singles,
        "excluded": excluded,
    }
