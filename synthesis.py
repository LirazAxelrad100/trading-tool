import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv

import alpha_vantage
import consensus_store
import opportunities_b
import prices
import risk
import sectors
import zacks_import

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are a financial data analyst helping an individual investor read their own research on a single stock ticker. You will be given structured data: Zacks Rank screening metrics, analyst consensus ratings, an Opportunities B score (a separate methodology built on analyst conviction and earnings-beat consistency, distinct from Zacks' estimate-revision-driven rank), recent earnings history, the next earnings date, recent insider trading activity, recent news headlines, and news sentiment scores.

Write a TIGHT, skimmable synthesis in prose — 3-4 paragraphs, aiming for roughly 180-250 words total (not per paragraph). This is a hard budget: pick the handful of facts that most matter and drop or fold in the rest, rather than covering every metric in the data. The reader should be able to read the whole thing in one pass, not skim past it because it's too long. Specifically:
- Begin every paragraph with a short bold lead-in — 3 to 7 words that summarise that paragraph's takeaway — wrapped in double asterisks, followed by 2-3 sentences of support, not a full explanatory essay. For example: "**Estimates rising, price lagging.** Analysts raised earnings forecasts over the past month, but the share price drifted lower over the same stretch — the market isn't confirming the optimism yet." The lead-in must describe what the paragraph says, never give a recommendation.
- Organize by THEME, not by data category — don't give VGM scores, Opportunities B, consensus, and insider activity each their own paragraph. Group whatever agrees into one paragraph and whatever conflicts into another; mention a metric only if it changes the reading, skip ones that just restate what's already been said.
- Explicitly call out where signals AGREE (reinforcing a read) and where they CONFLICT (creating ambiguity) — one clear sentence each, not paragraphs of caveats. Include the Zacks-vs-Opportunities-B comparison only if it's actually informative here (they measure different things: Zacks = is estimate momentum accelerating now; Opportunities B = how strong is underlying analyst conviction and the earnings-beat record).
- Fold in risk context (upcoming earnings date, beat/miss pattern) and the news narrative wherever they're most relevant — they don't need their own paragraph unless they're the single biggest story here.
- If data for a category is missing, unavailable, or simply doesn't add anything new, omit it entirely — don't mention a category just to say there's nothing notable in it.

Write for a smart reader who is NOT a finance professional. Avoid dense analyst jargon and vague shorthand phrases. The first time (and only the first time) you use a technical term (earnings surprise, estimate revision, trailing vs. projected growth, VGM score, consensus rating, EPS, "price action," etc.) in the whole response, gloss it in a short parenthetical of a few words — not a full explanatory sentence — then use the term freely afterward.

Be EXPLICIT and CONCRETE, never vague or metaphorical, but SHORT about it:
- Prefer plain phrasing over vague verbs: "the share price" not "price action"; "most recent news coverage" not "news lean."
- Whenever you say a signal is mixed or "not all good," name the SPECIFIC concern in the same sentence — don't leave it abstract, and don't spend a second sentence explaining it further than needed.
- Be clear whether a growth/estimate number is historical (already happened) or projected (a forecast) — a few words is enough ("up 12% over the past year" vs. "forecast to grow 12%"), don't over-explain the distinction every time.

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

# "Expectations stretched ahead of earnings" thresholds — forward-looking, not a recap of a
# past reaction: if a stock has already rallied hard and sentiment is running hot heading into
# its earnings date, a beat has less room to move the price (a real pattern the user flagged
# with MU/AMD — big beats, price fell anyway). See docs/plans/roadmap.md.
EARNINGS_WATCH_DAYS = 21          # "ahead of the print" window
STRETCHED_RUNUP_PCT = 15          # 4-week price move considered a meaningful run-up
BULLISH_SENTIMENT_THRESHOLD = 0.35  # Alpha Vantage's own "Bullish" cutoff (their docs' band)


def _earnings_risk(price_move_4w, next_earnings: Optional[str], sentiment) -> dict:
    if not next_earnings:
        return {"triggered": False, "near_earnings": False}
    try:
        days_out = (date.fromisoformat(next_earnings) - date.today()).days
    except ValueError:
        return {"triggered": False, "near_earnings": False}
    if not (0 <= days_out <= EARNINGS_WATCH_DAYS):
        return {"triggered": False, "near_earnings": False}

    avg_score = sentiment.get("average_score") if isinstance(sentiment, dict) else None
    runup = isinstance(price_move_4w, (int, float)) and price_move_4w >= STRETCHED_RUNUP_PCT
    bullish = isinstance(avg_score, (int, float)) and avg_score >= BULLISH_SENTIMENT_THRESHOLD

    return {
        "triggered": runup and bullish,
        "near_earnings": True,
        "days_to_earnings": days_out,
        "price_move_4w": price_move_4w,
        "sentiment_score": avg_score,
    }


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

    ob = data.get("opportunities_b") or {}
    ob_score = ob.get("score")
    ob_composite = ob_score.get("composite") if ob_score else None
    ob_cutoff = ob.get("shortlist_cutoff")
    ob_in_universe = ob.get("in_sp500_universe")
    universe_note = (
        "" if ob_in_universe
        else " — note it's outside the S&P 500 set Opportunities B actually screens, "
             "so it was never formally in the running for that list; this is a one-off "
             "read using the same math, not a shortlist placement"
    )

    if ob_composite is not None and ob_cutoff is not None:
        if bullish_rank and ob_composite < ob_cutoff:
            contradictions.append(
                f"Conflicting signal: Zacks Rank {rank} says earnings estimates are being raised right now, but the "
                f"Opportunities B score — a separate read based on analyst conviction (strong-buy vs. "
                f"buy ratings) and earnings-beat consistency — comes out at {ob_composite * 100:.0f}, "
                f"below the {ob_cutoff * 100:.0f} needed to make its current top-20 shortlist{universe_note}. "
                f"The two methodologies weigh different evidence and disagree here: Zacks is picking up "
                f"fresh estimate momentum that the conviction/beats lens isn't seeing."
            )
        elif not bullish_rank and ob_composite >= ob_cutoff:
            rank_note = f"is ranked {rank} by Zacks" if rank is not None else "isn't on the current Zacks Rank 1 list at all"
            contradictions.append(
                f"Mixed signal: this ticker {rank_note}, but its Opportunities B score ({ob_composite * 100:.0f}) "
                f"would clear the bar for the current top-20 shortlist{universe_note}. Analyst conviction and "
                f"earnings-beat consistency look strong even though Zacks isn't currently flagging accelerating "
                f"estimate revisions for it — the two methodologies are reading this name differently: one "
                f"possibility is steady, already-priced-in strength that Zacks' revision-based rank wouldn't "
                f"light up for; another is a name Zacks just hasn't caught up to yet."
            )

    earnings_risk = _earnings_risk(p4, next_earnings, data.get("news_sentiment"))

    return {"metrics": metrics, "contradictions": contradictions, "earnings_risk": earnings_risk}


def gather_ticker_data(ticker: str) -> dict:
    zacks_data = zacks_import.load_ranks()["ranks"].get(ticker)
    consensus = _safe(consensus_store.refresh, ticker)
    earnings_history = _safe(prices.fetch_earnings_history, ticker)
    earnings_calendar = _safe(prices.fetch_earnings_calendar, ticker)
    insider_transactions = _safe(prices.fetch_insider_transactions, ticker)
    news = _safe(prices.fetch_company_news, ticker)
    sentiment = _safe(alpha_vantage.fetch_news_sentiment, ticker)
    opp_b_score = opportunities_b.score_ticker(ticker)

    return {
        "ticker": ticker,
        "zacks": zacks_data,
        "analyst_consensus": consensus,
        "earnings_history": earnings_history,
        "next_earnings": earnings_calendar,
        "insider_transactions": insider_transactions,
        "recent_news": news,
        "news_sentiment": sentiment,
        "opportunities_b": {
            "score": opp_b_score,
            "in_sp500_universe": opportunities_b.in_universe(ticker),
            "shortlist_cutoff": opportunities_b.shortlist_cutoff(),
        },
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
        "opp_b_score": data["opportunities_b"]["score"],
        "sector_context": sectors.sector_context(ticker),
        "volatility": _safe(risk.compute_volatility, ticker),
    }
