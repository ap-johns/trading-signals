//@lang=wrun-ts
// IA-ATR-Model support ladder (Invest Answers), ported from alerts/indicators.py atr_levels().
// Despite the name these are not ATR multiples: Level 6 is the trailing high, and Levels 5..1
// sit 23.6 / 38.2 / 50 / 61.8 / 78.6% below it. Same numbers the dashboard's IA levels table uses.
// Intended for a daily chart: the default 252-bar lookback is one trading year (use 52 on weekly).
// Styled like the TradingView original: purple lines, each labelled at its right end.

param.int("lookback", 252, { min: 20, max: 1000, label: "Lookback (bars) for the trailing high" });

output("l6", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 6", format: "price", axis_label: true });
output("l5", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 5", format: "price", axis_label: true });
output("l4", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 4", format: "price", axis_label: true });
output("l3", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 3", format: "price", axis_label: true });
output("l2", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 2", format: "price", axis_label: true });
output("l1", line, overlay, { color: "#a855f7", width: 0.5, step: true, label: "Level 1", format: "price", axis_label: true });
output("t_tag", none, overlay, { label: "Label position (time)" });

string("n6", { max_bytes: 16 });
string("n5", { max_bytes: 16 });
string("n4", { max_bytes: 16 });
string("n3", { max_bytes: 16 });
string("n2", { max_bytes: 16 });
string("n1", { max_bytes: 16 });

// One name per level, just right of the newest bar.
draw.label("tag6", { x: "t_tag", y: "l6", text: "n6", color: "#a855f7", align: "left" });
draw.label("tag5", { x: "t_tag", y: "l5", text: "n5", color: "#a855f7", align: "left" });
draw.label("tag4", { x: "t_tag", y: "l4", text: "n4", color: "#a855f7", align: "left" });
draw.label("tag3", { x: "t_tag", y: "l3", text: "n3", color: "#a855f7", align: "left" });
draw.label("tag2", { x: "t_tag", y: "l2", text: "n2", color: "#a855f7", align: "left" });
draw.label("tag1", { x: "t_tag", y: "l1", text: "n1", color: "#a855f7", align: "left" });

let highs = new Highest(252);
let lastT: f64 = NaN;
let interval: f64 = NaN;

function onStart(): void {
  highs = new Highest(i32(p_lookback()));
}

function onBar(): void {
  const t = bar.time();
  if (!isNaN(lastT) && t > lastT) {
    const gap = t - lastT;
    if (isNaN(interval) || gap < interval) interval = gap;
  }
  lastT = t;

  // The window high over the last `lookback` bars, this bar included (matches high.iloc[-lookback:].max()).
  const anchor = highs.update(bar.high());
  if (isNaN(anchor) || anchor <= 0.0) return;
  out_l6(anchor);
  out_l5(anchor * (1.0 - 0.236));
  out_l4(anchor * (1.0 - 0.382));
  out_l3(anchor * (1.0 - 0.5));
  out_l2(anchor * (1.0 - 0.618));
  out_l1(anchor * (1.0 - 0.786));

  if (!bar.isLast() || isNaN(interval)) return;
  out_t_tag(t + interval);
  sb_clear(); sb_text("Level 6"); str_n6_sb();
  sb_clear(); sb_text("Level 5"); str_n5_sb();
  sb_clear(); sb_text("Level 4"); str_n4_sb();
  sb_clear(); sb_text("Level 3"); str_n3_sb();
  sb_clear(); sb_text("Level 2"); str_n2_sb();
  sb_clear(); sb_text("Level 1"); str_n1_sb();
}
