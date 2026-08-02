# Plan: Synthesized stock analysis (per-ticker, on-demand)

**Status:** ✅ implemented and verified, including the compare view. Both API keys working: `ANTHROPIC_API_KEY` (30-day expiry) and `ALPHA_VANTAGE_API_KEY` in `.env`. Code: `synthesis.py`, `alpha_vantage.py`, new functions in `prices.py`, endpoints in `main.py` (`/api/zacks/{ticker}/analyze`, `/api/zacks/compare`), UI in `static/app.js`/`index.html` (Analyze button + modal, Compare bar + modal in the Opportunities tab).

## Goal

For a specific ticker in the Zacks Rank 1 Opportunities table, generate a prose synthesis of all available signals to support an informed buy decision — not a table of numbers (the user already has that via Zacks), and not a directive "buy/sell" call (see CLAUDE.md hard rules).

## Trigger model

**On-demand, single ticker, user-initiated** (e.g. an "Analyze" button per row) — explicitly NOT run automatically for all ~219 Rank 1 tickers. Keeps API cost near-zero and avoids rate-limit issues, since this is meant for "help me think through this specific decision" moments, not a standing job.

## Data inputs (confirmed available, free tier)

1. **Zacks data** (already stored in `data/zacks_ranks.json`): rank, industry, price, 1-week/4-week price movers, EPS estimate change (4wk), projected earnings growth (1yr), Value/Growth/Momentum/VGM scores.
2. **Analyst consensus** (Finnhub `/stock/recommendation`, already built): strong buy/buy/hold/sell/strong sell counts + weighted average.
3. **Company earnings history** (Finnhub `/stock/earnings`) — NEW: last several quarters' actual vs. estimated EPS, surprise %. Confirmed working on free tier.
4. **Earnings calendar** (Finnhub `/calendar/earnings`) — NEW: next earnings date + estimate. Confirmed working. Useful "event risk ahead" context.
5. **Insider transactions** (Finnhub `/stock/insider-transactions`) — NEW: recent insider buy/sell activity (name, shares, price, date), sourced from SEC filings. Confirmed working.
6. **Company news headlines** (Finnhub `/company-news`) — NEW: recent real headlines for the LLM to read and characterize itself. Confirmed working; substitutes for Finnhub's gated sentiment score.
7. **Alpha Vantage News & Sentiment** — NEW: real sentiment scores across news + earnings call transcripts (confirmed working: `NEWS_SENTIMENT` function, per-article and per-ticker sentiment score/label). Free tier: 25 requests/day total — fine given on-demand single-ticker usage.

## Explicitly rejected (tested or researched, not usable)

- Finnhub `/news-sentiment` — 403, requires paid plan (tested live).
- Finnhub `/stock/price-target` — 403, requires paid plan (tested live).
- Yahoo Finance (any form) — no official API since 2017; unofficial scraping (`yfinance`-style) violates their ToS. Not used regardless of technical feasibility.
- Financial Modeling Prep price targets — free tier exists (250 calls/day) but couldn't verify live whether price targets specifically are free-tier-included or gated; would need a free FMP key to test before trusting. Deprioritized, not blocking.
- SEC EDGAR 13F institutional ownership — legitimate and fully free (primary government source), but adds parsing complexity for a "nice to have" signal. Not in scope for v1.

## Output

One Claude API call per ticker, assembling all of the above into a prompt, producing prose that:
- Connects signals across sources (e.g. "momentum is up X% and EPS estimates were revised up Y% in the last month, and Z of N analysts rate it Buy/Strong Buy — these agree" vs. "price is up but estimates haven't moved and analysts are split — that's a move without fundamental confirmation yet").
- Explicitly notes when signals conflict, rather than picking a side.
- Never concludes with "buy this" / "sell this" / ranks it against other tickers.

Displayed in a modal/popup (reuse the existing consensus-modal pattern) triggered per-ticker in the Opportunities table.

## Follow-on: compare two tickers side by side

Inspired by [Yahoo Finance's compare tool](https://finance.yahoo.com/compare/), but more compact and built on top of the single-ticker synthesis above rather than a separate feature.

**Design:** pick two tickers (e.g. a "Compare" selection in the Opportunities table), run the *exact same single-ticker synthesis independently for each* — two separate calls, neither aware of the other — and display both side by side: ticker/company/price header, the same metrics rows already shown in Opportunities (momentum, EPS Δ, VGM, consensus) per column, then each ticker's prose synthesis underneath its own column.

**Why independent calls, not one combined "compare" call:** this is the same "no directive conclusion" line as everywhere else, just easier to accidentally cross here since "compare" implicitly invites "which one's better." A single combined prompt risks drifting into "X looks stronger than Y." Two independent single-ticker write-ups shown side by side gives the same practical comparison — the user's eye does the comparing — without the model ever producing a comparative verdict.

**Cost:** just 2x the single-ticker cost (two independent calls), still cents.

## Facts table + contradiction flags (added later)

Both the single Analyze view and each Compare column now render, above the prose:
1. A **facts table** (`renderSignalsTable` in `app.js`) — Zacks Rank, 1W/4W price move, EPS estimate revision, projected 1-yr earnings growth (labelled "(forecast)"), VGM with its V/G/M breakdown, consensus counts + label, recent EPS surprises, next earnings date.
2. A **"Tensions to note"** box (`renderContradictions`) listing where signals *contradict* each other.

Each prose paragraph also opens with a **bold summary lead-in** (3–7 words) — the prompt asks for `**lead-in.**` per paragraph and the frontend renders `**…**` → `<strong>` via `renderAnalysisText` (which HTML-escapes first, since the analysis is model output injected through innerHTML). This was originally incidental model behavior the user found useful; made deterministic via the prompt so it doesn't come and go between generations. Lead-ins must summarise, never recommend.

Both the table and tensions come from `synthesis.derive_signals(data)` — **deterministic rules, not the LLM** (reliable, free, and easy to keep strictly descriptive). Current contradiction rules: bullish rank + weak VGM (D/F); bullish rank + price down ≥10% over 4W (market not confirming); estimates raised but price fell (mutually exclusive with the previous one to avoid double-flagging); bullish rank + a recent earnings miss. These flag tension for the user to weigh — they never resolve it into a "better"/"less risky"/buy verdict (that hard line is why this is rule-based description, not an LLM judgement). Verified the rules reproduce the real SNDK (1 tension) vs SIMO (3 tensions) reading.

## Status of open items

- [x] Anthropic Console account + billing set up, key tested working.
- [x] Alpha Vantage free API key, tested working.
- [x] Prompt/system-instruction wording (`synthesis.SYSTEM_PROMPT`) — tested on multiple real tickers (NVDA, INTC, AGX), scanned output for directive/comparative language ("recommend," "should buy/sell," "better than," "winner," etc.) — clean on every run so far.
- [x] Plain-language pass: initial output was too jargon-heavy for a non-professional reader (e.g. "a strong trailing earnings growth figure," "price action is choppy and doesn't confirm the bullish rank"). Prompt now requires every technical term to be briefly explained in plain words inline, with two before/after examples baked into the prompt itself (examples steer tone more reliably than abstract instructions). Also requires explicitly distinguishing historical ("already happened") vs. projected ("a forecast") figures, since conflating them is an easy, misleading mistake. Re-verified clean of directive language after this change too.
- [x] Single-ticker synthesis built and verified (`/api/zacks/{ticker}/analyze`).
- [x] Compare view built and verified (`/api/zacks/compare?a=X&b=Y`) — two independent calls, side-by-side columns, no comparative verdict observed in testing.

## Known limitations

- Each analysis costs a few seconds (data gathering across 4+ APIs + one Claude call) — acceptable for on-demand use, not for bulk.
- `max_tokens=2200` on the Claude call (raised from 1400 → 700 originally, twice, after the plain-language pass made responses longer); if a future prompt change makes responses regularly run longer again, check `stop_reason` for `max_tokens` truncation.
- Per-source failures (e.g. a ticker Alpha Vantage or Finnhub earnings doesn't cover) are caught and simply omitted from the data sent to Claude, not fatal to the whole analysis.

## Bug found & fixed: thinking blocks silently eating the token budget

Real production bug, not a one-off: `message.content[0].text` assumed the first content block was always text. Sonnet 5 defaults to **adaptive thinking** when the `thinking` param isn't set, so responses could come back as `['thinking', 'text']` — or, if the model spent long enough "thinking," `['thinking']` alone with `stop_reason: max_tokens` and **zero actual text produced**. That crashed with `AttributeError: 'ThinkingBlock' object has no attribute 'text'`, surfaced to the user as a raw non-JSON "Internal Server Error" (compare(WDC, STX) was the case that caught it).

Two-part fix:
1. Explicitly pass `thinking={"type": "disabled"}` — this task is data-formatting, not multi-step reasoning, so thinking adds cost/risk with no benefit here. Confirmed reliable across repeated runs after this change.
2. Defensively extract text via `[b.text for b in message.content if b.type == "text"]` rather than indexing `[0]`, and raise a clear `RuntimeError` (→ clean JSON 500, not a raw crash) if no text block comes back at all, so any *future* edge case fails informatively instead of crashing.
