#!/usr/bin/env node
/**
 * Copy review — see every ticker's generated text at once, instead of clicking through.
 *
 * Three checks, all deterministic and all free (reads stored data, calls no API):
 *
 *   1. SNAPSHOT   prints the rendered text per ticker so a whole screen can be scanned.
 *   2. INVARIANCE flags any line that is byte-identical for every ticker. Per-item copy that
 *                 never varies is not about the item — this is exactly the fault behind
 *                 "Your holdings already include one bloc..." and "is the stock swimming
 *                 with or against its sector's tide?", both of which read as facts about
 *                 the stock while being the same sentence every time.
 *   3. JARGON     flags finance vocabulary that assumes the reader already knows it.
 *
 * None of this is an eval. Evals are for output you cannot predict; this text is written in
 * app.js and always renders the same way, so a snapshot and a couple of assertions cover it
 * at a fraction of the cost. Evals belong on the LLM prose in synthesis.py, which this
 * deliberately does not touch.
 *
 *   node tools/copy_review.js
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");
const read = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, "data", f), "utf8"));

// app.js is browser-global script, so give it just enough DOM to parse and define functions.
const stubEl = new Proxy(
  {},
  { get: () => () => stubEl, set: () => true }
);
const sandbox = {
  document: {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => stubEl,
    addEventListener: () => {},
  },
  window: {},
  fetch: () => Promise.reject(new Error("copy_review does not call the network")),
  alert: () => {},
  console,
  setTimeout,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ROOT, "static", "app.js"), "utf8"), sandbox);
// `const`/`let` at the top level of a script do not become properties of the context object,
// so reach them by evaluating inside it instead.
const evalIn = (expr) => vm.runInContext(expr, sandbox);

const strip = (html) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();

const watchlist = read("watchlist.json");
sandbox.watchlist = watchlist;
sandbox.lastHoldings = read("holdings.json");

// Part 1 — real data, one line per ticker.
const SURFACES = [
  { name: "Watch List row — since added", render: (w) => sandbox.sinceAddedCell(w) },
  {
    name: "Pre-buy context",
    render: (w) => {
      sandbox.riskTicker = w;
      const bits = [];
      if (typeof w.move_3m === "number" && w.move_3m <= -20) {
        bits.push(`down ${Math.abs(w.move_3m).toFixed(1)}% over 3 months — bet on a turn`);
      }
      for (const tag of sandbox.watchHashtags(w)) {
        const peers = watchlist.filter((x) => x.id !== w.id && sandbox.watchHashtags(x).includes(tag));
        if (!peers.length) continue;
        const stage = evalIn(
          `themeStage(avg(${JSON.stringify(peers.map((x) => x.move_12m))}), avg(${JSON.stringify(
            peers.map((x) => x.move_3m)
          )}))`
        );
        if (stage) bits.push(`${tag}: ${evalIn(`THEME_STAGES[${JSON.stringify(stage)}].label`)}`);
      }
      return bits.join(" | ");
    },
  },
];

// Part 2 — every branch of the badge copy, from synthetic inputs. This needs no data and no
// API call, and it is where the real value is: a case matrix shows all the wording side by
// side, which is how "It can't say whether a fall is over" was caught sitting on a stock that
// had risen 74%. Clicking through real tickers would only have shown that by luck.
const CASES = [
  ["risen hard, profits up more", { price_12m_pct: 9, eps_growth_pct: 42, price_3m_pct: -45, pct_from_52w_high: -46, multiple_change_pct: -23, quadrant: "in_line" }],
  ["risen hard, price outran profits", { price_12m_pct: 74, eps_growth_pct: 42, price_3m_pct: 21, pct_from_52w_high: -5, multiple_change_pct: 22, quadrant: "in_line" }],
  ["flat multiple, deep drawdown", { price_12m_pct: 59, eps_growth_pct: 51, price_3m_pct: -52, pct_from_52w_high: -52, multiple_change_pct: 6, quadrant: "in_line" }],
  ["price down, profits up", { price_12m_pct: -20, eps_growth_pct: 30, price_3m_pct: -25, pct_from_52w_high: -35, multiple_change_pct: -38, quadrant: "divergence" }],
  ["both falling", { price_12m_pct: -30, eps_growth_pct: -15, price_3m_pct: -20, pct_from_52w_high: -40, multiple_change_pct: -18, quadrant: "both_falling" }],
  ["price up, profits down", { price_12m_pct: 25, eps_growth_pct: -10, price_3m_pct: 5, pct_from_52w_high: -2, multiple_change_pct: 39, quadrant: "multiple_expansion" }],
  ["profits rebounding off zero", { price_12m_pct: 57, eps_growth_pct: 744, price_3m_pct: -2, pct_from_52w_high: -21, multiple_change_pct: -81, quadrant: "in_line", eps_base_distorted: true }],
  ["no drawdown at all", { price_12m_pct: 40, eps_growth_pct: 35, price_3m_pct: 12, pct_from_52w_high: -1, multiple_change_pct: 4, quadrant: "in_line" }],
];

const JARGON = [
  "VGM", "P/E", "multiple expansion", "price action", "basis points", "alpha", "beta",
  "valuation of each dollar", "EPS", "TTM", "YoY", "drawdown", "relative strength",
];

let invarianceFailures = 0;
let jargonFailures = 0;

for (const surface of SURFACES) {
  console.log(`\n${"=".repeat(72)}\n${surface.name}\n${"=".repeat(72)}`);
  const rendered = new Map();
  for (const w of watchlist) {
    let text = "";
    try {
      text = strip(surface.render(w) || "");
    } catch (e) {
      text = `<render error: ${e.message}>`;
    }
    rendered.set(w.ticker, text);
    console.log(`  ${w.ticker.padEnd(6)} ${text || "(empty)"}`);
  }

  const nonEmpty = [...rendered.values()].filter(Boolean);
  const distinct = new Set(nonEmpty);
  if (nonEmpty.length > 2 && distinct.size === 1) {
    console.log(`\n  ⚠ INVARIANCE: identical for all ${nonEmpty.length} tickers — this is not about the ticker.`);
    invarianceFailures++;
  }
  for (const [ticker, text] of rendered) {
    const hits = JARGON.filter((j) => text.toLowerCase().includes(j.toLowerCase()));
    if (hits.length) {
      console.log(`  ⚠ JARGON in ${ticker}: ${hits.join(", ")}`);
      jargonFailures++;
    }
  }
}

console.log(`\n${"=".repeat(72)}\nPrice vs. profits — every branch of the copy\n${"=".repeat(72)}`);
for (const [label, f] of CASES) {
  const text = strip(sandbox.renderFundamentals(f));
  console.log(`\n  ${label}\n    ${text}`);
  const hits = JARGON.filter((j) => text.toLowerCase().includes(j.toLowerCase()));
  if (hits.length) {
    console.log(`    ⚠ JARGON: ${hits.join(", ")}`);
    jargonFailures++;
  }
  // A caveat about a fall has no business on a case that has not fallen.
  if (f.pct_from_52w_high > -25 && /whether a fall is over/.test(text)) {
    console.log("    ⚠ NON-SEQUITUR: fall caveat on a case with no meaningful fall");
    invarianceFailures++;
  }
}

console.log(
  `\n${"=".repeat(72)}\n${invarianceFailures} structural warning(s), ${jargonFailures} jargon warning(s).`
);
console.log("The LLM prose in synthesis.py is not covered here — unpredictable output needs evals, not a snapshot.");
process.exit(invarianceFailures ? 1 : 0);
