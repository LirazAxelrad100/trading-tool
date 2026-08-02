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
