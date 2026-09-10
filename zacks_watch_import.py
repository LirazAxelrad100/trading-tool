import csv
import json
import re
from pathlib import Path

import zacks_import

DOWNLOADS_DIR = Path.home() / "Downloads"
STATE_FILE = Path(__file__).parent / "data" / "zacks_watch_state.json"
FILENAME_PATTERN = re.compile(r"(zacks|rank|growth)", re.IGNORECASE)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"processed": {}}
    return json.loads(STATE_FILE.read_text())


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def run() -> None:
    state = load_state()
    processed = state["processed"]

    candidates = [p for p in DOWNLOADS_DIR.glob("*.csv") if FILENAME_PATTERN.search(p.name)]

    for path in candidates:
        mtime = path.stat().st_mtime
        if processed.get(path.name) == mtime:
            continue

        try:
            # Route on the file's own columns rather than its name. The Growth export
            # arrives named after whatever the Zacks portfolio is called (e.g.
            # "liraz_-_growth-2026-09-10.csv"), so a filename rule would skip it silently.
            with open(path, newline="", encoding="utf-8-sig") as f:
                header = csv.DictReader(f).fieldnames
            if zacks_import.is_growth_export(header):
                result = zacks_import.import_growth_csv(path)
                print(f"Imported growth estimates from {path.name}: {result['imported_count']} tickers")
            else:
                result = zacks_import.import_csv(path)
                print(f"Imported {path.name}: {result['imported_count']} tickers")
        except ValueError as e:
            print(f"Skipped {path.name}: {e}")
        except Exception as e:
            print(f"Failed on {path.name}: {e}")
            continue

        processed[path.name] = mtime

    save_state(state)


if __name__ == "__main__":
    run()
