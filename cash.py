"""Money sitting uninvested at the broker, so proceeds don't drop out of sight after a sale.

Once a position is sold it leaves the holdings table, and nothing on the screen says the money
is still there waiting. Real case (2026-11-04): cash left from a sale had been forgotten for two
weeks, and every plan made in that time was short by that amount.

The tool can't see the account, so the starting point is a figure she types from the broker's
screen. From there it follows her own records: sales recorded after that moment add their
total, purchases subtract theirs. Worked out on every read rather than kept as a running
balance, so correcting or removing a lot or a sale corrects this too. Typing a new figure
starts again from there, and that is also the way to take in what the tool can't know: tax,
deposits, interest, fees.

Only the main broker counts. Old holdings at the other bank are not traded, and money there is
not waiting to be invested.
"""

from typing import Optional

BROKER = "Trade Republic"


def _purchases(holdings: list, sales: list) -> list:
    """Every lot ever bought at this broker: still held, or gone inside a sale's `lots_sold`.
    A position bought and fully sold since the figure was typed leaves no lot in holdings, so
    without the second half its sale would be added and its purchase never taken off."""
    found = []
    for holding in holdings or []:
        if (holding.get("broker") or BROKER) == BROKER:
            found += [(holding.get("ticker"), lot) for lot in holding.get("lots") or []]
    for sale in sales or []:
        if (sale.get("broker") or BROKER) == BROKER:
            found += [(sale.get("ticker"), lot) for lot in sale.get("lots_sold") or []]
    return found


def current(entry: Optional[dict], holdings: list, sales: list) -> dict:
    """`entry` is what she typed: {amount, as_of}, with as_of a local timestamp."""
    if not entry:
        return {"entered": False}
    as_of = entry["as_of"]
    changes = []

    for sale in sales or []:
        when = sale.get("sell_datetime") or sale.get("sell_date") or ""
        if (sale.get("broker") or BROKER) == BROKER and when > as_of:
            changes.append({
                "kind": "sold",
                "ticker": sale.get("ticker"),
                "date": when[:10],
                "amount": sale.get("total_sum") or 0.0,
            })

    # A sale knows its time of day; a purchase has only a date. So a purchase counts only if it
    # was also recorded after the figure was typed: one bought this morning and typed in before
    # she read the figure is already inside it. Lots older than this feature have no stamp, and
    # a purchase dated before the figure is inside it however late it was recorded.
    bought_lots = {}
    for ticker, lot in _purchases(holdings, sales):
        date = (lot.get("purchase_date") or "")[:10]
        if lot.get("recorded_at", "") > as_of and date >= as_of[:10]:
            key = (ticker, date, lot.get("recorded_at"), lot.get("cost_basis"))
            bought_lots[key] = bought_lots.get(key, 0.0) + (lot.get("shares") or 0) * (lot.get("cost_basis") or 0)
    for (ticker, date, _, _), amount in bought_lots.items():
        changes.append({"kind": "bought", "ticker": ticker, "date": date, "amount": amount})

    changes.sort(key=lambda c: c["date"])
    amount = entry["amount"] + sum(c["amount"] if c["kind"] == "sold" else -c["amount"] for c in changes)
    return {"entered": True, "amount": amount, "typed": entry["amount"], "as_of": as_of, "changes": changes}
