"""The Monday email: is each holding still doing what I bought it for? (2026-11-24)

Her request after VLO, where next year's profit had been expected below this year's for two
weeks without her noticing: "a weekly checking of how my holdings are doing ... something
that will give me indication if the stock is doing what i want it to or i should consider it."

Built on three rules from that conversation:
- **Only what needs a look.** A holding with nothing to say is named once at the end. The
  grey status line under each row was removed the same day for being noise; an email that
  lists every holding every week would be the same mistake.
- **Her own reasons first.** Where her wrong-if is a number (`estimate_floor` on the
  holding: next year's profit per share), it is checked against the latest export.
- **Facts, never a verdict.** "Next year's estimate fell 3%", never "consider selling".

Sources, all free:
- Estimates: the Zacks Growth export, compared week on week through `estimate_history.json`
  (recorded on every import, backfilled from the daily backups). Zacks' screener can't
  restrict a screen to her portfolio, so the 4-week estimate-change columns aren't available.
- Zacks Rank and analysts: her portfolio's "Daily update" and "Broker recs" exports, read
  straight from ~/Downloads (newest file of each). Stale or missing files are said, not hidden.
- Price trend: Lang & Schwarz daily closes (ls_tc.daily_closes), EUR, no daily cap.

Sent once per week, on the first daily run from Monday 08:00 (daily_check.weekly_email()).
"""

import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent / "data"
ESTIMATE_HISTORY_FILE = DATA_DIR / "estimate_history.json"
STATE_FILE = DATA_DIR / "weekly_check_state.json"
CHECKPOINTS_FILE = DATA_DIR / "checkpoints.json"
DOWNLOADS_DIR = Path.home() / "Downloads"
BACKUP_DIR = Path.home() / "Documents" / "trading-tool-backups"

NEAR_STOP = 0.05  # within 5% above the stop loss
REPORT_SOON_DAYS = 14  # time to write a decision question first
ESTIMATE_MOVE = 0.005  # a change under 0,5% is rounding, not a revision
STALE_DAYS = 8  # an export older than this is called out


# ---------- estimate history ----------

def _load_history() -> dict:
    return json.loads(ESTIMATE_HISTORY_FILE.read_text()) if ESTIMATE_HISTORY_FILE.exists() else {}


def record_estimates(growth: dict, on: str) -> None:
    """One point per ticker per export day: {ticker: {date: {"this": x, "next": y}}}.
    Called by zacks_import.import_growth_csv() on every import."""
    hist = _load_history()
    for ticker, g in growth.items():
        if g.get("this_fy_est") is None and g.get("next_fy_est") is None:
            continue
        hist.setdefault(ticker, {})[on] = {"this": g.get("this_fy_est"), "next": g.get("next_fy_est")}
    ESTIMATE_HISTORY_FILE.write_text(json.dumps(hist, indent=1, sort_keys=True))


def backfill_from_backups() -> int:
    """Seed the history from the daily backups' copies of zacks_growth.json, keyed by each
    entry's own import date, so week-on-week works from the first email. Safe to rerun."""
    hist, added = _load_history(), 0
    for snap in sorted(BACKUP_DIR.glob("20*/zacks_growth.json")):
        for ticker, g in (json.loads(snap.read_text()).get("growth") or {}).items():
            on = (g.get("imported_at") or "")[:10]
            if on and on not in hist.get(ticker, {}) and g.get("next_fy_est") is not None:
                hist.setdefault(ticker, {})[on] = {"this": g.get("this_fy_est"), "next": g.get("next_fy_est")}
                added += 1
    ESTIMATE_HISTORY_FILE.write_text(json.dumps(hist, indent=1, sort_keys=True))
    return added


def _point_before(points: dict, latest: str, days: int) -> Optional[tuple]:
    """The newest recorded export at least `days` before the latest one."""
    cutoff = (date.fromisoformat(latest) - timedelta(days=days)).isoformat()
    older = [d for d in points if d <= cutoff]
    return (max(older), points[max(older)]) if older else None


# ---------- Zacks portfolio exports in Downloads ----------

def _num(s) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def latest_export(kind: str) -> tuple:
    """({ticker: row}, file date) from the newest '<portfolio>_-_<kind>-YYYY-MM-DD.csv'."""
    files = sorted(DOWNLOADS_DIR.glob(f"*_-_{kind}-*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        return {}, None
    path = files[-1]
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = {r["Symbol"].strip().upper(): r for r in csv.DictReader(f) if r.get("Symbol")}
    return rows, (m.group(1) if m else None)


def _col(row: dict, start: str):
    """Zacks headers carry markup ('Upgrades<br />(1 Wk)'), so match on how they start."""
    return next((v for k, v in row.items() if k and k.startswith(start)), None)


# ---------- the check ----------

def _eu(n: float) -> str:
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(r: float, sign: bool = True) -> str:
    s = f"{abs(r) * 100:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + "%"
    return (("+" if r > 0 else "−" if r < 0 else "") + s) if sign else s


def _d(iso: str) -> str:
    return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d.%m.%Y")


def _price_trend(closes: dict) -> Optional[dict]:
    days = sorted(closes)
    if len(days) < 60:
        return None
    c = [closes[d] for d in days]
    avg_now = sum(c[-50:]) / 50
    avg_before = sum(c[-60:-10]) / 50
    return {"vs_avg": c[-1] / avg_now - 1, "avg_falling": avg_now < avg_before, "four_weeks": c[-1] / c[-21] - 1}


def build(holdings: list, growth: dict, closes_for, state: dict, today: Optional[date] = None) -> dict:
    """Subject, body and the ranks to remember. `closes_for(holding)` returns {date: close}."""
    today = today or date.today()
    hist = _load_history()
    update, update_date = latest_export("update")
    broker, broker_date = latest_export("broker")
    checkpoints = json.loads(CHECKPOINTS_FILE.read_text()) if CHECKPOINTS_FILE.exists() else []
    last_ranks = state.get("ranks") or {}

    flagged, quiet, raised, ranks = [], [], [], {}
    export_days, compared_days = set(), set()
    for h in holdings:
        t = h["ticker"]
        lines = []
        g = growth.get(t) or {}
        this_est, next_est = g.get("this_fy_est"), g.get("next_fy_est")

        # Her own wrong-if, where it is a number.
        floor = h.get("estimate_floor")
        if floor and next_est is not None and next_est < floor:
            lines.append(f"Your wrong-if: next year's estimate is ${_eu(next_est)}, below your line of ${_eu(floor)}.")

        # Estimates, week on week and over four weeks.
        points = hist.get(t) or {}
        if points:
            latest = max(points)
            export_days.add(latest)
            now = points[latest]["next"]
            week = _point_before(points, latest, 6)
            month = _point_before(points, latest, 27)
            if week and now is not None and week[1]["next"]:
                compared_days.add(week[0])
                ch = now / week[1]["next"] - 1
                if ch <= -ESTIMATE_MOVE:
                    four = f", {_pct(now / month[1]['next'] - 1)} over four weeks" if month and month[1]["next"] else ""
                    lines.append(f"Next year's estimate cut: ${_eu(week[1]['next'])} → ${_eu(now)} ({_pct(ch)}{four}).")
                elif ch >= ESTIMATE_MOVE:
                    raised.append(f"{t} {_pct(ch)}")
        # VLO's lesson (rules file, lesson 4): not cut is not the same as growing.
        if this_est and next_est is not None and this_est > 0 and next_est < this_est:
            lines.append(f"Next year's profit per share expected below this year's: ${_eu(this_est)} → ${_eu(next_est)} ({_pct(next_est / this_est - 1)}).")

        # Zacks Rank and analysts.
        rank = _num(_col(update.get(t, {}), "Zacks Rank"))
        if rank:
            ranks[t] = int(rank)
            was = last_ranks.get(t)
            if was and rank > was:
                lines.append(f"Zacks Rank worse: {was} → {int(rank)}.")
            elif rank >= 4 and not was:
                lines.append(f"Zacks Rank {int(rank)} (sell side).")
        b = broker.get(t)
        if b:
            down = _num(_col(b, "Downgrades")) or 0
            abr_ch = _num(_col(b, "Change")) or 0
            if down:
                lines.append(f"{int(down)} analyst downgrade{'s' if down > 1 else ''} this week.")
            elif abr_ch >= 0.1:
                abr = _num(_col(b, "ABR"))
                lines.append(f"Analysts' average rating worse this week: {abr - abr_ch:.2f} → {abr:.2f} (1 = strong buy, 5 = strong sell).".replace(".", ","))

        # Price: stop loss and trend.
        price, stop = h.get("current_price"), h.get("stop_price")
        if price and stop:
            gap = price / stop - 1
            if gap < 0:
                lines.append(f"Below its stop loss ({_eu(stop)}) by {_pct(-gap, sign=False)}.")
            elif gap <= NEAR_STOP:
                lines.append(f"{_pct(gap, sign=False)} above its stop loss ({_eu(stop)}).")
        trend = _price_trend(closes_for(h) or {})
        if trend and trend["vs_avg"] < 0 and trend["avg_falling"]:
            lines.append(f"Falling: below its 50-day average, which is itself going down; {_pct(trend['four_weeks'])} in four weeks.")

        # A report soon: time to write the decision question first.
        report = g.get("next_report_date")
        if report and today.isoformat() <= report <= (today + timedelta(days=REPORT_SOON_DAYS)).isoformat():
            written = any(cp.get("ticker") == t and cp.get("report_date") == report for cp in checkpoints)
            lines.append(f"Reports on {_d(report)}." + (" Your decision question is ready." if written else " No decision question written yet."))

        (flagged.append((t, lines)) if lines else quiet.append(t))

    head = [f"Weekly check — {today.strftime('%d.%m.%Y')}", ""]
    if export_days:
        latest = max(export_days)
        head.append(
            f"Estimates: your Growth export of {_d(latest)}"
            + (f", compared with {_d(max(compared_days))}." if compared_days else ". Nothing a week older to compare with yet.")
        )
        if (today - date.fromisoformat(latest)).days > STALE_DAYS:
            head.append("That export is more than a week old: export Growth again for current estimates.")
    for name, d in (("Daily update", update_date), ("Broker recs", broker_date)):
        if not d:
            head.append(f"No '{name}' export found in Downloads, so its part is missing.")
        elif (today - date.fromisoformat(d)).days > STALE_DAYS:
            head.append(f"Your '{name}' export is from {_d(d)}: export it again for this week's figures.")
    head.append("")

    body = head
    if flagged:
        body.append("Worth a look:")
        for t, lines in flagged:
            body += ["", t] + [f"  - {l}" for l in lines]
        body.append("")
    if raised:
        body.append("Next year's estimate raised this week: " + " · ".join(raised) + ".")
    if quiet:
        body.append("Nothing new: " + " · ".join(quiet) + ".")
    body += ["", "Facts only. Whether any of this changes your reason to own a stock is your call."]

    n = len(flagged)
    subject = f"Weekly check: {n} holding{'s' if n != 1 else ''} worth a look" if n else "Weekly check: nothing new"
    return {"subject": subject, "body": "\n".join(body), "ranks": ranks}


def due(state: dict, today: Optional[date] = None) -> bool:
    """Once per ISO week, from Monday on: a missed Monday goes out on the next day's run."""
    today = today or date.today()
    return state.get("last_week") != today.strftime("%G-W%V")


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def mark_sent(ranks: dict, today: Optional[date] = None) -> None:
    today = today or date.today()
    STATE_FILE.write_text(json.dumps({"last_week": today.strftime("%G-W%V"), "sent_on": today.isoformat(), "ranks": ranks}, indent=1))
