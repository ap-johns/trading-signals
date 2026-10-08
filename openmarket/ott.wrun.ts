//@lang=wrun-ts
// OTT (Optimized Trend Tracker), ported from alerts/indicators.py calculate_ott(), itself an exact
// replication of KivancOzbilgic's Pine Script. Same settings as config.json: source = Open,
// period 10, percent 3.
//   MAvg = VAR (variable index dynamic average) of the open, seeded at 0 like Pine's nz(VAR[1]).
//   A trailing stop ratchets under MAvg in an uptrend and over it in a downtrend; OTT is that stop
//   nudged by percent/2. The plotted OTT is shifted 2 bars (OTT[2]), and buy/sell fire only on
//   the bar MAvg crosses it, exactly as the daily Telegram alerts do.
// The weekly OTT (the digest's "weekly trend intact" gate, +3 in the favorability score) runs the
// same engine on Monday-start UTC weeks built from the chart's own bars, fed each week's open.
// It is drawn as a stepped line, green while weekly MAvg is above it and red below.

param.int("period", 10, { min: 2, max: 100, label: "OTT period" });
param.number("percent", 3, { min: 0.1, max: 20, label: "OTT percent" });
param.bool("show_weekly", true, { label: "Show weekly OTT" });

// The two lines start hidden (the fill alone shows the trend); switch them on in the Style tab.
output("mavg", line, overlay, { color: "#0585E1", width: 1, label: "MAvg", format: "price", visible: false });
output("ott", line, overlay, { color: "#B800D9", width: 2, label: "OTT", format: "price", visible: false });
output("d_regime", none, overlay, { label: "Daily trend (1 up, 0 down)" });
// Shade between MAvg and OTT: green while MAvg is above OTT (uptrend), red below.
fill("mavg", "ott", { color_by: "d_regime", colors: ["#ef4444", "#22c55e"], opacity: 0.15 });
output("wk_ott", line, overlay, { color_by: "wk_regime", colors: ["#ef4444", "#22c55e"], width: 1, step: true, line_style: "dashed", label: "Weekly OTT", format: "price" });
output("wk_regime", none, overlay, { label: "Weekly trend (1 bullish, 0 bearish)" });
output("buy", shape, overlay, { shape: "triangle_up", location: "below_bar", width: 12, color: "#22c55e", shape_where: "is_buy", label: "OTT buy" });
output("sell", shape, overlay, { shape: "triangle_down", location: "above_bar", width: 12, color: "#ef4444", shape_where: "is_sell", label: "OTT sell" });
const isBuy = output("is_buy", none);
const isSell = output("is_sell", none);
alert("ott_buy", { when: isBuy, message: "{{symbol}}: OTT buy at {{close}}", description: "Daily OTT buy (MAvg crossed above OTT)" });
alert("ott_sell", { when: isSell, message: "{{symbol}}: OTT sell at {{close}}", description: "Daily OTT sell (MAvg crossed below OTT)" });

string("wk_text", { max_bytes: 32 });
handles.label({ text: "wk_text", color: "#e5e7eb", style: "plain", align: "left" });
const wkTag = draw.label(0);

// VAR starts from 0, so the first bars climb from nothing; hide them until it has converged.
const WARMUP_BARS: i32 = 100;
const WARMUP_WEEKS: i32 = 52;

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

let daily = new Ott(10, 3.0);
let weekly = new Ott(10, 3.0);
let showWeekly: bool = true;
let curWeek: f64 = NaN;
let lastT: f64 = NaN;
let interval: f64 = NaN;

function onStart(): void {
  const period = i32(p_period());
  const percent = p_percent();
  daily = new Ott(period, percent);
  weekly = new Ott(period, percent);
  showWeekly = pb_show_weekly();
}

function onBar(): void {
  const t = bar.time();
  const open = bar.open();
  if (isNaN(open)) return;
  if (!isNaN(lastT) && t > lastT) {
    const gap = t - lastT;
    if (isNaN(interval) || gap < interval) interval = gap;
  }
  lastT = t;

  daily.update(open);

  // A week's OTT input is its open, fixed on the week's first bar, so it never repaints mid-week.
  const week = Math.floor((Math.floor(t / 86400.0) + 3.0) / 7.0);
  if (week != curWeek) {
    curWeek = week;
    weekly.update(open);
  }

  if (daily.n > WARMUP_BARS && !isNaN(daily.ottShift)) {
    out_mavg(daily.mavg);
    out_ott(daily.ottShift);
    out_d_regime(daily.mavg > daily.ottShift ? 1.0 : 0.0);
    out_buy(bar.low());
    out_sell(bar.high());
    out_is_buy(daily.signal == 1 ? 1.0 : 0.0);
    out_is_sell(daily.signal == -1 ? 1.0 : 0.0);
  }

  const wkReady = showWeekly && weekly.n > WARMUP_WEEKS && !isNaN(weekly.ottShift);
  if (wkReady) {
    const bull = weekly.mavg > weekly.ottShift; // dca_rank.py's wk_bull
    out_wk_ott(weekly.ottShift);
    out_wk_regime(bull ? 1.0 : 0.0);
    if (bar.isLast() && !isNaN(interval)) {
      sb_clear();
      sb_text(bull ? "Weekly OTT bullish" : "Weekly OTT bearish");
      wkTag.set(t + interval, weekly.ottShift).text(str_wk_text_sb)
        .color(bull ? rgba(34, 197, 94, 255) : rgba(239, 68, 68, 255));
    }
  }
}
