# Trading Tool

Local live tool for tracking holdings and manually-simulated trailing stops (Trade Republic / Scalable Capital don't support native trailing stops). Data lives in `data/holdings.json` on this machine only.

## Setup

```bash
cd trading-tool
./venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:
- `FINNHUB_API_KEY` — free at [finnhub.io/register](https://finnhub.io/register)
- `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` — for email alerts. The app password (not your real Gmail password) comes from [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (requires 2-Step Verification on your Google account).
- `NOTIFY_TO_EMAIL` — where alerts get sent (defaults to `GMAIL_ADDRESS` if unset).
- `ANTHROPIC_API_KEY` — for the Analyze/Compare synthesis feature. Pay-as-you-go, from [platform.claude.com](https://platform.claude.com) (Settings → Billing to add credit, then API Keys to create one — recommend a real expiry like 30 days, not "Never," per the console's own guidance).
- `ALPHA_VANTAGE_API_KEY` — for news sentiment in the synthesis feature. Free, from [alphavantage.co](https://www.alphavantage.co/support/#api-key).

**Your data never goes into git.** Everything under `data/` is ignored — real holdings,
watchlist, sales history, portfolio value history, and the API caches — so a clone starts
empty and you add your own positions through the UI. `data/holdings.example.json` documents
the schema; `data/sp500.json` is bundled reference data the Opportunities B screen needs.

## Run it

```bash
./venv/bin/uvicorn main:app --reload --port 8000
```

Then open http://127.0.0.1:8000

## What's here

- Two tabs: **My Stocks** (Add holding form, holdings table, breakout/stop-hit alerts) and **Opportunities** (Zacks Rank 1 table, CSV import, consensus refresh) — keeps either view short instead of one long scrolling page.
- Add/edit holdings: ticker, shares, buy in (cost basis), purchase date, stop loss, trailing high, exit plan. There's no plain "delete" — see **Sell & sales history** below for how a holding leaves the table.
- **Multi-lot holdings**: a holding tracks each purchase as its own **lot** (shares, buy-in, date). The table shows the aggregate (total shares, weighted-average buy-in); a per-row **Lots** button opens a modal to view/add/edit/remove lots (a `(N lots)` link appears once there's more than one). **Selling is FIFO** — the oldest lot goes first — so realized gains and the estimated tax match your broker's (German capital-gains basis), instead of an average approximation. The sell preview shows the FIFO gain live. Buying more of a ticker you hold = adding a lot, not a new row.
- **Runs automatically on page load** — matches the original brief's "check on every app open" design. No need to click anything; the summary panel below the table populates itself.
- **Refresh all prices**: fetches a live price for every holding at once (Finnhub USD quote × live USD/EUR rate from Frankfurter/ECB, since Trade Republic quotes everything in EUR), updates each holding's Current price, and checks each one for two things — a ≥10% breakout above its trailing high, or price at/below its stop loss.
- Per-row **Refresh** button does the same for a single holding.
- **Manual-price holdings**: some instruments you hold on Trade Republic have no matching free price feed — e.g. Lenovo, where the ticker `LNVGY` on Finnhub is a US ADR bundling 20 of the ordinary shares you actually hold, so its price is ~20× yours. Refresh **detects** this (a fetched price more than 10× off your saved one) and, instead of overwriting, asks whether to keep your own price and mark the holding **manual**. A manual holding shows "manual price" instead of a Refresh button, keeps the price you type in the Edit form, shows "—" for Today %, and is skipped by Refresh-all and the daily check. You can toggle it back on anytime via the "manual price" checkbox in Edit. (Only US-listed instruments are on Finnhub's free tier — non-US ordinary shares and ADR-ratio mismatches can't be auto-priced.)
- **Confirm**: after a triggered breakout flag, click confirm once you've manually updated the stop-loss at your broker — this resets Trailing high and Stop loss together.
- **Stop-loss hit alert**: shows your pre-set exit plan, estimated gain/loss vs. buy-in, an estimated tax figure (26.375% Abgeltungssteuer, not netted against your remaining Sparerpauschbetrag), and the latest analyst consensus (Finnhub) — facts to decide fast, not a directive recommendation.
- **Trailing %** is always derived as `(trailing_high - stop_loss) / trailing_high` — never stored independently, so it can't go stale after an edit.
- **Total** column = shares × Current price, plus a portfolio-wide "Total value of assets" sum at the bottom.
- Click the Ticker, Shares, Purchase date, Total, or % Portfolio column headers to sort (click again to reverse).
- **% Portfolio**: each holding's Total as a share of the portfolio's combined Total value of assets — concentration at a glance.
- **Portfolio value over time**: a line chart at the bottom of My Stocks. A real data point is recorded each day you Refresh-all (and by the daily check), so the line builds up accurately going forward. A **"Load past ~3 months (approx)"** button seeds a backward curve from each holding's price history (Alpha Vantage) — labeled *approximate* because it values your *current* holdings back through time (ignoring past buys/sells) and uses ~10 of the 25/day AV calls. Real recorded points always take precedence over reconstructed ones.
- All money values and percentages display in EU format (`1.234,56`, not `3519.32`).
- **Price chart**: clicking any ticker name (Holdings or Opportunities) opens a popup with a 30-day price chart (`GET /api/prices/{ticker}/history`, Alpha Vantage `TIME_SERIES_DAILY` converted to EUR) plus the analyst consensus breakdown — green/red based on the period's % change. Price history is cached once per ticker per day (`data/price_history_cache.json`) since it shares Alpha Vantage's 25-requests/day free-tier cap with the sentiment feature, and this popup gets opened far more casually than the deliberate Analyze action.
- **Current price** is plain, uncolored text — deliberately, after an earlier refresh-to-refresh coloring attempt turned out to just add noise now that Today % exists.
- **Today %**: Finnhub's own day-change figure (`dp` from `/quote`, vs. their previous-close reference) — not something this tool derives itself, since a self-tracked "first price we happened to check today" depends on when that first refresh ran and can already be well after a big move. Colored green/red on its own sign; shows `—` before the first refresh. This is the only price-direction color in the Holdings table.
- **Ticker name** is clickable — opens a popup with the full analyst consensus breakdown (strong buy/buy/hold/sell/strong sell counts) and an average rating (1 = Strong Buy, 5 = Strong Sell). The ticker name itself is colored green/red when that average shifts since the last refresh, same persistence logic as the price color.

### Sell & sales history

**Sell** (per-row button in Holdings, replaces what used to be Delete) is how a holding leaves the table — either partially or fully:

- Opens a small form pre-filled with the holding's full share count: **shares sold**, **total sum received (EUR)**, **sell date**, **sell time**. Shares sold defaults to the full position but can be lowered for a partial sale (e.g. your "sell gains only" exit plan — pull out just the gain, keep the rest invested).
- **Opening the Sell (or Edit) form auto-refreshes that holding's price first** (skipped for manual-price holdings), and the Sell form shows the live "Current price" as a reference — so the sanity check below compares against a current figure and you can eyeball your entry against the market price.
- **Sale price per share isn't a separate input** — it's derived as `total sum ÷ shares sold` and stored alongside the total, since typing both independently risks the two disagreeing by a few cents. **Total spend** (`shares sold × buy in`) is stored too, alongside Total received, so both sides of the trade are visible side by side in History. Realized gain/loss (`total received − total spend`) and estimated tax (26.375% of any gain) are computed the same way.
- **Sanity check on the total**: if the entered total implies a per-share price more than 10× off the holding's last known price, the sale is flagged with a "record it anyway?" confirmation before saving — catches a mistyped total (the comma/period trap) at entry instead of leaving a wildly-wrong loss in History. It's confirmable, not a hard block, so a genuine edge case is never trapped; server-side (`SALE_PRICE_SANITY_FACTOR` in `main.py`), so it holds regardless of how the sale is submitted.
- If shares sold equals the full holding, the row is removed entirely (full liquidation). If it's less, the row stays with its share count reduced — cost basis, stop loss, trailing high, and exit plan are untouched, consistent with this tool's averaged-cost-basis approach to multi-lot holdings.
- Every sell writes one entry to the **History** tab (`data/sales_history.json`): ticker, shares sold, sale price, total received, cost basis, realized gain/loss, estimated tax, sell date/time. Entries are sortable-by-date (newest first) and each has its own **Remove** button — there's no separate "delete a holding by mistake" action; if you added a holding in error, Sell it (any values) and then Remove that entry from History, since a data-entry mistake isn't a real transaction worth keeping a permanent record of.

### Daily automated check (launchd)

`daily_check.py` runs the same refresh-all logic standalone (no dev server needed) and emails a summary **only if there's something to report** — a breakout, a stop-loss hit, or a ticker that failed to fetch. Scheduled via a LaunchAgent:

```bash
# one-time setup (already done):
launchctl load ~/Library/LaunchAgents/com.tradingtool.dailycheck.plist

# to check it's running:
launchctl list | grep tradingtool

# to force a manual run right now:
launchctl start com.tradingtool.dailycheck

# to stop the daily schedule entirely:
launchctl unload ~/Library/LaunchAgents/com.tradingtool.dailycheck.plist
```

Runs daily at 8:00 AM. Logs go to `daily_check.log` in this folder. Requires the Python binary at `venv/bin/python3` (symlinked to the system CommandLineTools Python) to have **Full Disk Access** (System Settings → Privacy & Security → Full Disk Access) — without it, launchd can't read files under `~/Documents`.

If the Mac is asleep at 8:00, macOS runs the missed job once it wakes — which can land before Wi-Fi has reconnected. Both the exchange-rate fetch and the email send retry up to 3 times, ~20s apart, to ride out that window; if the network is genuinely down for longer than that, the run fails silently in the log with no email (there's no way around this without external infrastructure this tool doesn't have).

### Zacks Rank import (opportunity screening)

Zacks Premium doesn't have an API on this subscription tier, and automating a login+scrape against their site would violate their ToS — so this stays CSV-based, but the import itself is now hands-off:

- **Import Zacks CSV** button opens a real file picker (`POST /api/zacks/upload`, multipart file upload) — pick the exported CSV from wherever you saved it. On success it reports the count plus how many tickers were new and how many dropped off. Stores rank per ticker in `data/zacks_ranks.json`. There's also a path-based variant (`POST /api/zacks/import`) that auto-detects the newest matching file in `~/Downloads` without uploading — used internally by the automated watcher below, not by the button.
- **Re-import reconciles against the new list** (Rank 1 churns a lot — ~35–40% turnover day to day): tickers still on the list have their CSV metrics refreshed but keep their fetched **consensus** (so you don't have to re-run the ~4-minute consensus refresh every day); tickers that *dropped off* the list are pruned so the table only shows what's currently ranked. Pruning is scoped to the rank tier(s) in the file being imported, so importing a Rank 1 screen never disturbs a separately-imported Rank 2 set.
- Handles two export shapes: a `Zacks Rank` column per row (e.g. an unfiltered "Company Name,Ticker,Zacks Rank" export), or a screen pre-filtered to one rank tier with no rank column — in that case the rank is inferred from the filename (`rank_1.csv` → 1). **If your Zacks screen has an option to always include the Rank column in the export, turn that on** — it removes the filename-guessing entirely and is more reliable.
- **`zacks_watch_import.py`** + a second LaunchAgent (`com.tradingtool.zackswatch`, uses `WatchPaths` on `~/Downloads`) auto-imports any new/changed file whose name contains "zacks" or "rank" — so exporting the screen from Zacks' site is the *only* manual step; the import itself happens within moments, no command needed.
- Zacks Rank appears as a column in the holdings table for tickers present in the imported data (rank 1 highlighted green); `—` if a holding isn't in whatever screen was last imported.
- This only covers screening/opportunity discovery, not your actual holdings' ranks unless they happen to appear in that screen. Zacks offers a separate "My Portfolio" email alert feature that could cover your actual holdings (AMD/PLTR/VLO/NBIS weren't in the Rank 1 screen) — worth subscribing to as a complementary, official-channel alternative to another CSV.
- Parser also captures Industry, Price, 1-week/4-week price movers, EPS estimate change, projected earnings growth, and Value/Growth/Momentum/VGM scores when the export includes them (it does, for the "custom screen" format).

### Opportunities B (analyst-conviction shortlist over the S&P 500)

A deliberately **short second source** in its own tab, built to be *methodologically different* from the Zacks list (which is estimate-revision momentum, and skews small/mid-cap). B screens the **S&P 500** — large, liquid, well-covered names — by analyst conviction and earnings-beat consistency, so the two lists disagree in useful ways. `opportunities_b.py`, universe bundled in `data/sp500.json` (from the public-domain `datasets/s-and-p-500-companies` dataset — Finnhub's own constituent endpoint is paywalled).

- **Two-stage funnel** to keep API cost sane: Stage 1 does one analyst-recommendation call per S&P 500 name (~500 calls, cached), filters to Buy-or-better with ≥5 analysts, ranks by conviction, and keeps the top 40; Stage 2 adds earnings-beat consistency (one call each) for just those 40 and computes the composite. Output is the **top ~20**, because the whole point is a list short enough to actually work through (a 200-name screen adds nothing).
- **Composite score = 45% conviction + 45% earnings-beat consistency + 10% opinion drift.** Conviction weights Strong-Buy ratings double; beats = fraction of recent quarters that beat estimates (the most Zacks-orthogonal signal); **drift** = whether analyst opinion improved over the last 4 months, read for free from the history Finnhub already returns in the recommendation call (no snapshot pipeline — that granularity is right, ratings barely move day to day). The score orders your attention; the component columns stay visible so you see *why*, and it's never a "buy this" verdict.
- **1W % and 3M % price momentum** columns (sortable, green/red) — trailing 1-week (5-day) and 3-month (13-week) returns, pulled from Finnhub's free `stock/metric` endpoint (one call per shortlisted name, **no Alpha Vantage budget cost**). 3-month rather than Opp A's 4-week because a true trailing-4-week needs daily history (AV-budget-limited), and 1-week + 3-month is a more informative short-vs-medium spread anyway.
- **"Also Zacks 1" column** flags names that appear on *both* independent screens — two different methods agreeing is a meaningful, descriptive cross-reference.
- **Refresh (~10 min)** button (`POST /api/opportunities-b/refresh`) runs the full scan; `GET /api/opportunities-b` returns the cached result (`data/opportunities_b.json`). Clickable tickers and the per-row **Analyze** reuse the same popup/synthesis as the Zacks table. Same guardrail: sorted, never a pick. (Not scheduled — you trigger it; could be added to launchd later like the daily check.)
- A **Compare bar** at the bottom of the tab runs the same two-independent-syntheses side-by-side view as the Zacks tab (shared `compareTickers`, just pointed at the B tab's inputs) — works for any two tickers.
- The composite is also computed **live for any single ticker in the Analyze / Compare view** (`opportunities_b.score_ticker`, surfaced as `opp_b_score`) — so you can see a name's B score even if it's outside the top 20 or isn't S&P 500 at all, since the score depends only on conviction/beats/drift, not list membership. The column headers carry hover ⓘ tooltips explaining each part of the score.
- **Score formula** (0–100): `45% conviction + 45% earnings-beats + 10% opinion-drift`, where conviction = `(2·StrongBuy + Buy) / (2·analysts)`, beats = fraction of last 4 quarters beaten, drift = 4-month change in the analyst average (centered at 0.5). It's relative, not a probability.

### Opportunities table (Zacks Rank 1)

A second table below Holdings lists every currently-imported Rank 1 ticker, sortable by Ticker, Company, Price, 1W %, 4W %, EPS Est Δ, or Consensus — click a header same as the holdings table. **No pick is asserted or ranked by the tool** — this surfaces the data so you apply your own judgment about which lens (momentum, improving estimates, analyst sentiment) matters for a given decision. This is a deliberate design line, same principle as the exit-plan/stop-hit alert: an LLM outputting "buy this one, it has the best potential" against real money is functionally investment advice regardless of how it's framed, so that's not something this tool does.

- **Refresh consensus** button (`POST /api/zacks/refresh-consensus`) fetches Finnhub analyst consensus for every currently Rank-1 ticker — this is a separate, explicit, opt-in action from the CSV import, since it's ~1 API call per ticker with a 1-second delay between calls to respect Finnhub's free-tier rate limit. For ~220 tickers this takes **several minutes**; the button disables itself and shows a wait message while running, and confirms via alert (`Consensus updated for N of M tickers`) when done.
- **Analyze** button per row generates an on-demand, per-ticker prose synthesis (`POST /api/zacks/{ticker}/analyze`) — pulls Zacks metrics, analyst consensus, recent earnings history, next earnings date, insider transactions, recent news, and Alpha Vantage news sentiment, and asks Claude to connect the signals, flag where they agree or conflict, and note risk context (e.g. an upcoming earnings date). Never a directive "buy/sell" call or a ranking — see `docs/plans/synthesized-stock-analysis.md` for the full design and the exact prompt boundary. Costs a few cents per call, pay-as-you-go against your own Anthropic API key.
- **Compare** bar (bottom of the Opportunities panel) runs the same analysis independently for two tickers and shows them side by side — two separate Claude calls that never see each other, specifically to avoid the model ever producing a comparative verdict ("X is better than Y"). Works for any ticker Finnhub covers, not just ones in the current Zacks import.

```bash
# same commands as above, just the other Label:
launchctl load ~/Library/LaunchAgents/com.tradingtool.zackswatch.plist
launchctl list | grep tradingtool
launchctl unload ~/Library/LaunchAgents/com.tradingtool.zackswatch.plist
```

Note: `WatchPaths` fires on *any* change to `~/Downloads`, not just Zacks files — the script itself is a fast no-op unless a matching CSV actually changed, but it does wake up somewhat often if you download things frequently.

### Field definitions

- **Buy in**: what you paid per share at purchase. Historical record only.
- **Stop loss**: the real stop-loss price you have set at your broker. The app only tracks what you tell it; it doesn't place or move real orders — actual downside protection is your broker's live order.
- **Trailing high**: the high-water mark used to decide when to raise your stop — only moves when you Confirm a triggered breakout (≥10% above it). Deliberately *not* the live price, since a real trailing stop should only ratchet up, never loosen on a down day.
- **Current price**: the freshest known price, from Refresh. Drives the Total column.
- **Trailing %**: derived as `(trailing_high - stop_loss) / trailing_high` — not a fixed constant, just happens to be ~10% for all current holdings because that's the distance chosen at entry.
- **Exit plan**: your own pre-committed decision for what to do if this holding gets stopped out — *Sell all*, *Sell gains only*, or *Hold / reassess*. Set in advance, surfaced (not decided) when the stop-loss alert fires.

### Known gaps

- **No ticker validation.** Whatever you type is stored as-is (uppercased). If Finnhub can't find a price for it, Refresh will show an error for that row (e.g. it once caught a typo: "MIU" → should have been "MU").
- **Price is an approximation, not TR's exact quote.** There's no free API for Trade Republic's exact LS-Exchange EUR price on US-listed stocks, so this converts a US-exchange USD quote via the live ECB USD/EUR rate. Very close in practice, but not penny-perfect.
- **Estimated tax doesn't account for Sparerpauschbetrag used elsewhere this year**, or losses offsetting other gains — it's a simple 26.375% on the gain portion only, meant as a quick estimate, not a filing-accurate number.
- **Multi-lot holdings**: a stock bought across multiple purchases is entered as a single row with an averaged cost basis and one purchase date, not one row per lot. Fine for trailing-stop tracking, but will misstate the taxable gain on a partial sale, since German capital gains tax uses FIFO per lot. Deferred to the tax-lot-awareness milestone (needs a data model change: splitting the stop-tracking "holding" from a list of lots underneath it).

## Not yet built

- Full decision-support layer (earnings surprise history, estimate revisions — analyst consensus counts and Zacks Rank are in, the rest isn't)
- Decumulation model
- Watchlist (candidates you don't yet hold — Zacks Rank import + live price/consensus infrastructure already supports this, just needs a UI)
- Position sizing, spread-cost estimator, concentration checks, tax-lot awareness (ported from the original claude.ai artifact)

See `~/Downloads/trading-tool-project-brief.md` for full context and figures.
