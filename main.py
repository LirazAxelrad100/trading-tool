import json
import shutil
import tempfile
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import alpha_vantage
import consensus_store
import ls_tc
import opportunities_b
import prices
import sectors
import synthesis
import zacks_import
from alpha_vantage import AlphaVantageError
from prices import PriceError

DATA_FILE = Path(__file__).parent / "data" / "holdings.json"
SALES_HISTORY_FILE = Path(__file__).parent / "data" / "sales_history.json"
PORTFOLIO_HISTORY_FILE = Path(__file__).parent / "data" / "portfolio_history.json"
HOLDINGS_HISTORY_FILE = Path(__file__).parent / "data" / "holdings_history.json"
WATCHLIST_FILE = Path(__file__).parent / "data" / "watchlist.json"
STATIC_DIR = Path(__file__).parent / "static"
DOWNLOADS_DIR = Path.home() / "Downloads"

app = FastAPI(title="Trading Tool")

ExitPlan = Literal["sell_all", "sell_gains_only", "hold"]
EXIT_PLAN_LABELS = {
    "sell_all": "Sell all",
    "sell_gains_only": "Sell gains only",
    "hold": "Hold / reassess",
}
CAPITAL_GAINS_TAX_RATE = 0.26375


def load_holdings() -> list[dict]:
    holdings = json.loads(DATA_FILE.read_text())
    migrated = False
    for h in holdings:
        if "current_price" not in h:
            h["current_price"] = h["reference_high"]
            migrated = True
        if "exit_plan" not in h:
            h["exit_plan"] = "hold"
            migrated = True
        if "previous_price" not in h:
            h["previous_price"] = h["current_price"]
            migrated = True
        if "consensus" not in h:
            h["consensus"] = None
            h["consensus_avg"] = None
            h["previous_consensus_avg"] = None
            migrated = True
        if "day_open_price" in h:
            del h["day_open_price"]
            del h["day_open_date"]
            migrated = True
        if "day_change_pct" not in h:
            h["day_change_pct"] = None
            migrated = True
        if "manual_price" not in h:
            h["manual_price"] = False
            migrated = True
        if "lots" not in h:
            # Multi-lot migration: the old single cost basis becomes one lot.
            h["lots"] = [{
                "shares": h["shares"],
                "cost_basis": h["cost_basis"],
                "purchase_date": h["purchase_date"],
            }]
            migrated = True
    for h in holdings:
        recompute_aggregates(h)  # keep derived shares/cost_basis/purchase_date in sync with lots
    if migrated:
        save_holdings(holdings)
    return holdings


def recompute_aggregates(holding: dict) -> None:
    """Derive the position-level shares / weighted-average cost_basis / earliest
    purchase_date from the lots, so all existing code and UI keep reading those
    fields unchanged. Lots are the source of truth."""
    lots = holding.get("lots") or []
    total_shares = sum(lot["shares"] for lot in lots)
    holding["shares"] = total_shares
    if total_shares > 0:
        holding["cost_basis"] = sum(lot["shares"] * lot["cost_basis"] for lot in lots) / total_shares
        holding["purchase_date"] = min(lot["purchase_date"] for lot in lots)


def save_holdings(holdings: list[dict]) -> None:
    DATA_FILE.write_text(json.dumps(holdings, indent=2))


def load_sales_history() -> list[dict]:
    if not SALES_HISTORY_FILE.exists():
        return []
    return json.loads(SALES_HISTORY_FILE.read_text())


def save_sales_history(entries: list[dict]) -> None:
    SALES_HISTORY_FILE.write_text(json.dumps(entries, indent=2))


def load_portfolio_history() -> list[dict]:
    if not PORTFOLIO_HISTORY_FILE.exists():
        return []
    return json.loads(PORTFOLIO_HISTORY_FILE.read_text())


def save_portfolio_history(points: list[dict]) -> None:
    points.sort(key=lambda p: p["date"])
    PORTFOLIO_HISTORY_FILE.write_text(json.dumps(points, indent=2))


def record_portfolio_snapshot(holdings: list[dict]) -> None:
    """Upsert today's total portfolio value (shares × current_price, summed) into the
    history — one point per day, overwriting an earlier same-day refresh."""
    total = sum(h["shares"] * h["current_price"] for h in holdings)
    if total <= 0:
        return
    today = date.today().isoformat()
    points = [p for p in load_portfolio_history() if p["date"] != today]
    points.append({"date": today, "value": total})
    save_portfolio_history(points)


def load_holdings_history() -> list[dict]:
    if not HOLDINGS_HISTORY_FILE.exists():
        return []
    return json.loads(HOLDINGS_HISTORY_FILE.read_text())


def save_holdings_history(points: list[dict]) -> None:
    points.sort(key=lambda p: (p["date"], p["ticker"]))
    HOLDINGS_HISTORY_FILE.write_text(json.dumps(points, indent=2))


def record_holdings_snapshot(holdings: list[dict]) -> None:
    """Upsert today's per-holding value (shares × current_price) into the history —
    one point per ticker per day, overwriting an earlier same-day refresh. Feeds the
    weekly-by-stock table; started 2026-08-15, so history builds up going forward only."""
    today = date.today().isoformat()
    points = [p for p in load_holdings_history() if p["date"] != today]
    for h in holdings:
        value = h["shares"] * h["current_price"]
        if value <= 0:
            continue
        points.append({"date": today, "ticker": h["ticker"], "value": value})
    save_holdings_history(points)


class HoldingIn(BaseModel):
    ticker: str
    shares: float
    cost_basis: float
    purchase_date: str
    stop_price: float
    reference_high: Optional[float] = None
    trailing_pct: Optional[float] = None
    current_price: Optional[float] = None
    exit_plan: ExitPlan = "hold"
    isin: Optional[str] = None


class HoldingUpdate(BaseModel):
    ticker: Optional[str] = None
    shares: Optional[float] = None
    cost_basis: Optional[float] = None
    purchase_date: Optional[str] = None
    stop_price: Optional[float] = None
    reference_high: Optional[float] = None
    current_price: Optional[float] = None
    exit_plan: Optional[ExitPlan] = None
    manual_price: Optional[bool] = None
    isin: Optional[str] = None


class LotIn(BaseModel):
    shares: float
    cost_basis: float
    purchase_date: str


class LotUpdate(BaseModel):
    shares: float
    cost_basis: float
    purchase_date: str


class ConfirmRequest(BaseModel):
    new_reference_high: float
    new_stop_price: float


class SellRequest(BaseModel):
    shares_sold: float
    total_sum: float
    sell_date: str
    sell_time: Optional[str] = None
    override_price_check: bool = False


TRIGGER_THRESHOLD = 0.10
# A recorded sale price this many times off the holding's last known price is
# almost certainly a mistyped total (the comma/period trap that bit INTC and STX),
# not a real trade — no stock moves an order of magnitude between refresh and sale.
SALE_PRICE_SANITY_FACTOR = 10
# A fetched price this many times off the holding's stored price almost always
# means the ticker resolves to a different instrument than the user actually holds
# (e.g. LNVGY = a US ADR bundling 20 Trade-Republic ordinary shares). Rather than
# clobber the user's price, refresh flags it so they can switch to a manual price.
PRICE_MISMATCH_FACTOR = 10


def find_holding(holdings: list[dict], holding_id: str) -> dict:
    for h in holdings:
        if h["id"] == holding_id:
            return h
    raise HTTPException(status_code=404, detail="Holding not found")


@app.get("/api/holdings")
def list_holdings():
    holdings = load_holdings()
    for h in holdings:
        h.update(consensus_store.overlay_consensus(h["ticker"]))
    return holdings


@app.post("/api/holdings")
def create_holding(holding: HoldingIn):
    holdings = load_holdings()
    reference_high = holding.reference_high if holding.reference_high is not None else holding.cost_basis
    if holding.trailing_pct is not None:
        trailing_pct = holding.trailing_pct
    else:
        trailing_pct = (reference_high - holding.stop_price) / reference_high

    new_holding = {
        "id": str(uuid.uuid4()),
        "ticker": holding.ticker.upper(),
        "lots": [{
            "shares": holding.shares,
            "cost_basis": holding.cost_basis,
            "purchase_date": holding.purchase_date,
        }],
        "stop_price": holding.stop_price,
        "reference_high": reference_high,
        "trailing_pct": trailing_pct,
        "current_price": holding.current_price if holding.current_price is not None else reference_high,
        "previous_price": holding.current_price if holding.current_price is not None else reference_high,
        "exit_plan": holding.exit_plan,
        "consensus": None,
        "consensus_avg": None,
        "previous_consensus_avg": None,
        "day_change_pct": None,
        "manual_price": False,
        "isin": holding.isin.strip().upper() if holding.isin else None,
    }
    recompute_aggregates(new_holding)
    holdings.append(new_holding)
    save_holdings(holdings)
    return new_holding


@app.post("/api/holdings/{holding_id}/lots")
def add_lot(holding_id: str, lot: LotIn):
    holdings = load_holdings()
    holding = find_holding(holdings, holding_id)
    if lot.shares <= 0 or lot.cost_basis < 0:
        raise HTTPException(status_code=422, detail="Shares must be > 0 and cost basis >= 0.")
    holding.setdefault("lots", []).append({
        "shares": lot.shares,
        "cost_basis": lot.cost_basis,
        "purchase_date": lot.purchase_date,
    })
    recompute_aggregates(holding)
    save_holdings(holdings)
    return holding


@app.put("/api/holdings/{holding_id}/lots/{lot_index}")
def update_lot(holding_id: str, lot_index: int, lot: LotUpdate):
    holdings = load_holdings()
    holding = find_holding(holdings, holding_id)
    lots = holding.get("lots") or []
    if lot_index < 0 or lot_index >= len(lots):
        raise HTTPException(status_code=404, detail="Lot not found")
    if lot.shares <= 0 or lot.cost_basis < 0:
        raise HTTPException(status_code=422, detail="Shares must be > 0 and cost basis >= 0.")
    lots[lot_index] = {"shares": lot.shares, "cost_basis": lot.cost_basis, "purchase_date": lot.purchase_date}
    recompute_aggregates(holding)
    save_holdings(holdings)
    return holding


@app.delete("/api/holdings/{holding_id}/lots/{lot_index}")
def delete_lot(holding_id: str, lot_index: int):
    holdings = load_holdings()
    holding = find_holding(holdings, holding_id)
    lots = holding.get("lots") or []
    if lot_index < 0 or lot_index >= len(lots):
        raise HTTPException(status_code=404, detail="Lot not found")
    if len(lots) == 1:
        raise HTTPException(status_code=422, detail="Can't remove the last lot — sell the holding instead.")
    lots.pop(lot_index)
    recompute_aggregates(holding)
    save_holdings(holdings)
    return holding


@app.put("/api/holdings/{holding_id}")
def update_holding(holding_id: str, update: HoldingUpdate):
    holdings = load_holdings()
    holding = find_holding(holdings, holding_id)
    changes = update.model_dump(exclude_unset=True)

    # shares/cost_basis/purchase_date are derived from lots. For a single-lot holding
    # we forward an edit of them onto that one lot (keeps the plain Edit form working);
    # for a multi-lot holding they're ignored here — the per-lot editor handles those.
    lot_fields = {k: changes.pop(k) for k in ("shares", "cost_basis", "purchase_date") if k in changes}
    lots = holding.get("lots") or []
    if lot_fields and len(lots) == 1:
        lots[0].update(lot_fields)

    if "isin" in changes and changes["isin"]:
        changes["isin"] = changes["isin"].strip().upper()

    for key, value in changes.items():
        holding[key] = value

    if "current_price" in changes:
        # A manual price edit invalidates the refresh anchor (apply_quote) — otherwise
        # a same-day refresh right after this edit would ignore it and roll forward
        # from the stale pre-edit anchor instead. See apply_quote in main.py.
        holding.pop("price_anchor", None)
        holding.pop("anchor_fx_rate", None)
        holding.pop("anchor_previous_close_usd", None)

    recompute_aggregates(holding)
    holding["trailing_pct"] = (holding["reference_high"] - holding["stop_price"]) / holding["reference_high"]
    save_holdings(holdings)
    return holding


@app.post("/api/holdings/{holding_id}/sell")
def sell_holding(holding_id: str, sell: SellRequest):
    holdings = load_holdings()
    holding = find_holding(holdings, holding_id)

    if sell.shares_sold <= 0 or sell.shares_sold > holding["shares"] + 1e-9:
        raise HTTPException(
            status_code=422,
            detail="Shares sold must be greater than 0 and cannot exceed the holding's shares.",
        )

    sale_price = sell.total_sum / sell.shares_sold

    ref_price = holding.get("current_price")
    if not sell.override_price_check and ref_price and (
        sale_price > ref_price * SALE_PRICE_SANITY_FACTOR
        or sale_price < ref_price / SALE_PRICE_SANITY_FACTOR
    ):
        # Confirmable, not a hard block — the frontend turns this into a "record anyway?"
        # prompt and resubmits with override_price_check=True. Raw numbers only; the
        # frontend formats them (EU) into the message.
        raise HTTPException(
            status_code=422,
            detail={
                "code": "price_sanity",
                "ticker": holding["ticker"],
                "sale_price": sale_price,
                "ref_price": ref_price,
                "factor": SALE_PRICE_SANITY_FACTOR,
            },
        )

    # FIFO: consume the oldest lots first (German capital-gains basis). total_spend is
    # the actual cost of the specific shares sold, so realized gain matches the broker.
    lots = sorted(holding.get("lots") or [], key=lambda lot: lot["purchase_date"])
    remaining = sell.shares_sold
    total_spend = 0.0
    lots_sold = []
    kept = []
    for lot in lots:
        if remaining <= 1e-9:
            kept.append(lot)
            continue
        take = min(lot["shares"], remaining)
        total_spend += take * lot["cost_basis"]
        lots_sold.append({"shares": take, "cost_basis": lot["cost_basis"], "purchase_date": lot["purchase_date"]})
        remaining -= take
        leftover = lot["shares"] - take
        if leftover > 1e-9:
            kept.append({**lot, "shares": leftover})
    holding["lots"] = kept

    realized_gain = sell.total_sum - total_spend
    estimated_tax = max(0, realized_gain) * CAPITAL_GAINS_TAX_RATE
    effective_cost = total_spend / sell.shares_sold if sell.shares_sold else 0
    remaining_shares = sum(lot["shares"] for lot in kept)
    sell_datetime = f"{sell.sell_date}T{sell.sell_time}" if sell.sell_time else sell.sell_date

    entry = {
        "id": str(uuid.uuid4()),
        "ticker": holding["ticker"],
        "shares_sold": sell.shares_sold,
        "sale_price": sale_price,
        "total_sum": sell.total_sum,
        "cost_basis": effective_cost,  # FIFO-effective avg of the shares actually sold
        "total_spend": total_spend,
        "realized_gain": realized_gain,
        "estimated_tax": estimated_tax,
        "sell_datetime": sell_datetime,
        "purchase_date": lots_sold[0]["purchase_date"] if lots_sold else holding["purchase_date"],
        "lots_sold": lots_sold,  # per-lot FIFO breakdown
        "remaining_shares": remaining_shares,
    }

    entries = load_sales_history()
    entries.append(entry)
    save_sales_history(entries)

    if remaining_shares <= 1e-9:
        holdings = [h for h in holdings if h["id"] != holding_id]
    else:
        recompute_aggregates(holding)

    save_holdings(holdings)
    return entry


@app.get("/api/sales-history")
def list_sales_history():
    return sorted(load_sales_history(), key=lambda e: e["sell_datetime"], reverse=True)


@app.delete("/api/sales-history/{entry_id}")
def delete_sales_entry(entry_id: str):
    entries = load_sales_history()
    entries = [e for e in entries if e["id"] != entry_id]
    save_sales_history(entries)
    return {"ok": True}


class WatchlistIn(BaseModel):
    ticker: str


class WatchlistNoteIn(BaseModel):
    note: str = ""


def load_watchlist() -> list[dict]:
    if not WATCHLIST_FILE.exists():
        return []
    return json.loads(WATCHLIST_FILE.read_text())


def save_watchlist(items: list[dict]) -> None:
    WATCHLIST_FILE.write_text(json.dumps(items, indent=2))


def find_watch_item(items: list[dict], item_id: str) -> dict:
    for it in items:
        if it["id"] == item_id:
            return it
    raise HTTPException(status_code=404, detail="Watchlist item not found")


def fetch_watch_data(ticker: str, rate: float) -> dict:
    """Best-effort enrichment for one watchlist ticker: current price, 1W/3M trailing
    returns, the Opportunities-B composite score, and analyst consensus. Price is the
    only piece that must succeed (raises PriceError, since an unpriceable ticker is
    almost certainly a typo) — the rest degrade to None rather than blocking add/refresh,
    same spirit as synthesis.py's _safe()."""
    quote = prices.fetch_quote(ticker, rate)
    data = {
        "current_price": quote["price"],
        "move_1w": None,
        "move_3m": None,
        "score": None,
        "consensus": None,
        "last_refreshed": datetime.now(timezone.utc).isoformat(),
    }
    try:
        returns = prices.fetch_price_returns(ticker)
        data["move_1w"], data["move_3m"] = returns["move_1w"], returns["move_3m"]
    except PriceError:
        pass
    try:
        data["score"] = opportunities_b.score_ticker(ticker)
    except PriceError:
        pass
    try:
        data["consensus"] = consensus_store.refresh(ticker)
    except PriceError:
        pass
    return data


@app.get("/api/watchlist")
def list_watchlist():
    items = load_watchlist()
    for it in items:
        it.update(consensus_store.overlay_consensus(it["ticker"]))
    return items


@app.post("/api/watchlist")
def add_watchlist_item(item: WatchlistIn):
    items = load_watchlist()
    ticker = item.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=422, detail="Ticker is required.")
    if any(it["ticker"] == ticker for it in items):
        raise HTTPException(status_code=422, detail=f"{ticker} is already on your watch list.")
    try:
        rate = prices.fetch_usd_to_eur_rate()
        data = fetch_watch_data(ticker, rate)
    except PriceError as e:
        raise HTTPException(status_code=502, detail=f"Could not find a price for '{ticker}' — check the symbol. ({e})")

    new_item = {"id": str(uuid.uuid4()), "ticker": ticker, "added_date": date.today().isoformat(), "note": "", **data}
    items.append(new_item)
    save_watchlist(items)
    return new_item


@app.delete("/api/watchlist/{item_id}")
def delete_watchlist_item(item_id: str):
    items = load_watchlist()
    items = [it for it in items if it["id"] != item_id]
    save_watchlist(items)
    return {"ok": True}


@app.put("/api/watchlist/{item_id}/note")
def update_watchlist_note(item_id: str, body: WatchlistNoteIn):
    items = load_watchlist()
    watch_item = find_watch_item(items, item_id)
    watch_item["note"] = body.note
    save_watchlist(items)
    return watch_item


@app.post("/api/watchlist/{item_id}/refresh")
def refresh_watchlist_item(item_id: str):
    items = load_watchlist()
    watch_item = find_watch_item(items, item_id)
    try:
        rate = prices.fetch_usd_to_eur_rate()
        watch_item.update(fetch_watch_data(watch_item["ticker"], rate))
    except PriceError as e:
        raise HTTPException(status_code=502, detail=str(e))
    save_watchlist(items)
    return watch_item


@app.post("/api/watchlist/refresh-all")
def refresh_all_watchlist():
    items = load_watchlist()
    try:
        rate = prices.fetch_usd_to_eur_rate()
    except PriceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    errors = []
    for i, it in enumerate(items):
        try:
            it.update(fetch_watch_data(it["ticker"], rate))
        except PriceError as e:
            errors.append({"ticker": it["ticker"], "error": str(e)})
        if i < len(items) - 1:
            time.sleep(1)

    save_watchlist(items)
    return {"items": items, "errors": errors}


def evaluate_trailing(holding: dict, current_price: float) -> dict:
    reference_high = holding["reference_high"]
    stop_price = holding["stop_price"]

    stop_hit = current_price <= stop_price
    total_gain = (stop_price - holding["cost_basis"]) * holding["shares"]
    estimated_tax = max(0, total_gain) * CAPITAL_GAINS_TAX_RATE

    pct_move = (current_price - reference_high) / reference_high
    triggered = pct_move >= TRIGGER_THRESHOLD
    pct_above_stop = (current_price - stop_price) / stop_price

    result = {
        "id": holding["id"],
        "ticker": holding["ticker"],
        "stop_hit": stop_hit,
        "total_gain": total_gain,
        "estimated_tax": estimated_tax,
        "exit_plan": holding["exit_plan"],
        "exit_plan_label": EXIT_PLAN_LABELS[holding["exit_plan"]],
        "triggered": triggered,
        "old_high": reference_high,
        "new_price": current_price,
        "pct_move": pct_move,
        "pct_above_stop": pct_above_stop,
        "day_change_pct": holding.get("day_change_pct"),
        "current_stop": stop_price,
        "suggested_new_stop": None,
        "reset_new_stop": current_price * (1 - holding["trailing_pct"]),
        "analyst_consensus": None,
    }
    if triggered:
        result["suggested_new_stop"] = current_price * (1 - holding["trailing_pct"])
    result["analyst_consensus"] = holding.get("consensus")
    return result


def update_price(holding: dict, new_price: float) -> None:
    if new_price != holding["current_price"]:
        holding["previous_price"] = holding["current_price"]
    holding["current_price"] = new_price


def apply_ls_tc_price(holding: dict) -> bool:
    """If this holding has an ISIN, price it directly from Lang & Schwarz
    (ls-tc.de) — the actual EUR price Trade Republic trades against — instead
    of the Finnhub-based anchor/roll-forward approximation in apply_quote.
    Both current_price and day_change_pct come from ls-tc.de itself, so no
    anchor bookkeeping is needed (it's already the real price, not something
    to correct). Returns True if applied; False (no ISIN, or the fetch failed)
    means the caller should fall back to the existing Finnhub-based path. See
    ls_tc.py and CLAUDE.md."""
    isin = holding.get("isin")
    if not isin:
        return False
    try:
        quote = ls_tc.fetch_price(isin)
    except ls_tc.LsTcError:
        return False
    holding["day_change_pct"] = quote["day_change_pct"]
    update_price(holding, quote["price"])
    for k in ("price_anchor", "anchor_fx_rate", "anchor_previous_close_usd"):
        holding.pop(k, None)
    return True


def update_consensus(holding: dict, entry: dict) -> None:
    """entry is a consensus_store entry (already has "average" computed) — the single
    shared fetch, not an independent one, so this holding's number matches whatever
    Opportunities/Watchlist/Analyze show for the same ticker. See consensus_store.py."""
    new_avg = entry["average"]
    old_avg = holding.get("consensus_avg")
    if old_avg is None or new_avg != old_avg:
        holding["previous_consensus_avg"] = old_avg if old_avg is not None else new_avg
    holding["consensus"] = entry
    holding["consensus_avg"] = new_avg


def is_price_mismatch(holding: dict, fetched_price: float) -> bool:
    ref = holding.get("current_price")
    if not ref or not fetched_price:
        return False
    return fetched_price > ref * PRICE_MISMATCH_FACTOR or fetched_price < ref / PRICE_MISMATCH_FACTOR


def apply_quote(holding: dict, quote: dict, current_fx_rate: float) -> None:
    """Roll the price forward from a fixed EUR anchor (our believed price as of
    Finnhub's own previous close) by today's relative move (day_change_pct) and
    by how much the USD/EUR rate moved since that anchor was set — instead of
    overwriting with Finnhub's raw converted price. Finnhub's absolute number
    never matches Trade Republic's exactly (different venue for the underlying
    quote, different FX conversion), so replacing the stored price outright
    re-imports that gap on every refresh. Rolling forward relatively keeps it
    anchored to whatever true TR price it was last set to (manually, on a Sell,
    etc.) — see CLAUDE.md.

    The anchor — not the mutable current_price — is what day_change_pct gets
    applied to, and only advances when Finnhub's previous_close_usd itself
    changes (a new trading day). day_change_pct is always "vs. yesterday's
    close", not "vs. your last refresh", so applying it on top of an
    already-rolled-forward current_price would double-count the same move on a
    second same-day refresh.

    Two different situations both leave a holding with no anchor, and they need
    different bootstrap math. A genuine new trading day (anchor_previous_close_usd
    is present but stale) means current_price is our last TR-verified value as of
    a prior close — a valid "0%" baseline, so today's full move applies to it as-is.
    A manual price edit (main.py's PUT handler) or a brand-new holding instead
    leaves current_price representing "right now" — it already includes whatever
    move has happened today, so naively treating it as the baseline and applying
    day_change_pct on top would double-count that already-realized move (real
    incident 2026-08-11: every holding edited that morning showed a fresh,
    same-direction-as-the-day's-move error on its very next refresh). For that
    case the anchor is backed out by dividing by (1 + day_change_pct) instead, so
    this refresh reproduces the price you just entered instead of jumping.

    While the US market is closed, Finnhub is frozen on the last close, so
    day_change_pct is a fully-realized move already reflected in reality (and
    likely already in a TR-verified anchor) — applying it would double-count
    that move. Skip the roll entirely in that case; still record day_change_pct
    since the Today % badge shows it regardless, but leave the anchor alone too
    so the first refresh after the market opens bootstraps cleanly."""
    holding["day_change_pct"] = quote["day_change_pct"]

    if prices.us_market_open():
        day_change_pct = quote["day_change_pct"] or 0.0
        previous_close_usd = quote.get("previous_close_usd")

        if "anchor_previous_close_usd" not in holding:
            # No anchor at all: either a brand-new holding, or one whose anchor was
            # just cleared by a manual price edit this session. current_price means
            # "right now", not "prior close" — back out the equivalent close-basis
            # anchor so this call reproduces current_price instead of double-
            # counting today's already-realized move.
            holding["price_anchor"] = holding["current_price"] / (1 + day_change_pct)
            holding["anchor_fx_rate"] = current_fx_rate
            holding["anchor_previous_close_usd"] = previous_close_usd
        elif holding["anchor_previous_close_usd"] != previous_close_usd:
            # Genuine new trading day — current_price is our last TR-verified value
            # as of a prior close, a valid 0%-baseline. Roll it by today's full move.
            holding["price_anchor"] = holding["current_price"]
            holding["anchor_fx_rate"] = current_fx_rate
            holding["anchor_previous_close_usd"] = previous_close_usd

        fx_ratio = current_fx_rate / holding["anchor_fx_rate"]
        new_price = holding["price_anchor"] * (1 + day_change_pct) * fx_ratio
        update_price(holding, new_price)

    try:
        update_consensus(holding, consensus_store.refresh(holding["ticker"]))
    except PriceError:
        pass


@app.post("/api/holdings/{holding_id}/refresh")
def refresh_holding_price(holding_id: str, override_price_check: bool = False):
    holdings = load_holdings()
    holding = find_holding(holdings, holding_id)

    if apply_ls_tc_price(holding):
        try:
            update_consensus(holding, consensus_store.refresh(holding["ticker"]))
        except PriceError:
            pass
        save_holdings(holdings)
        return evaluate_trailing(holding, holding["current_price"])

    try:
        rate = prices.fetch_usd_to_eur_rate()
    except PriceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if holding.get("manual_price"):
        # The absolute Finnhub price is the wrong instrument/ratio for these, so it's
        # never usable as-is — but the ticker's own day_change_pct still is (see
        # apply_quote). If even that fails to fetch, just keep the price frozen.
        try:
            quote = prices.fetch_quote(holding["ticker"], rate)
        except PriceError:
            return {**evaluate_trailing(holding, holding["current_price"]), "skipped_manual": True}
        apply_quote(holding, quote, rate)
        save_holdings(holdings)
        return evaluate_trailing(holding, holding["current_price"])

    try:
        quote = prices.fetch_quote(holding["ticker"], rate)
    except PriceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not override_price_check and is_price_mismatch(holding, quote["price"]):
        # Don't clobber the user's price — hand the mismatch to the frontend so
        # it can offer "keep my price (manual)" vs "use the fetched price".
        return {
            "id": holding["id"],
            "ticker": holding["ticker"],
            "price_mismatch": {
                "fetched": quote["price"],
                "current": holding["current_price"],
                "factor": PRICE_MISMATCH_FACTOR,
            },
        }

    apply_quote(holding, quote, rate)
    save_holdings(holdings)
    return evaluate_trailing(holding, holding["current_price"])


@app.post("/api/holdings/refresh-all")
def refresh_all_prices():
    holdings = load_holdings()
    try:
        rate = prices.fetch_usd_to_eur_rate()
    except PriceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    results = []
    for holding in holdings:
        if apply_ls_tc_price(holding):
            try:
                update_consensus(holding, consensus_store.refresh(holding["ticker"]))
            except PriceError:
                pass
            results.append(evaluate_trailing(holding, holding["current_price"]))
            continue
        if holding.get("manual_price"):
            # See refresh_holding_price: the absolute fetched price is never usable
            # for these, but day_change_pct still is. Keep the price frozen if even
            # that fails to fetch.
            try:
                quote = prices.fetch_quote(holding["ticker"], rate)
            except PriceError:
                results.append({**evaluate_trailing(holding, holding["current_price"]), "skipped_manual": True})
                continue
            apply_quote(holding, quote, rate)
            results.append(evaluate_trailing(holding, holding["current_price"]))
            continue
        try:
            quote = prices.fetch_quote(holding["ticker"], rate)
        except PriceError as e:
            results.append({"id": holding["id"], "ticker": holding["ticker"], "error": str(e)})
            continue
        # Bulk can't prompt, so a mismatch just protects the stored price and is
        # flagged for the user to resolve on a single Refresh of that holding.
        if is_price_mismatch(holding, quote["price"]):
            results.append({
                "id": holding["id"],
                "ticker": holding["ticker"],
                "price_mismatch": {
                    "fetched": quote["price"],
                    "current": holding["current_price"],
                    "factor": PRICE_MISMATCH_FACTOR,
                },
            })
            continue
        apply_quote(holding, quote, rate)
        results.append(evaluate_trailing(holding, holding["current_price"]))

    save_holdings(holdings)
    record_portfolio_snapshot(holdings)  # one portfolio-value point per day
    record_holdings_snapshot(holdings)  # one per-holding value point per day
    return results


@app.post("/api/holdings/{holding_id}/confirm")
def confirm_trailing_stop(holding_id: str, req: ConfirmRequest):
    holdings = load_holdings()
    holding = find_holding(holdings, holding_id)
    holding["reference_high"] = req.new_reference_high
    holding["stop_price"] = req.new_stop_price
    save_holdings(holdings)
    return holding


@app.get("/api/zacks")
def get_zacks_ranks():
    data = zacks_import.load_ranks()
    for ticker, entry in data["ranks"].items():
        entry.update(consensus_store.overlay_consensus(ticker))
    return data


@app.post("/api/zacks/import")
def import_zacks(path: Optional[str] = None, default_rank: Optional[int] = None):
    if path:
        csv_path = Path(path)
    else:
        candidates = sorted(
            DOWNLOADS_DIR.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates = [p for p in candidates if "zacks" in p.name.lower() or "rank" in p.name.lower()]
        if not candidates:
            raise HTTPException(
                status_code=404,
                detail="No Zacks-looking CSV found in Downloads (expected a filename containing 'zacks' or 'rank')",
            )
        csv_path = candidates[0]

    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {csv_path}")

    try:
        return zacks_import.import_csv(csv_path, default_rank=default_rank)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/zacks/upload")
async def upload_zacks(file: UploadFile = File(...), default_rank: Optional[int] = None):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / file.filename
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            return zacks_import.import_csv(tmp_path, default_rank=default_rank)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/zacks/refresh-consensus")
def refresh_zacks_consensus():
    data = zacks_import.load_ranks()
    tickers = list(data["ranks"].keys())
    updated = 0
    errors = []

    for i, ticker in enumerate(tickers):
        try:
            entry = consensus_store.refresh(ticker)
            data["ranks"][ticker]["consensus"] = entry
            data["ranks"][ticker]["consensus_avg"] = entry["average"]
            updated += 1
        except PriceError as e:
            errors.append({"ticker": ticker, "error": str(e)})
        if i < len(tickers) - 1:
            time.sleep(1)

    zacks_import.save_ranks(data)
    return {"updated": updated, "total": len(tickers), "errors": errors}


@app.post("/api/zacks/{ticker}/analyze")
def analyze_ticker(ticker: str):
    try:
        return synthesis.synthesize(ticker.upper())
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/zacks/compare")
def compare_tickers(a: str, b: str):
    # Two independent single-ticker syntheses, neither aware of the other —
    # deliberate, see docs/plans/synthesized-stock-analysis.md.
    try:
        return {"a": synthesis.synthesize(a.upper()), "b": synthesis.synthesize(b.upper())}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/prices/{ticker}/history")
def price_history(ticker: str, days: int = 30):
    ticker = ticker.upper()
    try:
        rate = prices.fetch_usd_to_eur_rate()
        usd_prices = alpha_vantage.fetch_daily_prices(ticker, days=days)
    except (PriceError, AlphaVantageError) as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not usd_prices:
        raise HTTPException(status_code=404, detail=f"No price history for '{ticker}'")

    eur_prices = [{"date": p["date"], "close": p["close"] * rate} for p in usd_prices]
    change_pct = (eur_prices[-1]["close"] - eur_prices[0]["close"]) / eur_prices[0]["close"] * 100

    return {"ticker": ticker, "prices": eur_prices, "change_pct": change_pct}


@app.get("/api/opportunities-b")
def get_opportunities_b():
    return opportunities_b.load_opportunities_b()


@app.post("/api/opportunities-b/refresh")
def refresh_opportunities_b():
    # Long-running (~10 min): one recommendation call per S&P 500 name, then
    # earnings for the shortlist. Synchronous, like the Zacks consensus refresh.
    try:
        return opportunities_b.build()
    except PriceError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/portfolio-history")
def get_portfolio_history():
    return load_portfolio_history()


@app.get("/api/holdings-history")
def get_holdings_history():
    return load_holdings_history()


@app.post("/api/portfolio-history/seed")
def seed_portfolio_history():
    """Reconstruct an APPROXIMATE backward curve: value current holdings using each
    ticker's daily price history (Alpha Vantage), so there's a line to look at before
    the daily recorded points accumulate. Approximate because it applies *today's*
    share counts and FX rate to past prices (ignores past buys/sells). Fills only dates
    not already recorded, so real snapshots always win."""
    holdings = load_holdings()
    try:
        rate = prices.fetch_usd_to_eur_rate()
    except PriceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # non-manual holdings contribute a historical series; manual ones a flat value.
    series = {}  # ticker -> {date: close_eur}
    flat_value = 0.0
    non_manual = 0
    for h in holdings:
        if h.get("manual_price"):
            flat_value += h["shares"] * h["current_price"]
            continue
        non_manual += 1
        try:
            hist = alpha_vantage.fetch_daily_prices(h["ticker"], days=90)
        except AlphaVantageError:
            continue
        series[h["ticker"]] = {p["date"]: p["close"] * rate for p in hist}

    # Require *every* non-manual holding — a partial fetch would sum only some
    # positions and draw a misleadingly-low curve. Better to seed nothing.
    if len(series) < non_manual:
        raise HTTPException(
            status_code=502,
            detail=f"Only got history for {len(series)} of {non_manual} holdings "
                   f"(Alpha Vantage daily cap?) — try again tomorrow so the curve isn't understated.",
        )

    # only dates where every fetched ticker has a price (avoids gaps/jumps)
    common_dates = set.intersection(*[set(d) for d in series.values()])
    shares = {h["ticker"]: h["shares"] for h in holdings}
    reconstructed = []
    for d in sorted(common_dates):
        value = flat_value + sum(series[t][d] * shares[t] for t in series)
        reconstructed.append({"date": d, "value": value, "approx": True})

    existing = {p["date"] for p in load_portfolio_history()}
    points = load_portfolio_history() + [p for p in reconstructed if p["date"] not in existing]
    save_portfolio_history(points)
    return {"seeded": len([p for p in reconstructed if p["date"] not in existing]), "total_points": len(points)}


@app.get("/api/sectors")
def get_sectors():
    return sectors.load_sector_strength()


@app.post("/api/sectors/refresh")
def refresh_sectors():
    # ~2.5 min: 11 sector-ETF history pulls, throttled for Alpha Vantage's 5/min.
    return sectors.build_sector_strength()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
