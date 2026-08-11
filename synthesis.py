import json
import os
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv

import alpha_vantage
import consensus_store
import opportunities_b
import prices
import sectors
import zacks_import

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are a financial data analyst helping an individual investor read their own research on a single stock ticker. You will be given structured data: Zacks Rank screening metrics, analyst consensus ratings, recent earnings history, the next earnings date, recent insider trading activity, recent news headlines, and news sentiment scores.

Write a clear, readable synthesis in prose (3-5 short paragraphs). Specifically:
- Begin every paragraph with a short bold lead-in — 3 to 7 words that summarise that paragraph's takeaway — wrapped in double asterisks, followed by the full explanation. For example: "**Estimates rising, price lagging.** Analysts have nudged their earnings forecasts up over the past month, but the share price has drifted lower over the same stretch…". The lead-in must describe what the paragraph says, never give a recommendation.
- Connect related data points to each other — e.g. does price momentum agree with earnings estimate revisions? Does analyst consensus align with recent insider activity? Does the Zacks Rank agree with the broader analyst consensus, or diverge?
- Explicitly call out where signals AGREE (reinforcing a read) and where they CONFLICT (creating ambiguity) — do not paper over contradictions to produce a tidier story.
- Note relevant risk context, such as an upcoming earnings date that could introduce volatility, or a pattern of earnings beats/misses.
- Use the news headlines and sentiment data to describe the current narrative around the stock, not just restate the numbers.
- If data for a category is missing or unavailable, simply omit it — do not speculate to fill the gap.

Write for a smart reader who is NOT a finance professional — not a Wall Street analyst, not an accountant. Avoid dense analyst jargon and vague shorthand phrases. Every time you use a technical term (earnings surprise, estimate revision, trailing vs. projected growth, VGM/Value/Growth/Momentum score, consensus rating, EPS, basis point, "price action," etc.), briefly explain what it actually means in plain words, in the same sentence or the next one — don't assume it's already understood, and don't just swap one piece of jargon for another.

Be EXPLICIT and CONCRETE, never vague or metaphorical. Two rules:
- Prefer plain explicit phrasing over vague verbs: write "most of the recent news coverage" rather than "news lean"; "the share price" rather than "price action".
- Whenever you say a signal is mixed, has "cross-currents", or is "not all good", you MUST immediately name the SPECIFIC concern instead of leaving it abstract — say *what* the negative stories or conflicts actually are.

Three examples of the rewrite expected:
- Instead of "a strong trailing earnings growth figure," write "profits have grown a lot over the past year (up X%), which is unusually fast — this describes what already happened, not a forecast."
- Instead of "price action is choppy and doesn't confirm the bullish rank," write something like "the stock's price has been bouncing up and down without a clear direction lately, which doesn't really back up the bullish signal from the rank — if the rank were right, you'd more likely expect the price to be climbing steadily instead."
- Instead of "news sentiment is net positive but carries real cross-currents," write "most of the recent news coverage is more positive than negative. The main concerns showing up are [name them specifically — e.g. a downgrade from one bank, a lawsuit over X, or slowing sales in Y]."
Be precise about whether a growth/estimate number is historical (already happened) or projected (a forecast) — always make that fact obvious, since conflating the two is a common and misleading mistake.

Strict rules, do not violate these under any framing:
- Never tell the user whether to buy, sell, or hold. Do not use directive language like "recommend," "should buy," "should sell," "a good entry point," etc.
- Never rank or compare this ticker against any other ticker.
- Never declare an overall verdict like "this is a strong opportunity" or "this is risky" — describe what the specific data shows and let the user draw their own conclusion.
- You are producing analysis, not advice. The decision is always the user's."""


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (prices.PriceError, alpha_vantage.AlphaVantageError) as e:
        return {"error": str(e)}


CONSENSUS_WEIGHTS = consensus_store.CONSENSUS_WEIGHTS


def _consensus_summary(c) -> Optional[dict]:
    if not isinstance(c, dict) or c.get("error"):
        return None
    counts = {k: c.get(k, 0) for k in CONSENSUS_WEIGHTS}
    n = sum(counts.values())
    if n == 0:
        return None
    avg = sum(counts[k] * w for k, w in CONSENSUS_WEIGHTS.items()) / n
    return {**counts, "n": n, "average": avg}


def derive_signals(data: dict) -> dict:
    """Pull the key facts into a flat metrics dict and flag where signals CONTRADICT
    each other. Deterministic rules, not the LLM — reliable, free, and (crucially) purely
    descriptive: they surface tension for the user to weigh, never a buy/sell/'better' verdict.
    See CLAUDE.md hard rules."""
    z = data.get("zacks") or {}
    rank = z.get("rank")
    p1, p4 = z.get("price_move_1w"), z.get("price_move_4w")
    eps4 = z.get("eps_est_change_4w")
    vgm, value, growth, mom = (z.get("vgm_score"), z.get("value_score"),
                               z.get("growth_score"), z.get("momentum_score"))
    egrowth = z.get("earnings_growth_1y")

    cons = _consensus_summary(data.get("analyst_consensus"))

    surprises = []
    eh = data.get("earnings_history")
    if isinstance(eh, list):
        for r in eh:
            if isinstance(r, dict) and r.get("surprise_percent") is not None:
                surprises.append({"period": r.get("period"), "surprise_percent": r.get("surprise_percent")})

    ne = data.get("next_earnings")
    next_earnings = ne.get("date") if isinstance(ne, dict) and not ne.get("error") else None

    metrics = {
        "zacks_rank": rank,
        "price_move_1w": p1,
        "price_move_4w": p4,
        "eps_est_change_4w": eps4,
        "earnings_growth_1y": egrowth,
        "value_score": value,
        "growth_score": growth,
        "momentum_score": mom,
        "vgm_score": vgm,
        "consensus": cons,
        "recent_surprises": surprises,
        "next_earnings": next_earnings,
    }

    contradictions = []
    bullish_rank = rank in (1, 2)
    weak_vgm = vgm in ("D", "F")
    is_num = lambda x: isinstance(x, (int, float))

    if bullish_rank and weak_vgm:
        contradictions.append(
            f"Zacks Rank {rank} says earnings estimates are being raised, but the VGM grade is {vgm} "
            f"(Value {value}, Growth {growth}) — strong estimate momentum sitting on a weak value/growth profile."
        )
    if bullish_rank and is_num(p4) and p4 <= -10:
        contradictions.append(
            f"The rank and analyst view are bullish, but the price is down {p4:.1f}% over the last 4 weeks — "
            f"the market isn't confirming that optimism yet."
        )
    elif is_num(eps4) and eps4 > 0 and is_num(p4) and p4 < 0:
        contradictions.append(
            f"Analysts raised earnings estimates (+{eps4:.1f}% in 4 weeks) while the price fell {p4:.1f}% — "
            f"forecasts and price action are pointing opposite ways."
        )
    if bullish_rank and surprises:
        misses = [s for s in surprises if is_num(s["surprise_percent"]) and s["surprise_percent"] < 0]
        if misses:
            m = misses[0]
            contradictions.append(
                f"The rank is bullish, but the company missed earnings estimates in {m['period']} "
                f"({m['surprise_percent']:.1f}%) — a recent stumble under an otherwise positive read."
            )

    return {"metrics": metrics, "contradictions": contradictions}


def gather_ticker_data(ticker: str) -> dict:
    zacks_data = zacks_import.load_ranks()["ranks"].get(ticker)
    consensus = _safe(consensus_store.refresh, ticker)
    earnings_history = _safe(prices.fetch_earnings_history, ticker)
    earnings_calendar = _safe(prices.fetch_earnings_calendar, ticker)
    insider_transactions = _safe(prices.fetch_insider_transactions, ticker)
    news = _safe(prices.fetch_company_news, ticker)
    sentiment = _safe(alpha_vantage.fetch_news_sentiment, ticker)

    return {
        "ticker": ticker,
        "zacks": zacks_data,
        "analyst_consensus": consensus,
        "earnings_history": earnings_history,
        "next_earnings": earnings_calendar,
        "insider_transactions": insider_transactions,
        "recent_news": news,
        "news_sentiment": sentiment,
    }


def synthesize(ticker: str) -> dict:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")

    data = gather_ticker_data(ticker)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=MODEL,
        max_tokens=2200,
        thinking={"type": "disabled"},
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Ticker: {ticker}\n\nData:\n{json.dumps(data, indent=2, default=str)}",
            }
        ],
    )
    text_blocks = [block.text for block in message.content if block.type == "text"]
    if not text_blocks:
        raise RuntimeError(f"Claude returned no text content for '{ticker}' (content types: {[b.type for b in message.content]})")
    analysis = "".join(text_blocks)

    return {
        "ticker": ticker,
        "analysis": analysis,
        "data_used": data,
        "signals": derive_signals(data),
        "opp_b_score": opportunities_b.score_ticker(ticker),
        "sector_context": sectors.sector_context(ticker),
    }
