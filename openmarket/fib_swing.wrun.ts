//@lang=wrun-ts
// Weekly swing fib retracement, ported from alerts/indicators.py calculate_fib_levels().
// The swing high is the highest weekly high in the lookback. The swing low is the low that
// launched the advance into it: walking back from the high, the running-minimum low extends to
// any lower low, and the walk stops at the first earlier rally of `reversal` off that minimum.
// The setup only draws if the low-to-high rise is at least `min_gain`. Levels are measured down
// from the high, as in the dashboard fib table and the DCA digest.
// Weekly bars are built from the chart's own bars (Monday-start UTC weeks, current week
// included, like yfinance), so it reads the same on a daily or weekly chart.
// Indices use min_gain 20 / reversal 10 in config.json; stocks use the defaults below.

param.int("lookback", 104, { min: 10, max: 1000, label: "Lookback (weeks)" });
param.number("min_gain", 30, { min: 1, max: 500, label: "Minimum swing gain (%)" });
param.number("reversal", 14, { min: 1, max: 100, label: "Earlier-leg reversal (%)" });
param.int("label_gap", 30, { min: 0, max: 200, label: "Label distance right of the last bar (bars)" });

output("sh", none, overlay, { label: "Swing high", format: "price" });
output("f382", none, overlay, { label: ".382", format: "price" });
output("f500", none, overlay, { label: ".5", format: "price" });
output("f618", none, overlay, { label: ".618", format: "price" });
output("f786", none, overlay, { label: ".786", format: "price" });
output("sl", none, overlay, { label: "Swing low", format: "price" });
output("t_low", none, overlay, { label: "Swing low time" });
output("t_high", none, overlay, { label: "Swing high time" });
output("t_end", none, overlay, { label: "Right edge time" });
output("retrace", none, overlay, { label: "Retraced (%)", format: "0.0" });
string("summary", { max_bytes: 96 });
string("tx_sh", { max_bytes: 32 });
string("tx_382", { max_bytes: 32 });
string("tx_500", { max_bytes: 32 });
string("tx_618", { max_bytes: 32 });
string("tx_786", { max_bytes: 32 });
string("tx_sl", { max_bytes: 32 });

// Levels run from the swing low to the right edge; the dotted leg joins the two swing points.
draw.line("sh_line", { x1: "t_low", y1: "sh", x2: "t_end", y2: "sh", color: "#94a3b8", width: 0.5 });
draw.line("f382_line", { x1: "t_low", y1: "f382", x2: "t_end", y2: "f382", color: "#38bdf8", width: 0.5 });
draw.line("f500_line", { x1: "t_low", y1: "f500", x2: "t_end", y2: "f500", color: "#4ade80", width: 0.5 });
draw.line("f618_line", { x1: "t_low", y1: "f618", x2: "t_end", y2: "f618", color: "#f59e0b", width: 1 });
draw.line("f786_line", { x1: "t_low", y1: "f786", x2: "t_end", y2: "f786", color: "#f97316", width: 0.5 });
draw.line("sl_line", { x1: "t_low", y1: "sl", x2: "t_end", y2: "sl", color: "#94a3b8", width: 0.5, line_style: "dashed" });
draw.line("leg", { x1: "t_low", y1: "sl", x2: "t_high", y2: "sh", color: "#94a3b8", width: 0.5, line_style: "dotted" });
// Labels are handles: a declared label centres on its x, a handle with align: "left" starts
// its text at x. The summary sits just above the swing-high line from the swing low's date;
// the TradingView-style level tags (ratio (price), 0 = high, 1 = low) start just past each line's end.
handles.label({ text: "summary", color: "#e5e7eb", style: "plain", align: "left" });
const info = draw.label(0);
const tagSh = draw.label(1);
const tag382 = draw.label(2);
const tag500 = draw.label(3);
const tag618 = draw.label(4);
const tag786 = draw.label(5);
const tagSl = draw.label(6);

const MAX_WEEKS: i32 = 1100; // ring size, above the lookback cap
const wkHigh = new StaticArray<f64>(MAX_WEEKS);
const wkLow = new StaticArray<f64>(MAX_WEEKS);
const wkHighT = new StaticArray<f64>(MAX_WEEKS); // time of the bar that set the week's high
const wkLowT = new StaticArray<f64>(MAX_WEEKS);
let weeks: i32 = 0;
let curWeek: f64 = NaN;
let lastT: f64 = NaN;
let interval: f64 = NaN;
let lookback: i32 = 104;
let minGain: f64 = 0.30;
let reversal: f64 = 0.14;
let labelGap: f64 = 30.0;

function slot(i: i32): i32 { return i % MAX_WEEKS; }

function onStart(): void {
  lookback = i32(p_lookback());
  minGain = p_min_gain() / 100.0;
  reversal = p_reversal() / 100.0;
  labelGap = p_label_gap();
}

function clearSetup(): void {
  out_sh(NaN); out_f382(NaN); out_f500(NaN); out_f618(NaN); out_f786(NaN); out_sl(NaN);
  out_t_low(NaN); out_t_high(NaN); out_t_end(NaN); out_retrace(NaN);
}

function onBar(): void {
  const t = bar.time();
  const h = bar.high();
  const l = bar.low();
  if (isNaN(h) || isNaN(l)) return;
  if (!isNaN(lastT) && t > lastT) {
    const gap = t - lastT;
    if (isNaN(interval) || gap < interval) interval = gap;
  }
  lastT = t;

  // Fold this bar into its Monday-start UTC week (day 0 = Thursday 1970-01-01, so +3).
  const week = Math.floor((Math.floor(t / 86400.0) + 3.0) / 7.0);
  if (week != curWeek) {
    curWeek = week;
    const s = slot(weeks);
    wkHigh[s] = h; wkLow[s] = l; wkHighT[s] = t; wkLowT[s] = t;
    weeks += 1;
  } else {
    const s = slot(weeks - 1);
    if (h > wkHigh[s]) { wkHigh[s] = h; wkHighT[s] = t; }
    if (l < wkLow[s]) { wkLow[s] = l; wkLowT[s] = t; }
  }

  // The swing is a property of the newest bar: run-level drawings read only that row.
  if (!bar.isLast()) return;
  clearSetup();
  const n = weeks < lookback ? weeks : lookback;
  if (n < 2 || isNaN(interval)) return;
  const start = weeks - n;

  // Swing high: the window's highest weekly high, earliest week on a tie (pandas idxmax).
  let sh: f64 = -Infinity;
  let iH: i32 = start;
  for (let i = start; i < weeks; i++) {
    const v = wkHigh[slot(i)];
    if (v > sh) { sh = v; iH = i; }
  }
  if (iH - start + 1 < 2) return;

  // Walk back from the high's week for the launch low of the advance.
  let runMin = wkLow[slot(iH)];
  let sl = runMin;
  let iL = iH;
  for (let i = iH - 1; i >= start; i--) {
    const v = wkLow[slot(i)];
    if (v < runMin) {
      runMin = v; sl = v; iL = i;
    } else if (runMin > 0.0 && (v - runMin) / runMin >= reversal) {
      break; // an earlier rally of >= reversal off the running min: a separate leg
    }
  }
  if (sl <= 0.0 || sh <= sl) return;
  const gain = (sh - sl) / sl;
  if (gain < minGain) return;

  const span = sh - sl;
  const frac = (sh - bar.close()) / span; // 0 at the high, 1 at the swing low
  out_sh(sh);
  out_f382(sh - 0.382 * span);
  out_f500(sh - 0.5 * span);
  out_f618(sh - 0.618 * span);
  out_f786(sh - 0.786 * span);
  out_sl(sl);
  out_t_low(wkLowT[slot(iL)]);
  out_t_high(wkHighT[slot(iH)]);
  out_t_end(t + labelGap * interval);
  out_retrace(frac * 100.0);

  // Level tags start one bar past the line ends, coloured to match their lines.
  const tx = t + (labelGap + 1.0) * interval;
  sb_clear(); sb_text("0 ("); sb_f64(sh, 2); sb_text(")");
  tagSh.set(tx, sh).text(str_tx_sh_sb).color(rgba(148, 163, 184, 255));
  sb_clear(); sb_text("0.382 ("); sb_f64(sh - 0.382 * span, 2); sb_text(")");
  tag382.set(tx, sh - 0.382 * span).text(str_tx_382_sb).color(rgba(56, 189, 248, 255));
  sb_clear(); sb_text("0.5 ("); sb_f64(sh - 0.5 * span, 2); sb_text(")");
  tag500.set(tx, sh - 0.5 * span).text(str_tx_500_sb).color(rgba(74, 222, 128, 255));
  sb_clear(); sb_text("0.618 ("); sb_f64(sh - 0.618 * span, 2); sb_text(")");
  tag618.set(tx, sh - 0.618 * span).text(str_tx_618_sb).color(rgba(245, 158, 11, 255));
  sb_clear(); sb_text("0.786 ("); sb_f64(sh - 0.786 * span, 2); sb_text(")");
  tag786.set(tx, sh - 0.786 * span).text(str_tx_786_sb).color(rgba(249, 115, 22, 255));
  sb_clear(); sb_text("1 ("); sb_f64(sl, 2); sb_text(")");
  tagSl.set(tx, sl).text(str_tx_sl_sb).color(rgba(148, 163, 184, 255));

  // Deepest level the pullback has reached, as fib_score.level_reached() reports it.
  sb_clear();
  sb_text("swing +"); sb_f64(gain * 100.0, 0);
  sb_text("%  retraced "); sb_f64(frac * 100.0, 0); sb_text("%");
  if (frac >= 0.786) sb_text("  past .786");
  else if (frac >= 0.618) sb_text("  .618 reached");
  else if (frac >= 0.5) sb_text("  .5 reached");
  else if (frac >= 0.382) sb_text("  .382 reached");
  info.set(wkLowT[slot(iL)], sh + 0.04 * span).text(str_summary_sb);
}
