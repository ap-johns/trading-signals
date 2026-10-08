//@lang=wrun-ts
// JS:DCA Kit: the DCA tools from this repo in one indicator, so they take one chart slot.
// Each part has its own settings group and an on/off switch: IA levels, Fib swing, DCA tier.
//
// IA levels (alerts/indicators.py atr_levels): Level 6 is the trailing high over `ia_lookback`
// bars; Levels 5..1 sit 23.6 / 38.2 / 50 / 61.8 / 78.6% below it. Not ATR multiples, despite
// the IA-ATR-Model name. 252 bars = one trading year on a daily chart (use 52 on weekly).
//
// Fib swing (alerts/indicators.py calculate_fib_levels): the swing high is the highest weekly
// high in `fib_lookback` weeks; the swing low is the low that launched the advance into it,
// walking back until an earlier rally of `reversal` off the running minimum marks a separate
// leg. Draws only if the rise is at least `min_gain`. Weekly bars are built from the chart's own
// bars (Monday-start UTC weeks, current week included). Indices use min_gain 20 / reversal 10.
//
// DCA tier card (alerts/fib_score.py tier(), fed as alerts/dca_rank.py feeds it): a corner table
// with the tier the dashboard and digest would give this name today, and the inputs behind it.
//   broken    retraced to or past the swing low
//   caution   weekly OTT bearish, below the 200-day SMA, or no more than 5% above the 200-week EMA
//   favoured  z <= -0.75 and retraced to at least .5 (the digest's buy list)
//   cheap, shallow / quality, not cheap   the trend is fine but one of those two is missing
// z is today's distance from the 200-day SMA against that distance's last 166 values (dca_rank
// fetches the last 365 daily bars, and the SMA exists from the 200th of them).
// The 200-week EMA runs over weekly closes from the first bar the chart has, so a short chart
// history reads it a little differently from yfinance's full history. Use on a daily chart.

param.bool("show_ia", true, { label: "Show IA levels", group: "IA levels" });
param.int("ia_lookback", 252, { min: 20, max: 1000, label: "Lookback (bars) for the trailing high", group: "IA levels" });
param.bool("show_fib", false, { label: "Show fib swing", group: "Fib swing" });
param.int("fib_lookback", 104, { min: 10, max: 1000, label: "Lookback (weeks)", group: "Fib swing" });
param.number("min_gain", 30, { min: 1, max: 500, label: "Minimum swing gain (%)", group: "Fib swing" });
param.number("reversal", 14, { min: 1, max: 100, label: "Earlier-leg reversal (%)", group: "Fib swing" });
param.int("label_gap", 30, { min: 0, max: 200, label: "Fib label distance right of the last bar (bars)", group: "Fib swing" });
param.bool("show_card", true, { label: "Show DCA tier card", group: "DCA tier" });
param.bool("card_trend", false, { label: "Show trend rows (200d, 200w, weekly OTT)", group: "DCA tier" });

// IA ladder: purple stepped lines, prices tagged on the axis.
output("l6", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 6", format: "price", axis_label: true, legend: false });
output("l5", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 5", format: "price", axis_label: true, legend: false });
output("l4", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 4", format: "price", axis_label: true, legend: false });
output("l3", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 3", format: "price", axis_label: true, legend: false });
output("l2", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 2", format: "price", axis_label: true, legend: false });
output("l1", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 1", format: "price", axis_label: true, legend: false });

// Fib swing: data-only coordinates for the run-level lines below.
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
string("tx_l6", { max_bytes: 16 });
string("tx_l5", { max_bytes: 16 });
string("tx_l4", { max_bytes: 16 });
string("tx_l3", { max_bytes: 16 });
string("tx_l2", { max_bytes: 16 });
string("tx_l1", { max_bytes: 16 });

// Fib levels run from the swing low to the right edge; the dotted leg joins the two swing points.
draw.line("sh_line", { x1: "t_low", y1: "sh", x2: "t_end", y2: "sh", color: "#94a3b8", width: 0.5 });
draw.line("f382_line", { x1: "t_low", y1: "f382", x2: "t_end", y2: "f382", color: "#38bdf8", width: 0.5 });
draw.line("f500_line", { x1: "t_low", y1: "f500", x2: "t_end", y2: "f500", color: "#4ade80", width: 0.5 });
draw.line("f618_line", { x1: "t_low", y1: "f618", x2: "t_end", y2: "f618", color: "#f59e0b", width: 1 });
draw.line("f786_line", { x1: "t_low", y1: "f786", x2: "t_end", y2: "f786", color: "#f97316", width: 0.5 });
draw.line("sl_line", { x1: "t_low", y1: "sl", x2: "t_end", y2: "sl", color: "#94a3b8", width: 0.5, line_style: "dashed" });
draw.line("leg", { x1: "t_low", y1: "sl", x2: "t_high", y2: "sh", color: "#94a3b8", width: 0.5, line_style: "dotted" });

// DCA tier card. tier_code follows fib_score.TIER_ORDER (0 favoured .. 4 broken, 5 no swing setup)
// and picks the tier cell's fill; each ok_* is 0 fail, 1 neutral, 2 pass and picks its value's colour.
output("tier_code", none, overlay, { label: "DCA tier (0 favoured, 1 cheap shallow, 2 quality not cheap, 3 caution, 4 broken)" });
output("z", none, overlay, { label: "z-score vs 200d SMA", format: "0.00" });
output("d200", none, overlay, { label: "vs 200d SMA (%)", format: "0.0" });
output("w200", none, overlay, { label: "vs 200w EMA (%)", format: "0.0" });
output("wk_bull", none, overlay, { label: "Weekly OTT (1 bullish, 0 bearish)" });
output("ok_ret", none);
output("ok_z", none);
output("ok_d200", none);
output("ok_w200", none);
output("ok_wk", none);
output("card_rows", none); // 3, or 6 with the trend rows on
string("c_title", { max_bytes: 16 });
string("c_tier", { max_bytes: 24 });
string("c_ret_l", { max_bytes: 16 });
string("c_ret", { max_bytes: 24 });
string("c_z_l", { max_bytes: 16 });
string("c_z", { max_bytes: 16 });
string("c_d200_l", { max_bytes: 16 });
string("c_d200", { max_bytes: 16 });
string("c_w200_l", { max_bytes: 16 });
string("c_w200", { max_bytes: 16 });
string("c_wk_l", { max_bytes: 16 });
string("c_wk", { max_bytes: 16 });
render.table("dca_card", {
  rows: 6,
  cols: 2,
  rows_by: "card_rows",
  cells: ["c_title", "c_tier", "c_ret_l", "c_ret", "c_z_l", "c_z", "c_d200_l", "c_d200", "c_w200_l", "c_w200", "c_wk_l", "c_wk"],
  position: "top_center",
  offset: [0, 4],
  column_widths: [72, 0],
  cell_padding: 3,
  font_size: 9,
  align: "right",
  text_color: "#e2e8f0",
  background_color: "#0f172a",
  background_opacity: 0.85,
  border_color: "#475569",
  border_width: 1,
  corner_radius: 4,
  grid_color: "#334155",
  grid_width: 1,
  grid_lines: "rows",
  styles: [
    { cell: "c_title", align: "left", font_weight: "bold" },
    { cell: "c_tier", font_weight: "bold", color_by: "tier_code", colors: ["#15803d", "#0f766e", "#1d4ed8", "#b45309", "#b91c1c", "#334155"], opacity: 0.8 },
    { cell: "c_ret_l", align: "left" },
    { cell: "c_z_l", align: "left" },
    { cell: "c_d200_l", align: "left" },
    { cell: "c_w200_l", align: "left" },
    { cell: "c_wk_l", align: "left" },
    { cell: "c_ret", text_color_by: "ok_ret", text_colors: ["#f87171", "#e2e8f0", "#4ade80"] },
    { cell: "c_z", text_color_by: "ok_z", text_colors: ["#f87171", "#e2e8f0", "#4ade80"] },
    { cell: "c_d200", text_color_by: "ok_d200", text_colors: ["#f87171", "#e2e8f0", "#4ade80"] },
    { cell: "c_w200", text_color_by: "ok_w200", text_colors: ["#f87171", "#e2e8f0", "#4ade80"] },
    { cell: "c_wk", text_color_by: "ok_wk", text_colors: ["#f87171", "#e2e8f0", "#4ade80"] },
  ],
});

// Labels are handles: a declared label centres on its x, a handle with align: "left" starts its
// text at x, so each tag begins just past the end of its line instead of sitting on it.
handles.label({ text: "summary", color: "#e5e7eb", style: "plain", align: "left" });
const info = draw.label(0);
const tagSh = draw.label(1);
const tag382 = draw.label(2);
const tag500 = draw.label(3);
const tag618 = draw.label(4);
const tag786 = draw.label(5);
const tagSl = draw.label(6);
const tagL6 = draw.label(7);
const tagL5 = draw.label(8);
const tagL4 = draw.label(9);
const tagL3 = draw.label(10);
const tagL2 = draw.label(11);
const tagL1 = draw.label(12);

const MAX_WEEKS: i32 = 1100; // ring size, above the fib lookback cap
const wkHigh = new StaticArray<f64>(MAX_WEEKS);
const wkLow = new StaticArray<f64>(MAX_WEEKS);
const wkHighT = new StaticArray<f64>(MAX_WEEKS); // time of the bar that set the week's high
const wkLowT = new StaticArray<f64>(MAX_WEEKS);
let weeks: i32 = 0;
let curWeek: f64 = NaN;
let lastT: f64 = NaN;
let interval: f64 = NaN;
let highs = new Highest(252);
let showIa: bool = true;
let showFib: bool = false;
let fibLookback: i32 = 104;
let minGain: f64 = 0.30;
let reversal: f64 = 0.14;
let labelGap: f64 = 30.0;
let showCard: bool = true;
let cardTrend: bool = false;

// Daily ring for the 200-day SMA and the z-score sample.
const RING: i32 = 400;
const dClose = new StaticArray<f64>(RING);
const dPc = new StaticArray<f64>(RING); // % above the 200-day SMA, NaN before it exists
let bars: i32 = 0;
let sum200: f64 = 0.0;

// 200-week EMA of weekly closes (pandas ewm(span=200, adjust=False), seeded at the first close).
const W_ALPHA: f64 = 2.0 / 201.0;
let emaDone: f64 = NaN; // through the last completed week
let wkClose: f64 = NaN; // the forming week's close so far

class Ott {
  period: i32;
  percent: f64;
  valpha: f64;
  n: i32 = 0;
  prevSrc: f64 = NaN;
  ud: StaticArray<f64> = new StaticArray<f64>(9);
  dd: StaticArray<f64> = new StaticArray<f64>(9);
  cur: i32 = 0;
  mavg: f64 = 0.0;
  prevMavg: f64 = NaN;
  longStop: f64 = 0.0;
  shortStop: f64 = 0.0;
  dir: i32 = 1;
  ott1: f64 = NaN; // raw OTT one bar ago
  ott2: f64 = NaN; // raw OTT two bars ago
  ottShift: f64 = NaN; // OTT[2], what is plotted and crossed
  prevOttShift: f64 = NaN;
  signal: i32 = 0; // 1 buy, -1 sell, 0 none

  constructor(period: i32, percent: f64) {
    this.period = period;
    this.percent = percent;
    this.valpha = 2.0 / (f64(period) + 1.0);
  }

  update(src: f64): void {
    this.signal = 0;
    this.prevMavg = this.mavg;

    // VAR: CMO over 9-bar sums of up and down moves (a partial window early, like min_periods=1).
    let up = 0.0;
    let dn = 0.0;
    if (this.n > 0) {
      const d = src - this.prevSrc;
      if (d > 0.0) up = d;
      if (d < 0.0) dn = -d;
    }
    this.prevSrc = src;
    this.ud[this.cur] = up;
    this.dd[this.cur] = dn;
    this.cur = (this.cur + 1) % 9;
    let sumU = 0.0;
    let sumD = 0.0;
    for (let i = 0; i < 9; i++) { sumU += this.ud[i]; sumD += this.dd[i]; }
    if (this.n > 0) {
      const total = sumU + sumD;
      const cmo = total != 0.0 ? Math.abs((sumU - sumD) / total) : 0.0;
      const a = this.valpha * cmo;
      this.mavg = a * src + (1.0 - a) * this.mavg;
    }

    // Trailing stop: the long stop only ratchets up, the short stop only down.
    const fark = this.mavg * this.percent * 0.01;
    const ls = this.mavg - fark;
    const ss = this.mavg + fark;
    if (this.n == 0) {
      this.longStop = ls;
      this.shortStop = ss;
    } else {
      const prevL = this.longStop;
      const prevS = this.shortStop;
      this.longStop = this.mavg > prevL ? Math.max(ls, prevL) : ls;
      this.shortStop = this.mavg < prevS ? Math.min(ss, prevS) : ss;
      if (this.dir == -1 && this.mavg > prevS) this.dir = 1;
      else if (this.dir == 1 && this.mavg < prevL) this.dir = -1;
    }
    const mt = this.dir == 1 ? this.longStop : this.shortStop;
    const ott = this.mavg > mt ? mt * (200.0 + this.percent) / 200.0 : mt * (200.0 - this.percent) / 200.0;

    // Shift by two bars, then look for a crossover of MAvg through OTT[2].
    this.prevOttShift = this.ottShift;
    this.ottShift = this.n >= 2 ? this.ott2 : NaN;
    this.ott2 = this.ott1;
    this.ott1 = ott;
    if (this.n >= 3 && !isNaN(this.ottShift) && !isNaN(this.prevOttShift)) {
      const above = this.mavg > this.ottShift;
      const wasAbove = this.prevMavg > this.prevOttShift;
      const below = this.mavg < this.ottShift;
      const wasBelow = this.prevMavg < this.prevOttShift;
      if (above && !wasAbove) this.signal = 1;
      else if (below && !wasBelow) this.signal = -1;
    }
    this.n += 1;
  }
}

let weekly = new Ott(10, 3.0);
const WARMUP_WEEKS: i32 = 52;

function slot(i: i32): i32 { return i % MAX_WEEKS; }

function onStart(): void {
  showIa = pb_show_ia();
  showFib = pb_show_fib();
  highs = new Highest(i32(p_ia_lookback()));
  fibLookback = i32(p_fib_lookback());
  minGain = p_min_gain() / 100.0;
  reversal = p_reversal() / 100.0;
  labelGap = p_label_gap();
  showCard = pb_show_card();
  cardTrend = pb_card_trend();
}

function clearFib(): void {
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

  // IA ladder: the window high over the last ia_lookback bars, this bar included.
  const anchor = highs.update(h);
  const iaReady = showIa && !isNaN(anchor) && anchor > 0.0;
  if (iaReady) {
    out_l6(anchor);
    out_l5(anchor * (1.0 - 0.236));
    out_l4(anchor * (1.0 - 0.382));
    out_l3(anchor * (1.0 - 0.5));
    out_l2(anchor * (1.0 - 0.618));
    out_l1(anchor * (1.0 - 0.786));
  }

  // Fold this bar into its Monday-start UTC week (day 0 = Thursday 1970-01-01, so +3).
  const week = Math.floor((Math.floor(t / 86400.0) + 3.0) / 7.0);
  if (week != curWeek) {
    curWeek = week;
    if (!isNaN(wkClose)) emaDone = isNaN(emaDone) ? wkClose : emaDone + W_ALPHA * (wkClose - emaDone);
    if (!isNaN(bar.open())) weekly.update(bar.open()); // dca_rank's weekly OTT runs on weekly opens
    const s = slot(weeks);
    wkHigh[s] = h; wkLow[s] = l; wkHighT[s] = t; wkLowT[s] = t;
    weeks += 1;
  } else {
    const s = slot(weeks - 1);
    if (h > wkHigh[s]) { wkHigh[s] = h; wkHighT[s] = t; }
    if (l < wkLow[s]) { wkLow[s] = l; wkLowT[s] = t; }
  }
  const close = bar.close();
  wkClose = close;

  // 200-day SMA and the close's % distance from it.
  const r = bars % RING;
  if (bars >= 200) sum200 -= dClose[(bars - 200) % RING];
  dClose[r] = close;
  sum200 += close;
  bars += 1;
  const sma200 = bars >= 200 ? sum200 / 200.0 : NaN;
  dPc[r] = isNaN(sma200) ? NaN : (close - sma200) / sma200 * 100.0;

  // Labels and the fib swing are properties of the newest bar.
  if (!bar.isLast() || isNaN(interval)) return;

  if (iaReady) {
    const purple = rgba(168, 85, 247, 255);
    const ix = t + interval;
    sb_clear(); sb_text("Level 6"); tagL6.set(ix, anchor).text(str_tx_l6_sb).color(purple).style(LabelStyle.Knockout);
    sb_clear(); sb_text("Level 5"); tagL5.set(ix, anchor * (1.0 - 0.236)).text(str_tx_l5_sb).color(purple).style(LabelStyle.Knockout);
    sb_clear(); sb_text("Level 4"); tagL4.set(ix, anchor * (1.0 - 0.382)).text(str_tx_l4_sb).color(purple).style(LabelStyle.Knockout);
    sb_clear(); sb_text("Level 3"); tagL3.set(ix, anchor * (1.0 - 0.5)).text(str_tx_l3_sb).color(purple).style(LabelStyle.Knockout);
    sb_clear(); sb_text("Level 2"); tagL2.set(ix, anchor * (1.0 - 0.618)).text(str_tx_l2_sb).color(purple).style(LabelStyle.Knockout);
    sb_clear(); sb_text("Level 1"); tagL1.set(ix, anchor * (1.0 - 0.786)).text(str_tx_l1_sb).color(purple).style(LabelStyle.Knockout);
  }

  clearFib();
  let frac: f64 = NaN; // NaN = no swing setup, as dca_rank skips the name
  if (showFib || showCard) frac = swing(t);
  if (showCard) card(close, sma200, frac);
}

// Finds the weekly swing; draws it if show_fib is on. Returns the retracement fraction.
function swing(t: f64): f64 {
  const n = weeks < fibLookback ? weeks : fibLookback;
  if (n < 2) return NaN;
  const start = weeks - n;

  // Swing high: the window's highest weekly high, earliest week on a tie (pandas idxmax).
  let sh: f64 = -Infinity;
  let iH: i32 = start;
  for (let i = start; i < weeks; i++) {
    const v = wkHigh[slot(i)];
    if (v > sh) { sh = v; iH = i; }
  }
  if (iH - start + 1 < 2) return NaN;

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
  if (sl <= 0.0 || sh <= sl) return NaN;
  const gain = (sh - sl) / sl;
  if (gain < minGain) return NaN;

  const span = sh - sl;
  const frac = (sh - bar.close()) / span; // 0 at the high, 1 at the swing low
  if (!showFib) return frac;
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

  // Fib tags start one bar past the line ends, coloured to match their lines (0 = high, 1 = low).
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
  return frac;
}

function signed(v: f64, decimals: i32): void {
  if (v >= 0.0) sb_text("+");
  sb_f64(v, decimals);
}

// The DCA tier card: fib_score.tier() over the same inputs dca_rank.py computes.
function card(close: f64, sma200: f64, frac: f64): void {
  // z: today's 200d distance against its last 166 values. dca_rank fetches the last 365 bars and
  // the 200-day SMA first exists on the 200th, so 166 is the most it ever has (fewer on a young chart).
  const n = bars < 365 ? bars - 199 : 166;
  let z: f64 = NaN;
  if (n > 1) {
    let sum = 0.0;
    for (let i = bars - n; i < bars; i++) sum += dPc[i % RING];
    const mean = sum / f64(n);
    let ss = 0.0;
    for (let i = bars - n; i < bars; i++) { const d = dPc[i % RING] - mean; ss += d * d; }
    const sd = Math.sqrt(ss / f64(n - 1));
    if (sd > 0.0) z = (dPc[(bars - 1) % RING] - mean) / sd;
  }
  const d200 = isNaN(sma200) ? NaN : (close - sma200) / sma200 * 100.0;
  // The forming week's close moves the EMA, as yfinance's current weekly bar does; needs 104 weeks.
  const ema = isNaN(emaDone) ? close : emaDone + W_ALPHA * (close - emaDone);
  const w200 = weeks >= 104 ? (close - ema) / ema * 100.0 : NaN;
  const wkReady = weekly.n > WARMUP_WEEKS && !isNaN(weekly.ottShift);
  const bull = wkReady && weekly.mavg > weekly.ottShift;

  // fib_score.tier()
  const hasSwing = !isNaN(frac);
  const cheap = !isNaN(z) && z <= -0.75;
  const deep = hasSwing && frac >= 0.5;
  let code: i32 = 5;
  if (hasSwing) {
    if (frac >= 1.0) code = 4;
    else if (!bull || (!isNaN(d200) && d200 < 0.0) || (!isNaN(w200) && w200 <= 5.0)) code = 3;
    else if (cheap && deep) code = 0;
    else if (cheap) code = 1;
    else code = 2;
  }
  out_tier_code(f64(code));
  out_z(z);
  out_d200(d200);
  out_w200(w200);
  out_wk_bull(wkReady ? (bull ? 1.0 : 0.0) : NaN);
  out_ok_ret(!hasSwing ? 1.0 : (frac >= 1.0 ? 0.0 : (deep ? 2.0 : 1.0)));
  out_ok_z(cheap ? 2.0 : 1.0);
  out_ok_d200(isNaN(d200) ? 1.0 : (d200 < 0.0 ? 0.0 : 2.0));
  out_ok_w200(isNaN(w200) ? 1.0 : (w200 <= 5.0 ? 0.0 : 2.0));
  out_ok_wk(!wkReady ? 1.0 : (bull ? 2.0 : 0.0));
  // The trend rows only matter when they fail, so a Caution tier shows them whatever the setting.
  out_card_rows(cardTrend || code == 3 ? 6.0 : 3.0);

  str_c_title("DCA tier");
  if (code == 0) str_c_tier("Favoured");
  else if (code == 1) str_c_tier("Cheap, shallow");
  else if (code == 2) str_c_tier("Quality, not cheap");
  else if (code == 3) str_c_tier("Caution");
  else if (code == 4) str_c_tier("Broken");
  else str_c_tier("No swing setup");

  str_c_ret_l("Retraced");
  if (!hasSwing) str_c_ret("-");
  else {
    sb_clear(); sb_f64(frac * 100.0, 0); sb_text("%");
    if (frac >= 0.786) sb_text(" (.786)");
    else if (frac >= 0.618) sb_text(" (.618)");
    else if (frac >= 0.5) sb_text(" (.5)");
    else if (frac >= 0.382) sb_text(" (.382)");
    str_c_ret_sb();
  }
  str_c_z_l("z vs 200d");
  if (isNaN(z)) str_c_z("-"); else { sb_clear(); signed(z, 2); str_c_z_sb(); }
  str_c_d200_l("vs 200d SMA");
  if (isNaN(d200)) str_c_d200("-"); else { sb_clear(); signed(d200, 1); sb_text("%"); str_c_d200_sb(); }
  str_c_w200_l("vs 200w EMA");
  if (isNaN(w200)) str_c_w200("-"); else { sb_clear(); signed(w200, 0); sb_text("%"); str_c_w200_sb(); }
  str_c_wk_l("Weekly OTT");
  str_c_wk(!wkReady ? "warming up" : (bull ? "bullish" : "bearish"));
}
