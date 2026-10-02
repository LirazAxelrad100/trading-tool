"""What is actually owed on share sales this year — losses included.

Every tax figure in this tool used to be per-sale: `max(0, gain) * 26,375%`, computed
independently for each row, with every loss showing 0,00. That is not how German
capital-gains tax works, and the user is the one who said so — *"in germany we can reduce
tax if we have lose"*.

Losses from share sales go into the **Verlustverrechnungstopf** and offset gains from other
share sales in the same year; Trade Republic nets them at source and refunds tax it already
withheld. Only the net is taxable. The gap is not academic: on 2026-09-17 the History tab's
per-row column summed to several hundred euros of supposedly-owed tax while the real position
for the year was a **net loss** — nothing owed, and the loss carried forward. Acting on
the per-row number would have meant believing a tax bill that does not exist, and treating
every realised loss as if it were worth nothing.

Scope and limits, all deliberate:

- **Share losses only offset share gains.** That is the German rule for `Aktien` (a separate
  pot from other investment income), and every instrument in this tool is a share, so the
  simple version is the correct one here. It would stop being correct the day a bond, fund or
  derivative is recorded.
- **The Sparerpauschbetrag** (€1.000 a year) is applied to a positive net. It is shared across
  every account the user holds, so the tool can only assume the whole allowance is available
  here — stated in the UI rather than hidden.
- **Church tax is not included.** The 26,375% is 25% plus the 5,5% Solidaritätszuschlag, the
  rate already used everywhere else in the tool.
- **Carry-forward is computed from this tool's own records.** The sales log is complete for
  2026 and there is nothing before it, so the 2026 opening balance is genuinely zero. A year
  this tool did not record would need its carry-in supplied from outside.

It is an estimate, not a tax return. Trade Republic reports to the Finanzamt at source and its
own numbers are the ones that count.
"""

import collections
from typing import Optional

CAPITAL_GAINS_TAX_RATE = 0.26375  # 25% Kapitalertragsteuer + 5,5% Solidaritätszuschlag
ANNUAL_ALLOWANCE_EUR = 1000.0  # Sparerpauschbetrag, per person per year, across all accounts


def _year(sale: dict) -> Optional[str]:
    stamp = sale.get("sell_datetime") or sale.get("sell_date") or ""
    return stamp[:4] or None


def year_summary(sales: list, year: str, carried_in: float = 0.0,
                 allowance: float = ANNUAL_ALLOWANCE_EUR) -> dict:
    """Realised gains, realised losses and what is actually owed for one calendar year.
    `allowance` is what is available against these sales — the whole Sparerpauschbetrag by
    default, or only what is left at one bank when computing that bank on its own."""
    rows = [s for s in sales or [] if _year(s) == str(year)]
    gains = sum(s["realized_gain"] for s in rows if (s.get("realized_gain") or 0) > 0)
    losses = sum(s["realized_gain"] for s in rows if (s.get("realized_gain") or 0) < 0)
    net = gains + losses - carried_in

    taxable = max(0.0, net - allowance)
    allowance_used = min(max(net, 0.0), allowance)
    return {
        "year": str(year),
        "sales": len(rows),
        "gains": gains,
        "losses": losses,
        "net": net,
        "taxable": taxable,
        "estimated_tax": taxable * CAPITAL_GAINS_TAX_RATE,
        "allowance": allowance,
        "allowance_used": allowance_used,
        # A negative net is not "no tax and nothing else" — it is a balance that reduces next
        # year's bill, which is the part the per-row column threw away.
        "carry_forward": abs(net) if net < 0 else 0.0,
        "carried_in": carried_in,
    }


def years(sales: list) -> list:
    """Every calendar year with a recorded sale, newest first."""
    return sorted({y for y in (_year(s) for s in sales or []) if y}, reverse=True)


DEFAULT_BROKER = "Trade Republic"


def sale_broker(sale: dict) -> str:
    """Every sale recorded before brokers existed was on Trade Republic."""
    return sale.get("broker") or DEFAULT_BROKER


# Each bank keeps its own loss pot and applies only the allowance filed with it
# (Freistellungsauftrag), so tax withheld at source has to be computed bank by bank. A loss at
# one bank does not reduce tax withheld at the other — that only happens in the yearly tax
# return, and only if the bank holding the losses issues a Verlustbescheinigung, which has to
# be requested by 15 December (the pot is then closed there rather than carried forward).
#
# Settings per broker, from data/tax_settings.json:
#   allowance_left   — what is left of the allowance filed at that bank this year (dividends
#                      use it up first). Missing → 0, except when no bank has settings at all,
#                      where the old single-bank assumption (the whole allowance) still holds.
#   share_loss_pot   — the bank's own reported share-loss pot, as a positive number, with
#                      `as_of`. When set, it replaces this tool's records up to that date and
#                      only sales recorded after it are added. When missing, the pot is
#                      computed from this tool's own sales log (right for Trade Republic,
#                      whose 2026 sales are all recorded here).
#   as_of            — also dates the allowance: dividends paid after it are taken off.
#   dividends        — not stored; added at read time by main.tax_settings_with_dividends().
def bank_summary(sales: list, year: str, broker: str, settings: Optional[dict] = None,
                 any_settings: bool = True) -> dict:
    settings = settings or {}
    rows = [s for s in sales or [] if sale_broker(s) == broker]
    pot = settings.get("share_loss_pot")
    as_of = settings.get("as_of")
    carried_in = 0.0
    if pot is not None:
        carried_in = float(pot)
        if as_of:
            rows = [s for s in rows if (s.get("sell_datetime") or s.get("sell_date") or "")[:10] > as_of]
    if "allowance_left" in settings:
        allowance = float(settings["allowance_left"] or 0)
    else:
        allowance = 0.0 if any_settings else ANNUAL_ALLOWANCE_EUR
    entered = allowance
    # Dividends paid since the allowance was read have used part of it (see dividends.py).
    divs = settings.get("dividends")
    if divs:
        allowance = max(0.0, allowance - divs["paid_eur"])
    summary = year_summary(rows, year, carried_in=carried_in, allowance=allowance)
    summary.update({"broker": broker, "pot_as_of": as_of if pot is not None else None,
                    "pot_from": "bank" if pot is not None else "records",
                    "allowance_entered": entered, "dividends": divs})
    return summary


def by_bank(sales: list, year: str, settings: dict, brokers: list) -> dict:
    """Each bank on its own (what is withheld at source), then the year as the tax return sees
    it once losses are moved across with a Verlustbescheinigung."""
    names = sorted(set(brokers) | {sale_broker(s) for s in sales or []} | set(settings or {}))
    any_settings = bool(settings)
    banks = [bank_summary(sales, year, b, (settings or {}).get(b), any_settings) for b in names]
    net = sum(b["net"] for b in banks)
    taxable = max(0.0, net - ANNUAL_ALLOWANCE_EUR)
    return {
        "year": str(year),
        "banks": banks,
        "at_source_tax": sum(b["estimated_tax"] for b in banks),
        "combined": {
            "net": net,
            "taxable": taxable,
            "estimated_tax": taxable * CAPITAL_GAINS_TAX_RATE,
            "carry_forward": abs(net) if net < 0 else 0.0,
        },
    }


def tax_on_next_gain(sales: list, year: str, gain: float, broker: Optional[str] = None,
                     settings: Optional[dict] = None) -> dict:
    """What one more sale would actually add to the year's tax — the question the sell
    preview is really asking. It used to answer `max(0, gain) * rate`, which ignores every
    loss already banked: when realised losses in the pot exceed the gain being considered,
    the sale adds nothing, and quoting the standalone rate is an argument not to sell that is
    simply untrue.

    With a broker, it is that bank's pot and that bank's allowance — what would actually be
    withheld when selling there."""
    if broker is not None:
        bank_settings = (settings or {}).get(broker)
        any_settings = bool(settings)
        before = bank_summary(sales, year, broker, bank_settings, any_settings)
        extra = {"sell_datetime": f"{year}-12-31", "realized_gain": gain, "broker": broker}
        after = bank_summary(sales + [extra], year, broker, bank_settings, any_settings)
        return {
            "tax_before": before["estimated_tax"],
            "tax_after": after["estimated_tax"],
            "extra_tax": after["estimated_tax"] - before["estimated_tax"],
            "net_before": before["net"],
            "offset_available": before["carry_forward"],
            "allowance": before["allowance"] - before["allowance_used"],
        }
    before = year_summary(sales, year)
    after = year_summary(sales + [{"sell_datetime": f"{year}-01-01", "realized_gain": gain}], year)
    return {
        "tax_before": before["estimated_tax"],
        "tax_after": after["estimated_tax"],
        "extra_tax": after["estimated_tax"] - before["estimated_tax"],
        "net_before": before["net"],
        "offset_available": before["carry_forward"],
    }
