"""
Generate an HTML dashboard showing OTT signals for all tickers.
"""

import json
import os
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

from indicators import calculate_ott, calculate_sma, calculate_ema, calculate_fib_levels, atr_levels, IA_LEVEL_RATIOS
from fib_score import favorability, tier, level_reached, fib_params, rank_key
from seasonality import seasonality_context, seasonality_banner_html
from macro import macro_context, macro_banner_html

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_PATH = os.environ.get("DASHBOARD_OUTPUT", os.path.join(REPO_DIR, "docs", "index.html"))


def load_config():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f)


def load_analyst_levels():
    """Load analyst buy levels (e.g. Jacob @ Invest Answers), keyed by display name."""
    path = os.path.join(SCRIPT_DIR, "analyst_levels.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def analyst_label_html(display_name, price, analyst_levels):
    """Render a small label showing analyst buy levels, hit ones highlighted."""
    info = analyst_levels.get(display_name)
    if not info or not info.get("buy_levels"):
        return ""
    levels = sorted((float(l) for l in info["buy_levels"]), reverse=True)
    source = info.get("source", "Analyst")
    date = info.get("date", "")
    parts = []
    for lvl in levels:
        hit = price is not None and price <= lvl
        cls = "analyst-hit" if hit else "analyst-pending"
        parts.append(f'<span class="{cls}">{fmt_price(lvl)}</span>')
    title = source + (f" · {date}" if date else "")
    return (
        f' <span class="analyst-level" title="{title}">'
        f'&#9733; buy: {", ".join(parts)}</span>'
    )


def _fmt_date(idx):
    """Format a DataFrame index label (Timestamp) as a short date, e.g. '3 Jun 25'."""
    if idx is None:
        return ""
    if hasattr(idx, "strftime"):
        try:
            return idx.strftime("%-d %b %y")
        except ValueError:
            return idx.strftime("%d %b %y")
    return str(idx)


# Fib retracement depth colour ramp (shallow -> deep). Warm, increasing "heat"
# with depth so the eye reads how far price has pulled back into the buy zone.
FIB_RATIOS = (0.382, 0.5, 0.618, 0.786)


def fib_retrace_color(frac):
    """Colour for a retracement fraction (0 = at high, 1 = at swing low)."""
    if frac >= 1.0:
        return "#6b6b6b"   # below the swing low — trend broken
    if frac >= 0.786:
        return "#e85d5d"   # deep
    if frac >= 0.618:
        return "#f07d3c"   # golden-pocket zone
    if frac >= 0.5:
        return "#f0a83c"
    if frac >= 0.382:
        return "#e0c04a"
    return "#6b7fb0"       # shallow — barely retraced


def fib_level_label(frac):
    """Which fib level the retracement has reached."""
    if frac >= 1.0:
        return "below low"
    reached = [r for r in FIB_RATIOS if frac >= r]
    return f"{max(reached)}" if reached else "above 0.382"


def fib_meter_html(frac):
    """A horizontal meter: left = swing high (0%), right = swing low (100%),
    with fib level ticks and a fill up to the current retracement."""
    color = fib_retrace_color(frac)
    fill = max(0.0, min(frac, 1.0)) * 100
    ticks = "".join(
        f'<span class="fib-tick" style="left:{r * 100:.1f}%"></span>' for r in FIB_RATIOS
    )
    return (
        f'<span class="fib-meter">'
        f'<span class="fib-meter-fill" style="width:{fill:.1f}%;background:{color};"></span>'
        f'{ticks}'
        f'</span>'
    )


def nearest_support(low, price, window=10, lookback=180):
    """Nearest horizontal support below the current price: the highest daily
    pivot low (local minimum over +/- window bars) that sits below price."""
    low = low.dropna().iloc[-lookback:]
    vals = low.values
    n = len(vals)
    pivots = []
    for i in range(n):
        a = max(0, i - window)
        b = min(n, i + window + 1)
        if vals[i] == vals[a:b].min():
            pivots.append(vals[i])
    below = [v for v in pivots if v < price * 0.999]
    return float(max(below)) if below else None


def zscore_color(z):
    """Colour a z-score by how unusual it is (matches the main table convention)."""
    if z is None:
        return "#888"
    a = abs(z)
    if a >= 2:
        return "#ffffff"
    if a >= 1.5:
        return "#f0d060"
    return "#888"


def slope_arrow(direction):
    """Up/down/flat arrow for a moving-average slope."""
    if direction == "up":
        return ' <span style="color:#00e676;" title="50d SMA rising">&#9650;</span>'
    if direction == "down":
        return ' <span style="color:#ff5252;" title="50d SMA falling">&#9660;</span>'
    if direction == "flat":
        return ' <span style="color:#888;" title="50d SMA flat">&#9644;</span>'
    return ""


def level_cell(level, price):
    """Render a support/MA level with its distance from price; highlight if near
    (within 3%) so confluence with the current price is visible at a glance."""
    if level is None or price is None:
        return '<span class="fib-dt">&mdash;</span>'
    dist = (price - level) / price * 100  # + = price above the level
    cls = "fib-near" if abs(dist) <= 5 else ""
    return f'<span class="{cls}">{fmt_price(level)}</span> <span class="fib-dt">{dist:+.0f}%</span>'


def long_term_cell(price, ema_200w, wk_bull):
    """Long-term trend read: price vs the 200-week EMA + weekly OTT direction.
    This is the buy-and-hold "is the trend intact" guard against value traps."""
    if ema_200w and price is not None:
        pct = (price - ema_200w) / ema_200w * 100
        color = "#00e676" if pct >= 0 else "#ff5252"
        ema_html = f'<span style="color:{color};" title="vs 200-week EMA (${ema_200w:,.0f})">{pct:+.0f}% 200w</span>'
    else:
        ema_html = '<span class="fib-dt" title="not enough weekly history">&mdash; 200w</span>'
    if wk_bull is None:
        ott_html = ""
    elif bool(wk_bull):
        ott_html = ' <span style="color:#00e676;" title="weekly OTT bullish">wk&#9650;</span>'
    else:
        ott_html = ' <span style="color:#ff5252;" title="weekly OTT bearish">wk&#9660;</span>'
    return ema_html + ott_html


def score_color(score):
    """Colour the favorability score (higher = stronger DCA setup)."""
    if score is None:
        return "#6b6b6b"
    if score >= 8:
        return "#00e676"
    if score >= 6:
        return "#7ed957"
    if score >= 4:
        return "#e0c04a"
    return "#8a93b8"


def fib_summary_html(items):
    """Auto-generated DCA read: a few labelled lines derived from the same scores."""
    def names(t, n=None, detail=False):
        picks = [x for x in items if x["tier"] == t]
        if n:
            picks = picks[:n]
        if detail:
            return ", ".join(
                f'{x["name"]} <span class="fib-dt">({level_reached(x["frac"]) or "&lt;0.382"}, {x["z"]:+.1f}&sigma;)</span>'
                if x["z"] is not None else x["name"] for x in picks)
        return ", ".join(x["name"] for x in picks)

    lines = []
    fav = names("favoured", n=3, detail=True)
    if fav:
        lines.append(f'<div class="fib-sum-line"><span class="fib-sum-tag fav">Favoured now</span> {fav} '
                     f'<span class="fib-dt">&mdash; cheap, golden-pocket pullback, long-term trend intact</span></div>')
    cs = names("cheap_shallow")
    if cs:
        lines.append(f'<div class="fib-sum-line"><span class="fib-sum-tag mid">Cheap, shallow dip</span> {cs} '
                     f'<span class="fib-dt">&mdash; stretched below trend but only a small pullback</span></div>')
    nc = names("quality_not_cheap")
    if nc:
        lines.append(f'<div class="fib-sum-line"><span class="fib-sum-tag mid">Quality, not on sale</span> {nc} '
                     f'<span class="fib-dt">&mdash; strong trend, wait for a deeper dip / negative z</span></div>')
    ca = names("caution")
    if ca:
        lines.append(f'<div class="fib-sum-line"><span class="fib-sum-tag warn">Caution</span> {ca} '
                     f'<span class="fib-dt">&mdash; weekly trend rolling over / barely above 200w (value-trap risk)</span></div>')
    br = names("broken")
    if br:
        lines.append(f'<div class="fib-sum-line"><span class="fib-sum-tag skip">Skip</span> {br} '
                     f'<span class="fib-dt">&mdash; price below the swing low, trend broken</span></div>')

    # Concentration note: are the most actionable names (favoured + cheap/shallow)
    # crowded into one sector? Warn so DCA picks diversify.
    actionable = [x for x in items if x["tier"] in ("favoured", "cheap_shallow") and x.get("sector")]
    counts = {}
    for x in actionable:
        counts[x["sector"]] = counts.get(x["sector"], 0) + 1
    if counts:
        top_sector, n = max(counts.items(), key=lambda kv: kv[1])
        if n >= 2 and n >= len(actionable) / 2:
            lines.append(
                f'<div class="fib-sum-line"><span class="fib-sum-tag warn">Concentration</span> '
                f'{n} of the {len(actionable)} most-actionable names are <b>{top_sector}</b> '
                f'<span class="fib-dt">&mdash; they move together; pair one with a non-{top_sector} name to diversify</span></div>')
    return '<div class="fib-summary"><div class="fib-sum-head">DCA read (auto)</div>' + "".join(lines) + '</div>'


def _fib_build_items(all_data, tickers, sectors=None):
    """Compute + score a fib item for each ticker in a category, ranked best-first."""
    sectors = sectors or {}
    items = []
    for yf_ticker, display_name in tickers.items():
        data = all_data.get(yf_ticker, {})
        fib = data.get("fib")
        daily = data.get("daily", {})
        price = daily.get("price")
        if not fib or price is None:
            continue
        sl, sh = fib["swing_low"], fib["swing_high"]
        if sh <= sl:
            continue
        frac = (sh - price) / (sh - sl)
        weekly = data.get("weekly", {}) or {}
        z = daily.get("sma_zscore")
        sma50 = daily.get("sma_50")
        s50_dist = (price - sma50) / sma50 * 100 if sma50 else None
        s50_dir = daily.get("sma_50_dir")
        support = daily.get("support")
        sup_dist = (price - support) / price * 100 if support else None
        ema200w = weekly.get("ema_200w")
        w200 = (price - ema200w) / ema200w * 100 if ema200w else None
        sma200d = daily.get("sma_200d")
        d200 = (price - sma200d) / sma200d * 100 if sma200d else None
        wk_bull = bool(weekly.get("bullish")) if weekly.get("bullish") is not None else False
        score = favorability(frac, z, s50_dist, s50_dir, sup_dist, w200, wk_bull, d200)
        items.append({
            "name": display_name, "fib": fib, "price": price, "frac": frac,
            "daily": daily, "weekly": weekly, "z": z, "sma50": sma50, "support": support,
            "sma200d": sma200d, "sector": sectors.get(display_name),
            "score": score, "tier": tier(frac, z, w200, wk_bull, d200),
        })
    # Rank by tier quality first, then score within tier (see rank_key).
    items.sort(key=lambda x: rank_key(x["tier"], x["score"]))
    return items


def _fib_section_for(items, title):
    """Render one ranked table + summary for a category's items (Stocks / Indices)."""
    if not items:
        return ""
    rows = ""
    for rank, it in enumerate(items, 1):
        name, fib, price, frac, daily, weekly = (
            it["name"], it["fib"], it["price"], it["frac"], it["daily"], it["weekly"])
        broken = frac >= 1.0
        lo = f'{fmt_price(fib["swing_low"])} <span class="fib-dt">({_fmt_date(fib["swing_low_date"])})</span>'
        hi = f'{fmt_price(fib["swing_high"])} <span class="fib-dt">({_fmt_date(fib["swing_high_date"])})</span>'
        color = fib_retrace_color(frac)
        pct_label = f'{frac * 100:.0f}%'
        if broken:
            depth_html = f'<span class="fib-pct" style="color:{color};">{pct_label}</span> <span class="fib-broken">below low</span>'
        else:
            depth_html = f'<span class="fib-pct" style="color:{color};">{pct_label} <span class="fib-lvl">{fib_level_label(frac)}</span></span>'
        z = it["z"]
        z_html = (f'<span style="color:{zscore_color(z)};">{z:+.1f}&sigma;</span>'
                  if z is not None else '<span class="fib-dt">&mdash;</span>')
        sc = it["score"]
        sc_html = (f'<span style="color:{score_color(sc)};font-weight:700;">{sc:.1f}</span>'
                   if sc is not None else '<span class="fib-dt">skip</span>')
        sector_html = f'<span class="fib-sector">{it["sector"]}</span>' if it.get("sector") else ""
        d200 = level_cell(it["sma200d"], price) + slope_arrow(daily.get("sma_200d_dir")) if it.get("sma200d") else '<span class="fib-dt">&mdash;</span>'
        rows += f'''<tr>
            <td class="fib-rank">{rank}</td>
            <td class="fib-scorecell">{sc_html}</td>
            <td class="ticker">{name}{sector_html}</td>
            <td class="fib-range-cell">{lo} &rarr; {hi}</td>
            <td class="fib-gain">+{fib["gain"] * 100:.0f}%</td>
            <td class="fib-price">{fmt_price(price)}</td>
            <td class="fib-lv">{level_cell(it["sma50"], price)}{slope_arrow(daily.get("sma_50_dir"))}</td>
            <td class="fib-lv">{d200}</td>
            <td class="fib-lv">{level_cell(it["support"], price)}</td>
            <td class="fib-z">{z_html}</td>
            <td class="fib-lt">{long_term_cell(price, weekly.get("ema_200w"), weekly.get("bullish"))}</td>
            <td class="fib-meter-cell">{fib_meter_html(frac)}{depth_html}</td>
        </tr>\n'''
    return f'''
    <h3 class="fib-subtitle">{title}</h3>
    {fib_summary_html(items)}
    <table class="fib-table">
        <thead>
            <tr>
                <th>#</th>
                <th>Score</th>
                <th>Ticker</th>
                <th>Uptrend (low &rarr; high)</th>
                <th>Gain</th>
                <th class="fib-price">Price</th>
                <th>50d SMA</th>
                <th>200d SMA</th>
                <th>Support</th>
                <th>z-score</th>
                <th>Long-term trend</th>
                <th>Retracement <span class="fib-scale">high&larr;&nbsp;0.382&nbsp;0.5&nbsp;0.618&nbsp;0.786&nbsp;&rarr;low</span></th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>'''


def ia_levels_section_html(all_data, config):
    """Compact 'IA Levels' table — Fibonacci-% pullback bands from the trailing high
    (the reverse-engineered Invest Answers 'ATR' levels). Highlights the band price is
    currently in; L4-L5 is Jacob's accumulation zone."""
    cats = config.get("fib_alerts", {}).get("categories", ["Stocks"])
    labels = [6, 5, 4, 3, 2, 1]
    hdr_pct = {6: "high", 5: "-24%", 4: "-38%", 3: "-50%", 2: "-62%", 1: "-79%"}

    def depth_word(pct_off):
        if pct_off < 24:
            return "shallow dip", "#7aa2f7"
        if pct_off < 38:
            return "moderate dip", "#5fb87a"
        if pct_off < 50:
            return "deep dip", "#e0c04a"
        if pct_off < 62:
            return "very deep", "#e8925d"
        return "extreme", "#d97a6c"

    # Which levels/categories the IA-level BUY alerts watch (badge them on the dashboard)
    alert_cfg = config.get("ia_level_alerts", {})
    alert_cats = alert_cfg.get("categories", ["Stocks"])
    watched = alert_cfg.get("levels", [5, 4, 3])
    badge_word = {5: "mild dip", 4: "moderate dip", 3: "deep dip", 2: "very deep", 1: "extreme"}

    body = ""
    any_rows = False
    for cat in cats:
        cat_rows = ""
        for yf_ticker, name in config["watchlist"].get(cat, {}).items():
            d = all_data.get(yf_ticker, {}).get("daily", {})
            lv = d.get("ia_levels")
            price = d.get("price")
            if not lv or price is None:
                continue
            any_rows = True
            at_below = [k for k in labels if lv[k] <= price]
            support = max(at_below, key=lambda k: lv[k]) if at_below else 1

            # Alert bar: colour the row's left edge if price is at/below a watched
            # level (matches check_ia_levels); deeper level = brighter green.
            trig = [L for L in watched if price <= lv[L]] if cat in alert_cats else []
            if trig:
                dl = min(trig)  # deepest triggered level (lower number = deeper)
                word = badge_word.get(dl, "")
                row_cls = f"ia-trig-{dl}"
                trow_title = f' title="Price at IA L{dl} — {word}"'
            else:
                row_cls, trow_title = "", ""
            cells = ""
            for k in labels:
                cls = "ia-here" if k == support and at_below else "ia-cell"
                cells += f'<td class="{cls}">{fmt_price(lv[k])}</td>'

            # Pullback: how far below the high (Level 6), in plain terms
            pct_off = (lv[6] - price) / lv[6] * 100 if lv[6] else 0
            if price >= lv[6]:
                pull_html = '<span style="color:#7aa2f7;">at high</span>'
            else:
                _, wcol = depth_word(pct_off)
                pull_html = f'<span style="color:{wcol};font-weight:600;">&minus;{pct_off:.0f}%</span>'

            # Nearest level: a labelled bar (lower level | price marker | upper level)
            above = [k for k in labels if lv[k] > price]
            below = [k for k in labels if lv[k] <= price]
            upper_lv = min(above, key=lambda k: lv[k]) if above else None
            lower_lv = max(below, key=lambda k: lv[k]) if below else None
            if upper_lv and lower_lv:
                lo, up = lv[lower_lv], lv[upper_lv]
                pos = max(0.0, min(100.0, (price - lo) / (up - lo) * 100)) if up > lo else 50.0
                d_up, d_lo = (up - price) / price * 100, (price - lo) / price * 100
                # Distance is to the level in the DIRECTION OF TRAVEL — falling => the
                # lower level it's heading toward, rising => the upper. (When flat, the
                # nearest by distance.) The marker triangle points that way too.
                chg5 = d.get("chg5", 0.0)
                if chg5 > 0.5:
                    mkcls, target_lv, dist = "ia-mk-up", upper_lv, d_up
                elif chg5 < -0.5:
                    mkcls, target_lv, dist = "ia-mk-dn", lower_lv, d_lo
                else:
                    mkcls = "ia-mk-flat"
                    target_lv, dist = (upper_lv, d_up) if d_up <= d_lo else (lower_lv, d_lo)
                lbl_cls = "ia-prox-lbl near" if dist <= 3.0 else "ia-prox-lbl"
                prox = (f'<span class="ia-prox">'
                        f'<span class="ia-endlbl">L{lower_lv}<br>{fmt_price(lo)}</span>'
                        f'<span class="ia-prox-track">'
                        f'<span class="{lbl_cls}" style="left:{pos:.0f}%">{dist:.1f}%</span>'
                        f'<span class="ia-prox-marker {mkcls}" style="left:{pos:.0f}%"></span></span>'
                        f'<span class="ia-endlbl">L{upper_lv}<br>{fmt_price(up)}</span></span>')
            elif not above:
                prox = '<span class="ia-prox-txt">at the high</span>'
            else:
                prox = '<span class="ia-prox-txt">below L1</span>'
            cat_rows += (f'<tr class="{row_cls}"><td class="ticker"{trow_title}>{name}</td>'
                         f'<td class="fib-price">{fmt_price(price)}</td>{cells}'
                         f'<td class="ia-zone">{pull_html}</td>'
                         f'<td class="ia-prox-cell">{prox}</td></tr>\n')
        if cat_rows:
            body += f'<tr class="category-row"><td colspan="10">{cat}</td></tr>\n{cat_rows}'

    if not any_rows:
        return ""
    heads = "".join(f'<th>L{k}<span class="ia-hpct">{hdr_pct[k]}</span></th>' for k in labels)
    return f'''
    <h2 class="fib-title">IA Levels <span class="fib-sub">Fibonacci-% pullback bands from the trailing high (Invest Answers) &middot; <span style="color:#5fb87a;">green cell</span> = the band price sits in &middot; left bar = price at/below a level, by depth: <span style="color:#5fb87a;">L5</span> &rarr; <span style="color:#e0c04a;">L4</span> &rarr; <span style="color:#e8925d;">L3</span></span></h2>
    <div class="ia-key">Pullback depth: <span style="color:#7aa2f7;">shallow &lt;24%</span> &middot; <span style="color:#5fb87a;">moderate 24&ndash;38%</span> &middot; <span style="color:#e0c04a;">deep 38&ndash;50%</span> &middot; <span style="color:#e8925d;">very deep 50&ndash;62%</span> &middot; <span style="color:#d97a6c;">extreme &gt;62%</span></div>
    <table class="fib-table ia-table">
        <thead><tr><th>Ticker</th><th class="fib-price">Price</th>{heads}<th>Pullback<br>from high</th><th>Nearest level<br><span class="ia-hpct">marker = price (5-day): <span style="color:#5fb87a;">&#9654;</span> rising &middot; <span style="color:#d97a6c;">&#9664;</span> falling &middot; <span style="color:#e8e6e0;">&#9612;</span> flat</span></th></tr></thead>
        <tbody>{body}</tbody>
    </table>'''


def fib_section_html(all_data, config):
    """Fib retracement area: one ranked table per asset class (Stocks, Indices...)."""
    fib_cfg = config.get("fib_alerts", {})
    categories = fib_cfg.get("categories", ["Stocks"])
    sectors = config.get("sectors", {})
    sections = ""
    for cat in categories:
        tickers = config["watchlist"].get(cat, {})
        items = _fib_build_items(all_data, tickers, sectors)
        sections += _fib_section_for(items, cat)
    if not sections:
        return ""
    return f'''
    <h2 class="fib-title">DCA Buy Levels <span class="fib-sub">ranked by buy-and-hold favourability &mdash; fib retracement depth + trend, value (z), regime &amp; confluence &middot; <span class="fib-near">green</span> = price within 5% of the level &middot; <span style="color:#00e676;">&#9650;</span>/<span style="color:#ff5252;">&#9660;</span> = 50d SMA rising/falling</span></h2>
    {sections}'''


def get_ticker_data(yf_ticker, ott_period, ott_percent, ema_period,
                    fib_enabled=True, fib_lookback=104, fib_min_gain=0.30,
                    fib_reversal=0.14, fib_levels=(0.382, 0.5, 0.618, 0.786)):
    """Fetch data and calculate OTT for both timeframes."""
    results = {}

    # Daily
    try:
        t = yf.Ticker(yf_ticker)
        df = t.history(period="365d", interval="1d")
        if not df.empty and len(df) > ott_period + 10:
            src = df["Open"]
            ott_df = calculate_ott(src, period=ott_period, percent=ott_percent)
            ema_200 = calculate_sma(df["Close"], period=ema_period)

            # Current state
            mavg_above_ott = ott_df["mavg"].iloc[-1] > ott_df["ott"].iloc[-1]

            # Find recent signals (last 60 days)
            signals_mask = ott_df["signal"] != 0
            recent_signals = []
            for idx in ott_df[signals_mask].tail(5).index:
                sig = ott_df.loc[idx, "signal"]
                recent_signals.append({
                    "date": idx.strftime("%-d %b %y"),
                    "type": "BUY" if sig == 1 else "SELL",
                    "price": df["Close"].loc[idx],
                })

            # Z-score of current distance from 200d SMA
            pct_from_sma_series = (df["Close"] - ema_200) / ema_200 * 100
            pct_from_sma_series = pct_from_sma_series.dropna()
            sma_zscore = None
            if len(pct_from_sma_series) > 1 and pct_from_sma_series.std() > 0:
                sma_zscore = (pct_from_sma_series.iloc[-1] - pct_from_sma_series.mean()) / pct_from_sma_series.std()

            # 50d SMA (+ its slope) and nearest horizontal support, for fib-table confluence
            price_now = df["Close"].iloc[-1]
            sma_50_series = calculate_sma(df["Close"], period=50)
            sma_50 = float(sma_50_series.iloc[-1]) if pd.notna(sma_50_series.iloc[-1]) else None
            # Slope over ~20 sessions: rising 50d = dynamic support, falling = rolled over
            sma_50_dir = None
            if sma_50 is not None and len(sma_50_series) > 21 and pd.notna(sma_50_series.iloc[-21]):
                prev = sma_50_series.iloc[-21]
                if prev > 0:
                    chg = (sma_50 - prev) / prev * 100
                    sma_50_dir = "up" if chg > 0.5 else ("down" if chg < -0.5 else "flat")
            support = nearest_support(df["Low"], price_now)

            # 200d SMA regime: value (already = ema_200) + slope. Below the 200d =
            # medium-term trend broken (a value-trap guard for buy-and-hold).
            sma_200d = float(ema_200.iloc[-1]) if pd.notna(ema_200.iloc[-1]) else None
            sma_200d_dir = None
            if sma_200d is not None and len(ema_200) > 21 and pd.notna(ema_200.iloc[-21]):
                prev200 = ema_200.iloc[-21]
                if prev200 > 0:
                    chg200 = (sma_200d - prev200) / prev200 * 100
                    sma_200d_dir = "up" if chg200 > 0.3 else ("down" if chg200 < -0.3 else "flat")

            # Short-term direction: 5-session % change (for "approaching/leaving" a level)
            chg5 = float((df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1) * 100) if len(df) >= 6 else 0.0

            results["daily"] = {
                "price": price_now,
                "chg5": chg5,
                "ema_200": ema_200.iloc[-1],
                "sma_zscore": sma_zscore,
                "sma_50": sma_50,
                "sma_50_dir": sma_50_dir,
                "sma_200d": sma_200d,
                "sma_200d_dir": sma_200d_dir,
                "support": support,
                "ia_levels": atr_levels(df["High"]),
                "mavg": ott_df["mavg"].iloc[-1],
                "ott": ott_df["ott"].iloc[-1],
                "bullish": mavg_above_ott,
                "signals": recent_signals,
                "last_date": df.index[-1].strftime("%-d %b %y"),
            }
    except Exception as e:
        results["daily"] = {"error": str(e)}

    # 4h (from 1h candles)
    try:
        t = yf.Ticker(yf_ticker)
        df_1h = t.history(period="60d", interval="1h")
        if not df_1h.empty:
            df_4h = df_1h.resample("4h").agg({
                "Open": "first", "High": "max", "Low": "min",
                "Close": "last", "Volume": "sum",
            }).dropna()

            if len(df_4h) > ott_period + 10:
                src = df_4h["Open"]
                ott_df = calculate_ott(src, period=ott_period, percent=ott_percent)
                ema_200 = calculate_sma(df_4h["Close"], period=ema_period)

                mavg_above_ott = ott_df["mavg"].iloc[-1] > ott_df["ott"].iloc[-1]

                signals_mask = ott_df["signal"] != 0
                recent_signals = []
                for idx in ott_df[signals_mask].tail(5).index:
                    sig = ott_df.loc[idx, "signal"]
                    recent_signals.append({
                        "date": idx.strftime("%-d %b %y %H:%M"),
                        "type": "BUY" if sig == 1 else "SELL",
                        "price": df_4h["Close"].loc[idx],
                    })

                results["4h"] = {
                    "price": df_4h["Close"].iloc[-1],
                    "ema_200": ema_200.iloc[-1],
                    "mavg": ott_df["mavg"].iloc[-1],
                    "ott": ott_df["ott"].iloc[-1],
                    "bullish": mavg_above_ott,
                    "signals": recent_signals,
                    "last_date": df_4h.index[-1].strftime("%-d %b %y %H:%M"),
                }
    except Exception as e:
        results["4h"] = {"error": str(e)}

    # Weekly (resampled from daily)
    try:
        t = yf.Ticker(yf_ticker)
        df = t.history(period="max", interval="1wk")
        if not df.empty:
            df_w = df.dropna()

            if len(df_w) > ott_period + 10:
                src = df_w["Open"]
                ott_df = calculate_ott(src, period=ott_period, percent=ott_percent)
                ema_200 = calculate_sma(df_w["Close"], period=ema_period)
                sma_200w = calculate_sma(df_w["Close"], period=200)
                # 200-week EMA — the long-term trend anchor (needs enough history)
                ema_200w_series = calculate_ema(df_w["Close"], period=200)
                n_weeks = len(df_w)
                ema_200w = float(ema_200w_series.iloc[-1]) if n_weeks >= 104 else None

                mavg_above_ott = ott_df["mavg"].iloc[-1] > ott_df["ott"].iloc[-1]

                signals_mask = ott_df["signal"] != 0
                recent_signals = []
                for idx in ott_df[signals_mask].tail(5).index:
                    sig = ott_df.loc[idx, "signal"]
                    recent_signals.append({
                        "date": idx.strftime("%-d %b %y"),
                        "type": "BUY" if sig == 1 else "SELL",
                        "price": df_w["Close"].loc[idx],
                    })

                results["weekly"] = {
                    "price": df_w["Close"].iloc[-1],
                    "ema_200": ema_200.iloc[-1],
                    "sma_200w": sma_200w.iloc[-1] if pd.notna(sma_200w.iloc[-1]) else None,
                    "ema_200w": ema_200w,
                    "n_weeks": n_weeks,
                    "mavg": ott_df["mavg"].iloc[-1],
                    "ott": ott_df["ott"].iloc[-1],
                    "bullish": mavg_above_ott,
                    "signals": recent_signals,
                    "last_date": df_w.index[-1].strftime("%-d %b %y"),
                }

                # Fibonacci retracement of the dominant weekly uptrend
                if fib_enabled:
                    results["fib"] = calculate_fib_levels(
                        df_w["High"], df_w["Low"],
                        lookback=fib_lookback, min_gain=fib_min_gain,
                        reversal=fib_reversal, ratios=tuple(fib_levels),
                    )
    except Exception as e:
        results["weekly"] = {"error": str(e)}

    return results


def fmt_price(val):
    """Format price: $1.2k for values >= 1000, $123.45 otherwise."""
    if abs(val) >= 1000:
        return f"${val/1000:.1f}k"
    return f"${val:.2f}"


def generate_html(all_data, config):
    """Generate the dashboard HTML."""
    now = datetime.now().strftime("%-d %b %y %H:%M")
    analyst_levels = load_analyst_levels()

    strategy_labels = {
        "Crypto": "4yr Cycle: buy on cycle timing or -10/-20/-30% below 200w EMA, sell near cycle peak",
        "Indices": "Always-In: sell on any OTT sell, buy back on OTT buy or 5% dip from sell",
        "Stocks": "OTT + SMA: buy on OTT or 50 SMA cross, sell on OTT above 200 SMA",
    }

    rows = ""
    for category, tickers in config["watchlist"].items():
        strat_label = strategy_labels.get(category, "")
        rows += f'<tr class="category-row"><td colspan="6">{category} <span class="strat-label">{strat_label}</span></td></tr>\n'

        for yf_ticker, display_name in tickers.items():
            # Crypto uses cycle strategy, not OTT
            if category == "Crypto":
                try:
                    t = yf.Ticker(yf_ticker)
                    df_w = t.history(period="5y", interval="1wk")
                    if not df_w.empty and len(df_w) > 50:
                        ema_200w = calculate_ema(df_w["Close"], period=200)
                        price = df_w["Close"].iloc[-1]
                        ema_val = ema_200w.iloc[-1]
                        pct_from_ema = (price - ema_val) / ema_val * 100 if pd.notna(ema_val) else 0

                        # Determine cycle status
                        cycle_config = config.get("crypto_cycle", {})
                        ticker_overrides = cycle_config.get("ticker_overrides", {})
                        override = ticker_overrides.get(yf_ticker, {})
                        windows = override.get("buy_windows", cycle_config.get("buy_windows", []))
                        sell_date_str = cycle_config.get("sell_date", "2029-11-01")

                        now_dt = datetime.now()
                        in_window = False
                        next_window = None
                        for w in windows:
                            center = datetime.strptime(w["center"], "%Y-%m-%d")
                            half = timedelta(days=w["months"] * 30)
                            w_start, w_end = center - half, center + half
                            if w_start <= now_dt <= w_end:
                                in_window = True
                            elif w_start > now_dt and (next_window is None or w_start < next_window):
                                next_window = w_start

                        if in_window:
                            status = "IN BUY WINDOW"
                            state_class = "bullish"
                        elif pct_from_ema < 0:
                            status = f"{pct_from_ema:.0f}% from 200w EMA"
                            state_class = "bearish"
                        else:
                            status = f"+{pct_from_ema:.0f}% above 200w EMA"
                            state_class = "bullish"

                        if next_window:
                            days_to = (next_window - now_dt).days
                            window_note = f"Next window: {next_window.strftime('%-d %b %y')} ({days_to}d)"
                        else:
                            window_note = f"Sell target: {sell_date_str}"

                        # Find historical cycle signals from EMA dip levels
                        close = df_w["Close"]
                        cycle_signals = []
                        dip_only_in_window = override.get("dip_only_in_window", False)

                        # Build buy ranges for this ticker
                        buy_ranges = []
                        for w in windows:
                            center = datetime.strptime(w["center"], "%Y-%m-%d")
                            half = timedelta(days=w["months"] * 30)
                            buy_ranges.append((center - half, center + half))

                        # Historical cycle sell dates
                        alert_months_cfg = cycle_config.get("alert_months_before", 1)
                        cycle_sell_dates = [
                            datetime(2013, 10, 1),
                            datetime(2017, 11, 1),
                            datetime(2021, 10, 1),
                            datetime(2025, 9, 1),
                        ]
                        future_dt = datetime.strptime(sell_date_str, "%Y-%m-%d")
                        cycle_sell_dates.append(future_dt - timedelta(days=alert_months_cfg * 30))

                        for i in range(1, len(df_w)):
                            p = close.iloc[i]
                            e = ema_200w.iloc[i]
                            if pd.isna(e):
                                continue
                            pct = (p - e) / e * 100
                            d = df_w.index[i].to_pydatetime().replace(tzinfo=None)
                            in_w = any(s <= d <= en for s, en in buy_ranges)

                            # Cycle sell dates
                            for sell_dt in cycle_sell_dates:
                                if d >= sell_dt and d < sell_dt + timedelta(days=7):
                                    cycle_signals.append({"date": d.strftime("%-d %b %y"), "type": "SELL", "price": p})
                                    break

                            # Window entry
                            if in_w and not any(s <= df_w.index[i-1].to_pydatetime().replace(tzinfo=None) <= en for s, en in buy_ranges):
                                cycle_signals.append({"date": d.strftime("%-d %b %y"), "type": "BUY", "price": p})

                            # Dip levels
                            for level in [-10, -20, -30]:
                                if pct <= level:
                                    dip_ok = in_w if dip_only_in_window else True
                                    if dip_ok:
                                        prev_pct = (close.iloc[i-1] - ema_200w.iloc[i-1]) / ema_200w.iloc[i-1] * 100 if pd.notna(ema_200w.iloc[i-1]) else 0
                                        if prev_pct > level:
                                            cycle_signals.append({"date": d.strftime("%-d %b %y"), "type": "BUY", "price": p})

                        # Build pills (most recent first)
                        cycle_signals.reverse()
                        pills = []
                        for sig in cycle_signals[:8]:
                            sig_class = "buy-signal" if sig["type"] == "BUY" else "sell-signal"
                            sig_date = datetime.strptime(sig["date"], "%d %b %y")
                            if (now_dt - sig_date).days <= 7:
                                sig_class += " recent-signal"
                            pills.append(f'<span class="signal-pill {sig_class}">{sig["date"]}<br><span class="sig-price">{fmt_price(sig["price"])}</span></span>')

                        if pills:
                            latest_pill = pills[0]
                            if len(pills) > 1:
                                uid = f"{display_name}_cycle".replace(" ", "")
                                older = " ".join(pills[1:])
                                sig = cycle_signals[0]
                                sig_class = "buy-signal" if sig["type"] == "BUY" else "sell-signal"
                                sig_date = datetime.strptime(sig["date"], "%d %b %y")
                                if (now_dt - sig_date).days <= 7:
                                    sig_class += " recent-signal"
                                first_pill = (
                                    f'<span class="signal-pill clickable {sig_class}" '
                                    f'onclick="document.getElementById(\'{uid}\').classList.toggle(\'show\')">'
                                    f'{sig["date"]}<br><span class="sig-price">{fmt_price(sig["price"])}</span></span>'
                                )
                                signals_html = f'{first_pill}<span id="{uid}" class="older-signals"> {" ".join(pills[1:])}</span>'
                            else:
                                signals_html = latest_pill
                        else:
                            signals_html = ""

                        # Daily 200d SMA z-score (display only; crypto is not alerted on it).
                        # Labelled "vs 200d SMA" to distinguish from the 200w EMA figure above.
                        crypto_z = all_data.get(yf_ticker, {}).get("daily", {}).get("sma_zscore")
                        zscore_html = ""
                        if crypto_z is not None:
                            z_abs = abs(crypto_z)
                            z_sign = "+" if crypto_z >= 0 else ""
                            if z_abs >= 2:
                                z_style = "color:#ffffff;"
                            elif z_abs >= 1.5:
                                z_style = "color:#f0d060;"
                            else:
                                z_style = "color:#888;"
                            zscore_html = f' <span style="{z_style}">({z_sign}{crypto_z:.1f}σ vs 200d SMA)</span>'

                        status_html = f'<span class="strat-label">{status}{zscore_html} | {window_note}</span>'
                        if signals_html:
                            status_html = f'{signals_html} {status_html}'
                        status_html += analyst_label_html(display_name, price, analyst_levels)

                        trend_arrow = "&#9650;" if pct_from_ema > 0 else "&#9660;"
                        rows += f'''<tr data-tf="daily">
                            <td class="ticker"><span class="trend-icon {state_class}">{trend_arrow}</span> {display_name}</td>
                            <td class="signals">{status_html}</td>
                        </tr>\n'''
                except Exception as e:
                    rows += f'<tr data-tf="daily"><td class="ticker">{display_name}</td><td class="error">Error: {e}</td></tr>\n'
                continue

            # Indices use always-in strategy
            if category == "Indices":
                try:
                    t = yf.Ticker(yf_ticker)
                    df = t.history(period="365d", interval="1d")
                    if not df.empty and len(df) > 200:
                        src = df["Open"]
                        ott_df = calculate_ott(src, period=config["ott"]["period"], percent=config["ott"]["percent"])
                        sma_200 = calculate_sma(df["Close"], period=200)
                        close = df["Close"]
                        price = close.iloc[-1]
                        sma_val = sma_200.iloc[-1]
                        above_200 = price > sma_val if pd.notna(sma_val) else False
                        pct_from_sma = (price - sma_val) / sma_val * 100 if pd.notna(sma_val) else 0

                        # Z-score of current distance from 200d SMA (same as other sections)
                        pct_from_sma_series = ((close - sma_200) / sma_200 * 100).dropna()
                        sma_zscore = None
                        if len(pct_from_sma_series) > 1 and pct_from_sma_series.std() > 0:
                            sma_zscore = (pct_from_sma_series.iloc[-1] - pct_from_sma_series.mean()) / pct_from_sma_series.std()

                        # 200w SMA
                        pct_from_200w = None
                        try:
                            df_w = t.history(period="max", interval="1wk").dropna()
                            if len(df_w) >= 200:
                                sma_200w = calculate_sma(df_w["Close"], period=200)
                                sma_200w_val = sma_200w.iloc[-1]
                                if pd.notna(sma_200w_val) and sma_200w_val > 0:
                                    pct_from_200w = (price - sma_200w_val) / sma_200w_val * 100
                        except Exception:
                            pass

                        # Simulate always-in: find sell signals (OTT sell above 200 SMA)
                        # and buy signals (OTT buy or 5% dip from last sell)
                        index_signals = []
                        last_sell_price = None
                        for i in range(1, len(df)):
                            sig = ott_df["signal"].iloc[i]
                            p = close.iloc[i]
                            s = sma_200.iloc[i]
                            a200 = p > s if pd.notna(s) else False

                            # SELL: any OTT sell signal
                            if sig == -1:
                                index_signals.append({"date": df.index[i].strftime("%-d %b %y"), "type": "SELL", "price": p})
                                last_sell_price = p
                            # BUY: OTT buy or 5% dip from sell
                            elif sig == 1:
                                index_signals.append({"date": df.index[i].strftime("%-d %b %y"), "type": "BUY", "price": p})
                            elif last_sell_price and p < last_sell_price * 0.95:
                                index_signals.append({"date": df.index[i].strftime("%-d %b %y"), "type": "BUY", "price": p})
                                last_sell_price = None


                        # Build pills (most recent first)
                        index_signals.reverse()
                        pills = []
                        has_recent_signal = False
                        recent_signal_type = None
                        for sig in index_signals[:5]:
                            sig_class = "buy-signal" if sig["type"] == "BUY" else "sell-signal"
                            sig_date = datetime.strptime(sig["date"], "%d %b %y")
                            if (now_dt - sig_date).days <= 7:
                                sig_class += " recent-signal"
                                has_recent_signal = True
                                recent_signal_type = sig["type"]
                            pills.append(f'<span class="signal-pill {sig_class}">{sig["date"]}<br><span class="sig-price">{fmt_price(sig["price"])}</span></span>')

                        if pills:
                            if len(pills) > 1:
                                uid = f"{display_name}_idx".replace(" ", "")
                                sig = index_signals[0]
                                sig_class = "buy-signal" if sig["type"] == "BUY" else "sell-signal"
                                sig_date_dt = datetime.strptime(sig["date"], "%d %b %y")
                                if (now_dt - sig_date_dt).days <= 7:
                                    sig_class += " recent-signal"
                                first_pill = (
                                    f'<span class="signal-pill clickable {sig_class}" '
                                    f'onclick="document.getElementById(\'{uid}\').classList.toggle(\'show\')">'
                                    f'{sig["date"]}<br><span class="sig-price">{fmt_price(sig["price"])}</span></span>'
                                )
                                signals_html = f'{first_pill}<span id="{uid}" class="older-signals"> {" ".join(pills[1:])}</span>'
                            else:
                                signals_html = pills[0]
                        else:
                            signals_html = '<span class="no-signal">No signals</span>'

                        row_class = ""
                        if has_recent_signal:
                            row_class = "recent-buy-row" if recent_signal_type == "BUY" else "recent-sell-row"

                        bullish = above_200
                        state_class = "bullish" if bullish else "bearish"
                        trend_arrow = "&#9650;" if bullish else "&#9660;"
                        sma_pct_class = "above-ema" if pct_from_sma >= 0 else "below-ema"
                        sma_pct_label = f"+{pct_from_sma:.1f}%" if pct_from_sma >= 0 else f"{pct_from_sma:.1f}%"
                        zscore_html = ""
                        if sma_zscore is not None:
                            z_abs = abs(sma_zscore)
                            z_sign = "+" if sma_zscore >= 0 else ""
                            if z_abs >= 2:
                                z_style = "color:#ffffff;"
                            elif z_abs >= 1.5:
                                z_style = "color:#f0d060;"
                            else:
                                z_style = "color:#888;"
                            zscore_html = f' <span style="{z_style}">({z_sign}{sma_zscore:.1f}σ)</span>'
                        sma_status = f'<span class="{sma_pct_class}" style="margin-right:8px;font-size:0.85em;">{sma_pct_label} from 200d SMA{zscore_html}</span>'
                        if pct_from_200w is not None:
                            w_pct_class = "above-ema" if pct_from_200w >= 0 else "below-ema"
                            w_pct_label = f"+{pct_from_200w:.1f}%" if pct_from_200w >= 0 else f"{pct_from_200w:.1f}%"
                            sma_status += f' <span class="{w_pct_class}" style="font-size:0.85em;">{w_pct_label} from 200w SMA</span>'
                        sma_status += analyst_label_html(display_name, price, analyst_levels)
                        rows += f'''<tr class="{row_class}" data-tf="daily">
                            <td class="ticker"><span class="trend-icon {state_class}">{trend_arrow}</span> {display_name}</td>
                            <td class="signals">{signals_html} {sma_status}</td>
                        </tr>\n'''
                except Exception as e:
                    rows += f'<tr data-tf="daily"><td class="ticker">{display_name}</td><td class="error">Error: {e}</td></tr>\n'
                continue

            data = all_data.get(yf_ticker, {})

            for tf in ["daily", "4h", "weekly"]:
                tf_data = data.get(tf, {})
                if "error" in tf_data:
                    rows += f'<tr data-tf="{tf}"><td>{display_name}</td><td colspan="5" class="error">Error: {tf_data["error"]}</td></tr>\n'
                    continue
                if not tf_data:
                    continue

                bullish = tf_data["bullish"]
                state_class = "bullish" if bullish else "bearish"
                state_text = "BULLISH" if bullish else "BEARISH"
                price = tf_data["price"]
                ema_200 = tf_data["ema_200"]
                ema_class = "above-ema" if price > ema_200 else "below-ema"
                pct_from_sma = (price - ema_200) / ema_200 * 100 if ema_200 else 0
                ema_label = f"+{pct_from_sma:.1f}%" if pct_from_sma >= 0 else f"{pct_from_sma:.1f}%"

                # Recent signals as pills
                all_signals = tf_data["signals"][-5:]  # Last 5
                has_recent_signal = False
                recent_signal_type = None
                now = datetime.now()

                if not all_signals:
                    signals_html = '<span class="no-signal">No recent signals</span>'
                else:
                    # Build signal pills with recency check
                    pills = []
                    for sig in all_signals:
                        sig_class = "buy-signal" if sig["type"] == "BUY" else "sell-signal"
                        sig_date = now
                        for fmt in ("%d %b %y %H:%M", "%d %b %y"):
                            try:
                                sig_date = datetime.strptime(sig["date"], fmt)
                                break
                            except ValueError:
                                continue
                        days_ago = (now - sig_date).days
                        if days_ago <= 7:
                            sig_class += " recent-signal"
                            has_recent_signal = True
                            recent_signal_type = sig["type"]
                        pills.append(f'<span class="signal-pill {sig_class}">{sig["date"]}<br><span class="sig-price">{fmt_price(sig["price"])}</span></span>')

                    # Reverse so most recent is first
                    pills.reverse()
                    if len(pills) > 1:
                        uid = f"{display_name}_{tf}".replace(" ", "")
                        # Rebuild first pill with onclick
                        sig = all_signals[-1]  # most recent (list wasn't reversed)
                        sig_class = "buy-signal" if sig["type"] == "BUY" else "sell-signal"
                        sig_date = now
                        for fmt in ("%d %b %y %H:%M", "%d %b %y"):
                            try:
                                sig_date = datetime.strptime(sig["date"], fmt)
                                break
                            except ValueError:
                                continue
                        if (now - sig_date).days <= 7:
                            sig_class += " recent-signal"
                        first_pill = (
                            f'<span class="signal-pill clickable {sig_class}" '
                            f'onclick="document.getElementById(\'{uid}\').classList.toggle(\'show\')">'
                            f'{sig["date"]}<br><span class="sig-price">{fmt_price(sig["price"])}</span></span>'
                        )
                        older_pills = " ".join(pills[1:])
                        signals_html = (
                            f'{first_pill}'
                            f'<span id="{uid}" class="older-signals"> {older_pills}</span>'
                        )
                    else:
                        signals_html = pills[0]

                row_class = ""
                if has_recent_signal:
                    row_class = "recent-buy-row" if recent_signal_type == "BUY" else "recent-sell-row"

                trend_arrow = "&#9650;" if bullish else "&#9660;"  # ▲ or ▼
                sma_status = ""
                if tf == "daily":
                    sma_pct_class = "above-ema" if pct_from_sma >= 0 else "below-ema"
                    sma_pct_label = f"+{pct_from_sma:.1f}%" if pct_from_sma >= 0 else f"{pct_from_sma:.1f}%"
                    zscore = tf_data.get("sma_zscore")
                    zscore_html = ""
                    if zscore is not None:
                        z_abs = abs(zscore)
                        z_sign = "+" if zscore >= 0 else ""
                        if z_abs >= 2:
                            z_style = "color:#ffffff;"
                        elif z_abs >= 1.5:
                            z_style = "color:#f0d060;"
                        else:
                            z_style = "color:#888;"
                        zscore_html = f' <span style="{z_style}">({z_sign}{zscore:.1f}σ)</span>'
                    sma_status = f'<span class="{sma_pct_class}" style="margin-left:8px;font-size:0.85em;">{sma_pct_label} from 200d SMA{zscore_html}</span>'
                    # 200w SMA from weekly data
                    weekly_data = data.get("weekly", {})
                    sma_200w_val = weekly_data.get("sma_200w")
                    if sma_200w_val and sma_200w_val > 0:
                        pct_from_200w = (price - sma_200w_val) / sma_200w_val * 100
                        w_pct_class = "above-ema" if pct_from_200w >= 0 else "below-ema"
                        w_pct_label = f"+{pct_from_200w:.1f}%" if pct_from_200w >= 0 else f"{pct_from_200w:.1f}%"
                        sma_status += f' <span class="{w_pct_class}" style="margin-left:8px;font-size:0.85em;">{w_pct_label} from 200w SMA</span>'
                    sma_status += analyst_label_html(display_name, price, analyst_levels)
                rows += f'''<tr class="{row_class}" data-tf="{tf}">
                    <td class="ticker"><span class="trend-icon {state_class}">{trend_arrow}</span> {display_name}</td>
                    <td class="signals">{signals_html} {sma_status}</td>
                    <td class="detail-col price">{fmt_price(price)}</td>
                    <td class="detail-col ema">{fmt_price(ema_200)}</td>
                    <td class="detail-col mavg">{fmt_price(tf_data["mavg"])}</td>
                    <td class="detail-col ott">{fmt_price(tf_data["ott"])}</td>
                </tr>\n'''

    fib_section = fib_section_html(all_data, config)
    ia_section = ia_levels_section_html(all_data, config)
    season_banner = seasonality_banner_html(seasonality_context(datetime.now().month))
    macro_banner = macro_banner_html(macro_context(config))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OTT Signal Dashboard</title>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    :root {{
        --bg: #1a1d22;
        --surface: #252830;
        --surface-raised: #2d3038;
        --surface-hover: #343843;
        --ink: #e8e6e0;
        --ink-soft: #a8a59c;
        --ink-faint: #6e6c63;
        --line: #2d3038;
        --line-soft: #25282f;
        --accent: #d4a866;
        --sans: 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        --mono: 'JetBrains Mono', 'Courier New', monospace;
        --radius: 8px;
        --radius-lg: 12px;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: var(--sans);
        background: var(--bg);
        color: var(--ink);
        padding: 28px 24px 48px;
        max-width: 1280px;
        margin: 0 auto;
        line-height: 1.5;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }}
    ::selection {{ background: var(--accent); color: var(--bg); }}
    a {{ color: var(--accent); text-decoration: none; border-bottom: 1px solid transparent; transition: border-color 0.15s; }}
    a:hover {{ border-bottom-color: var(--accent); }}
    h1 {{
        color: var(--ink);
        margin-bottom: 4px;
        font-size: 28px;
        font-weight: 600;
        letter-spacing: -0.02em;
    }}
    .updated {{
        color: var(--ink-soft);
        font-size: 13px;
        margin-bottom: 18px;
    }}
    .params {{
        color: var(--ink-faint);
        font-family: var(--mono);
        font-size: 12px;
        margin-bottom: 16px;
    }}
    .controls {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
        flex-wrap: wrap;
    }}
    .tf-toggle {{
        display: flex;
        gap: 2px;
        background: var(--surface);
        padding: 4px;
        border-radius: var(--radius);
    }}
    .details-btn {{
        padding: 6px 14px;
        border: 1px solid var(--line);
        border-radius: 6px;
        background: var(--surface);
        color: var(--ink-soft);
        font-family: var(--sans);
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s;
    }}
    .details-btn:hover {{
        background: var(--surface-hover);
        color: var(--ink);
    }}
    .details-btn.active {{
        background: var(--accent);
        color: var(--bg);
        border-color: var(--accent);
    }}
    .detail-col {{
        display: none;
    }}
    table.show-details .detail-col {{
        display: table-cell;
    }}
    .tf-btn {{
        padding: 6px 16px;
        border: none;
        border-radius: 6px;
        background: transparent;
        color: var(--ink-soft);
        font-family: var(--sans);
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s;
    }}
    .tf-btn:hover {{
        color: var(--ink);
    }}
    .tf-btn.active {{
        background: var(--surface-raised);
        color: var(--ink);
    }}
    table {{
        width: auto;
        border-collapse: collapse;
        font-size: 13px;
        background: var(--surface);
        border-radius: var(--radius);
        overflow: hidden;
        margin-bottom: 6px;
    }}
    td.signals, th.signals-header {{
        text-align: left;
        white-space: nowrap;
        padding-left: 20px;
    }}
    th {{
        background: var(--surface-raised);
        color: var(--ink-soft);
        padding: 11px 8px;
        text-align: left;
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        border-bottom: 1px solid var(--line);
        position: sticky;
        top: 0;
    }}
    td {{
        padding: 7px 8px;
        border-bottom: 1px solid var(--line-soft);
    }}
    tr:hover {{
        background: var(--surface-hover);
    }}
    .category-row {{
        background: var(--surface-raised) !important;
    }}
    .strat-label {{
        font-weight: 400;
        font-size: 10px;
        color: var(--ink-faint);
        text-transform: none;
        letter-spacing: 0;
        margin-left: 8px;
    }}
    .category-row td {{
        font-weight: 600;
        color: var(--accent);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        padding: 7px 12px;
        border-bottom: none;
    }}
    .ticker {{
        font-weight: 600;
        color: var(--ink);
        font-size: 14px;
        white-space: nowrap;
    }}
    .trend-icon {{
        font-size: 10px;
        margin-right: 3px;
    }}
    .timeframe {{
        color: var(--ink-soft);
        font-size: 12px;
    }}
    .state {{
        font-weight: 700;
        font-size: 13px;
    }}
    .bullish {{ color: #00e676; }}
    .bearish {{ color: #ff5252; }}
    .price {{ color: var(--ink); font-weight: 500; }}
    .above-ema {{ color: #00e676; }}
    .below-ema {{ color: #ff5252; }}
    .mavg, .ott {{ color: var(--ink-soft); }}
    .signal-pill {{
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 10px;
        font-weight: 600;
        margin: 1px 2px;
        text-align: center;
        line-height: 1.3;
    }}
    .sig-price {{
        font-size: 9px;
        opacity: 0.8;
    }}
    .buy-signal {{
        background: rgba(27, 94, 32, 0.5);
        color: rgba(255, 255, 255, 0.5);
    }}
    .sell-signal {{
        background: rgba(183, 28, 28, 0.5);
        color: rgba(255, 255, 255, 0.5);
    }}
    .no-signal {{
        color: #555;
        font-size: 12px;
    }}
    .clickable-header {{
        cursor: pointer;
        user-select: none;
    }}
    .clickable-header:hover {{
        color: #ccc;
    }}
    .expand-all-btn {{
        cursor: pointer;
        font-size: 10px;
        color: #666;
        margin-left: 4px;
        transition: transform 0.2s;
        display: inline-block;
    }}
    .expand-all-btn:hover {{
        color: #aaa;
    }}
    .expand-all-btn.expanded {{
        transform: rotate(90deg);
    }}
    .clickable {{
        cursor: pointer;
    }}
    .clickable:hover {{
        opacity: 0.8;
    }}
    .older-signals {{
        display: none;
    }}
    .older-signals.show {{
        display: inline;
    }}
    .recent-signal.buy-signal {{
        background: #1b5e20;
        color: #fff;
    }}
    .recent-signal.sell-signal {{
        background: #b71c1c;
        color: #fff;
    }}
    .recent-buy-row {{
        border-left: 4px solid #00e676;
    }}
    .recent-sell-row {{
        border-left: 4px solid #ff5252;
    }}
    .error {{
        color: #ff5252;
        font-size: 12px;
    }}
    .analyst-level {{
        margin-left: 8px;
        font-size: 0.85em;
        color: #c9a227;
        cursor: help;
    }}
    .analyst-pending {{ color: #c9a227; }}
    .analyst-hit {{
        color: #00e676;
        font-weight: 700;
    }}
    .season-banner, .macro-banner {{
        margin-top: 20px;
        padding: 10px 14px;
        background: var(--surface);
        border: 1px solid var(--line);
        border-left: 3px solid var(--accent);
        border-radius: var(--radius);
        font-size: 12.5px;
        color: var(--ink-soft);
    }}
    .macro-banner {{ margin-bottom: 6px; }}
    .season-icon {{ margin-right: 4px; }}
    .season-banner b, .macro-banner b {{ color: var(--ink); }}
    .season-note {{ color: var(--ink-faint); font-size: 0.9em; }}
    .macro-take {{ color: var(--ink); margin-top: 6px; font-size: 1em; line-height: 1.5; }}
    .macro-note {{ color: var(--ink-faint); margin-top: 5px; font-size: 0.95em; line-height: 1.5; }}
    .fib-title {{
        margin-top: 34px;
        font-size: 22px;
        font-weight: 600;
        letter-spacing: -0.01em;
        color: var(--ink);
    }}
    .fib-sub {{ font-size: 0.6em; font-weight: 400; color: var(--ink-soft); margin-left: 8px; }}
    .fib-subtitle {{
        margin-top: 24px;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--accent);
        margin-bottom: 4px;
    }}
    .fib-table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 8px;
        font-size: 13px;
        background: var(--surface);
        border-radius: var(--radius);
        overflow: hidden;
    }}
    .fib-table th {{
        text-align: left;
        padding: 10px;
        background: var(--surface-raised);
        color: var(--ink-soft);
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        border-bottom: 1px solid var(--line);
        white-space: nowrap;
    }}
    .fib-table td {{
        padding: 8px 10px;
        border-bottom: 1px solid var(--line-soft);
        vertical-align: middle;
    }}
    .fib-table tbody tr:last-child td {{ border-bottom: none; }}
    .fib-scale {{ font-size: 0.8em; font-weight: 400; color: var(--ink-faint); margin-left: 6px; text-transform: none; letter-spacing: 0; }}
    .fib-range-cell {{ color: var(--ink-soft); white-space: nowrap; }}
    .fib-dt {{ color: var(--ink-faint); }}
    .fib-gain {{ color: #00e676; font-weight: 600; }}
    .fib-price {{ color: var(--ink); font-weight: 600; white-space: nowrap; }}
    .fib-lv {{ color: var(--ink-soft); white-space: nowrap; }}
    .fib-z {{ white-space: nowrap; }}
    .fib-lt {{ white-space: nowrap; }}
    .fib-near {{ color: #00e676; font-weight: 600; }}
    .ia-cell {{ color: var(--ink-soft); white-space: nowrap; }}
    .ia-here {{
        color: #5fb87a;
        font-weight: 700;
        background: rgba(95,184,122,0.12);
        border-radius: 4px;
        white-space: nowrap;
    }}
    .ia-hpct {{ display: block; font-size: 0.78em; font-weight: 400; color: var(--ink-faint); }}
    .ia-key {{ margin: 6px 0 2px; font-size: 12px; color: var(--ink-faint); }}
    .ia-trig-5 {{ border-left: 4px solid #5fb87a; }}
    .ia-trig-4 {{ border-left: 4px solid #e0c04a; }}
    .ia-trig-3 {{ border-left: 4px solid #e8925d; }}
    .ia-trig-2, .ia-trig-1 {{ border-left: 4px solid #d97a6c; }}
    .ia-zone {{ white-space: nowrap; font-weight: 600; }}
    .ia-prox-cell {{ white-space: nowrap; }}
    .ia-prox {{ display: inline-flex; align-items: center; gap: 7px; }}
    .ia-endlbl {{ font-size: 0.72em; line-height: 1.1; color: var(--ink-faint); text-align: center; }}
    .ia-prox-track {{
        position: relative;
        display: inline-block;
        width: 96px;
        flex: 0 0 96px;
        height: 8px;
        margin-top: 14px;
        background: var(--surface-raised);
        border-radius: 4px;
        vertical-align: middle;
    }}
    .ia-endlbl {{ flex: 0 0 54px; }}
    .ia-prox-lbl {{
        position: absolute;
        bottom: 11px;
        transform: translateX(-50%);
        font-size: 0.78em;
        color: var(--ink-soft);
        white-space: nowrap;
    }}
    .ia-prox-lbl.near {{ color: #5fb87a; font-weight: 700; }}
    .ia-prox-marker {{ position: absolute; top: 50%; transform: translate(-50%, -50%); }}
    .ia-mk-flat {{ width: 3px; height: 14px; background: #e8e6e0; border-radius: 2px; box-shadow: 0 0 0 2px var(--surface); }}
    .ia-mk-up {{
        width: 0; height: 0;
        border-top: 6px solid transparent; border-bottom: 6px solid transparent;
        border-left: 9px solid #5fb87a;
    }}
    .ia-mk-dn {{
        width: 0; height: 0;
        border-top: 6px solid transparent; border-bottom: 6px solid transparent;
        border-right: 9px solid #d97a6c;
    }}
    .ia-prox-txt {{ color: var(--ink-soft); font-size: 0.9em; margin-left: 2px; }}
    .ia-prox-txt.near {{ color: #5fb87a; font-weight: 700; }}
    .fib-sector {{
        margin-left: 7px;
        padding: 1px 7px;
        border-radius: 10px;
        background: var(--surface-raised);
        color: var(--ink-soft);
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 0.02em;
        vertical-align: middle;
    }}
    .fib-rank {{ color: var(--ink-faint); text-align: right; width: 24px; font-family: var(--mono); }}
    .fib-scorecell {{ white-space: nowrap; font-family: var(--mono); }}
    .fib-summary {{
        margin-top: 8px;
        padding: 14px 16px;
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius-lg);
        font-size: 13px;
        line-height: 1.7;
    }}
    .fib-sum-head {{ color: var(--ink-faint); font-weight: 600; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.85em; }}
    .fib-sum-line {{ margin: 2px 0; }}
    .fib-sum-tag {{
        display: inline-block;
        min-width: 128px;
        padding: 1px 8px;
        margin-right: 8px;
        border-radius: 4px;
        font-size: 0.82em;
        font-weight: 600;
        text-align: center;
    }}
    .fib-sum-tag.fav {{ background: #10391f; color: #00e676; }}
    .fib-sum-tag.mid {{ background: #3a3320; color: #e0c04a; }}
    .fib-sum-tag.warn {{ background: #3a2320; color: #ff8a5c; }}
    .fib-sum-tag.skip {{ background: #2a2a30; color: #888; }}
    .fib-meter-cell {{ white-space: nowrap; }}
    .fib-meter {{
        position: relative;
        display: inline-block;
        width: 180px;
        height: 14px;
        background: var(--surface-raised);
        border-radius: 3px;
        vertical-align: middle;
        overflow: hidden;
    }}
    .fib-meter-fill {{
        position: absolute;
        left: 0; top: 0; bottom: 0;
        border-radius: 3px 0 0 3px;
    }}
    .fib-tick {{
        position: absolute;
        top: 0; bottom: 0;
        width: 1px;
        background: rgba(255,255,255,0.28);
    }}
    .fib-pct {{ margin-left: 8px; font-weight: 600; }}
    .fib-lvl {{ font-weight: 400; font-size: 0.85em; opacity: 0.85; }}
    .fib-broken {{ margin-left: 6px; color: #6b6b6b; font-size: 0.85em; }}
    .legend {{
        margin-top: 24px;
        padding: 14px 16px;
        background: var(--surface);
        border-radius: var(--radius-lg);
        color: var(--ink-soft);
        font-size: 12px;
        line-height: 1.9;
    }}
</style>
</head>
<body>
    <h1>OTT Signal Dashboard</h1>
    <div class="updated">Last updated: {now}</div>
    <div class="params">OTT Period: {config["ott"]["period"]} | OTT Percent: {config["ott"]["percent"]} | Source: Open | MA Type: VAR | EMA: {config["ema_period"]}</div>
    <div class="controls">
        <div class="tf-toggle">
            <button class="tf-btn" onclick="setTimeframe('weekly', this)">Weekly</button>
            <button class="tf-btn active" onclick="setTimeframe('daily', this)">Daily</button>
            <button class="tf-btn" onclick="setTimeframe('4h', this)">4H</button>
        </div>
        <button class="details-btn" onclick="toggleDetails(this)">Show Details</button>
    </div>
    <table>
        <thead>
            <tr>
                <th class="clickable-header" onclick="toggleRecentOnly(document.getElementById('recent-filter-btn'))">Ticker <span class="expand-all-btn" id="recent-filter-btn">&#9654;</span></th>
                <th class="signals-header clickable-header" onclick="toggleAllSignals(document.getElementById('signals-expand-btn'))">Signals <span class="expand-all-btn" id="signals-expand-btn">&#9654;</span></th>
                <th class="detail-col">Price</th>
                <th class="detail-col">200 SMA</th>
                <th class="detail-col">MAvg</th>
                <th class="detail-col">OTT Line</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    {macro_banner}
    {season_banner}
    {fib_section}
    {ia_section}
    <div class="legend">
        <span class="signal-pill buy-signal">date</span> = Buy signal &nbsp;
        <span class="signal-pill sell-signal">date</span> = Sell signal &nbsp; | &nbsp;
        <span class="bullish">&#9650;</span> = MAvg above OTT (bullish) &nbsp;
        <span class="bearish">&#9660;</span> = MAvg below OTT (bearish) &nbsp; | &nbsp;
        <span style="font-size:0.9em;">σ = how unusual the current distance from 200d SMA is for this ticker (<span style="color:#888;">&lt;1.5σ normal</span>, <span style="color:#f0d060;">&ge;1.5σ notable</span>, <span style="color:#ffffff;">&ge;2σ unusual</span>)</span>
        <br><span style="font-size:0.9em;">&#9733; buy: analyst buy levels (hover for source &amp; date) &mdash; <span style="color:#c9a227;">pending</span>, <span style="color:#00e676;">reached</span></span>
    </div>
    <div style="margin-top: 24px;"><a href="backtest.html" style="font-size: 13px;">View Backtest Results &rarr;</a></div>

    <script>
    let currentTf = 'daily';
    let recentOnly = true;

    function applyFilters() {{
        document.querySelectorAll('tr[data-tf]').forEach(row => {{
            const tfMatch = row.dataset.tf === currentTf;
            const recentMatch = !recentOnly || row.classList.contains('recent-buy-row') || row.classList.contains('recent-sell-row');
            row.style.display = (tfMatch && recentMatch) ? '' : 'none';
        }});
    }}
    function setTimeframe(tf, btn) {{
        currentTf = tf;
        document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        applyFilters();
    }}
    function toggleRecentOnly(btn) {{
        recentOnly = !recentOnly;
        // expanded arrow = showing all, collapsed = recent only
        if (recentOnly) {{ btn.classList.remove('expanded'); }} else {{ btn.classList.add('expanded'); }}
        applyFilters();
    }}
    function toggleAllSignals(btn) {{
        btn.classList.toggle('expanded');
        const expanded = btn.classList.contains('expanded');
        document.querySelectorAll('.older-signals').forEach(el => {{
            if (expanded) {{ el.classList.add('show'); }} else {{ el.classList.remove('show'); }}
        }});
    }}
    function toggleDetails(btn) {{
        const table = document.querySelector('table');
        table.classList.toggle('show-details');
        btn.classList.toggle('active');
        btn.textContent = btn.classList.contains('active') ? 'Hide Details' : 'Show Details';
    }}
    applyFilters();
    </script>
</body>
</html>"""

    return html


def main():
    config = load_config()
    ott_period = config["ott"]["period"]
    ott_percent = config["ott"]["percent"]
    ema_period = config["ema_period"]
    fib_cfg = config.get("fib_alerts", {})
    fib_categories = fib_cfg.get("categories", ["Stocks"])

    print(f"OTT Dashboard Generator - {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Flatten watchlist, tracking category (drives per-category fib params)
    all_tickers = {}
    for category, tickers in config["watchlist"].items():
        for yf_ticker, display_name in tickers.items():
            all_tickers[yf_ticker] = (display_name, category)

    print(f"Fetching data for {len(all_tickers)} tickers...")
    all_data = {}
    for yf_ticker, (display_name, category) in all_tickers.items():
        print(f"  {display_name}...", end=" ", flush=True)
        fp = fib_params(fib_cfg, category)  # per-category detection params
        all_data[yf_ticker] = get_ticker_data(
            yf_ticker, ott_period, ott_percent, ema_period,
            fib_enabled=category in fib_categories,
            fib_lookback=fp["lookback"], fib_min_gain=fp["min_gain"],
            fib_reversal=fp["reversal"], fib_levels=fp["levels"],
        )
        print("done")

    html = generate_html(all_data, config)

    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    print(f"\nDashboard written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
