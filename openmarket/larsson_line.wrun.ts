//@lang=wrun-ts
// JS:Larsson Line, a lookalike of the Larsson Line. The original (Mikael Larsson, TradingView) is
// closed source; this is a fit to two screenshots of it on BTC daily, Apr 2025 to Sep 2026. Two
// EMAs of the bar's average price (open + high + low + close) / 4, fast 28 and slow 55, with the
// colour changing only once the fast line is `confirm` percent past the slow one. That puts all
// five of the original's turns within about three days, keeps it yellow through Sep 2025 when
// the lines touched without separating, and holds the line levels within about 1%. It is not
// OTT: OTT flips far more often.
// Lines and band are yellow in an uptrend, blue in a downtrend.

param.int("fast", 28, { min: 2, max: 200, label: "Fast EMA length" });
param.int("slow", 55, { min: 3, max: 400, label: "Slow EMA length" });
param.number("confirm", 0.4, { min: 0, max: 5, label: "Turn once the lines are this far apart (%)" });

// dir: 0 down, 1 up. It holds until the fast line is `confirm` percent through the slow one.
output("dir", none, overlay, { label: "Trend (0 down, 1 up)" });
output("fast_line", line, overlay, { color_by: "dir", colors: ["#7C6CFF", "#BFAE3A"], width: 1.5, label: "Fast", format: "price" });
output("slow_line", line, overlay, { color_by: "dir", colors: ["#7C6CFF", "#BFAE3A"], width: 1.5, label: "Slow", format: "price" });
fill("fast_line", "slow_line", { color_by: "dir", colors: ["#9C8CF2", "#FFEB3B"], opacity: 0.45 });

// EMA seeded at the first value, like pandas ewm(adjust=False) and Pine's ta.ema after warm-up.
let fastAlpha: f64 = 2.0 / 29.0;
let slowAlpha: f64 = 2.0 / 56.0;
let fastEma: f64 = NaN;
let slowEma: f64 = NaN;
let confirmPct: f64 = 0.4;
let dir: f64 = NaN;
let n: i32 = 0;
let warmup: i32 = 110;

function onStart(): void {
  fastAlpha = 2.0 / (p_fast() + 1.0);
  slowAlpha = 2.0 / (p_slow() + 1.0);
  confirmPct = p_confirm();
  warmup = i32(p_slow()) * 2; // hide the first stretch while the slow EMA settles
}

function onBar(): void {
  const o = bar.open();
  const h = bar.high();
  const l = bar.low();
  const c = bar.close();
  if (isNaN(o) || isNaN(h) || isNaN(l) || isNaN(c)) return;
  const src = (o + h + l + c) / 4.0;
  fastEma = isNaN(fastEma) ? src : fastEma + fastAlpha * (src - fastEma);
  slowEma = isNaN(slowEma) ? src : slowEma + slowAlpha * (src - slowEma);
  n += 1;

  const gap = (fastEma - slowEma) / slowEma * 100.0;
  if (isNaN(dir)) dir = gap > 0.0 ? 1.0 : 0.0;
  else if (dir == 0.0 && gap > confirmPct) dir = 1.0;
  else if (dir == 1.0 && gap < -confirmPct) dir = 0.0;
  if (n <= warmup) return;

  out_fast_line(fastEma);
  out_slow_line(slowEma);
  out_dir(dir);
}
