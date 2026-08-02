import json
import re
from pathlib import Path

import zacks_import

DOWNLOADS_DIR = Path.home() / "Downloads"
STATE_FILE = Path(__file__).parent / "data" / "zacks_watch_state.json"
FILENAME_PATTERN = re.compile(r"(zacks|rank)", re.IGNORECASE)


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
