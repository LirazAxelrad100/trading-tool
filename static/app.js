const API = "/api/holdings";

async function fetchHoldings() {
  const res = await fetch(API);
  return res.json();
}

// US market hours (9:30–16:00 ET, Mon–Fri; holidays not accounted for). When closed,
// Finnhub freezes on the last US close, so prices/Today % won't be live — flag it.
function usMarketOpen() {
  const et = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay();
  if (day === 0 || day === 6) return false;
  const mins = et.getHours() * 60 + et.getMinutes();
  return mins >= 9 * 60 + 30 && mins < 16 * 60;
}

// Shown as a hint after a refresh, only while the US market is closed.
function updateMarketStatus() {
  const el = document.getElementById("market-status");
  if (!el) return;
  if (usMarketOpen()) {
    el.style.display = "none";
    el.textContent = "";
  } else {
    el.textContent = "⧗ US market closed — the prices and Today % you just loaded are the last US close, not live. They'll update after US open (~15:30 CET).";
    el.style.display = "block";
  }
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

function zacksCell(ticker) {
  const entry = zacksRanks[ticker];
  if (!entry) return "—";
  return entry.rank === 1 ? `<span class="zacks-rank-1">1</span>` : String(entry.rank);
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

function renderSignals(result) {
  const sig = result.signals || {};
  return (
    renderOppBScore(result.opp_b_score) +
    renderSectorContext(result.sector_context) +
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
        </td>
        <td class="${dayChangeClass(h.day_change_pct)}">${fmtDayChangePct(h.day_change_pct)}</td>
        <td>${fmt(h.total)}</td>
        <td>${fmtPct(h.portfolio_pct)}</td>
        <td>${zacksCell(h.ticker)}</td>
        <td>${exitPlanSelect(h.id, h.exit_plan)}</td>
        <td>
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
      <td>${fmt(h.current_price)}${h.manual_price ? ' <span class="subtitle">(manual)</span>' : ""}</td>
      <td class="${dayChangeClass(h.day_change_pct)}">${h.manual_price ? "—" : fmtDayChangePct(h.day_change_pct)}</td>
      <td class="${gainClass(h)} total-cell" onclick="showUnrealized('${h.id}')">${fmt(h.total)}</td>
      <td>${fmtPct(h.portfolio_pct)}</td>
      <td>${zacksCell(h.ticker)}</td>
      <td>${EXIT_PLAN_LABELS[h.exit_plan]}</td>
      <td>
        ${h.manual_price ? '<span class="subtitle">manual price</span>' : `<button class="secondary" onclick="refreshHolding('${h.id}')">Refresh</button>`}
        <button class="secondary" onclick="openLotsModal('${h.id}')">Lots</button>
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

  const payload = { ticker, stop_price, reference_high, current_price, exit_plan, manual_price };

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
  const exit_plan = document.getElementById("f-exit-plan").value;

  if (!ticker || isNaN(shares) || isNaN(cost_basis) || !purchase_date || isNaN(stop_price)) {
    alert("Fill in ticker, shares, cost basis, purchase date, and stop price.");
    return;
  }

  const payload = { ticker, shares, cost_basis, purchase_date, stop_price, exit_plan };
  if (refRaw) payload.reference_high = parseEuNumber(refRaw);

  await fetch(API, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  ["f-ticker", "f-shares", "f-cost", "f-date", "f-stop", "f-ref"].forEach(
    (id) => (document.getElementById(id).value = "")
  );
  document.getElementById("f-exit-plan").value = "hold";
  await render();
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
    updateMarketStatus();
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh all prices";
  }
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
  return w[field];
}

function renderWatchlist() {
  const body = document.getElementById("watchlist-body");
  const emptyMsg = document.getElementById("watchlist-empty-msg");
  body.innerHTML = "";
  emptyMsg.style.display = watchlist.length === 0 ? "block" : "none";

  const rows = [...watchlist];
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

  for (const field of ["ticker", "score", "move_1w", "move_3m"]) {
    const el = document.getElementById(`watch-arrow-${field}`);
    if (!el) continue;
    el.textContent = field === watchSortField ? (watchSortDir === 1 ? "▲" : "▼") : "";
  }

  for (const w of rows) {
    const tr = document.createElement("tr");
    const scoreText = w.score ? Math.round(w.score.composite * 100) : "—";
    tr.innerHTML = `
      <td><span class="ticker-name" onclick="showWatchConsensus('${w.id}')">${w.ticker}</span></td>
      <td>${w.added_date}</td>
      <td>${w.current_price != null ? fmt(w.current_price) : "—"}</td>
      <td>${scoreText}</td>
      <td>${coloredPct(w.move_1w)}</td>
      <td>${coloredPct(w.move_3m)}</td>
      <td>${zacksCell(w.ticker)}</td>
      <td></td>
      <td>
        <button class="secondary" onclick="analyzeTicker('${w.ticker}')">Analyze</button>
        <button class="secondary" onclick="refreshWatchItem('${w.id}')">Refresh</button>
        <button class="danger" onclick="removeWatchItem('${w.id}')">Remove</button>
      </td>
    `;
    const noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.className = "watch-note-input";
    noteInput.placeholder = "Why this ticker?";
    noteInput.value = w.note || "";
    noteInput.addEventListener("change", () => saveWatchNote(w.id, noteInput.value));
    tr.children[7].appendChild(noteInput);
    body.appendChild(tr);
  }
}

async function saveWatchNote(id, note) {
  await fetch(`/api/watchlist/${id}/note`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  const w = watchlist.find((x) => x.id === id);
  if (w) w.note = note;
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
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) return;
  const btn = document.getElementById("watch-add-btn");
  btn.disabled = true;
  btn.textContent = "Adding…";
  try {
    const res = await fetch("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Failed to add ticker.");
      return;
    }
    input.value = "";
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
loadZacksStatus().then(() => render()).then(() => refreshAllPrices()).then(() => loadPortfolioChart());
