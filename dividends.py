"""Dividends that use up a bank's allowance, so the tax on a sale there is known before selling.

Every German bank applies the allowance filed with it (Freistellungsauftrag) to all capital
income in the order it arrives, and dividends arrive four times a year whether or not anything
is sold. The tool asks the user to enter the allowance left as the bank shows it, with a
date, and that figure goes stale with the next dividend. This module works out what has been
paid since that date, so the tax a sale would add is computed against the allowance actually
left. It also gives what is still to come before 31 December, which matters for a sale planned
later in the year.

Only banks with an allowance are looked at. Trade Republic has none, so a dividend there
cannot change the tax on a sale, and its holdings cost no calls.

Amounts are gross (before the 15% US withholding), because the gross is what uses up the
allowance. They are converted at today's rate rather than the payment-day rate, which is
close enough for a figure the bank will settle to the cent anyway.

Source: Alpha Vantage `DIVIDENDS` (free; real payment dates, including dividends declared but
not yet paid). Past the last declared payment, dates are projected from the stock's own
rhythm and marked as estimates.
"""

from datetime import date, timedelta
from typing import Optional

import alpha_vantage
from alpha_vantage import AlphaVantageError


def _shares_on(holding: dict, ex_date: str) -> float:
    """Shares that earned a dividend: bought before its ex-date. A lot bought on the ex-date
    itself does not qualify."""
    return sum(lot["shares"] for lot in holding.get("lots") or [] if lot["purchase_date"] < ex_date)


def _projected(rows: list, today: date, year_end: date) -> list:
    """Payments not yet declared: last year's payment in the same season, one year on, at
    the newest amount. Companies keep their calendar far more reliably than an even gap —
    Meta's last gap was 95 days, which would have pushed its December payment into January.
    A payment more than twice the newest amount is a one-off special and is not repeated, and
    one within 45 days of a declared payment is that payment, already counted."""
    if not rows:
        return []
    latest = rows[0]["amount"]
    declared = [date.fromisoformat(r["payment_date"]) for r in rows if r["payment_date"] > today.isoformat()]
    out = []
    for r in rows:
        if r["amount"] > 2 * latest:
            continue
        pay = date.fromisoformat(r["payment_date"]) + timedelta(days=364)
        if not (today < pay <= year_end) or any(abs((pay - d).days) <= 45 for d in declared):
            continue
        ex = date.fromisoformat(r["ex_dividend_date"]) + timedelta(days=364)
        out.append({"payment_date": pay.isoformat(), "ex_dividend_date": ex.isoformat(),
                    "amount": latest, "estimated": True})
    return out


def for_bank(holdings: list, broker: str, since: Optional[str], usd_to_eur: float,
             today: Optional[date] = None, cached_only: bool = False) -> dict:
    """Dividends at one bank: paid after `since` (the date the allowance was read) and still
    to come this year. Without `since` nothing counts as paid: the allowance figure has no date,
    so there is no telling which dividends it already includes."""
    today = today or date.today()
    year_start = date(today.year, 1, 1).isoformat()
    last_year = bool(since) and since < year_start
    year_end = date(today.year, 12, 31)
    paid, expected, missing = [], [], []

    for h in holdings:
        if (h.get("broker") or "") != broker:
            continue
        try:
            rows = alpha_vantage.fetch_dividends(h["ticker"], cached_only=cached_only)
        except AlphaVantageError:
            missing.append(h["ticker"])
            continue
        # Declared but unpaid, then projected past the newest row (which may be that declared one).
        known = [dict(r, estimated=False) for r in rows
                 if today.isoformat() < r["payment_date"] <= year_end.isoformat()]
        known += _projected(rows, today, year_end)
        if since and not last_year:
            for r in rows:
                if since < r["payment_date"] <= today.isoformat():
                    shares = _shares_on(h, r["ex_dividend_date"])
                    if shares:
                        paid.append(_item(h["ticker"], r, shares, usd_to_eur, estimated=False))
        for r in known:
            shares = _shares_on(h, r["ex_dividend_date"]) if not r["estimated"] else h.get("shares") or 0
            if shares:
                expected.append(_item(h["ticker"], r, shares, usd_to_eur, estimated=r["estimated"]))

    paid.sort(key=lambda d: d["payment_date"])
    expected.sort(key=lambda d: d["payment_date"])
    return {
        "since": since,
        # The allowance resets on 1 January, so a figure read last year says nothing about now.
        "allowance_last_year": last_year,
        "paid": paid,
        "paid_eur": sum(d["eur"] for d in paid),
        "expected": expected,
        "expected_eur": sum(d["eur"] for d in expected),
        "missing": missing,
    }


def _item(ticker: str, row: dict, shares: float, usd_to_eur: float, estimated: bool) -> dict:
    return {
        "ticker": ticker,
        "payment_date": row["payment_date"],
        "shares": shares,
        "per_share_usd": row["amount"],
        "eur": shares * row["amount"] * usd_to_eur,
        "estimated": estimated,
    }
