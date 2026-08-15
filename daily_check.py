import time
from datetime import date

import main
import notifier
import prices

RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 20


def fetch_rate_with_retry() -> float:
    """A launchd-fired run right after the Mac wakes from sleep can hit a DNS
    failure because Wi-Fi hasn't reconnected yet — this happened for real and
    silently dropped a day's check. A few retries a beat apart covers that
    transient case without adding real delay on the common path."""
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return prices.fetch_usd_to_eur_rate()
        except prices.PriceError as e:
            last_error = e
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)
    raise last_error


def send_email_with_retry(subject: str, body: str) -> None:
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            notifier.send_email(subject, body)
            return
        except Exception as e:
            last_error = e
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)
    print(f"Failed to send email after {RETRY_ATTEMPTS} attempts: {last_error}")


def eu_num(n: float) -> str:
    """EU number: period thousands, comma decimal (e.g. 1414.57 -> '1.234,57').
    Matches the web UI's Intl.NumberFormat('de-DE') so the emailed alert reads
    the same as the on-screen one. The X placeholder swap avoids clobbering the
    two separators mid-replace."""
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def eu_pct(ratio: float) -> str:
    """EU percentage from a ratio, 1 decimal (e.g. 0.10 -> '10,0%')."""
    return f"{ratio * 100:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + "%"


def format_breakout(result: dict) -> str:
    return (
        f"{result['ticker']}: up {eu_pct(result['pct_move'])} "
        f"({eu_num(result['old_high'])} -> {eu_num(result['new_price'])}). "
        f"Current stop {eu_num(result['current_stop'])}, suggested new stop "
        f"{eu_num(result['suggested_new_stop'])}."
    )


def format_stop_hit(result: dict) -> str:
    gain_word = "gain" if result["total_gain"] >= 0 else "loss"
    line = (
        f"{result['ticker']}: at or below stop loss "
        f"(price {eu_num(result['new_price'])}, stop {eu_num(result['current_stop'])}). "
        f"Exit plan: {result['exit_plan_label']}. "
        f"Estimated {gain_word}: {eu_num(result['total_gain'])}, "
        f"estimated tax: {eu_num(result['estimated_tax'])}."
    )
    c = result.get("analyst_consensus")
    if c:
        line += (
            f" Analyst consensus ({c['period']}): {c['strong_buy']} strong buy, "
            f"{c['buy']} buy, {c['hold']} hold, {c['sell']} sell, {c['strong_sell']} strong sell."
        )
    return line


def format_error(result: dict) -> str:
    return f"{result['ticker']}: ERROR — {result['error']}"


def run() -> None:
    holdings = main.load_holdings()
    try:
        rate = fetch_rate_with_retry()
    except prices.PriceError as e:
        send_email_with_retry(
            "Trading tool: daily check failed",
            f"Could not fetch USD/EUR rate: {e}",
        )
        print(f"Failed: {e}")
        return

    breakouts = []
    stop_hits = []
    errors = []

    for holding in holdings:
        try:
            quote = prices.fetch_quote(holding["ticker"], rate)
        except prices.PriceError as e:
            # Manual-price holdings (e.g. an EU-listed ordinary share vs. its US
            # ADR) commonly have no live feed at all — that's not an error, just
            # keep the price frozen. A real ticker failing to fetch still counts.
            if not holding.get("manual_price"):
                errors.append({"ticker": holding["ticker"], "error": str(e)})
            continue
        main.apply_quote(holding, quote, rate)
        result = main.evaluate_trailing(holding, holding["current_price"])
        if result["stop_hit"]:
            stop_hits.append(result)
        elif result["triggered"]:
            breakouts.append(result)

    main.save_holdings(holdings)
    main.record_portfolio_snapshot(holdings)  # daily portfolio-value point for the chart
    main.record_holdings_snapshot(holdings)  # daily per-holding value point for the weekly table

    if not breakouts and not stop_hits and not errors:
        print(f"{date.today()}: nothing to report.")
        return

    lines = [f"Daily trailing-stop check — {date.today()}", ""]
    if stop_hits:
        lines.append(f"{len(stop_hits)} holding(s) at or below stop loss:")
        lines += [f"  - {format_stop_hit(r)}" for r in stop_hits]
        lines.append("")
    if breakouts:
        lines.append(f"{len(breakouts)} holding(s) hit a new trailing high:")
        lines += [f"  - {format_breakout(r)}" for r in breakouts]
        lines.append("")
    if errors:
        lines.append(f"{len(errors)} ticker(s) failed to fetch:")
        lines += [f"  - {format_error(r)}" for r in errors]

    body = "\n".join(lines)
    subject = (
        f"Trading tool: {len(stop_hits)} stop hit(s), "
        f"{len(breakouts)} update(s), {len(errors)} error(s)"
    )
    send_email_with_retry(subject, body)
    print(body)


if __name__ == "__main__":
    run()
