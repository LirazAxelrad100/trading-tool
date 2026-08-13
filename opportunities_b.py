"""Opportunities B — an analyst-conviction shortlist over the S&P 500, built to be
a methodologically *different* second source from the Zacks Rank 1 list.

Two-stage funnel (keeps API cost sane vs. a full composite over 500 names):
  Stage 1 — one recommendation call per S&P 500 name (cheap, whole universe):
            filter to Buy-or-better with real coverage, rank by conviction, keep top N.
  Stage 2 — for that shortlist only, add earnings-beat consistency (one call each),
            compute the composite, keep the top ~20.

Composite = 0.45*conviction + 0.45*earnings-beats + 0.10*opinion-drift. Conviction and
beats are the two real drivers (beats is the most Zacks-orthogonal signal); drift is a
light tiebreaker read from the 4 months Finnhub already returns in the recommendation
call — see docs. Purely descriptive/sorted, never a "buy this" pick (CLAUDE.md hard rule).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import prices
import zacks_import

DATA_DIR = Path(__file__).parent / "data"
UNIVERSE_FILE = DATA_DIR / "sp500.json"
OUTPUT_FILE = DATA_DIR / "opportunities_b.json"

MIN_ANALYSTS = 5          # ignore thinly-covered names
MAX_CONSENSUS_AVG = 2.0   # Buy or better (1=Strong Buy … 5=Strong Sell)
SHORTLIST_SIZE = 40       # stage-1 survivors that get enriched in stage 2
FINAL_SIZE = 20           # the point is a *short* list, not another 200-name screen
RATE_SLEEP = 1.1          # stay under Finnhub's 60/min free-tier limit

W_CONVICTION = 0.45
W_BEATS = 0.45
W_DRIFT = 0.10

# Finnhub's recommendation JSON uses camelCase keys.
CONSENSUS_WEIGHTS = {"strongBuy": 1, "buy": 2, "hold": 3, "sell": 4, "strongSell": 5}


def load_universe() -> dict:
    return json.loads(UNIVERSE_FILE.read_text())["constituents"]


def load_opportunities_b() -> dict:
    if not OUTPUT_FILE.exists():
        return {"generated_at": None, "list": []}
    return json.loads(OUTPUT_FILE.read_text())


def in_universe(ticker: str) -> bool:
    """Whether this ticker is in the S&P 500 set Opportunities B actually screens.
    A ticker outside it can still get an on-demand score_ticker() read, but it was
    never in the running for the published shortlist - a different situation from
    scoring low, worth telling apart when comparing against Zacks."""
    return ticker in load_universe()


def shortlist_cutoff() -> Optional[float]:
    """Lowest composite score currently making the top-N shortlist - a data-driven
    'would this ticker make the cut today' bar. None if the shortlist hasn't been
    built yet."""
    lst = load_opportunities_b().get("list") or []
    if not lst:
        return None
    return min(r["composite"] for r in lst)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _consensus_metrics(history: list):
    latest = history[0]
    n = sum(latest[k] for k in CONSENSUS_WEIGHTS)
    if n == 0:
        return None
    avg = sum(latest[k] * w for k, w in CONSENSUS_WEIGHTS.items()) / n
    # conviction: strong-buys count double, normalised to 0-1 (all SB -> 1, all Buy -> 0.5)
    conviction = (2 * latest["strongBuy"] + latest["buy"]) / (2 * n)

    # drift: oldest period's avg minus latest — positive means opinion improved
    # (avg fell toward Strong Buy) over the ~4 months Finnhub returns.
    drift_raw = 0.0
    oldest = history[-1]
    on = sum(oldest[k] for k in CONSENSUS_WEIGHTS)
    if on:
        oavg = sum(oldest[k] * w for k, w in CONSENSUS_WEIGHTS.items()) / on
        drift_raw = oavg - avg
    drift_norm = _clamp(0.5 + drift_raw / 0.6)  # ±0.3 avg-points spans the full 0-1

    return {
        "n": n,
        "avg": avg,
        "conviction": conviction,
        "drift_raw": drift_raw,
        "drift_norm": drift_norm,
        "counts": {k: latest[k] for k in CONSENSUS_WEIGHTS},
        "period": latest.get("period"),
    }


def _beats(ticker: str):
    """(#beats, #quarters) over recent earnings, or (None, 0) if uncovered."""
    try:
        eh = prices.fetch_earnings_history(ticker, limit=4)
    except prices.PriceError:
        return None, 0
    surprises = [r for r in eh if r.get("surprise_percent") is not None]
    if not surprises:
        return None, 0
    beat = sum(1 for r in surprises if r["surprise_percent"] > 0)
    return beat, len(surprises)


def score_ticker(ticker: str) -> dict:
    """Compute the Opportunities-B composite for a single ticker on demand. Works for
    ANY ticker (in the top-20 or not, S&P 500 or not) since the score depends only on
    conviction/beats/drift, not on list membership. Returns None if the ticker has no
    usable analyst coverage."""
    try:
        m = _consensus_metrics(prices.fetch_recommendation_history(ticker))
    except prices.PriceError:
        return None
    if not m:
        return None
    beat, beat_total = _beats(ticker)
    beats_norm = (beat / beat_total) if beat_total else 0.5
    composite = W_CONVICTION * m["conviction"] + W_BEATS * beats_norm + W_DRIFT * m["drift_norm"]
    return {
        "composite": composite,
        "conviction": m["conviction"],
        "consensus_avg": m["avg"],
        "n": m["n"],
        "beats": beat,
        "beats_total": beat_total,
        "drift": m["drift_raw"],
    }


def build(universe_limit: int = None) -> dict:
    """Run the full funnel and write data/opportunities_b.json. `universe_limit`
    caps how many names Stage 1 scans (used only for quick tests)."""
    universe = load_universe()
    tickers = list(universe.keys())
    if universe_limit:
        tickers = tickers[:universe_limit]

    # Stage 1 — consensus over the universe
    stage1 = []
    errors = 0
    for i, t in enumerate(tickers):
        try:
            m = _consensus_metrics(prices.fetch_recommendation_history(t))
        except prices.PriceError:
            m = None
            errors += 1
        if m and m["n"] >= MIN_ANALYSTS and m["avg"] <= MAX_CONSENSUS_AVG:
            stage1.append((t, m))
        if i < len(tickers) - 1:
            time.sleep(RATE_SLEEP)

    stage1.sort(key=lambda x: x[1]["conviction"], reverse=True)
    shortlist = stage1[:SHORTLIST_SIZE]

    # Stage 2 — enrich the shortlist with earnings-beat consistency + composite
    zacks = zacks_import.load_ranks().get("ranks", {})
    results = []
    for idx, (t, m) in enumerate(shortlist):
        beat, beat_total = _beats(t)
        beats_norm = (beat / beat_total) if beat_total else 0.5  # neutral if uncovered
        composite = W_CONVICTION * m["conviction"] + W_BEATS * beats_norm + W_DRIFT * m["drift_norm"]
        results.append({
            "ticker": t,
            "company": universe[t]["company"],
            "sector": universe[t]["sector"],
            "composite": composite,
            "conviction": m["conviction"],
            "consensus_avg": m["avg"],
            "consensus": m["counts"],
            "n": m["n"],
            "drift": m["drift_raw"],
            "beats": beat,
            "beats_total": beat_total,
            "also_zacks_1": zacks.get(t, {}).get("rank") == 1,
            "period": m["period"],
        })
        if idx < len(shortlist) - 1:
            time.sleep(RATE_SLEEP)

    results.sort(key=lambda r: r["composite"], reverse=True)
    final = results[:FINAL_SIZE]

    # Price momentum for just the final list (1 Finnhub metric call each — free tier,
    # no Alpha Vantage budget). 1-week (5-day) and 3-month (13-week) trailing returns.
    for i, r in enumerate(final):
        try:
            ret = prices.fetch_price_returns(r["ticker"])
            r["move_1w"], r["move_3m"] = ret["move_1w"], ret["move_3m"]
        except prices.PriceError:
            r["move_1w"], r["move_3m"] = None, None
        if i < len(final) - 1:
            time.sleep(RATE_SLEEP)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(tickers),
        "passed_filter": len(stage1),
        "fetch_errors": errors,
        "list": final,
    }
    OUTPUT_FILE.write_text(json.dumps(out, indent=2))
    return out
