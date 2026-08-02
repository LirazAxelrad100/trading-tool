# Roadmap — postponed / considered ideas

Running list of things we discussed and deliberately deferred, so the reasoning isn't lost.
Everything here must respect the project's hard rules (no directive advice, no ToS-violating
scraping, test free-tier endpoints before trusting — see CLAUDE.md).

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
  shares sold first). Real example: a holding was partly sold — the broker's FIFO gain,
  but our average-cost figure was materially lower. We had to hand-patch the history entry to match.
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
