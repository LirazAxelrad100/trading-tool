"""Money you moved in or out, so the portfolio line stops calling it performance.

`portfolio_history.json` records what the holdings are worth each day. A deposit raises
that number without a single price moving, and a withdrawal lowers it — so the chart shows
a step you caused and reads it as a gain. Real case (2026-09-16): the line jumped 6,08% on
a day the portfolio actually rose 1,41%, because new cash arrived that morning and bought DELL.
This is the same fault `concentration.py` guards against with `_changed_dates()`, one level
up: a value that changes for a reason other than price.

Deliberately not a deposits ledger the user has to maintain. Every figure here is recovered
from records the tool already keeps:

- money spent buying = each lot's `shares * cost_basis` on its `purchase_date`, across
  current holdings **and** `lots_sold` inside `sales_history.json`. That second half matters:
  a position bought and later sold entirely leaves no lots behind, so without it the purchase
  is invisible and the day reads as a loss. HPE is exactly that case — bought 13.08, gone by
  18.08.
- money received selling = each sale's `total_sum` on its sell date.

**The net is what matters, not the gross.** Four of the six flow days in the first real run
were same-day rotations — one position sold and another bought for almost the same sum — where the
chart was never wrong, because no money entered or left. Marking those would have pointed at
three days that needed no explaining and buried the three that did.

A sale with no `lots_sold` cannot have its purchase recovered (the five oldest predate that
field). Those are reported in `unrecoverable` rather than silently treated as zero, since a
missing purchase looks exactly like a withdrawal.
"""

import collections
from typing import Optional

# Below this, a "flow" is rounding noise or a fractional-share remainder, not something the
# user did. Rotations land here too: sell 4.000, buy 4.050, net 50 — the chart was right
# that day, so marking it would add a label with nothing to say.
MATERIAL_EUR = 100.0


def by_date(holdings: list, sales: list) -> dict:
    """{date: {bought, sold, net}} in EUR, for every date money moved."""
    bought = collections.defaultdict(float)
    sold = collections.defaultdict(float)

    for holding in holdings or []:
        for lot in holding.get("lots") or []:
            date = (lot.get("purchase_date") or "")[:10]
            if date:
                bought[date] += (lot.get("shares") or 0) * (lot.get("cost_basis") or 0)

    for sale in sales or []:
        date = (sale.get("sell_datetime") or sale.get("sell_date") or "")[:10]
        if date:
            sold[date] += sale.get("total_sum") or 0
        # The purchase side of a position that has since been closed lives only here.
        for lot in sale.get("lots_sold") or []:
            date = (lot.get("purchase_date") or "")[:10]
            if date:
                bought[date] += (lot.get("shares") or 0) * (lot.get("cost_basis") or 0)

    out = {}
    for date in set(bought) | set(sold):
        out[date] = {
            "bought": bought.get(date, 0.0),
            "sold": sold.get(date, 0.0),
            "net": bought.get(date, 0.0) - sold.get(date, 0.0),
        }
    return out


def unrecoverable(sales: list) -> list:
    """Sales whose purchase cost cannot be recovered, so their buy day is missing a flow."""
    return [
        {"ticker": s.get("ticker"), "date": (s.get("sell_datetime") or s.get("sell_date") or "")[:10]}
        for s in sales or []
        if not s.get("lots_sold")
    ]


def overlay(points: list, holdings: list, sales: list) -> list:
    """Attach `cash_flow` to each history point that has a material one, and `real_change_pct`
    — that day's move with the money movement taken out, which is what actually happened."""
    flows = by_date(holdings, sales)
    previous = None
    for point in points or []:
        flow = flows.get(point.get("date"))
        if flow and abs(flow["net"]) >= MATERIAL_EUR:
            point["cash_flow"] = flow["net"]
            point["cash_bought"] = flow["bought"]
            point["cash_sold"] = flow["sold"]
            if previous:
                point["real_change_pct"] = (
                    (point["value"] - flow["net"]) / previous - 1
                ) * 100
        previous = point.get("value") or previous
    return points


def total_return_pct(points: list, holdings: list, sales: list) -> Optional[float]:
    """The return the holdings actually produced over the recorded period: each day's move
    with that day's money movement removed, chained together. The chart header used to show
    (last - first) / first, which counts every deposit as a gain. On a real portfolio a single
    day's deposit can be several percent of the total, so that is not a rounding error."""
    if not points or len(points) < 2:
        return None
    flows = by_date(holdings, sales)
    growth = 1.0
    previous = points[0].get("value")
    for point in points[1:]:
        value = point.get("value")
        if not previous or not value:
            previous = value or previous
            continue
        net = (flows.get(point.get("date")) or {}).get("net", 0.0)
        if abs(net) < MATERIAL_EUR:
            net = 0.0
        growth *= (value - net) / previous
        previous = value
    return (growth - 1) * 100
