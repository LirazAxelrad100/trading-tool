import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_FILE = Path(__file__).parent / "data" / "zacks_ranks.json"
RANK_IN_FILENAME = re.compile(r"rank[_-]?(\d)", re.IGNORECASE)


def guess_default_rank(filename: str) -> Optional[int]:
    match = RANK_IN_FILENAME.search(filename)
    return int(match.group(1)) if match else None


def parse_pct(value: Optional[str]) -> Optional[float]:
    if not value or value.strip().upper() == "NA":
        return None
    try:
        return float(value.strip().rstrip("%"))
    except ValueError:
        return None


def parse_num(value: Optional[str]) -> Optional[float]:
    if not value or value.strip().upper() == "NA":
        return None
    try:
        return float(value.strip().replace(",", ""))
    except ValueError:
        return None


# (csv header, output key, parser) for optional metric columns some Zacks exports include
METRIC_COLUMNS = [
    ("Industry", "industry", str.strip),
    ("Price", "price", parse_num),
    ("Price Movers: 1 Week(%)", "price_move_1w", parse_pct),
    ("Price Movers: 4 Week(%)", "price_move_4w", parse_pct),
    ("EPS F1 Est: 4 Week Change", "eps_est_change_4w", parse_pct),
    ("Projected Earnings Growth (1 Yr)(%)", "earnings_growth_1y", parse_pct),
    ("Value Score", "value_score", str.strip),
    ("Growth Score", "growth_score", str.strip),
    ("Momentum Score", "momentum_score", str.strip),
    ("VGM Score", "vgm_score", str.strip),
]


def parse_zacks_csv(path: Path, default_rank: Optional[int] = None) -> dict:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        ticker_field = "Ticker" if "Ticker" in fieldnames else "Symbol"
        company_field = "Company Name" if "Company Name" in fieldnames else "Company"
        has_rank_column = "Zacks Rank" in fieldnames
        available_metrics = [(h, key, parser) for h, key, parser in METRIC_COLUMNS if h in fieldnames]

        if not has_rank_column and default_rank is None:
            raise ValueError(
                "This CSV has no 'Zacks Rank' column, and no default_rank was given. "
                "Pass default_rank= to say what rank every row in this file represents."
            )

        entries = {}
        for row in reader:
            ticker = (row.get(ticker_field) or "").strip().upper()
            if not ticker:
                continue
            if has_rank_column:
                try:
                    rank = int(row.get("Zacks Rank", "").strip())
                except ValueError:
                    continue
            else:
                rank = default_rank

            entry = {
                "company": (row.get(company_field) or "").strip(),
                "rank": rank,
            }
            for header, key, parser in available_metrics:
                raw = row.get(header)
                entry[key] = parser(raw) if raw is not None else None
            entries[ticker] = entry
    return entries


def load_ranks() -> dict:
    if not DATA_FILE.exists():
        return {"last_imported_at": None, "last_source_file": None, "ranks": {}}
    return json.loads(DATA_FILE.read_text())


def save_ranks(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, indent=2))


# Enrichment fields that live on a ticker's entry but don't come from the CSV
# (populated separately by the consensus-refresh batch). Preserve these across a
# re-import so a fresh CSV doesn't wipe the ~4-minute consensus fetch.
PRESERVED_KEYS = ("consensus", "consensus_avg", "previous_consensus_avg")


def import_csv(path: Path, default_rank: Optional[int] = None) -> dict:
    if default_rank is None:
        default_rank = guess_default_rank(path.name)
    new_entries = parse_zacks_csv(path, default_rank=default_rank)
    data = load_ranks()
    ranks = data["ranks"]
    now = datetime.now(timezone.utc).isoformat()

    added = [t for t in new_entries if t not in ranks]

    for ticker, entry in new_entries.items():
        existing = ranks.get(ticker, {})
        preserved = {k: existing[k] for k in PRESERVED_KEYS if k in existing}
        ranks[ticker] = {**entry, **preserved, "imported_at": now, "source_file": path.name}

    # Prune tickers that were in a rank tier this import covers but dropped off the
    # new list — e.g. a stock that left Rank 1 today. Only tiers present in this file
    # are touched, so a separately-imported rank-2 set isn't disturbed by a rank-1 import.
    imported_ranks = {e["rank"] for e in new_entries.values()}
    removed = [
        t for t, e in list(ranks.items())
        if t not in new_entries and e.get("rank") in imported_ranks
    ]
    for t in removed:
        del ranks[t]

    data["last_imported_at"] = now
    data["last_source_file"] = path.name
    save_ranks(data)
    return {
        "imported_count": len(new_entries),
        "added_count": len(added),
        "removed_count": len(removed),
        "source_file": path.name,
        "imported_at": now,
    }


# ---------------------------------------------------------------------------
# Zacks "Growth" portfolio export — the only free source of *forward* estimates
# ---------------------------------------------------------------------------
# Every other number in this tool looks backwards. Finnhub's estimate endpoints
# (stock/eps-estimate, stock/revenue-estimate, stock/price-target) are all paid-tier
# and 403 on ours, live-tested 2026-09-10. Its metric block does carry `forwardPE`,
# but that cannot be turned into an expected growth rate: the trailing P/E there is
# built on official accounting profit while the forward one uses analysts' adjusted
# profit, so dividing one by the other mixes two different definitions — on MMSI it
# implied +83% against Zacks' own +12%.
#
# This export solves it properly, because it gives the estimates themselves rather
# than a ratio built from them: last year's actual EPS and the estimates for this
# and next fiscal year, on one consistent basis. It comes from the user's own Zacks
# account via the portfolio page's Export button — a manual CSV export, which the
# project's no-automated-acquisition rule allows (it is the scraping/login that is
# out of bounds, not ingesting a file the user downloaded).
#
# It also supplies the next earnings date per ticker, which Finnhub's free tier
# cannot give per symbol at all (see the calendar/earnings note in CLAUDE.md).

GROWTH_FILE = Path(__file__).parent / "data" / "zacks_growth.json"

GROWTH_REQUIRED_COLUMNS = ("This FY Est", "Next FY Est")


def is_growth_export(fieldnames) -> bool:
    """Route by columns, not filename. The user exports these by hand and the file
    arrives named after whatever the portfolio is called, so a filename rule would
    miss it — and silently, which is the worst kind of miss."""
    names = set(fieldnames or [])
    return all(c in names for c in GROWTH_REQUIRED_COLUMNS)


def _growth_pct(base: Optional[float], later: Optional[float]) -> Optional[float]:
    """Percent change, or None when the starting point makes it meaningless.

    A base at or below zero is the trap: PBF went from -4.13 to 15.73, which is a real
    and welcome swing but not a growth *rate* — the arithmetic would report -481%. Same
    judgement as fundamentals.eps_base_distorted, for the same reason: a number that
    cannot be read plainly is worse than a blank."""
    if base is None or later is None or base <= 0:
        return None
    return (later / base - 1) * 100


def parse_report_date(value: Optional[str]) -> Optional[str]:
    """Zacks writes M/D/YY. Store ISO so the frontend can format it EU-style."""
    if not value or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%y").date().isoformat()
    except ValueError:
        return None


def parse_growth_csv(path: Path) -> dict:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not is_growth_export(reader.fieldnames):
            raise ValueError(
                "This CSV has no 'This FY Est'/'Next FY Est' columns — it is not a Zacks "
                "Growth export. On the portfolio page, pick the Growth tab before Export."
            )
        entries = {}
        for row in reader:
            ticker = (row.get("Symbol") or "").strip().upper()
            if not ticker:
                continue
            last = parse_num(row.get("Last FY Actual"))
            this_fy = parse_num(row.get("This FY Est"))
            next_fy = parse_num(row.get("Next FY Est"))
            entries[ticker] = {
                "company": (row.get("Company") or "").strip(),
                "growth_score": (row.get("Growth Score") or "").strip() or None,
                "last_fy_actual": last,
                "this_fy_est": this_fy,
                "next_fy_est": next_fy,
                # This year against last year's actual, and next year against this year's
                # estimate. The second is the forward one worth reading: both sides are
                # estimates, so it is a clean statement of the growth analysts expect.
                "growth_this_year_pct": _growth_pct(last, this_fy),
                "growth_next_year_pct": _growth_pct(this_fy, next_fy),
                "ltg_pct": parse_pct(row.get("LTG %")),
                "next_report_date": parse_report_date(row.get("Next Report Date")),
            }
    return entries


def load_growth() -> dict:
    if not GROWTH_FILE.exists():
        return {"last_imported_at": None, "last_source_file": None, "growth": {}}
    return json.loads(GROWTH_FILE.read_text())


def import_growth_csv(path: Path) -> dict:
    """Merge rather than replace: the export only covers the tickers in that portfolio,
    so a second export for a different set must add to what is there rather than wipe it.
    No pruning either — unlike the rank list, a ticker missing from this file means it was
    not in the portfolio, not that anything about it changed."""
    new_entries = parse_growth_csv(path)
    data = load_growth()
    now = datetime.now(timezone.utc).isoformat()
    for ticker, entry in new_entries.items():
        data["growth"][ticker] = {**entry, "imported_at": now, "source_file": path.name}
    data["last_imported_at"] = now
    data["last_source_file"] = path.name
    GROWTH_FILE.write_text(json.dumps(data, indent=2))
    return {
        "imported_count": len(new_entries),
        "source_file": path.name,
        "imported_at": now,
    }


def overlay_growth(ticker: str) -> dict:
    """The forward fields for one ticker, or {} — shaped like consensus_store's overlay so
    the GET handlers can merge it at read time without every caller knowing the file."""
    entry = load_growth()["growth"].get(ticker.upper())
    if not entry:
        return {}
    return {
        "growth_next_year_pct": entry.get("growth_next_year_pct"),
        "growth_this_year_pct": entry.get("growth_this_year_pct"),
        "next_report_date": entry.get("next_report_date"),
    }
