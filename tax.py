"""What is actually owed on share sales this year — losses included.

Every tax figure in this tool used to be per-sale: `max(0, gain) * 26,375%`, computed
independently for each row, with every loss showing 0,00. That is not how German
capital-gains tax works, and the user is the one who said so — *"in germany we can reduce
tax if we have lose"*.

Losses from share sales go into the **Verlustverrechnungstopf** and offset gains from other
share sales in the same year; Trade Republic nets them at source and refunds tax it already
withheld. Only the net is taxable. The gap is not academic: on 2026-09-17 the History tab's
per-row column summed to **€[redacted] of tax** while the real position for the year was a **net
loss of €[redacted]** — nothing owed, and €[redacted] carried forward against future gains. Acting on
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


def year_summary(sales: list, year: str, carried_in: float = 0.0) -> dict:
    """Realised gains, realised losses and what is actually owed for one calendar year."""
    rows = [s for s in sales or [] if _year(s) == str(year)]
    gains = sum(s["realized_gain"] for s in rows if (s.get("realized_gain") or 0) > 0)
    losses = sum(s["realized_gain"] for s in rows if (s.get("realized_gain") or 0) < 0)
    net = gains + losses - carried_in

    taxable = max(0.0, net - ANNUAL_ALLOWANCE_EUR)
    allowance_used = min(max(net, 0.0), ANNUAL_ALLOWANCE_EUR)
    return {
        "year": str(year),
        "sales": len(rows),
        "gains": gains,
        "losses": losses,
        "net": net,
        "taxable": taxable,
        "estimated_tax": taxable * CAPITAL_GAINS_TAX_RATE,
        "allowance": ANNUAL_ALLOWANCE_EUR,
        "allowance_used": allowance_used,
        # A negative net is not "no tax and nothing else" — it is a balance that reduces next
        # year's bill, which is the part the per-row column threw away.
        "carry_forward": abs(net) if net < 0 else 0.0,
        "carried_in": carried_in,
    }


def years(sales: list) -> list:
    """Every calendar year with a recorded sale, newest first."""
    return sorted({y for y in (_year(s) for s in sales or []) if y}, reverse=True)


def tax_on_next_gain(sales: list, year: str, gain: float) -> dict:
    """What one more sale would actually add to the year's tax — the question the sell
    preview is really asking. It used to answer `max(0, gain) * rate`, which ignores every
    loss already banked: with €[redacted] of realised losses sitting in the pot, a €[redacted] gain
    adds nothing, and quoting €[redacted] of tax against it is an argument not to sell that is
    simply untrue."""
    before = year_summary(sales, year)
    after = year_summary(sales + [{"sell_datetime": f"{year}-01-01", "realized_gain": gain}], year)
    return {
        "tax_before": before["estimated_tax"],
        "tax_after": after["estimated_tax"],
        "extra_tax": after["estimated_tax"] - before["estimated_tax"],
        "net_before": before["net"],
        "offset_available": before["carry_forward"],
    }
