"""Daily snapshot of data/ and CLAUDE.md to a folder outside the repo.

Everything in data/ is gitignored (real positions must not reach git), which means git
is no longer an accidental backup of it — and the irreplaceable parts cannot be rebuilt
from anywhere else: portfolio_history.json and holdings_history.json are time series only
recordable going forward, and holdings.json holds reference_high/trailing_pct/exit_plan,
which the broker doesn't know.

CLAUDE.md is here for the same reason as of 22.09.2026. It used to be tracked, and the
repo is public, so every session that wrote a real figure into it published one — a risk
that had to be managed forever rather than fixed once. Untracking it ends that, but it
also means the project's entire accumulated context now lives in exactly one file on one
machine, with nothing behind it. So it gets backed up with the data.

Written in Python and run by launchd through the venv interpreter on purpose: that binary
already has Full Disk Access granted, so it can read ~/Documents (see CLAUDE.md).
"""

import shutil
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
EXTRA_FILES = [PROJECT_DIR / "CLAUDE.md"]  # untracked since 22.09.2026 — see the docstring
BACKUP_ROOT = Path.home() / "Documents" / "trading-tool-backups"
KEEP_DAYS = 30


def main() -> None:
    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"No JSON files in {DATA_DIR} — refusing to write an empty snapshot.")
    # A missing extra is skipped rather than fatal: the data is the thing that cannot be
    # rebuilt, and a renamed context file should not cost a day's snapshot of it.
    files += [f for f in EXTRA_FILES if f.exists()]

    dest = BACKUP_ROOT / date.today().isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)

    # Rotate: keep the newest KEEP_DAYS snapshots. Names are ISO dates, so they sort
    # chronologically as strings.
    snapshots = sorted((d for d in BACKUP_ROOT.iterdir() if d.is_dir()), key=lambda d: d.name)
    for old in snapshots[:-KEEP_DAYS]:
        shutil.rmtree(old)

    kept = min(len(snapshots), KEEP_DAYS)
    print(f"{date.today().isoformat()}: backed up {len(files)} files to {dest} ({kept} snapshots kept)")


if __name__ == "__main__":
    main()
