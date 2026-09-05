# Roadmap — postponed / considered ideas

Running list of things we discussed and deliberately deferred, so the reasoning isn't lost.
Everything here must respect the project's hard rules (no directive advice, no ToS-violating
scraping, test free-tier endpoints before trusting — see CLAUDE.md).

## Risk assessment (August 2026)

Context: added a per-ticker **historical volatility** badge to the Analyze popup (`risk.py`,
annualized std-dev of daily returns from the already-cached Alpha Vantage price history) —
descriptive only, explicitly framed as backward-looking, not a prediction. Discussing what
else is worth adding; two ideas below, deliberately picked to give genuine *new* information
rather than just re-displaying data already visible elsewhere in the tool.

### Earnings-reaction risk (forward-looking, not a recap)
Motivated by a real pattern the user noticed: recent "amazing" earnings beats (MU, AMD) were
followed by the stock dropping anyway — a beat alone isn't a reliable green light lately.
A flag that only reports "the last beat wasn't rewarded" *after* the fact was rejected as low
value ("knowing the change after it happened is not worth the token of building it"). Reframed
into two forward-looking layers:
1. **Expectations-stretched flag, ahead of the print** — ✅ BUILT (2026-08-17). If a stock has
   already rallied hard in the weeks before its earnings date and sentiment is running very
   bullish, a beat has less room to move the price (arguably what happened with MU/AMD). Uses
   data already fetched for Analyze (`price_move_4w`, `news_sentiment` average score,
   `next_earnings` date) — no new API calls. `synthesis.py`'s `_earnings_risk()`.
2. **Per-ticker beat-to-price track record** — ❌ DROPPED (2026-08-18), blocked twice over.
   The idea: pull the last ~6-8 *actual* earnings report dates and check whether the price
   actually rose in the day(s) after each, producing an honest stat like "beaten 4 of 4
   quarters, but price rose after only 1 of those 4" — a base rate for how much weight this
   ticker's next beat deserves. Two live-tested blockers, in order:
   - Finnhub's `calendar/earnings` **cannot** return historical report dates for a specific
     symbol on the free tier (see the hard rule in CLAUDE.md) — pivoted to Alpha Vantage's
     `EARNINGS` endpoint instead, which **does** work free and returns real `reportedDate`/
     `reportedEPS`/`estimatedEPS`/`surprisePercentage`/`reportTime` per quarter (live-verified
     2026-08-18, e.g. MU: 122 quarters back).
   - But the earnings dates alone aren't enough — reading the price reaction around each one
     needs *years* of daily closes, and Alpha Vantage's free tier only gives ~100 trading days
     (`outputsize=compact`); `outputsize=full` is **premium-only** (live-tested 2026-08-18,
     confirmed by the API's own error message). Considered Stooq as a free, no-key full-history
     source instead (kept AV just for the earnings dates) — also a dead end: its `robots.txt`
     disallows automated access for everyone except Googlebot/Bingbot, and its CSV download
     endpoint now sits behind an active proof-of-work bot challenge, which we won't attempt to
     solve. No further free/legal full-history source identified. Revisit only if a paid data
     source ever becomes worth it for this tool, or a new free option surfaces.

### Postponed: correlation-aware concentration / stress view
The user already sees per-stock concentration clearly (the % Portfolio column — WDC + PLTR
alone are ~44% of the portfolio) and didn't want a feature that just re-displays that. The
genuinely new angle: **correlation, not just size** — if the biggest holdings move on the same
trigger (e.g. WDC/MU/NVDA/AMD all being AI-capex-sensitive), real concentration risk is bigger
than the % numbers suggest, because one headline can hit all of them at once. Computable from
price history already fetched per holding (pairwise correlation of daily returns). From there,
a grounded stress scenario becomes meaningful — "if AI-linked names as a group dropped 20%,
the portfolio would move roughly X%" — because it's based on the portfolio's actual correlated
exposure, not a generic what-if. Purely descriptive/scenario math, no recommendation attached
(the "what to do about it" stays the user's call, per the no-directive-advice hard rule).
The earnings-reaction work above is now resolved (one piece shipped, the other dropped), so
this is next up whenever risk-assessment work resumes.

## Momentum, themes and the recovery lens (September 2026)

Context: reviewed `~/Documents/projects/claude-trading-skills` (a large set of GitHub trading
skills) for anything worth adopting, with the stated goal "find stocks that are going up".
Most of that library assumes a data stack this tool doesn't have (FINVIZ Elite €35/mo, FMP
paid tier) and an active-trading posture (position sizing, Alpaca order templates) that
conflicts with the no-directive-advice rule. Adopt *concepts*, not code.

### Built this session — momentum-burst badge (`momentum.py`)
See CLAUDE.md for the full description. Two key findings worth not relearning:
- Alpha Vantage's `TIME_SERIES_DAILY` was already returning open/high/low/volume and
  `fetch_daily_prices` was **discarding all but the close** — so full OHLCV momentum signals
  cost zero extra API calls.
- Finnhub's `/quote` + `stock/metric` (both already fetched per watchlist refresh) cover a
  usable subset — day change, close location, 5-day run-up, 52-week distance, 10d-vs-3m volume
  elevation — so scanning the whole Watch List is free. `/quote` has **no volume field**, which
  is why true volume-spike and range-expansion reads need the Alpha Vantage bars.

### Rejected from the skills library, with reasons
- `breakout-trade-planner` — the risk arithmetic (entry/stop/R-multiples) is *not* advice and
  would be safe to borrow; but the sizing multipliers (textbook 1.75× vs. developing 0×), the
  curated "Actionable Orders" list, and `side: buy, qty: N` broker templates are. Also built
  for many small swing trades with an Alpaca API account — the opposite of this portfolio.
- `vcp-screener`, `canslim-screener`, `institutional-flow-tracker` — all need a paid FMP tier
  for full-universe scans; 13F data also carries a 45-day reporting lag.
- `theme-detector` — genuinely additive (see below), but its free mode **scrapes FINVIZ**,
  which their ToS prohibits, and the legitimate path needs FINVIZ Elite at €35/mo.

### The case for themes, proven on real holdings (2026-09-04)
Five Watch List names — STRL, VRT, ONTO, AEHR, FN — turned out to be one AI-infrastructure bet
held five times: all up enormously over 12 months, all down 10–52% since early June, all well
below their 52-week highs. `sectors.py` **cannot see this**: it files STRL and VRT under
Industrials, ONTO/AEHR under Information Technology, and returns `None` for FN. An 11-sector
GICS view structurally splits a cross-sector theme apart. This is the concrete answer to
"would theme detection add value over our sector view" — yes, and additive rather than a
replacement.

### Backlog, in recommended build order
1. **Thesis capture at entry.** ✅ BUILT (2026-09-05) — see CLAUDE.md's Watch List entry. Shipped as tag + source link + why + an automatic entry snapshot. Two design notes worth keeping: an early reading that the 8 empty notes meant "optional fields get skipped under time pressure" was **wrong** — the note field simply didn't exist when those rows were added, and that mistaken premise was the whole argument for deferring the `why` field. And the user's own argument for including it is the one that settled it: *"if we don't have this in the interface it will never happen"* — the same reasoning as the pre-trade-checklist item below. The existing notes also turned out to be source labels rather than reasoning, which is why tag and why are separate fields and why tags double as the grouping in item 3. When adding a Watch List item, record *why* (recovery /
   momentum / theme / income) and *what would prove it wrong*, extending the free-text note
   that already exists. Then the tool can close the loop itself later: "added 9 Aug at $528 as
   a recovery thesis; now $483, earnings still growing, multiple flat over 12 months." Cheap,
   no new API calls, and it makes every later feature more useful. The existing note field
   already proved the value — "zacks report ai bubble" explained more about STRL than any
   metric did.
2. **Fundamentals-vs-price panel (the recovery lens).** ✅ BUILT (2026-09-05) — `fundamentals.py`, see CLAUDE.md. The design note worth keeping: the 12-month window is forced by Finnhub's TTM growth figures and is *blind on its own* — every ticker tested came out "in line" because a recent drawdown hides inside a net-positive year. Pairing the multiple change with the drawdown is what makes it informative. The tool is entirely trend-following
   (Zacks revisions, Opportunities B conviction, momentum, sentiment) — every signal asks "is
   this working now". A recovery thesis says "it isn't, and that's the point", so the tool will
   structurally always look bearish on one. The missing lens is a 2×2: price up/down against
   earnings up/down, where **price down + earnings up** is the recovery setup and **both down**
   is the value-trap shape. Free from `stock/metric` + `stock/earnings`, both already fetched.
   Multiple change is derivable without any paid historical-P/E data:
   `(1 + price_return) / (1 + eps_growth) - 1`. Run on STRL over 12 months: price +59%, EPS
   +51% → the multiple is roughly unchanged over a year, meaning the June spike to 49× was the
   anomaly, not the fall. Honest limit: this identifies the *entry condition* for a recovery
   thesis, never the timing — nothing can tell you a decline is over.
3. **Concentration grouping** — "these names move together". Smaller and cheaper than full
   theme detection, and it would have caught the five-names-one-bet problem in August. Buildable
   from trailing returns already fetched on every watchlist refresh.
4. **Risk preview on Watch List items** — before buying, show "at today's price with a 15% stop,
   a full position of €X puts €Y at risk, Z% of the portfolio". This is the genuinely borrowable
   half of `breakout-trade-planner`: arithmetic about a hypothetical, no buy/qty/conviction.
5. **`market-breadth-analyzer`** (from the skills library) — free public CSV, no API key, one
   fetch/day, zero per-ticker cost. Scores 0–100 whether a rally is broad or narrow. Relevant
   because breakout setups fail disproportionately when breadth is narrow.
6. **Static pre-trade checklist in the UI.** Decided (2026-09-04) that the *static* questions
   belong in the tool and the *adaptive* reasoning belongs in conversation with Claude. Reason:
   a checklist's whole value is firing at the moment of decision rather than depending on
   remembering to open Claude Code. Adaptive questions ("this is a recovery thesis, so ask about
   multiple compression") can't be pre-written. If these are ever LLM-generated, the prompt needs
   `SYSTEM_PROMPT`-level discipline — a question smuggles advice easily ("have you considered the
   multiple must reach 72×?" is a recommendation wearing a question mark).
7. **Theme lifecycle staging** — the one thing the cheaper alternatives can't replicate: flagging
   a theme as Emerging vs. Exhausting *before* the unwind. Needs FINVIZ Elite (€35/mo). Only
   worth revisiting if the user decides to pay.

### Known loose ends
- `sectors.ticker_sector()` returns `None` for FN and INOD — not in `sp500.json` and the Finnhub
  industry lookup didn't resolve them, so they have no sector context at all.
- Finnhub's `stock/metric` can describe a **different listing** than its own `/quote`: for TSM,
  `/quote` returns the US ADR (~$427) while the metric block returns the Taiwan listing's range
  (52w high 2535, low 1145 TWD). `momentum._pct_from_52w_high()` guards this by rejecting a price
  outside its own 52-week range, but other non-US-primary names may be affected elsewhere.
- Analyze's momentum tier reads Alpha Vantage daily bars, which lag by a day, so the
  bounce-in-a-downtrend tension fires a day late there while the Watch List (live Finnhub) sees
  it immediately. The badge discloses this as "(bars through <date>)". Fixing it means mixing
  today's price move with yesterday's volume figures — a real tradeoff, deliberately not taken.

## Data-source research (July 2026)

Goal the user stated: better **stock ranking/evaluation** and some **sector / market view**,
in service of smarter buy/sell decisions. Findings:

### Built
- **Sector relative-strength** (`sectors.py`) — 11 SPDR sector ETFs ranked by trailing
  1M/3M return (Alpha Vantage daily history, cached, ~2.5 min throttled build). Synthesized
  into the Analyze/Compare popup ("this stock's sector is #N of 11, leading/lagging") and the
  Opportunities B sector column. Descriptive only — never "sector X will outperform".

### Postponed (in rough priority order)
1. **Sector leaderboard view** — a compact standalone panel showing all 11 sectors ranked,
   as the at-a-glance reference behind the per-stock sector tags. (Engine already exists;
   this is just a small UI.)
2. **Sector column on Holdings + Zacks Opportunities tables** — *nice to have, low priority.*
   Same `sectors.ticker_sector` mapping, just surfaced in those tables too (Opportunities B
   already has it). Deliberately not urgent: the sector context already shows in the **Analyze
   popup** for any ticker regardless of tab, so this would only save a click, not add new info.
3. **FMP (Financial Modeling Prep)** — free tier ~250 req/day. Two draws: a ready-made
   **sector-performance** endpoint, and **analyst stock grades** (named-firm upgrades/downgrades
   — a *different* rating source than Finnhub's consensus counts, so a genuine second opinion).
   Needs a free key + a live free-tier test before trusting (docs have burned us before).
4. **13F "smart money"** (SEC EDGAR, free + legal, government) — what big institutions
   (Berkshire, large funds) hold and how it changed quarter-over-quarter. Caveats: ~45-day
   filing lag, long-only US-equity snapshot (no shorts/non-US/cash), needs XML parsing.
   The pretty aggregators (Dataroma/WhaleWisdom) scrape this — off-limits; use raw EDGAR.
5. **ETF holdings as curated lists** — issuer-published (iShares/SSGA) holdings CSVs of a
   respected active ETF, as a fund-manager-curated stock shortlist. Free/legal from the issuer.

### Rejected / dropped
- **FRED (macro/economic data)** — free + legal, but the user and I agreed it's *backdrop
  mood*, not a stock-selection signal. Indirect to individual buy/sell decisions; scope creep
  for a stock-picking tool. Revisit only if a "market regime" banner is ever wanted.
- **Yahoo Finance / TipRanks / MarketBeat / Seeking Alpha scraping** — ToS violations. Out,
  regardless of technical feasibility. Genuine curated *market commentary* is essentially all
  paywalled or scraping-only, so the free/legal substitutes are what we aggregate ourselves
  (analyst ratings, news sentiment, sector strength, and later positioning/13F).

## Multi-lot / per-lot FIFO cost basis  ✅ BUILT (2026-07-31)

Holdings now carry a `lots` list `{shares, cost_basis, purchase_date}`; the API derives
`shares`/`cost_basis`/`purchase_date` (via `recompute_aggregates`) so all existing UI keeps
working. Selling is **FIFO** (`sell_holding` consumes oldest lots first, records a `lots_sold`
breakdown, gain matches the broker). Endpoints: `POST/PUT/DELETE /api/holdings/{id}/lots[/{i}]`.
Frontend: a **Lots modal** per holding (view/add/edit/remove lots), a `(N lots)` link + "Lots"
button, FIFO gain in the sell preview, and the plain Edit form forwards shares/cost to the single
lot (multi-lot edits its shares/cost only through the Lots modal). Legacy holdings auto-migrated
to one lot. This removes the dependency on TR's "Avg buy in". Original design notes below (kept
for reference).

The single biggest accuracy gap. Today a holding stores **one average `cost_basis`**, so:
- We can't reproduce Trade Republic's realized gains, which use **FIFO** (oldest/cheapest
  shares sold first). This bit on a real sale: because the oldest lot was cheaper than the
  position's average cost, TR's FIFO gain came out materially higher than our average-cost
  figure, and the history entry had to be hand-patched to match the broker.
- Adding a second purchase of a held ticker has no clean home (you'd overwrite or average manually).

**Design sketch:**
- A holding becomes a container with a **list of lots**, each `{shares, cost_basis, purchase_date}`.
- Aggregate `cost_basis` (weighted average) is derived for display / trailing-stop logic.
- **Sell = FIFO**: consume oldest lots first, realized gain computed per lot at its *actual* cost,
  summed — this reproduces TR's numbers exactly, so we stop depending on TR's "Avg buy in".
- **Add**: buying a ticker you already hold adds a lot (not a new row / not a manual re-average).
- Migration: today's single-cost holdings become a one-lot list. Touches holdings schema,
  create/update/sell endpoints, `evaluate_trailing` (uses the aggregate), sell gain calc, the
  Add form, and History.
- German tax is FIFO, so this also makes the estimated-tax figures actually correct.

This supersedes the old "averaged cost basis for now" decision — the user has explicitly said
they want real multi-lot support.

## Ops / automation postponed
- **Schedule Opportunities B refresh and sector refresh via launchd** (like `daily_check`),
  so both stay fresh hands-off instead of manual buttons.
- **Alpha Vantage budget pressure**: sector build (11 calls) + price charts + Analyze sentiment
  all share the 25/day free cap. If it becomes a real pinch, a free no-key EOD source like
  Stooq (CSV) could feed the sector ETFs instead — would need a legality/reliability check first.

## Naming / wording
- Revisit calling the analyze/compare "Tensions" box a "tension/contradiction" — the user
  noted it's often more a *broader multi-lens view* than a true contradiction. Cosmetic; the
  flags themselves are fine.
