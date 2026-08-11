import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import prices

CACHE_FILE = Path(__file__).parent / "data" / "consensus_cache.json"

CONSENSUS_WEIGHTS = {"strong_buy": 1, "buy": 2, "hold": 3, "sell": 4, "strong_sell": 5}


def compute_average(consensus: dict) -> Optional[float]:
    total = sum(consensus[key] for key in CONSENSUS_WEIGHTS)
    if total == 0:
        return None
    weighted = sum(consensus[key] * weight for key, weight in CONSENSUS_WEIGHTS.items())
    return weighted / total


def _load() -> dict:
    if not CACHE_FILE.exists():
        return {}
    return json.loads(CACHE_FILE.read_text())


def _save(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def get(ticker: str) -> Optional[dict]:
    """Cached consensus for a ticker, if any surface has fetched it before — used to
    overlay a GET response so every screen shows the same number without needing its
    own refresh to have just run."""
    return _load().get(ticker.upper())


def refresh(ticker: str) -> dict:
    """The one place that calls Finnhub for analyst consensus. Holdings, Opportunities
    (Zacks), Watchlist, and Analyze/Compare all used to fetch this independently and
    store it in four separate places, so the same ticker could show a different
    consensus number on different screens depending on which was refreshed most
    recently. Every refresh path now writes here, and every display reads from here
    (see overlay_consensus), so the number is always identical everywhere."""
    ticker = ticker.upper()
    consensus = prices.fetch_analyst_consensus(ticker)
    entry = {**consensus, "average": compute_average(consensus), "fetched_at": datetime.now(timezone.utc).isoformat()}
    cache = _load()
    cache[ticker] = entry
    _save(cache)
    return entry


def overlay_consensus(ticker: str, avg_key: str = "consensus_avg", full_key: str = "consensus") -> dict:
    """The two fields every consensus display already reads, sourced from the shared
    cache when available so a screen never shows its own stale, independently-fetched
    copy alongside another screen's fresher one."""
    entry = get(ticker)
    if entry is None:
        return {}
    return {full_key: entry, avg_key: entry["average"]}
