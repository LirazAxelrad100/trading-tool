const API = "/api/holdings";

async function fetchHoldings() {
  const res = await fetch(API);
  return res.json();
}

// Hover tooltips for the ⓘ header icons. The tooltip is position:fixed (so the
// table's overflow container can't clip it); we place it under the icon and clamp
// it inside the viewport on each hover.
function initInfoTooltips() {
  for (const info of document.querySelectorAll(".info")) {
    const tip = info.querySelector(".tooltip");
    if (!tip || info.dataset.tipInit) continue;
    info.dataset.tipInit = "1";
    const show = () => {
      tip.style.display = "block";
      const r = info.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = Math.min(r.left, window.innerWidth - tw - 8);
      tip.style.left = Math.max(8, left) + "px";
      tip.style.top = r.bottom + 6 + "px";
    };
    const hide = () => (tip.style.display = "none");
    info.addEventListener("mouseenter", show);
    info.addEventListener("mouseleave", hide);
    info.addEventListener("focus", show);
    info.addEventListener("blur", hide);
  }
}

const euFormat = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const euPctFormat = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function fmt(n) {
  return euFormat.format(Number(n));
}

function fmtPct(n) {
  return euPctFormat.format(n * 100) + "%";
}

const euSharesFormat = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 8 });
function fmtShares(n) {
  return euSharesFormat.format(Number(n));
}

// Pre-fill a numeric text input in EU form (comma decimal, no grouping) so what
// the user sees round-trips cleanly through parseEuNumber on save.
function toEuInput(n) {
  return n == null || n === "" ? "" : String(n).replace(".", ",");
}

const EXIT_PLAN_LABELS = {
  hold: "Hold / reassess",
  sell_gains_only: "Sell gains only",
  sell_all: "Sell all",
};

function dayChangeClass(pct) {
  if (pct == null) return "";
  if (pct > 0) return "price-up";
  if (pct < 0) return "price-down";
  return "";
}

function fmtDayChangePct(pct) {
  return pct == null ? "—" : fmtPct(pct);
}

function consensusLabel(avg) {
  if (avg == null) return "No data";
  if (avg <= 1.5) return "Strong Buy";
  if (avg <= 2.5) return "Buy";
  if (avg <= 3.5) return "Hold";
  if (avg <= 4.5) return "Sell";
  return "Strong Sell";
}

let lastHoldings = [];
let zacksRanks = {};
let weeklyTableWeeksShown = 10;

function zacksCell(h) {
  const entry = zacksRanks[h.ticker];
  const rankPart =
    entry == null ? "—" : entry.rank === 1 ? `<span class="zacks-rank-1">1</span>` : String(entry.rank);
  const avgPart = h.consensus_avg != null ? h.consensus_avg.toFixed(2) : "—";
  return `${rankPart} / ${avgPart}`;
}

async function loadZacksStatus() {
  const res = await fetch("/api/zacks");
  const data = await res.json();
  zacksRanks = data.ranks || {};
  const statusEl = document.getElementById("zacks-status");
  if (data.last_imported_at) {
    const d = new Date(data.last_imported_at);
    const dateStr = d.toLocaleDateString("de-DE");
    const timeStr = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    statusEl.textContent = `Zacks: ${Object.keys(zacksRanks).length} tickers, last import ${dateStr} ${timeStr} (${data.last_source_file})`;
  } else {
    statusEl.textContent = "Zacks: no data imported yet";
  }
  renderOpportunities();
}

let oppSortField = "ticker";
let oppSortDir = 1;

function oppSortBy(field) {
  if (oppSortField === field) {
    oppSortDir *= -1;
  } else {
    oppSortField = field;
    oppSortDir = 1;
  }
  renderOpportunities();
}

function oppFmt(v) {
  return v == null ? "—" : fmt(v);
}

function oppFmtPctRaw(v) {
  return v == null ? "—" : euPctFormat.format(v) + "%";
}

function coloredPct(v) {
  if (v == null) return "—";
  const cls = v > 0 ? "price-up" : v < 0 ? "price-down" : "";
  return `<span class="${cls}">${oppFmtPctRaw(v)}</span>`;
}

function renderOpportunities() {
  const rows = Object.entries(zacksRanks)
    .filter(([, entry]) => entry.rank === 1)
    .map(([ticker, entry]) => ({ ticker, ...entry }));

  rows.sort((a, b) => {
    let av = a[oppSortField];
    let bv = b[oppSortField];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string") {
      av = av.toLowerCase();
      bv = bv.toLowerCase();
    }
    if (av < bv) return -1 * oppSortDir;
    if (av > bv) return 1 * oppSortDir;
    return 0;
  });

  for (const field of ["ticker", "company", "price", "price_move_1w", "price_move_4w", "eps_est_change_4w", "consensus_avg"]) {
    const el = document.getElementById(`opp-arrow-${field}`);
    if (!el) continue;
    el.textContent = field === oppSortField ? (oppSortDir === 1 ? "▲" : "▼") : "";
  }

  const body = document.getElementById("opportunities-body");
  const emptyMsg = document.getElementById("opp-empty-msg");
  body.innerHTML = "";
  emptyMsg.style.display = rows.length === 0 ? "block" : "none";

  for (const r of rows) {
    const tr = document.createElement("tr");
    const consensusText = r.consensus_avg != null ? `${r.consensus_avg.toFixed(2)} (${consensusLabel(r.consensus_avg)})` : "—";
    tr.innerHTML = `
      <td><span class="ticker-name" onclick="showConsensusByTicker('${r.ticker}')">${r.ticker}</span></td>
      <td>${r.company || "—"}</td>
      <td>${r.industry || "—"}</td>
      <td>${oppFmt(r.price)}</td>
      <td class="${r.price_move_1w > 0 ? "price-up" : r.price_move_1w < 0 ? "price-down" : ""}">${oppFmtPctRaw(r.price_move_1w)}</td>
      <td class="${r.price_move_4w > 0 ? "price-up" : r.price_move_4w < 0 ? "price-down" : ""}">${oppFmtPctRaw(r.price_move_4w)}</td>
      <td>${oppFmtPctRaw(r.eps_est_change_4w)}</td>
      <td>${r.vgm_score || "—"}</td>
      <td>${consensusText}</td>
      <td><button class="secondary" onclick="analyzeTicker('${r.ticker}')">Analyze</button></td>
    `;
    body.appendChild(tr);
  }
}

async function refreshOppConsensus() {
  const btn = document.getElementById("opp-consensus-btn");
  btn.disabled = true;
  btn.textContent = "Refreshing consensus… this takes a few minutes";
  try {
    const res = await fetch("/api/zacks/refresh-consensus", { method: "POST" });
    const result = await res.json();
    await loadZacksStatus();
    alert(`Consensus updated for ${result.updated} of ${result.total} tickers (${result.errors.length} failed to fetch).`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh consensus (~4 min)";
  }
}

async function uploadZacksFile(file) {
  if (!file) return;
  const btn = document.getElementById("zacks-import-btn");
  btn.disabled = true;
  btn.textContent = "Importing…";
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/zacks/upload", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Failed to import Zacks CSV.");
      return;
    }
    const result = await res.json();
    await loadZacksStatus();
    await render();
    alert(
      `Imported ${result.imported_count} tickers from ${result.source_file}.\n` +
        `${result.added_count} new, ${result.removed_count} dropped off the list. ` +
        `Consensus data is kept for tickers that stayed.`
    );
  } finally {
    btn.disabled = false;
    btn.textContent = "Import Zacks CSV";
    document.getElementById("zacks-file-input").value = "";
  }
}

function buildPriceChartSVG(priceHistory, changePct) {
  const closes = priceHistory.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const w = 400;
  const h = 100;
  const stepX = closes.length > 1 ? w / (closes.length - 1) : 0;
  const points = closes.map((c, i) => {
    const x = i * stepX;
    const y = h - ((c - min) / range) * h;
    return [x, y];
  });
  const isUp = changePct >= 0;
  const color = isUp ? "var(--green)" : "var(--rust)";
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L ${w} ${h} L 0 ${h} Z`;

  return `
    <svg viewBox="0 0 ${w} ${h}" class="price-chart-svg" preserveAspectRatio="none">
      <path d="${areaPath}" fill="${color}" opacity="0.15" stroke="none"></path>
      <path d="${linePath}" fill="none" stroke="${color}" stroke-width="2"></path>
    </svg>
  `;
}

async function loadPriceChart(containerId, ticker) {
  const container = document.getElementById(containerId);
  try {
    const res = await fetch(`/api/prices/${ticker}/history?days=30`);
    if (!res.ok) {
      const err = await res.json();
      container.innerHTML = `<p class="empty">${err.detail || "Chart unavailable."}</p>`;
      return;
    }
    const result = await res.json();
    const latest = result.prices[result.prices.length - 1].close;
    const changeClass = result.change_pct >= 0 ? "price-up" : "price-down";
    container.innerHTML = `
      <div class="price-chart-header">
        <strong>${fmt(latest)}</strong>
        <span class="${changeClass}">${result.change_pct >= 0 ? "+" : ""}${oppFmtPctRaw(result.change_pct)}</span>
        <span class="subtitle">past ${result.prices.length} trading days</span>
      </div>
      ${buildPriceChartSVG(result.prices, result.change_pct)}
    `;
  } catch (e) {
    container.innerHTML = `<p class="empty">Chart unavailable: ${e}</p>`;
  }
}

async function loadBreadth() {
  const container = document.getElementById("breadth");
  if (!container) return;
  try {
    const res = await fetch("/api/breadth");
    if (!res.ok) throw new Error((await res.json()).detail || "unavailable");
    renderBreadth(await res.json());
  } catch (e) {
    container.innerHTML = `<p class="empty">Breadth data unavailable: ${e.message || e}</p>`;
  }
}

let lastBreadth = null;

function renderBreadth(b) {
  lastBreadth = b;
  const container = document.getElementById("breadth");
  // 50% is the natural dividing line: below it, more stocks are falling than rising against
  // that average, whatever the index itself is doing.
  const narrow = b.above_50d < 50;
  const shrinking = b.above_50d < b.above_50d_prev;
  const reading = narrow
    ? "So fewer than half of stocks are rising, and recent index gains are being carried by a minority of large names rather than the market as a whole."
    : shrinking
    ? "So most stocks are still rising, but fewer than a month ago — the advance is getting narrower."
    : "So gains are broadly shared rather than concentrated in a few names.";

  container.innerHTML = `
    <p>A stock trading above its own average price of the last 50 days has been rising lately; below it, falling. Counting how many are on each side says whether a market rise is shared or carried by a few.</p>
    <table class="mini-table"><tbody>
      <tr><td>Rising lately (above their 50-day average)</td>
          <td><strong>${fmtPct(b.above_50d / 100)}</strong> of US stocks</td>
          <td class="subtitle">was ${fmtPct(b.above_50d_prev / 100)} a month ago</td></tr>
      <tr><td>Rising over the longer run (above their 200-day average)</td>
          <td><strong>${fmtPct(b.above_200d / 100)}</strong></td>
          <td class="subtitle">was ${fmtPct(b.above_200d_prev / 100)} a month ago</td></tr>
    </tbody></table>
    <p>${reading}</p>
    <p class="subtitle">As of ${b.as_of}, compared with ${b.compared_with}. Third-party public data (TraderMonty), fetched once a day — it lags by a day or two and could stop updating, so check the date if it looks frozen.</p>`;
}

async function loadConcentration() {
  const container = document.getElementById("concentration");
  if (!container) return;
  try {
    const res = await fetch("/api/concentration");
    renderConcentration(await res.json());
  } catch (e) {
    container.innerHTML = `<p class="empty">Unavailable: ${e}</p>`;
  }
}

let lastConcentration = null;

function renderConcentration(c) {
  lastConcentration = c;
  const container = document.getElementById("concentration");
  if (!c || c.error) {
    container.innerHTML = `<p class="empty">${c && c.error ? c.error : "No data yet."}</p>`;
    return;
  }
  const parts = [];

  for (const g of c.groups) {
    // A weak weakest-link means the bloc was chained together through a middle holding
    // rather than every member moving with every other — worth saying rather than hiding.
    const loose = g.min_correlation < 0.4;
    parts.push(`
      <div class="tensions">
        <strong>${g.tickers.join(" · ")} — ${fmtPct(g.weight_pct / 100)} of the portfolio</strong>
        <p>These have risen and fallen together over the period (average correlation ${fmt(
          g.avg_correlation
        )}${loose ? `, but as low as ${fmt(g.min_correlation)} for one pair` : ""}). A single piece of news that moves one is likely to move the rest, so they behave more like one position of ${fmtPct(
      g.weight_pct / 100
    )} than ${g.tickers.length} separate ones.</p>
      </div>`);
  }

  const dd = c.down_days;
  if (dd) {
    parts.push(`
      <p><strong>On the ${dd.days_used} worst days</strong> (portfolio averaged ${fmtPct(
      dd.portfolio_avg_pct / 100
    )} on those days) — day-to-day independence matters least exactly when things fall together, so this is the harder test:</p>
      <table class="mini-table"><tbody>${dd.holdings
        .map(
          (r) =>
            `<tr><td>${r.ticker}</td><td>${coloredPct(r.avg_return_pct)}</td><td class="subtitle">fell on ${
              r.fell_on
            } of ${r.of_days}</td></tr>`
        )
        .join("")}</tbody></table>`);
  }

  if (c.independent.length) {
    parts.push(
      `<p><strong>Moving on their own:</strong> ${c.independent
        .map((s) => `${s.ticker} (${fmtPct(s.weight_pct / 100)})`)
        .join(" · ")}</p>`
    );
  }
  if (c.excluded.length) {
    parts.push(
      `<p class="subtitle">Not included: ${c.excluded
        .map((e) => `${e.ticker} — ${e.reason}`)
        .join(" · ")}. Buying or selling changes a holding's recorded value without the price moving, which would look like a huge one-day swing.</p>`
    );
  }
  parts.push(
    `<p class="subtitle">Based on ${c.returns} days of recorded values (${c.from_date} to ${c.to_date}). That is a short run, so treat single pairs as tentative — a group is more trustworthy when several holdings agree. It gets steadier as more days are recorded.</p>`
  );
  container.innerHTML = parts.join("");
}

async function loadPortfolioChart() {
  const container = document.getElementById("portfolio-chart");
  if (!container) return;
  try {
    const res = await fetch("/api/portfolio-history");
    renderPortfolioChart(await res.json());
  } catch (e) {
    container.innerHTML = `<p class="empty">Chart unavailable: ${e}</p>`;
  }
}

function renderPortfolioChart(points) {
  const container = document.getElementById("portfolio-chart");
  if (!points || points.length === 0) {
    container.innerHTML = `<p class="empty">No history yet. Click "Load past ~3 months" for an approximate line — and it records a real point each day you refresh.</p>`;
    return;
  }
  if (points.length === 1) {
    container.innerHTML = `<p class="empty">One point so far: ${fmt(points[0].value)} on ${points[0].date}. The line grows each day you refresh — or "Load past ~3 months" to seed an approximate history now.</p>`;
    return;
  }
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const w = 600;
  const h = 140;
  const stepX = w / (points.length - 1);
  const coords = values.map((v, i) => [i * stepX, h - ((v - min) / range) * h]);
  const first = values[0];
  const last = values[values.length - 1];
  const changePct = ((last - first) / first) * 100;
  const up = last >= first;
  const color = up ? "var(--green)" : "var(--rust)";
  const linePath = coords.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L ${w} ${h} L 0 ${h} Z`;
  const anyApprox = points.some((p) => p.approx);
  container.innerHTML = `
    <div class="price-chart-header">
      <strong>${fmt(last)} EUR</strong>
      <span class="${up ? "price-up" : "price-down"}">${changePct >= 0 ? "+" : ""}${euPctFormat.format(changePct)}%</span>
      <span class="subtitle">${points[0].date} → ${points[points.length - 1].date}${anyApprox ? " · early points are approximate" : ""}</span>
    </div>
    <svg viewBox="0 0 ${w} ${h}" class="price-chart-svg" preserveAspectRatio="none">
      <path d="${areaPath}" fill="${color}" opacity="0.15" stroke="none"></path>
      <path d="${linePath}" fill="none" stroke="${color}" stroke-width="2"></path>
    </svg>`;
}

function isoWeekStart(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const day = (d.getDay() + 6) % 7; // Mon=0 .. Sun=6
  d.setDate(d.getDate() - day);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function aggregateWeekly(points) {
  // Keeps the latest-dated point within each week (Mon-start) as that week's value.
  const byWeek = new Map();
  for (const p of points) {
    const week = isoWeekStart(p.date);
    const existing = byWeek.get(week);
    if (!existing || p.date > existing.date) byWeek.set(week, p);
  }
  return byWeek;
}

async function loadWeeklyTable() {
  const container = document.getElementById("weekly-table-container");
  if (!container) return;
  try {
    const [totalRes, perStockRes] = await Promise.all([
      fetch("/api/portfolio-history"),
      fetch("/api/holdings-history"),
    ]);
    renderWeeklyTable(await totalRes.json(), await perStockRes.json());
  } catch (e) {
    container.innerHTML = `<p class="empty">Weekly table unavailable: ${e}</p>`;
  }
}

function weeklyChangeClass(current, previous) {
  if (!current || !previous) return "";
  if (current.value > previous.value) return "price-up";
  if (current.value < previous.value) return "price-down";
  return "";
}

function weekRangeLabel(weekStartStr) {
  const start = new Date(weekStartStr + "T00:00:00");
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const opts = { day: "2-digit", month: "2-digit" };
  return `${start.toLocaleDateString("de-DE", opts)} – ${end.toLocaleDateString("de-DE", opts)}`;
}

function renderWeeklyTable(totalPoints, perStockPoints) {
  const container = document.getElementById("weekly-table-container");
  if (!totalPoints || totalPoints.length === 0) {
    container.innerHTML = `<p class="empty">No history yet — builds up as you refresh each day.</p>`;
    return;
  }

  const totalByWeek = aggregateWeekly(totalPoints);
  const tickers = [...new Set(lastHoldings.map((h) => h.ticker))];
  const perTickerByWeek = {};
  for (const t of tickers) {
    perTickerByWeek[t] = aggregateWeekly(perStockPoints.filter((p) => p.ticker === t));
  }

  const allWeeks = [...totalByWeek.keys()].sort().reverse();
  const weeks = allWeeks.slice(0, weeklyTableWeeksShown);

  let html = `<div class="table-scroll"><table class="weekly-table"><thead><tr><th>Week (Mon–Sun)</th><th>Total</th>`;
  for (const t of tickers) html += `<th>${t}</th>`;
  html += `</tr></thead><tbody>`;

  for (let i = 0; i < weeks.length; i++) {
    const w = weeks[i];
    const isLatest = i === 0;
    const prevWeek = allWeeks[i + 1];
    const totalP = totalByWeek.get(w);
    const totalClass = isLatest ? weeklyChangeClass(totalP, prevWeek && totalByWeek.get(prevWeek)) : "";
    html += `<tr><td>${weekRangeLabel(w)}</td><td class="${totalClass}"><strong>${totalP ? fmt(totalP.value) : "–"}</strong></td>`;
    for (const t of tickers) {
      const p = perTickerByWeek[t].get(w);
      const cellClass = isLatest ? weeklyChangeClass(p, prevWeek && perTickerByWeek[t].get(prevWeek)) : "";
      html += `<td class="${cellClass}">${p ? fmt(p.value) : "–"}</td>`;
    }
    html += `</tr>`;
  }

  html += `</tbody></table></div>`;
  if (allWeeks.length > weeklyTableWeeksShown) {
    html += `<button class="secondary" onclick="showMoreWeeklyRows()">Show more weeks</button>`;
  }
  html += `<p class="subtitle">Per-stock history started 2026-08-15 — older weeks fill in with "–" until enough days accumulate.</p>`;
  container.innerHTML = html;
}

function showMoreWeeklyRows() {
  weeklyTableWeeksShown += 10;
  loadWeeklyTable();
}

async function seedPortfolioHistory() {
  if (!confirm("Estimate your portfolio's value over the past ~3 months from each holding's price history? It uses ~10 of your 25 daily Alpha Vantage calls and is approximate (based on your current holdings, ignoring past buys/sells).")) return;
  const btn = document.getElementById("seed-portfolio-btn");
  btn.disabled = true;
  btn.textContent = "Loading…";
  try {
    const res = await fetch("/api/portfolio-history/seed", { method: "POST" });
    if (!res.ok) {
      alert((await res.json()).detail || "Failed to load history.");
      return;
    }
    const data = await res.json();
    await loadPortfolioChart();
    await loadConcentration();
    await loadBreadth();
    alert(`Added ${data.seeded} approximate past points.`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Load past ~3 months (approx)";
  }
}

function renderConsensusModal(ticker, consensus, noDataHint) {
  const modal = document.getElementById("consensus-modal");
  const body = document.getElementById("consensus-modal-body");
  document.getElementById("consensus-modal-title").textContent = ticker;

  const consensusSection = consensus
    ? `
      <p class="total-line">Average rating: <strong>${consensus.average.toFixed(2)}</strong> (${consensusLabel(consensus.average)})</p>
      <p class="subtitle">Scale: 1 = Strong Buy, 5 = Strong Sell. Period: ${consensus.period}.</p>
      <table class="consensus-table">
        <tr><td>Strong buy</td><td>${consensus.strong_buy}</td></tr>
        <tr><td>Buy</td><td>${consensus.buy}</td></tr>
        <tr><td>Hold</td><td>${consensus.hold}</td></tr>
        <tr><td>Sell</td><td>${consensus.sell}</td></tr>
        <tr><td>Strong sell</td><td>${consensus.strong_sell}</td></tr>
      </table>
    `
    : `<p class="empty">${noDataHint}</p>`;

  body.innerHTML = `
    <div id="price-chart-container"><p class="empty">Loading chart…</p></div>
    ${consensusSection}
  `;
  modal.style.display = "flex";
  loadPriceChart("price-chart-container", ticker);
}

function showConsensus(id) {
  const h = lastHoldings.find((x) => x.id === id);
  renderConsensusModal(
    h ? h.ticker : "",
    h ? h.consensus : null,
    "No analyst consensus data yet — click Refresh on this holding first."
  );
}

function showConsensusByTicker(ticker) {
  const entry = zacksRanks[ticker];
  renderConsensusModal(
    ticker,
    entry ? entry.consensus : null,
    "No analyst consensus data yet — click Refresh consensus above first."
  );
}

function closeConsensusModal() {
  document.getElementById("consensus-modal").style.display = "none";
}

// Total cell colored by unrealized gain/loss (current value vs. what you paid).
function gainClass(h) {
  const cost = h.shares * h.cost_basis;
  return h.total > cost ? "price-up" : h.total < cost ? "price-down" : "";
}

function showUnrealized(id) {
  const h = lastHoldings.find((x) => x.id === id);
  if (!h) return;
  const invested = h.shares * h.cost_basis;
  const gain = h.total - invested;
  const pct = invested ? (gain / invested) * 100 : 0;
  const cls = gain >= 0 ? "price-up" : "price-down";
  document.getElementById("unrealized-title").textContent = `${h.ticker} — unrealized ${gain >= 0 ? "gain" : "loss"}`;
  document.getElementById("unrealized-body").innerHTML = `
    <table class="consensus-table">
      <tr><td>Avg buy-in</td><td>${fmt(h.cost_basis)} EUR</td></tr>
      <tr><td>Invested (${fmtShares(h.shares)} shares)</td><td>${fmt(invested)} EUR</td></tr>
      <tr><td>Current value</td><td>${fmt(h.total)} EUR</td></tr>
      <tr><td>Unrealized ${gain >= 0 ? "gain" : "loss"}</td><td class="${cls}"><strong>${fmt(gain)} EUR (${pct >= 0 ? "+" : ""}${euPctFormat.format(pct)}%)</strong></td></tr>
    </table>
    <p class="subtitle">Based on the current price ${fmt(h.current_price)} from the last refresh${h.manual_price ? " (manual)" : ""}.</p>`;
  document.getElementById("unrealized-modal").style.display = "flex";
}

function closeUnrealizedModal() {
  document.getElementById("unrealized-modal").style.display = "none";
}

function fmtScore(s) {
  return s || "—";
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Escape first (the analysis is model output injected via innerHTML), then render
// **bold** lead-ins. Paragraph breaks are kept by .analysis-text's white-space: pre-wrap.
function renderAnalysisText(s) {
  return escapeHtml(s || "").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function renderSignalsTable(m) {
  if (!m) return "";
  const cons = m.consensus;
  const consLine = cons
    ? `${cons.strong_buy} SB · ${cons.buy} B · ${cons.hold} H · ${cons.sell} S · ${cons.strong_sell} SS <span class="subtitle">(${consensusLabel(cons.average)})</span>`
    : "—";
  const surprises =
    m.recent_surprises && m.recent_surprises.length
      ? m.recent_surprises.map((s) => coloredPct(s.surprise_percent)).join(" · ")
      : "—";
  const projGrowth =
    m.earnings_growth_1y != null
      ? `${oppFmtPctRaw(m.earnings_growth_1y)} <span class="subtitle">(forecast)</span>`
      : "—";
  return `
    <table class="consensus-table signals-table">
      <tr><td>Zacks Rank</td><td>${m.zacks_rank ?? "—"}</td></tr>
      <tr><td>Price 1W / 4W</td><td>${coloredPct(m.price_move_1w)} / ${coloredPct(m.price_move_4w)}</td></tr>
      <tr><td>EPS est. revision (4W)</td><td>${coloredPct(m.eps_est_change_4w)}</td></tr>
      <tr><td>Proj. 1-yr earnings growth</td><td>${projGrowth}</td></tr>
      <tr><td>VGM (V / G / M)</td><td>${fmtScore(m.vgm_score)} <span class="subtitle">(${fmtScore(m.value_score)} / ${fmtScore(m.growth_score)} / ${fmtScore(m.momentum_score)})</span></td></tr>
      <tr><td>Consensus</td><td>${consLine}</td></tr>
      <tr><td>Recent EPS surprises</td><td>${surprises}</td></tr>
      <tr><td>Next earnings</td><td>${m.next_earnings || "—"}</td></tr>
    </table>
  `;
}

function renderContradictions(list) {
  if (!list || list.length === 0) {
    return `<p class="subtitle">No major contradictions among these signals.</p>`;
  }
  return `
    <div class="tensions">
      <strong>⚠ Tensions to note</strong>
      <ul>${list.map((c) => `<li>${c}</li>`).join("")}</ul>
    </div>
  `;
}

function renderOppBScore(s) {
  if (!s) {
    return `<div class="oppb-score"><strong>Opportunities B score: —</strong> <span class="subtitle">not enough analyst coverage to score</span></div>`;
  }
  const driftSym = s.drift > 0 ? "▲ improving" : s.drift < 0 ? "▼ cooling" : "flat";
  const beats = s.beats != null ? `${s.beats}/${s.beats_total}` : "—";
  return `
    <div class="oppb-score">
      <strong>Opportunities B score: ${Math.round(s.composite * 100)}</strong>
      <span class="subtitle">conviction ${s.conviction.toFixed(2)} · beats ${beats} · drift ${driftSym} — the same conviction+beats+drift lens as the B list, computed live for this ticker (not a verdict).</span>
    </div>`;
}

function renderSectorContext(sc) {
  if (!sc) return "";
  if (sc.rank == null) {
    return `<div class="sector-context"><strong>Sector:</strong> ${sc.sector} <span class="subtitle">— sector strength not computed yet (Refresh sectors in Opportunities B)</span></div>`;
  }
  const cls = sc.standing === "leading" ? "price-up" : sc.standing === "lagging" ? "price-down" : "";
  return `
    <div class="sector-context">
      <strong>Sector:</strong> ${sc.sector} — <span class="${cls}">#${sc.rank} of ${sc.total} by 3-month momentum (${sc.standing})</span>
      <span class="subtitle">sector 3M ${fmtPct(sc.ret_3m)} · 1M ${fmtPct(sc.ret_1m)} — is the stock swimming with or against its sector's tide?</span>
    </div>`;
}

function renderRisk(v) {
  if (!v || v.error) {
    return `<div class="risk-badge"><strong>Volatility: —</strong> <span class="subtitle">${v && v.error ? v.error : "not enough price history"}</span></div>`;
  }
  const cls = v.label === "Low" ? "price-up" : v.label === "Very high" || v.label === "High" ? "price-down" : "";
  return `
    <div class="risk-badge">
      <strong>Volatility: <span class="${cls}">${v.label}</span></strong>
      <span class="subtitle">${fmtPct(v.annualized_pct / 100)} a year — based on how much the price has been swinging day to day over the last ${v.days_used} trading days, scaled up to a yearly figure so it's easier to compare across stocks. Looks backward only, not a prediction.</span>
    </div>`;
}

function renderMomentum(m) {
  if (!m || m.error) {
    return `<div class="risk-badge"><strong>Today's momentum: —</strong> <span class="subtitle">${m && m.error ? m.error : "no recent price data"}</span></div>`;
  }
  const LABELS = {
    burst: "Sharp move up today",
    extended: "Already extended",
    "sharp drop": "Sharp fall today",
    quiet: "No burst signal",
  };
  let label = LABELS[m.state] || "No burst signal";
  let cls = m.state === "burst" ? "price-up" : m.state === "quiet" ? "" : "price-down";
  if (m.state === "burst" && m.trend === "downtrend") {
    label = "Bounce inside a downtrend";
    cls = "price-down";
  } else if (m.state === "burst" && m.trend === "uptrend") {
    label = "Sharp move up, in an uptrend";
  }

  const facts = [];
  if (m.day_change_pct != null) facts.push(`today ${fmtPct(m.day_change_pct / 100)}`);
  if (m.run_up_5d_pct != null) facts.push(`5 days ${fmtPct(m.run_up_5d_pct / 100)}`);
  if (m.volume_elevation != null) facts.push(`10-day volume ${fmt(m.volume_elevation)}× the 3-month average`);
  if (m.close_location != null)
    facts.push(`closed ${Math.round(m.close_location * 100)}% up the day's range`);
  if (m.pct_from_52w_high != null) facts.push(`${fmtPct(m.pct_from_52w_high / 100)} from its 52-week high`);

  const NOTES = {
    extended:
      "A move this size in a week means much of it has already happened — the question is whether you'd be arriving early or late, not whether it's rising.",
    burst:
      "A sharp up-day on heavier-than-usual volume. That describes what just happened, not what happens next.",
    "sharp drop":
      "A sharp fall today. Worth knowing why before reading anything else here — a drop can follow news that changes the picture entirely.",
    quiet: "Nothing unusual in the recent price or volume — trading in its normal range.",
  };
  let note = NOTES[m.state] || NOTES.quiet;
  if (m.state === "burst" && m.trend === "downtrend") {
    note =
      "A sharp up-day, but the stock is falling over the longer run — so this is a bounce within a decline rather than a fresh breakout. The two are easy to confuse on a single green day.";
  } else if (m.state === "burst" && m.trend === "uptrend") {
    note =
      "A sharp up-day in a stock that was already climbing and trades near its 52-week high. That describes what just happened, not what happens next.";
  }

  return `
    <div class="risk-badge">
      <strong>Today's momentum: <span class="${cls}">${label}</span></strong>
      <span class="subtitle">${facts.join(" · ")}. ${note}</span>
    </div>`;
}

// Below this the multiple hasn't meaningfully moved — the market pays about what it did.
const MULTIPLE_FLAT_PCT = 10;

function fundamentalsLabel(f) {
  // "Profits" rather than "earnings" throughout: same thing, but one of them is a word
  // outside finance too. The sign-only quadrant is also too crude when both are positive —
  // FN was price +9% against profits +42%, technically "both rising" while the valuation
  // fell 23% — so when both rise, the valuation change decides which outran which.
  if (f.quadrant === "divergence") return "Price fell while profits grew";
  if (f.quadrant === "both_falling") return "Price and profits both falling";
  if (f.quadrant === "multiple_expansion") return "Price rose while profits fell";
  const mc = f.multiple_change_pct;
  if (f.eps_base_distorted) return "Profits rebounding from a low base";
  if (mc == null || Math.abs(mc) < MULTIPLE_FLAT_PCT) return "Price and profits moved together";
  return mc < 0 ? "Profits grew faster than the price" : "Price rose faster than profits";
}

function renderFundamentals(f) {
  if (!f || f.error) {
    return `<div class="risk-badge"><strong>Price vs. profits: —</strong> <span class="subtitle">${
      f && f.error ? f.error : "no profit figures available for this company"
    }</span></div>`;
  }
  const cls = f.quadrant === "both_falling" ? "price-down" : f.quadrant === "divergence" ? "price-up" : "";
  const pct = (v) => fmtPct(v / 100);

  // Deliberately short: the year's price move, the year's profit move, what that does to
  // what investors pay, and how far the price is off its high. Sales growth, the P/E and
  // the beat record were dropped — the beat record already appears in the signals table
  // above, and the rest was reference detail crowding out the one comparison this exists
  // to make.
  const sentences = [];
  if (f.price_12m_pct != null && f.eps_growth_pct != null) {
    sentences.push(
      `Over the past year the share price moved ${pct(f.price_12m_pct)} while profit per share moved ${pct(
        f.eps_growth_pct
      )}.`
    );
  }
  if (f.price_3m_pct != null)
    sentences.push(`Over the past 3 months the share price moved ${pct(f.price_3m_pct)}.`);

  const mc = f.multiple_change_pct;
  const dd = f.pct_from_52w_high;
  if (f.eps_base_distorted) {
    sentences.push(
      "Profit grew so steeply that it is rebounding from a very low base rather than expanding, which makes comparing price against profit unreliable here."
    );
  } else if (mc != null) {
    const flat = Math.abs(mc) < MULTIPLE_FLAT_PCT;
    sentences.push(
      flat
        ? "So investors pay about what they did a year ago for the same profit."
        : `So investors now pay ${pct(Math.abs(mc))} ${mc > 0 ? "more" : "less"} for the same profit than a year ago.`
    );
    // Two different situations need different readings, and only the falling one is about a
    // recovery. A stock that has risen needs the opposite point: how much of the gain came
    // from the business earning more, and how much from the market simply paying more.
    if (dd != null && dd <= -25) {
      sentences.push(
        flat
          ? `The share price is ${pct(Math.abs(dd))} below its 12-month high, so the fall mostly undid an unusually high peak.`
          : mc < 0
          ? `The share price is ${pct(Math.abs(dd))} below its 12-month high — profit grew while the share got cheaper, the mismatch a recovery bet looks for.`
          : `The share price is ${pct(Math.abs(dd))} below its 12-month high and still costs more relative to profit than a year ago.`
      );
    } else if (!flat && mc > 0) {
      sentences.push(
        "Part of the gain is the business earning more and part is the market deciding to pay more for it — and the second half can reverse without the company doing anything wrong."
      );
    } else if (!flat && mc < 0) {
      sentences.push("Profit grew faster than the share price, so the shares are cheaper relative to earnings than a year ago.");
    }
  }

  return `
    <div class="risk-badge">
      <strong>Price vs. profits: <span class="${cls}">${fundamentalsLabel(f)}</span></strong>
      <span class="subtitle">${sentences.join(" ")}${
    f.pct_from_52w_high != null && f.pct_from_52w_high <= -25 ? " It can't say whether a fall is over." : ""
  }</span>
    </div>`;
}

function renderEarningsRisk(er) {
  if (!er || !er.near_earnings) return "";
  if (!er.triggered) {
    return `<p class="subtitle">Earnings in ${er.days_to_earnings} day${er.days_to_earnings === 1 ? "" : "s"} — price/sentiment don't look overheated going in.</p>`;
  }
  return `
    <div class="tensions">
      <strong>⚠ Expectations running hot ahead of earnings</strong>
      <p>Earnings in ${er.days_to_earnings} day${er.days_to_earnings === 1 ? "" : "s"}: price up ${fmtPct(er.price_move_4w / 100)} over the past 4 weeks and news sentiment reads Bullish (avg score ${er.sentiment_score.toFixed(2)}). A beat may already be priced in — historically, when expectations run this hot, even good results don't always move the price.</p>
    </div>`;
}

function renderSignals(result) {
  const sig = result.signals || {};
  return (
    renderOppBScore(result.opp_b_score) +
    renderSectorContext(result.sector_context) +
    renderRisk(result.volatility) +
    renderMomentum(result.momentum) +
    renderFundamentals(result.fundamentals) +
    renderEarningsRisk(sig.earnings_risk) +
    renderSignalsTable(sig.metrics) +
    renderContradictions(sig.contradictions)
  );
}

async function analyzeTicker(ticker) {
  const modal = document.getElementById("analysis-modal");
  const body = document.getElementById("analysis-modal-body");
  document.getElementById("analysis-modal-title").textContent = ticker;
  body.innerHTML = `<p class="empty">Gathering data and generating analysis… this takes a few seconds.</p>`;
  modal.style.display = "flex";

  try {
    const res = await fetch(`/api/zacks/${ticker}/analyze`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      body.innerHTML = `<p class="empty">${err.detail || "Failed to generate analysis."}</p>`;
      return;
    }
    const result = await res.json();
    body.innerHTML = renderSignals(result) + `<p class="analysis-text">${renderAnalysisText(result.analysis)}</p>`;
  } catch (e) {
    body.innerHTML = `<p class="empty">Failed to generate analysis: ${e}</p>`;
  }
}

function closeAnalysisModal() {
  document.getElementById("analysis-modal").style.display = "none";
}

function renderCompareColumn(result) {
  const zacks = result.data_used.zacks || {};
  return `
    <div class="compare-col">
      <h3>${result.ticker}</h3>
      <p class="subtitle">${zacks.company || ""}${zacks.industry ? " · " + zacks.industry : ""}</p>
      ${renderSignals(result)}
      <p class="analysis-text">${renderAnalysisText(result.analysis)}</p>
    </div>
  `;
}

async function compareTickers(aId = "compare-a", bId = "compare-b") {
  const a = document.getElementById(aId).value.trim().toUpperCase();
  const b = document.getElementById(bId).value.trim().toUpperCase();
  if (!a || !b) {
    alert("Enter both tickers to compare.");
    return;
  }
  const modal = document.getElementById("compare-modal");
  const body = document.getElementById("compare-modal-body");
  body.innerHTML = `<p class="empty">Generating independent analysis for both tickers… this takes a few seconds.</p>`;
  modal.style.display = "flex";

  try {
    const res = await fetch(`/api/zacks/compare?a=${a}&b=${b}`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      body.innerHTML = `<p class="empty">${err.detail || "Failed to compare."}</p>`;
      return;
    }
    const result = await res.json();
    body.innerHTML = renderCompareColumn(result.a) + renderCompareColumn(result.b);
  } catch (e) {
    body.innerHTML = `<p class="empty">Failed to compare: ${e}</p>`;
  }
}

function closeCompareModal() {
  document.getElementById("compare-modal").style.display = "none";
}

function exitPlanSelect(id, current) {
  const options = Object.entries(EXIT_PLAN_LABELS)
    .map(([value, label]) => `<option value="${value}" ${value === current ? "selected" : ""}>${label}</option>`)
    .join("");
  return `<select id="e-exitplan-${id}">${options}</select>`;
}

let editingId = null;
let sortField = null;
let sortDir = 1;

function sortBy(field) {
  if (sortField === field) {
    sortDir *= -1;
  } else {
    sortField = field;
    sortDir = 1;
  }
  render();
}

function updateSortArrows() {
  for (const field of ["ticker", "shares", "purchase_date", "total", "portfolio_pct", "day_change_pct"]) {
    const el = document.getElementById(`arrow-${field}`);
    if (!el) continue;
    el.textContent = field === sortField ? (sortDir === 1 ? "▲" : "▼") : "";
  }
}

async function render() {
  const holdings = await fetchHoldings();
  holdings.forEach((h) => (h.total = h.shares * h.current_price));
  const grandTotal = holdings.reduce((sum, h) => sum + h.total, 0);
  holdings.forEach((h) => (h.portfolio_pct = grandTotal ? h.total / grandTotal : 0));
  lastHoldings = holdings;

  if (sortField) {
    holdings.sort((a, b) => {
      let av = a[sortField];
      let bv = b[sortField];
      if (typeof av === "string") {
        av = av.toLowerCase();
        bv = bv.toLowerCase();
      }
      if (av < bv) return -1 * sortDir;
      if (av > bv) return 1 * sortDir;
      return 0;
    });
  }
  updateSortArrows();

  const body = document.getElementById("holdings-body");
  const emptyMsg = document.getElementById("empty-msg");
  body.innerHTML = "";
  emptyMsg.style.display = holdings.length === 0 ? "block" : "none";

  for (const h of holdings) {
    const tr = document.createElement("tr");
    if (h.id === editingId) {
      tr.innerHTML = `
        <td><input id="e-ticker-${h.id}" value="${h.ticker}" /></td>
        ${
          h.lots && h.lots.length > 1
            ? `<td>${fmtShares(h.shares)} <span class="lots-link" onclick="openLotsModal('${h.id}')">Lots</span></td>
               <td>${fmt(h.cost_basis)} <span class="subtitle">avg</span></td>
               <td>${h.purchase_date}</td>`
            : `<td><input id="e-shares-${h.id}" type="text" inputmode="decimal" value="${toEuInput(h.shares)}" /></td>
               <td><input id="e-cost-${h.id}" type="text" inputmode="decimal" value="${toEuInput(h.cost_basis)}" /></td>
               <td><input id="e-date-${h.id}" type="date" value="${h.purchase_date}" /></td>`
        }
        <td><input id="e-stop-${h.id}" type="text" inputmode="decimal" value="${toEuInput(h.stop_price)}" oninput="updateTrailPreview('${h.id}')" /></td>
        <td><input id="e-ref-${h.id}" type="text" inputmode="decimal" value="${toEuInput(h.reference_high)}" oninput="updateTrailPreview('${h.id}')" /></td>
        <td id="e-trailcalc-${h.id}">${fmtPct(h.trailing_pct)}</td>
        <td>
          <input id="e-price-${h.id}" type="text" inputmode="decimal" value="${toEuInput(h.current_price)}" />
          <label class="subtitle" style="display:block; margin-top:0.25rem;"><input type="checkbox" id="e-manual-${h.id}" ${h.manual_price ? "checked" : ""} /> manual price (don't auto-refresh)</label>
          <input id="e-isin-${h.id}" type="text" placeholder="ISIN (optional, for LS price)" value="${h.isin || ""}" style="display:block; margin-top:0.25rem; width:100%;" />
        </td>
        <td class="${dayChangeClass(h.day_change_pct)}">${fmtDayChangePct(h.day_change_pct)}</td>
        <td>${fmt(h.total)}</td>
        <td>${fmtPct(h.portfolio_pct)}</td>
        <td>${zacksCell(h)}</td>
        <td>
          <label class="subtitle" style="display:block;">Exit plan</label>
          ${exitPlanSelect(h.id, h.exit_plan)}
          <button onclick="saveEdit('${h.id}')">Save</button>
          <button class="secondary" onclick="cancelEdit()">Cancel</button>
        </td>
      `;
      body.appendChild(tr);
      continue;
    }
    tr.innerHTML = `
      <td><span class="ticker-name" onclick="showConsensus('${h.id}')">${h.ticker}</span></td>
      <td>${fmtShares(h.shares)}${h.lots && h.lots.length > 1 ? ` <span class="lots-link" onclick="openLotsModal('${h.id}')">(${h.lots.length} lots)</span>` : ""}</td>
      <td>${fmt(h.cost_basis)}</td>
      <td>${h.purchase_date}</td>
      <td>${fmt(h.stop_price)}</td>
      <td>${fmt(h.reference_high)}</td>
      <td>${fmtPct(h.trailing_pct)}</td>
      <td>${fmt(h.current_price)}${h.isin ? ' <span class="subtitle" title="Priced directly from Lang &amp; Schwarz via ISIN">(LS)</span>' : h.manual_price ? ' <span class="subtitle">(manual)</span>' : ""}</td>
      <td class="${dayChangeClass(h.day_change_pct)}">${!h.isin && h.manual_price ? "—" : fmtDayChangePct(h.day_change_pct)}</td>
      <td class="${gainClass(h)} total-cell" onclick="showUnrealized('${h.id}')">${fmt(h.total)}</td>
      <td>${fmtPct(h.portfolio_pct)}</td>
      <td>${zacksCell(h)}</td>
      <td>
        <button class="secondary" onclick="analyzeTicker('${h.ticker}')">Analyze</button>
        ${!h.isin && h.manual_price ? '<span class="subtitle">manual price</span>' : `<button class="secondary" onclick="refreshHolding('${h.id}')">Refresh</button>`}
        <button class="secondary" onclick="openLotsModal('${h.id}')">Lots</button>
        <button class="secondary" onclick="openThesisModal('${h.id}')" title="${
          h.why ? "Why you own this" : "Not written down yet"
        }">Why${h.why ? " ✓" : ""}</button>
        <button class="secondary" onclick="editHolding('${h.id}')">Edit</button>
        <button class="danger" onclick="sellHolding('${h.id}')">Sell</button>
      </td>
    `;
    body.appendChild(tr);
  }

  document.getElementById("grand-total").textContent = fmt(grandTotal);
}

async function editHolding(id) {
  // Freshen the price first (non-manual only) so the editable Current price field
  // shows a current figure. Done before entering edit mode, so there are no
  // in-progress inputs to clobber.
  const h = lastHoldings.find((x) => x.id === id);
  if (h && !h.manual_price) await refreshHoldingPriceQuiet(id);
  editingId = id;
  await render();
}

function cancelEdit() {
  editingId = null;
  render();
}

function updateTrailPreview(id) {
  const stop_price = parseEuNumber(document.getElementById(`e-stop-${id}`).value);
  const reference_high = parseEuNumber(document.getElementById(`e-ref-${id}`).value);
  const cell = document.getElementById(`e-trailcalc-${id}`);
  if (isNaN(stop_price) || isNaN(reference_high) || reference_high === 0) {
    cell.textContent = "—";
    return;
  }
  cell.textContent = fmtPct((reference_high - stop_price) / reference_high);
}

async function saveEdit(id) {
  const ticker = document.getElementById(`e-ticker-${id}`).value.trim();
  const stop_price = parseEuNumber(document.getElementById(`e-stop-${id}`).value);
  const reference_high = parseEuNumber(document.getElementById(`e-ref-${id}`).value);
  const current_price = parseEuNumber(document.getElementById(`e-price-${id}`).value);
  const exit_plan = document.getElementById(`e-exitplan-${id}`).value;
  const manual_price = document.getElementById(`e-manual-${id}`).checked;
  const isin = document.getElementById(`e-isin-${id}`).value.trim();

  const payload = { ticker, stop_price, reference_high, current_price, exit_plan, manual_price, isin };

  // shares/cost/date inputs only exist for single-lot holdings; multi-lot edits its
  // shares/cost via the Lots modal instead.
  const sharesEl = document.getElementById(`e-shares-${id}`);
  if (sharesEl) {
    payload.shares = parseEuNumber(sharesEl.value);
    payload.cost_basis = parseEuNumber(document.getElementById(`e-cost-${id}`).value);
    payload.purchase_date = document.getElementById(`e-date-${id}`).value;
  }

  const nums = [stop_price, reference_high, current_price];
  if (sharesEl) nums.push(payload.shares, payload.cost_basis);
  if (!ticker || nums.some(isNaN) || (sharesEl && !payload.purchase_date)) {
    alert("All fields are required and must be valid numbers.");
    return;
  }

  await fetch(`${API}/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  editingId = null;
  await render();
}

async function addHolding() {
  const ticker = document.getElementById("f-ticker").value.trim();
  const shares = parseEuNumber(document.getElementById("f-shares").value);
  const cost_basis = parseEuNumber(document.getElementById("f-cost").value);
  const purchase_date = document.getElementById("f-date").value;
  const stop_price = parseEuNumber(document.getElementById("f-stop").value);
  const refRaw = document.getElementById("f-ref").value.trim();
  const isin = document.getElementById("f-isin").value.trim();
  const exit_plan = document.getElementById("f-exit-plan").value;

  if (!ticker || isNaN(shares) || isNaN(cost_basis) || !purchase_date || isNaN(stop_price)) {
    alert("Fill in ticker, shares, cost basis, purchase date, and stop price.");
    return;
  }

  const payload = { ticker, shares, cost_basis, purchase_date, stop_price, exit_plan };
  if (refRaw) payload.reference_high = parseEuNumber(refRaw);
  if (isin) payload.isin = isin;

  const res = await fetch(API, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  // Buying something off the watch list should carry its reasoning onto the position —
  // the thesis was written while it was still a candidate, and the holding is where it
  // starts mattering. Matched on ticker so editing the field before submitting cancels it.
  if (res.ok && pendingPromotion) {
    if (pendingPromotion.ticker === ticker.toUpperCase()) {
      const created = await res.json();
      if (created && created.id && (pendingPromotion.why || pendingPromotion.source_url)) {
        await fetch(`/api/holdings/${created.id}/thesis`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            why: pendingPromotion.why || "",
            source_url: pendingPromotion.source_url || "",
          }),
        });
      }
      await fetch(`/api/watchlist/${pendingPromotion.watchId}`, { method: "DELETE" });
      await loadWatchlist();
    }
    setPendingPromotion(null);
  }

  ["f-ticker", "f-shares", "f-cost", "f-date", "f-stop", "f-ref", "f-isin"].forEach(
    (id) => (document.getElementById(id).value = "")
  );
  document.getElementById("f-exit-plan").value = "hold";
  await render();
}

let pendingPromotion = null;

function setPendingPromotion(p) {
  pendingPromotion = p;
  const banner = document.getElementById("promotion-note");
  if (!banner) return;
  banner.style.display = p ? "block" : "none";
  if (p) {
    banner.innerHTML = `Buying <strong>${escapeHtml(p.ticker)}</strong> from your watch list — its note ${
      p.why ? "will be copied onto the holding" : "is empty, so nothing will be copied"
    }, and the watch-list entry will be removed once you add it. <span class="lots-link" onclick="setPendingPromotion(null)">cancel</span>`;
  }
}

function promoteWatchItem(id) {
  const w = watchlist.find((x) => x.id === id);
  if (!w) return;
  // The checklist answers were written at the moment of deciding — they belong on the
  // position, not left behind on a list entry that is about to be deleted.
  const why = [
    w.why,
    w.tradeoff ? `Giving up: ${w.tradeoff}` : "",
    w.drawdown ? `Through a drawdown: ${w.drawdown}` : "",
  ]
    .filter((s) => (s || "").trim())
    .join("\n");
  setPendingPromotion({ watchId: w.id, ticker: w.ticker, why, source_url: w.source_url });
  showTab("stocks");
  const field = document.getElementById("f-ticker");
  field.value = w.ticker;
  document.getElementById("f-date").value = new Date().toISOString().slice(0, 10);
  field.scrollIntoView({ block: "center" });
  document.getElementById("f-shares").focus();
}

function renderFlag(id, result) {
  const flagsDiv = document.getElementById("flags");
  const existing = document.getElementById(`flag-${id}`);
  if (existing) existing.remove();

  if (result.skipped_manual) return;

  if (result.price_mismatch) {
    const m = result.price_mismatch;
    const note = document.createElement("div");
    note.id = `flag-${id}`;
    note.className = "panel no-trigger";
    note.textContent =
      `${result.ticker}: fetched price ${fmt(m.fetched)} is about ${m.factor}× off your saved ${fmt(m.current)} — ` +
      `likely a different instrument, so it was NOT updated. Click Refresh on that row to keep your price (manual) or accept the fetched one.`;
    flagsDiv.prepend(note);
    return;
  }

  if (result.error) {
    const note = document.createElement("div");
    note.id = `flag-${id}`;
    note.className = "panel flag";
    note.textContent = `${result.ticker}: ${result.error}`;
    flagsDiv.prepend(note);
    return;
  }

  if (result.stop_hit) {
    const gainWord = result.total_gain >= 0 ? "gain" : "loss";
    let consensusLine = "";
    if (result.analyst_consensus) {
      const c = result.analyst_consensus;
      consensusLine = `<div class="line">Analyst consensus (${c.period}): ${c.strong_buy} strong buy · ${c.buy} buy · ${c.hold} hold · ${c.sell} sell · ${c.strong_sell} strong sell</div>`;
    }
    const stopFlag = document.createElement("div");
    stopFlag.id = `flag-${id}`;
    stopFlag.className = "panel stop-hit";
    stopFlag.innerHTML = `
      <div class="line"><strong>${result.ticker}</strong> — at or below Stop loss</div>
      <div class="line">Current price: ${fmt(result.new_price)} · Stop loss: ${fmt(result.current_stop)}</div>
      <div class="line">Your exit plan: <strong>${result.exit_plan_label}</strong></div>
      <div class="line">Estimated ${gainWord}: ${fmt(result.total_gain)} · Estimated tax (26,375%): ${fmt(result.estimated_tax)}</div>
      ${consensusLine}
      <div class="actions">
        <button class="secondary" onclick="resetTrailingStop('${id}', ${result.new_price}, ${result.reset_new_stop})">Reset trailing stop to current price</button>
        <button class="secondary" onclick="document.getElementById('flag-${id}').remove()">Dismiss</button>
      </div>
    `;
    flagsDiv.prepend(stopFlag);
    return;
  }

  if (!result.triggered) {
    const note = document.createElement("div");
    note.id = `flag-${id}`;
    note.className = "panel no-trigger";
    const dayWord = result.day_change_pct >= 0 ? "up" : "down";
    const dayClause = result.day_change_pct == null ? "" : `is ${dayWord} by ${fmtPct(Math.abs(result.day_change_pct))} today, and `;
    note.textContent = `${result.ticker} ${dayClause}is ${fmtPct(result.pct_above_stop)} above stop loss, no change is needed.`;
    flagsDiv.prepend(note);
    return;
  }

  const flag = document.createElement("div");
  flag.id = `flag-${id}`;
  flag.className = "panel flag";
  flag.innerHTML = `
    <div class="line"><strong>${result.ticker}</strong> — up ${fmtPct(result.pct_move)} vs reference high</div>
    <div class="line">Reference high: ${fmt(result.old_high)} → New price: ${fmt(result.new_price)}</div>
    <div class="line">Current stop: ${fmt(result.current_stop)}</div>
    <div class="line">Suggested new stop: <strong>${fmt(result.suggested_new_stop)}</strong></div>
    <div class="actions">
      <button onclick="confirmHolding('${id}', ${result.new_price}, ${result.suggested_new_stop})">Confirm — I updated the stop at my broker</button>
      <button class="secondary" onclick="document.getElementById('flag-${id}').remove()">Dismiss</button>
    </div>
  `;
  flagsDiv.prepend(flag);
}

async function refreshHolding(id, overridePriceCheck = false) {
  const url = `${API}/${id}/refresh` + (overridePriceCheck ? "?override_price_check=true" : "");
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || "Failed to refresh price.");
    return;
  }
  const result = await res.json();

  if (result.skipped_manual) {
    await render();
    return;
  }

  if (result.price_mismatch) {
    const m = result.price_mismatch;
    const msg =
      `Finnhub returned ${fmt(m.fetched)} EUR for ${result.ticker}, but your saved price is ${fmt(m.current)} EUR — ` +
      `about ${m.factor}× off. This usually means Finnhub is pricing a different instrument than the one you hold ` +
      `(e.g. a US ADR vs. the ordinary share on Trade Republic).\n\n` +
      `OK = keep your own price and stop auto-refreshing this holding (mark as manual).\n` +
      `Cancel = use Finnhub's price anyway.`;
    if (confirm(msg)) {
      await fetch(`${API}/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ manual_price: true }),
      });
      await render();
    } else {
      await refreshHolding(id, true);
    }
    return;
  }

  await render();
  renderFlag(id, result);
}

async function refreshAllPrices() {
  const btn = document.getElementById("refresh-all-btn");
  btn.disabled = true;
  btn.textContent = "Refreshing…";
  try {
    const res = await fetch(`${API}/refresh-all`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Failed to refresh prices.");
      return;
    }
    const results = await res.json();
    await render();
    for (const result of results) {
      renderFlag(result.id, result);
    }
    await loadPortfolioChart(); // refresh-all recorded a new daily point
    await loadConcentration();
    await loadBreadth();
    await loadWeeklyTable();
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh all prices";
  }
}

async function resetTrailingStop(id, newReferenceHigh, newStopPrice) {
  if (!confirm(`Reset reference high to ${fmt(newReferenceHigh)} and stop loss to ${fmt(newStopPrice)}?`)) return;
  await confirmHolding(id, newReferenceHigh, newStopPrice);
}

async function confirmHolding(id, newReferenceHigh, newStopPrice) {
  await fetch(`${API}/${id}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      new_reference_high: newReferenceHigh,
      new_stop_price: newStopPrice,
    }),
  });
  document.getElementById(`flag-${id}`)?.remove();
  await render();
}

function showTab(name) {
  const tabs = ["stocks", "opportunities", "opportunities-b", "watchlist", "history"];
  for (const t of tabs) {
    document.getElementById(`tab-${t}`).style.display = name === t ? "block" : "none";
    document.getElementById(`tab-btn-${t}`).classList.toggle("active", name === t);
  }
  if (name === "history") loadHistory();
  if (name === "opportunities-b") loadOpportunitiesB();
  if (name === "watchlist") loadWatchlist();
}

let watchlist = [];
let watchSortField = null;
let watchTagFilter = null;
let watchSortDir = 1;

async function loadWatchlist() {
  const res = await fetch("/api/watchlist");
  watchlist = await res.json();
  renderWatchlist();
}

function watchSortBy(field) {
  if (watchSortField === field) {
    watchSortDir *= -1;
  } else {
    watchSortField = field;
    watchSortDir = 1;
  }
  renderWatchlist();
}

function watchSortValue(w, field) {
  if (field === "score") return w.score ? w.score.composite : null;
  if (field === "ticker") return w.ticker.toLowerCase();
  // Sorts bursting names to one end and extended ones to the other, with quiet in between.
  return w[field];
}

function renderWatchlist() {
  const body = document.getElementById("watchlist-body");
  const emptyMsg = document.getElementById("watchlist-empty-msg");
  body.innerHTML = "";
  emptyMsg.style.display = watchlist.length === 0 ? "block" : "none";

  const rows = watchTagFilter
    ? watchlist.filter((w) => watchHashtags(w).includes(watchTagFilter))
    : [...watchlist];
  if (watchSortField) {
    rows.sort((a, b) => {
      const av = watchSortValue(a, watchSortField);
      const bv = watchSortValue(b, watchSortField);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return -1 * watchSortDir;
      if (av > bv) return 1 * watchSortDir;
      return 0;
    });
  }

  renderWatchTagFilters();
  renderThemeStages();

  for (const field of ["ticker", "score", "move_1d", "move_1w", "move_3m"]) {
    const el = document.getElementById(`watch-arrow-${field}`);
    if (!el) continue;
    el.textContent = field === watchSortField ? (watchSortDir === 1 ? "▲" : "▼") : "";
  }

  for (const w of rows) {
    const tr = document.createElement("tr");
    const scoreText = w.score ? Math.round(w.score.composite * 100) : "—";
    tr.innerHTML = `
      <td>
        <span class="ticker-name" onclick="showWatchConsensus('${w.id}')">${w.ticker}</span>
        ${
          w.source_url
            ? `<a class="source-link" href="${escapeHtml(w.source_url)}" target="_blank" rel="noopener noreferrer" title="Open the source you added this from">↗</a>`
            : ""
        }
      </td>
      <td class="nowrap">${w.added_date}${sinceAddedCell(w)}</td>
      <td>${w.current_price != null ? fmt(w.current_price) : "—"}</td>
      <td>${scoreText}</td>
      <td>${coloredPct(w.move_1d)}</td>
      <td>${coloredPct(w.move_1w)}</td>
      <td>${coloredPct(w.move_3m)}</td>
      <td>${zacksCell(w)}</td>
      <td class="watch-note-cell"></td>
      <td>
        <button class="secondary" onclick="openRiskModal('${w.id}')" title="What would buying this put at risk?">Risk</button>
        <button class="secondary" onclick="promoteWatchItem('${w.id}')" title="Move this to your holdings, keeping the note">Bought</button>
        <button class="secondary" onclick="analyzeTicker('${w.ticker}')">Analyze</button>
        <button class="secondary" onclick="refreshWatchItem('${w.id}')">Refresh</button>
        <button class="danger" onclick="removeWatchItem('${w.id}')">Remove</button>
      </td>
    `;
    // Built as an element rather than innerHTML so the user's own text can never be
    // parsed as markup.
    const whyInput = document.createElement("input");
    whyInput.type = "text";
    whyInput.className = "watch-note-input";
    whyInput.placeholder = "Why — use #tags to group";
    whyInput.value = w.why || "";
    whyInput.addEventListener("change", () => saveWatchMeta(w.id, { why: whyInput.value }));
    tr.querySelector(".watch-note-cell").appendChild(whyInput);
    body.appendChild(tr);
  }
}

async function saveWatchMeta(id, patch) {
  const res = await fetch(`/api/watchlist/${id}/meta`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || "Could not save.");
    await loadWatchlist();
    return;
  }
  Object.assign(
    watchlist.find((x) => x.id === id) || {},
    await res.json()
  );
}

// Hashtags typed inside the free-text "why" are the grouping: one field to write in, and
// a new group is created just by typing one. A separate tag column was tried first and
// dropped — it only pays off if the wording stays consistent by hand.
const HASHTAG_RE = /#[\p{L}\p{N}_-]+/gu;

function watchHashtags(w) {
  return ((w.why || "").match(HASHTAG_RE) || []).map((h) => h.toLowerCase());
}

// Theme lifecycle, on the user's own #tags rather than a vendor's theme list. The paid
// FINVIZ-based skill scores 14 market-wide themes; these are the groups she actually holds
// opinions about, and two free trailing returns separate "was strong and is unwinding" from
// "still working" — which is the distinction that mattered, not the vendor's five-stage label.
const THEME_STAGES = {
  working: { label: "still working", cls: "price-up" },
  unwinding: { label: "was strong, now unwinding", cls: "price-down" },
  turning: { label: "falling for a year, rising lately", cls: "" },
  cold: { label: "not working", cls: "price-down" },
};

function themeStage(m12, m3) {
  if (m12 == null || m3 == null) return null;
  if (m12 >= 0 && m3 >= 0) return "working";
  if (m12 >= 0) return "unwinding";
  if (m3 >= 0) return "turning";
  return "cold";
}

function avg(values) {
  const nums = values.filter((v) => typeof v === "number");
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
}

function renderThemeStages() {
  const host = document.getElementById("watch-theme-stages");
  if (!host) return;
  const groups = new Map();
  for (const w of watchlist) {
    for (const h of new Set(watchHashtags(w))) {
      if (!groups.has(h)) groups.set(h, []);
      groups.get(h).push(w);
    }
  }
  const rows = [];
  for (const [tag, items] of [...groups.entries()].sort((a, b) => b[1].length - a[1].length)) {
    if (items.length < 2) continue; // one ticker is a stock, not a theme
    const m12 = avg(items.map((i) => i.move_12m));
    const m3 = avg(items.map((i) => i.move_3m));
    const oh = avg(items.map((i) => i.off_high));
    const stage = themeStage(m12, m3);
    if (!stage) continue;
    const s = THEME_STAGES[stage];
    rows.push(
      `<li><strong>${escapeHtml(tag)}</strong> · ${items.length} names — <span class="${s.cls}">${
        s.label
      }</span><br /><span class="subtitle">${coloredPct(m12)} over the year, ${coloredPct(
        m3
      )} over 3 months${oh != null ? `, ${fmtPct(Math.abs(oh) / 100)} below their highs on average` : ""}.</span></li>`
    );
  }
  host.innerHTML = rows.length
    ? `<ul class="checklist-context">${rows.join("")}</ul>`
    : `<p class="subtitle">Tag two or more tickers with the same #tag to see how that group is doing as a whole.</p>`;
}

function renderWatchTagFilters() {
  const host = document.getElementById("watch-tag-filters");
  if (!host) return;
  const counts = new Map();
  for (const w of watchlist) {
    for (const h of new Set(watchHashtags(w))) counts.set(h, (counts.get(h) || 0) + 1);
  }
  if (counts.size === 0) {
    host.innerHTML = `<span class="subtitle">Add #tags in the Why column to group tickers that came from the same idea.</span>`;
    return;
  }
  const chips = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(
      ([h, n]) =>
        `<button class="tag-chip${h === watchTagFilter ? " active" : ""}" onclick="toggleWatchTagFilter('${escapeHtml(
          h
        )}')">${escapeHtml(h)} <span class="subtitle">${n}</span></button>`
    );
  host.innerHTML =
    chips.join("") +
    (watchTagFilter ? `<button class="tag-chip" onclick="toggleWatchTagFilter(null)">clear</button>` : "");
}

function toggleWatchTagFilter(tag) {
  watchTagFilter = watchTagFilter === tag ? null : tag;
  renderWatchlist();
}

function sinceAddedCell(w) {
  // Rows added before entry prices were recorded show the date alone — a placeholder dash
  // just reads as a stray character next to it.
  if (!w.price_at_add || w.current_price == null) return "";
  return " " + coloredPct((w.current_price / w.price_at_add - 1) * 100);
}

function showWatchConsensus(id) {
  const w = watchlist.find((x) => x.id === id);
  renderConsensusModal(
    w ? w.ticker : "",
    w ? w.consensus : null,
    "No analyst consensus data yet — click Refresh on this item."
  );
}

async function addWatchItem() {
  const input = document.getElementById("watch-ticker-input");
  const urlInput = document.getElementById("watch-url-input");
  const whyInput = document.getElementById("watch-why-input");
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) return;
  const btn = document.getElementById("watch-add-btn");
  btn.disabled = true;
  btn.textContent = "Adding…";
  try {
    const res = await fetch("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker,
        source_url: urlInput.value.trim(),
        why: whyInput.value.trim(),
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Failed to add ticker.");
      return;
    }
    input.value = "";
    urlInput.value = "";
    // The why text is deliberately left in place: adds come in batches from one source,
    // so the next ticker from the same article keeps its #tag without retyping.
    await loadWatchlist();
  } finally {
    btn.disabled = false;
    btn.textContent = "Add";
  }
}

async function removeWatchItem(id) {
  if (!confirm("Remove this ticker from your watch list?")) return;
  await fetch(`/api/watchlist/${id}`, { method: "DELETE" });
  await loadWatchlist();
}

async function refreshWatchItem(id) {
  await fetch(`/api/watchlist/${id}/refresh`, { method: "POST" });
  await loadWatchlist();
}

async function refreshAllWatchlist() {
  const btn = document.getElementById("watch-refresh-all-btn");
  btn.disabled = true;
  btn.textContent = "Refreshing…";
  try {
    await fetch("/api/watchlist/refresh-all", { method: "POST" });
    await loadWatchlist();
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh all";
  }
}

let lastOppB = [];
let oppBSortField = "composite";
let oppBSortDir = -1;

function oppBSortBy(field) {
  if (oppBSortField === field) {
    oppBSortDir *= -1;
  } else {
    oppBSortField = field;
    oppBSortDir = field === "ticker" || field === "company" ? 1 : -1;
  }
  renderOpportunitiesB();
}

let sectorStrength = {};

async function loadSectorStrength() {
  try {
    const res = await fetch("/api/sectors");
    const data = await res.json();
    sectorStrength = data.sectors || {};
  } catch (e) {
    sectorStrength = {};
  }
}

async function loadOpportunitiesB() {
  await loadSectorStrength();
  const res = await fetch("/api/opportunities-b");
  const data = await res.json();
  lastOppB = data.list || [];
  const status = document.getElementById("oppb-status");
  if (data.generated_at) {
    const d = new Date(data.generated_at);
    status.textContent =
      `${data.passed_filter} of ${data.universe_size} passed · top ${lastOppB.length} shown · ` +
      `${d.toLocaleDateString("de-DE")} ${d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}`;
  } else {
    status.textContent = "Not generated yet";
  }
  renderOpportunitiesB();
}

function sectorCell(sector) {
  if (!sector) return "—";
  const s = sectorStrength[sector];
  if (!s || !s.rank) return sector;
  const cls = s.rank <= s.total / 3 ? "price-up" : s.rank > (2 * s.total) / 3 ? "price-down" : "";
  return `${sector} <span class="${cls}">#${s.rank}</span>`;
}

function renderOpportunitiesB() {
  const body = document.getElementById("opportunities-b-body");
  const rows = [...lastOppB];
  rows.sort((a, b) => {
    let av = a[oppBSortField];
    let bv = b[oppBSortField];
    if (typeof av === "string") {
      av = av.toLowerCase();
      bv = bv.toLowerCase();
    }
    if (av < bv) return -1 * oppBSortDir;
    if (av > bv) return 1 * oppBSortDir;
    return 0;
  });

  for (const f of ["ticker", "company", "composite", "conviction", "drift", "move_1w", "move_3m"]) {
    const el = document.getElementById(`oppb-arrow-${f}`);
    if (el) el.textContent = f === oppBSortField ? (oppBSortDir === 1 ? "▲" : "▼") : "";
  }

  body.innerHTML = "";
  document.getElementById("oppb-empty-msg").style.display = rows.length ? "none" : "block";
  for (const r of rows) {
    const tr = document.createElement("tr");
    const driftCls = r.drift > 0 ? "price-up" : r.drift < 0 ? "price-down" : "";
    const driftSym = r.drift > 0 ? "▲ improving" : r.drift < 0 ? "▼ cooling" : "flat";
    tr.innerHTML = `
      <td><span class="ticker-name" onclick="showConsensusForB('${r.ticker}')">${r.ticker}</span></td>
      <td>${r.company || "—"}</td>
      <td>${sectorCell(r.sector)}</td>
      <td><strong>${Math.round(r.composite * 100)}</strong></td>
      <td>${consensusLabel(r.consensus_avg)} <span class="subtitle">(${r.consensus.strongBuy} SB / ${r.n})</span></td>
      <td>${r.beats != null ? r.beats + "/" + r.beats_total : "—"}</td>
      <td class="${driftCls}">${driftSym}</td>
      <td>${coloredPct(r.move_1w)}</td>
      <td>${coloredPct(r.move_3m)}</td>
      <td>${r.also_zacks_1 ? '<span class="zacks-rank-1">✓</span>' : "—"}</td>
      <td><button class="secondary" onclick="analyzeTicker('${r.ticker}')">Analyze</button></td>
    `;
    body.appendChild(tr);
  }
}

function showConsensusForB(ticker) {
  const r = lastOppB.find((x) => x.ticker === ticker);
  const c = r
    ? {
        period: r.period,
        strong_buy: r.consensus.strongBuy,
        buy: r.consensus.buy,
        hold: r.consensus.hold,
        sell: r.consensus.sell,
        strong_sell: r.consensus.strongSell,
        average: r.consensus_avg,
      }
    : null;
  renderConsensusModal(ticker, c, "No consensus data.");
}

async function refreshSectors() {
  if (!confirm("This pulls 3-month history for the 11 sector ETFs (~2.5 min, throttled for Alpha Vantage). Start now?")) return;
  const btn = document.getElementById("sectors-refresh-btn");
  btn.disabled = true;
  btn.textContent = "Refreshing sectors…";
  try {
    const res = await fetch("/api/sectors/refresh", { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Failed to refresh sectors.");
      return;
    }
    const data = await res.json();
    await loadSectorStrength();
    renderOpportunitiesB();
    const n = Object.keys(data.sectors || {}).length;
    alert(`Sector strength updated — ${n} of 11 sectors ranked${n < 11 ? " (Alpha Vantage daily cap may have limited the rest — try again tomorrow)" : ""}.`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh sectors (~2.5 min)";
  }
}

async function refreshOpportunitiesB() {
  if (!confirm("This scans all ~500 S&P 500 names (one analyst-rating call each) and takes about 10 minutes. Start now?")) return;
  const btn = document.getElementById("oppb-refresh-btn");
  btn.disabled = true;
  btn.textContent = "Scanning… (~10 min)";
  try {
    const res = await fetch("/api/opportunities-b/refresh", { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Failed to refresh Opportunities B.");
      return;
    }
    const data = await res.json();
    await loadOpportunitiesB();
    alert(`Opportunities B updated — ${data.passed_filter} names passed the filter, top ${data.list.length} shown.`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh (~10 min)";
  }
}

function parseEuNumber(str) {
  if (typeof str !== "string") return NaN;
  str = str.trim();
  if (!str) return NaN;
  const commaCount = (str.match(/,/g) || []).length;
  const dotCount = (str.match(/\./g) || []).length;

  // Two or more separators: the LAST one is the decimal point and everything
  // before it is thousands grouping. Covers EU "2.345,67", US "2,345.67", and the
  // malformed-but-common all-one-separator forms "2,345,67" / "2.345.67" -> 3640.76.
  // Exception: if the separators are all the same character AND the final group is
  // a full 3-digit block, it's pure grouping with no decimals ("1.234.567" -> 1234567).
  if (commaCount + dotCount >= 2) {
    const lastSep = Math.max(str.lastIndexOf(","), str.lastIndexOf("."));
    const mixed = commaCount > 0 && dotCount > 0;
    const lastGroupLen = str.length - lastSep - 1;
    if (!mixed && lastGroupLen === 3) {
      return parseFloat(str.replace(/[.,]/g, ""));
    }
    const intPart = str.slice(0, lastSep).replace(/[.,]/g, "");
    const decPart = str.slice(lastSep + 1).replace(/[.,]/g, "");
    return parseFloat(intPart + "." + decPart);
  }

  // Single comma → decimal separator.
  if (commaCount === 1) {
    return parseFloat(str.replace(",", "."));
  }
  // Single dot followed by exactly 3 digits is almost certainly EU thousands
  // grouping typed without cents ("3.155" meaning 3155), not three decimal places.
  if (dotCount === 1) {
    const parts = str.split(".");
    if (parts[1].length === 3) return parseFloat(parts.join(""));
  }
  return parseFloat(str);
}

let sellingId = null;

// Refresh a single holding's price without rendering flags or firing the
// mismatch/manual prompts — used to freshen the price behind sell/edit so the
// sanity check compares against a current figure. Returns the latest holding.
async function refreshHoldingPriceQuiet(id) {
  try {
    await fetch(`${API}/${id}/refresh`, { method: "POST" });
  } catch (e) {
    /* keep last known price on any failure */
  }
  const holdings = await fetchHoldings();
  lastHoldings = holdings;
  return holdings.find((x) => x.id === id);
}

async function sellHolding(id) {
  let h = lastHoldings.find((x) => x.id === id);
  if (!h) return;
  sellingId = id;
  document.getElementById("sell-modal-title").textContent = `Sell ${h.ticker}`;
  document.getElementById("sell-shares").value = toEuInput(h.shares);
  document.getElementById("sell-total").value = "";
  const now = new Date();
  document.getElementById("sell-date").value = now.toISOString().slice(0, 10);
  document.getElementById("sell-time").value = now.toTimeString().slice(0, 5);
  document.getElementById("sell-preview").textContent = "";
  const ref = document.getElementById("sell-ref-price");
  ref.textContent = h.manual_price
    ? `Current price: ${fmt(h.current_price)} (manual)`
    : `Current price: ${fmt(h.current_price)} — refreshing…`;
  document.getElementById("sell-modal").style.display = "flex";

  if (!h.manual_price) {
    const fresh = await refreshHoldingPriceQuiet(id);
    // only apply if this modal is still the one open for this holding
    if (fresh && sellingId === id) {
      h = fresh;
      ref.textContent = `Current price: ${fmt(fresh.current_price)}`;
      updateSellPreview();
    }
  }
}

function closeSellModal() {
  document.getElementById("sell-modal").style.display = "none";
  sellingId = null;
}

let lotsHoldingId = null;
let editingLotIndex = null;

let riskTicker = null;

function openRiskModal(id) {
  const w = watchlist.find((x) => x.id === id);
  if (!w || w.current_price == null) return;
  riskTicker = w;
  document.getElementById("risk-modal-title").textContent = `${w.ticker} — before you buy`;
  document.getElementById("risk-stop-hint").textContent = "% below your buy price — 10% on most of yours, ~22% on MU and NBIS";
  document.getElementById("risk-amount").value = "";
  document.getElementById("risk-stop").value = "10";
  document.getElementById("risk-why").value = w.why || "";
  document.getElementById("risk-tradeoff").value = w.tradeoff || "";
  document.getElementById("risk-drawdown").value = w.drawdown || "";
  renderRiskPreview();
  renderRiskContext();
  document.getElementById("risk-modal").style.display = "flex";
}

function closeRiskModal() {
  document.getElementById("risk-modal").style.display = "none";
  riskTicker = null;
}

function renderRiskPreview() {
  const out = document.getElementById("risk-output");
  if (!riskTicker) return;
  const amount = parseEuNumber(document.getElementById("risk-amount").value);
  const stopPct = parseEuNumber(document.getElementById("risk-stop").value);
  if (isNaN(amount) || amount <= 0 || isNaN(stopPct) || stopPct <= 0 || stopPct >= 100) {
    out.innerHTML = `<p class="subtitle">Enter an amount to see the numbers.</p>`;
    return;
  }
  const price = riskTicker.current_price;
  const shares = amount / price;
  const atRisk = amount * (stopPct / 100);
  // The portfolio grows by whatever is invested, so the new position's share is measured
  // against the enlarged total rather than today's.
  const portfolio = (lastHoldings || []).reduce((s, h) => s + h.shares * h.current_price, 0);
  const enlarged = portfolio + amount;

  out.innerHTML = `
    <table class="mini-table"><tbody>
      <tr><td>Buys</td><td><strong>${fmt(shares)}</strong> shares at ${fmt(price)}</td></tr>
      <tr><td>Position size</td><td><strong>${fmtPct(amount / enlarged)}</strong> of your portfolio afterwards</td></tr>
      <tr><td>Stop at</td><td>${fmt(price * (1 - stopPct / 100))}</td></tr>
      <tr><td>If the stop is hit</td><td><span class="price-down">−${fmt(atRisk)}</span> — ${fmtPct(
    atRisk / enlarged
  )} of the portfolio</td></tr>
    </tbody></table>
    <p class="subtitle">A stop doesn't guarantee that exit price — a gap down opens below it, and the loss is whatever you actually sell at. Your broker's live order is the real protection; this tool only tracks the level.</p>`;
}

// The static half of the pre-buy checklist. These three questions don't change per stock —
// which is exactly why they belong in the interface rather than in a conversation you have to
// remember to start. The adaptive questions ("this is a recovery thesis, so ask about the
// multiple") can't be pre-written and stay a conversation with Claude.
async function saveChecklist() {
  if (!riskTicker) return;
  const patch = {
    why: document.getElementById("risk-why").value,
    tradeoff: document.getElementById("risk-tradeoff").value,
    drawdown: document.getElementById("risk-drawdown").value,
  };
  const res = await fetch(`/api/watchlist/${riskTicker.id}/meta`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    alert((await res.json()).detail || "Could not save.");
    return;
  }
  Object.assign(riskTicker, await res.json());
  await loadWatchlist();
  closeRiskModal();
}

// Answers the tool can supply, so the checklist doesn't ask what it already knows. No
// pass/fail: a tick would read as approval, and this is context, not a verdict.
function renderRiskContext() {
  const host = document.getElementById("risk-context");
  if (!host || !riskTicker) return;
  const bits = [];

  const c = lastConcentration;
  if (c && c.groups && c.groups.length) {
    const g = c.groups[0];
    bits.push(
      `<li>Your holdings already include one bloc that moves together: <strong>${g.tickers.join(
        " · "
      )}</strong>, ${fmtPct(g.weight_pct / 100)} of the portfolio.</li>`
    );
  }
  const b = lastBreadth;
  if (b) {
    bits.push(
      `<li>Across the market, <strong>${fmtPct(
        b.above_50d / 100
      )}</strong> of US stocks are rising lately (trading above their average price of the last 50 days), against ${fmtPct(
        b.above_50d_prev / 100
      )} a month ago.</li>`
    );
  }
  // Uses move_3m rather than the momentum object — watch-list rows stopped carrying one when
  // the Momentum column was replaced by 1D/1W/3M.
  if (typeof riskTicker.move_3m === "number" && riskTicker.move_3m <= -20) {
    bits.push(
      `<li>${riskTicker.ticker} is down ${fmtPct(
        Math.abs(riskTicker.move_3m) / 100
      )} over 3 months — buying now is a bet on a turn, not on continuation.</li>`
    );
  }
  if (riskTicker.price_at_add != null && riskTicker.current_price != null) {
    const move = (riskTicker.current_price / riskTicker.price_at_add - 1) * 100;
    bits.push(
      `<li>It has moved ${coloredPct(move)} since you put it on the list on ${riskTicker.added_date}.</li>`
    );
  }
  bits.push(
    `<li id="overlap-slot">Where does it sit — rising or falling, and does it move with what you already hold? <button class="secondary" onclick="checkOverlap()">Check</button> <span class="subtitle">uses one Alpha Vantage call the first time each day</span></li>`
  );
  host.innerHTML = `<ul class="checklist-context">${bits.join("")}</ul>`;
}

// Answers the overlap question rather than asking it. Kept behind a button because it spends
// from the 25/day Alpha Vantage budget the first time a ticker is checked on a given day.
async function checkOverlap() {
  const slot = document.getElementById("overlap-slot");
  if (!slot || !riskTicker) return;
  slot.innerHTML = "Checking…";
  try {
    // Both reads share alpha_vantage's per-ticker-per-day cache, so this is one call.
    const [res, posRes] = await Promise.all([
      fetch(`/api/concentration/compare/${riskTicker.ticker}`),
      fetch(`/api/breadth/position/${riskTicker.ticker}`),
    ]);
    const d = await res.json();
    const pos = await posRes.json();
    if (!res.ok || d.error) {
      slot.innerHTML = `<span class="subtitle">Couldn't check: ${d.detail || d.error}</span>`;
      return;
    }
    const top = d.pairs.slice(0, 3).map((p) => `${p.ticker} ${fmt(p.correlation)}`).join(" · ");
    const verdict = d.joins_group
      ? `<span class="price-down">It moves with your ${d.joins_group.join(" · ")} bloc</span>, which would take that group past ${fmtPct(
          d.joins_group_weight_pct / 100
        )} of the portfolio.`
      : d.pairs[0].correlation >= 0.35
      ? `<span>It leans towards your existing holdings without clearly joining them.</span>`
      : `<span class="price-up">It moves largely on its own</span> relative to what you hold.`;
    // Places the stock inside the market figure shown just above, using the same measure.
    let place = "";
    if (posRes.ok && !pos.error && lastBreadth) {
      place = pos.above
        ? `<br /><span class="price-up">It is one of the ${fmtPct(
            lastBreadth.above_50d / 100
          )} that are rising</span> — ${fmtPct(pos.distance_pct / 100)} above its own 50-day average.`
        : `<br /><span class="price-down">It is one of the ${fmtPct(
            1 - lastBreadth.above_50d / 100
          )} that are not rising</span> — ${fmtPct(
            Math.abs(pos.distance_pct) / 100
          )} below its own 50-day average.`;
    }
    slot.innerHTML = `${verdict}${place}<br /><span class="subtitle">Closest: ${top}. Based on ${d.days} shared days — a short run, and your holdings are valued in EUR while this is priced in USD, so a little currency movement leaks in.</span>`;
  } catch (e) {
    slot.innerHTML = `<span class="subtitle">Couldn't check: ${e.message || e}</span>`;
  }
}

let thesisHoldingId = null;

function openThesisModal(id) {
  const h = lastHoldings.find((x) => x.id === id);
  if (!h) return;
  thesisHoldingId = id;
  document.getElementById("thesis-modal-title").textContent = `${h.ticker} — why you own it`;
  document.getElementById("thesis-why").value = h.why || "";
  document.getElementById("thesis-url").value = h.source_url || "";
  document.getElementById("thesis-modal").style.display = "flex";
}

function closeThesisModal() {
  document.getElementById("thesis-modal").style.display = "none";
  thesisHoldingId = null;
}

async function saveThesis() {
  if (!thesisHoldingId) return;
  const res = await fetch(`/api/holdings/${thesisHoldingId}/thesis`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      why: document.getElementById("thesis-why").value,
      source_url: document.getElementById("thesis-url").value.trim(),
    }),
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || "Could not save.");
    return;
  }
  closeThesisModal();
  await render();
}

function openLotsModal(id) {
  const h = lastHoldings.find((x) => x.id === id);
  if (!h) return;
  lotsHoldingId = id;
  editingLotIndex = null;
  renderLotsModalBody(h);
  document.getElementById("lot-shares").value = "";
  document.getElementById("lot-cost").value = "";
  document.getElementById("lot-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("lots-modal").style.display = "flex";
}

function renderLotsModalBody(h) {
  document.getElementById("lots-modal-title").textContent = `${h.ticker} — purchases (${h.lots.length} lot${h.lots.length > 1 ? "s" : ""})`;
  const rows = h.lots
    .map((lot, i) => {
      if (i === editingLotIndex) {
        return `<tr>
          <td><input id="lot-e-shares-${i}" type="text" inputmode="decimal" value="${toEuInput(lot.shares)}" style="width:110px" /></td>
          <td><input id="lot-e-cost-${i}" type="text" inputmode="decimal" value="${toEuInput(lot.cost_basis)}" style="width:90px" /></td>
          <td><input id="lot-e-date-${i}" type="date" value="${lot.purchase_date}" /></td>
          <td>${fmt(lot.shares * h.current_price)}</td>
          <td><button onclick="saveLot(${i})">Save</button> <button class="secondary" onclick="cancelEditLot()">Cancel</button></td>
        </tr>`;
      }
      return `<tr>
        <td>${fmtShares(lot.shares)}</td>
        <td>${fmt(lot.cost_basis)}</td>
        <td>${lot.purchase_date}</td>
        <td>${fmt(lot.shares * h.current_price)}</td>
        <td>
          <button class="secondary" onclick="editLot(${i})">Edit</button>
          ${h.lots.length > 1 ? `<button class="danger" onclick="removeLot(${i})">Remove</button>` : ""}
        </td>
      </tr>`;
    })
    .join("");
  document.getElementById("lots-modal-body").innerHTML = `
    <p class="subtitle">Oldest lot is sold first (FIFO). Aggregate: <strong>${fmtShares(h.shares)}</strong> shares · avg buy-in <strong>${fmt(h.cost_basis)}</strong>.</p>
    <table class="consensus-table">
      <tr><th>Shares</th><th>Buy in</th><th>Date</th><th>Value now</th><th></th></tr>
      ${rows}
    </table>`;
}

function editLot(i) {
  editingLotIndex = i;
  renderLotsModalBody(lastHoldings.find((x) => x.id === lotsHoldingId));
}
function cancelEditLot() {
  editingLotIndex = null;
  renderLotsModalBody(lastHoldings.find((x) => x.id === lotsHoldingId));
}

async function refreshLotsModal() {
  await render();
  const h = lastHoldings.find((x) => x.id === lotsHoldingId);
  if (!h) return closeLotsModal();
  renderLotsModalBody(h);
}

async function saveLot(i) {
  const shares = parseEuNumber(document.getElementById(`lot-e-shares-${i}`).value);
  const cost_basis = parseEuNumber(document.getElementById(`lot-e-cost-${i}`).value);
  const purchase_date = document.getElementById(`lot-e-date-${i}`).value;
  if (isNaN(shares) || shares <= 0 || isNaN(cost_basis) || !purchase_date) {
    alert("Fill in shares, buy-in, and date.");
    return;
  }
  const res = await fetch(`${API}/${lotsHoldingId}/lots/${i}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shares, cost_basis, purchase_date }),
  });
  if (!res.ok) {
    alert((await res.json()).detail || "Failed to save lot.");
    return;
  }
  editingLotIndex = null;
  await refreshLotsModal();
}

async function removeLot(i) {
  if (!confirm("Remove this lot? Use this only to fix a data-entry mistake — it does NOT record a sale.")) return;
  const res = await fetch(`${API}/${lotsHoldingId}/lots/${i}`, { method: "DELETE" });
  if (!res.ok) {
    alert((await res.json()).detail || "Failed to remove lot.");
    return;
  }
  await refreshLotsModal();
}

async function submitAddLot() {
  const shares = parseEuNumber(document.getElementById("lot-shares").value);
  const cost_basis = parseEuNumber(document.getElementById("lot-cost").value);
  const purchase_date = document.getElementById("lot-date").value;
  if (isNaN(shares) || shares <= 0 || isNaN(cost_basis) || !purchase_date) {
    alert("Fill in shares bought, buy-in, and date.");
    return;
  }
  const res = await fetch(`${API}/${lotsHoldingId}/lots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shares, cost_basis, purchase_date }),
  });
  if (!res.ok) {
    alert((await res.json()).detail || "Failed to add lot.");
    return;
  }
  document.getElementById("lot-shares").value = "";
  document.getElementById("lot-cost").value = "";
  await refreshLotsModal();
}

function closeLotsModal() {
  document.getElementById("lots-modal").style.display = "none";
  lotsHoldingId = null;
  editingLotIndex = null;
}

// FIFO cost of selling `sharesToSell`, walking oldest lots first — mirrors the
// backend so the preview gain matches what will actually be recorded.
function fifoCost(lots, sharesToSell) {
  const sorted = [...(lots || [])].sort((a, b) => (a.purchase_date < b.purchase_date ? -1 : 1));
  let remaining = sharesToSell;
  let spend = 0;
  for (const lot of sorted) {
    if (remaining <= 1e-9) break;
    const take = Math.min(lot.shares, remaining);
    spend += take * lot.cost_basis;
    remaining -= take;
  }
  return spend;
}

function updateSellPreview() {
  const preview = document.getElementById("sell-preview");
  const shares = parseEuNumber(document.getElementById("sell-shares").value);
  const total = parseEuNumber(document.getElementById("sell-total").value);

  if (isNaN(shares) || shares <= 0 || isNaN(total)) {
    preview.innerHTML = "";
    return;
  }

  const salePrice = total / shares;
  let line = `= ${fmt(total)} EUR total · ${fmt(salePrice)} EUR/share`;

  const h = lastHoldings.find((x) => x.id === sellingId);
  if (h) {
    const gain = total - fifoCost(h.lots, shares); // FIFO: oldest lots first
    const multi = h.lots && h.lots.length > 1 ? " (FIFO)" : "";
    line += ` · ${gain >= 0 ? "gain" : "loss"} ${fmt(Math.abs(gain))} EUR${multi}`;
  }

  // Soft warning: if the implied per-share price is far from the live price, the
  // Shares sold field is probably wrong (e.g. left at the full holding on a partial
  // sale). Non-blocking — the 10x hard block doesn't catch these smaller mismatches.
  let warn = "";
  if (h && h.current_price && (salePrice > h.current_price * 1.5 || salePrice < h.current_price / 1.5)) {
    warn = `<div class="sell-warn">⚠ ${fmt(salePrice)}/share is far from the current ${fmt(h.current_price)} — check "Shares sold" (did you sell only part of the position?).</div>`;
  }
  preview.innerHTML = `<div>${line}</div>${warn}`;
}

async function submitSell(overridePriceCheck = false) {
  const shares_sold = parseEuNumber(document.getElementById("sell-shares").value);
  const total_sum = parseEuNumber(document.getElementById("sell-total").value);
  const sell_date = document.getElementById("sell-date").value;
  const sell_time = document.getElementById("sell-time").value;

  if (isNaN(shares_sold) || shares_sold <= 0 || isNaN(total_sum) || total_sum < 0 || !sell_date) {
    alert("Enter shares sold, total sum received, and a sell date.");
    return;
  }

  const res = await fetch(`${API}/${sellingId}/sell`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shares_sold, total_sum, sell_date, sell_time: sell_time || null, override_price_check: overridePriceCheck }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = err.detail;
    if (detail && typeof detail === "object" && detail.code === "price_sanity") {
      const msg =
        `This works out to a sale price of ${fmt(detail.sale_price)} EUR/share, ` +
        `but ${detail.ticker} was last around ${fmt(detail.ref_price)} EUR/share — ` +
        `off by more than ${detail.factor}×, which usually means the total sum was mistyped ` +
        `(a comma/period mixup). Record it anyway?`;
      if (confirm(msg)) await submitSell(true);
      return;
    }
    alert(`Failed to record sale: ${typeof detail === "string" ? detail : res.statusText}`);
    return;
  }

  closeSellModal();
  await render();
}

function fmtSellDatetime(s) {
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return `${d.toLocaleDateString("de-DE")} ${d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}`;
}

async function loadHistory() {
  const res = await fetch("/api/sales-history");
  const entries = await res.json();
  const body = document.getElementById("history-body");
  const emptyMsg = document.getElementById("history-empty-msg");
  body.innerHTML = "";
  emptyMsg.style.display = entries.length === 0 ? "block" : "none";

  for (const e of entries) {
    const tr = document.createElement("tr");
    const gainClass = e.realized_gain > 0 ? "price-up" : e.realized_gain < 0 ? "price-down" : "";
    tr.innerHTML = `
      <td>${e.ticker}</td>
      <td>${e.shares_sold}</td>
      <td>${fmt(e.cost_basis)}</td>
      <td>${fmt(e.total_spend)}</td>
      <td>${fmt(e.sale_price)}</td>
      <td>${fmt(e.total_sum)}</td>
      <td class="${gainClass}">${fmt(e.realized_gain)}</td>
      <td>${fmt(e.estimated_tax)}</td>
      <td>${fmtSellDatetime(e.sell_datetime)}</td>
      <td><button class="danger" onclick="removeSalesEntry('${e.id}')">Remove</button></td>
    `;
    body.appendChild(tr);
  }
}

async function removeSalesEntry(id) {
  if (!confirm("Remove this history entry? This cannot be undone.")) return;
  await fetch(`/api/sales-history/${id}`, { method: "DELETE" });
  await loadHistory();
}

initInfoTooltips();
loadZacksStatus().then(() => render()).then(() => refreshAllPrices()).then(() => loadPortfolioChart()).then(() => loadConcentration()).then(() => loadBreadth());
