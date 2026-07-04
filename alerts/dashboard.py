"""
Generate an HTML dashboard showing OTT signals for all tickers.
"""

import json
import os
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

from indicators import calculate_ott, calculate_sma, calculate_ema, calculate_fib_levels

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


def fib_section_html(all_data, config):
    """Build the Fibonacci retracement table for stocks with a qualifying uptrend."""
    stocks = config["watchlist"].get("Stocks", {})
    entries = []
    for yf_ticker, display_name in stocks.items():
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
        entries.append((display_name, fib, price, frac, daily))

    if not entries:
        return ""

    # Deepest retracements first (closest to a buy zone); broken (>=100%) last.
    entries.sort(key=lambda e: (e[3] >= 1.0, -e[3]))

    rows = ""
    for name, fib, price, frac, daily in entries:
        broken = frac >= 1.0
        lo = f'{fmt_price(fib["swing_low"])} <span class="fib-dt">({_fmt_date(fib["swing_low_date"])})</span>'
        hi = f'{fmt_price(fib["swing_high"])} <span class="fib-dt">({_fmt_date(fib["swing_high_date"])})</span>'
        color = fib_retrace_color(frac)
        pct_label = f'{frac * 100:.0f}%'
        if broken:
            depth_html = f'<span class="fib-pct" style="color:{color};">{pct_label}</span> <span class="fib-broken">below low</span>'
        else:
            depth_html = f'<span class="fib-pct" style="color:{color};">{pct_label} <span class="fib-lvl">{fib_level_label(frac)}</span></span>'
        sma50 = daily.get("sma_50")
        support = daily.get("support")
        z = daily.get("sma_zscore")
        z_html = (f'<span style="color:{zscore_color(z)};">{z:+.1f}&sigma;</span>'
                  if z is not None else '<span class="fib-dt">&mdash;</span>')
        rows += f'''<tr>
            <td class="ticker">{name}</td>
            <td class="fib-range-cell">{lo} &rarr; {hi}</td>
            <td class="fib-gain">+{fib["gain"] * 100:.0f}%</td>
            <td class="fib-price">{fmt_price(price)}</td>
            <td class="fib-lv">{level_cell(sma50, price)}{slope_arrow(daily.get("sma_50_dir"))}</td>
            <td class="fib-lv">{level_cell(support, price)}</td>
            <td class="fib-z">{z_html}</td>
            <td class="fib-meter-cell">{fib_meter_html(frac)}{depth_html}</td>
        </tr>\n'''

    return f'''
    <h2 class="fib-title">Fibonacci Retracements <span class="fib-sub">weekly uptrend &middot; deeper = closer to buy zone &middot; <span class="fib-near">green</span> = price within 5% of the level &middot; <span style="color:#00e676;">&#9650;</span>/<span style="color:#ff5252;">&#9660;</span> = 50d SMA rising/falling</span></h2>
    <table class="fib-table">
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Uptrend (low &rarr; high)</th>
                <th>Gain</th>
                <th class="fib-price">Price</th>
                <th>50d SMA</th>
                <th>Support</th>
                <th>z-score</th>
                <th>Retracement <span class="fib-scale">high&larr;&nbsp;0.382&nbsp;0.5&nbsp;0.618&nbsp;0.786&nbsp;&rarr;low</span></th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>'''


def get_ticker_data(yf_ticker, ott_period, ott_percent, ema_period,
                    fib_lookback=104, fib_min_gain=0.30, fib_reversal=0.14,
                    fib_levels=(0.382, 0.5, 0.618, 0.786)):
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

            results["daily"] = {
                "price": price_now,
                "ema_200": ema_200.iloc[-1],
                "sma_zscore": sma_zscore,
                "sma_50": sma_50,
                "sma_50_dir": sma_50_dir,
                "support": support,
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
                    "mavg": ott_df["mavg"].iloc[-1],
                    "ott": ott_df["ott"].iloc[-1],
                    "bullish": mavg_above_ott,
                    "signals": recent_signals,
                    "last_date": df_w.index[-1].strftime("%-d %b %y"),
                }

                # Fibonacci retracement of the dominant weekly uptrend
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

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OTT Signal Dashboard</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #1a1a2e;
        color: #e0e0e0;
        padding: 12px;
    }}
    h1 {{
        color: #fff;
        margin-bottom: 4px;
        font-size: 20px;
    }}
    .updated {{
        color: #888;
        font-size: 13px;
        margin-bottom: 20px;
    }}
    .params {{
        color: #666;
        font-size: 12px;
        margin-bottom: 15px;
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
        gap: 4px;
    }}
    .details-btn {{
        padding: 6px 14px;
        border: 1px solid #333;
        border-radius: 6px;
        background: #16213e;
        color: #888;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
    }}
    .details-btn:hover {{
        background: #1f2b45;
        color: #ccc;
    }}
    .details-btn.active {{
        background: #0f3460;
        color: #fff;
        border-color: #0f3460;
    }}
    .detail-col {{
        display: none;
    }}
    table.show-details .detail-col {{
        display: table-cell;
    }}
    .tf-btn {{
        padding: 6px 18px;
        border: 1px solid #333;
        border-radius: 6px;
        background: #16213e;
        color: #888;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
    }}
    .tf-btn:hover {{
        background: #1f2b45;
        color: #ccc;
    }}
    .tf-btn.active {{
        background: #0f3460;
        color: #fff;
        border-color: #0f3460;
    }}
    table {{
        width: auto;
        border-collapse: collapse;
        font-size: 13px;
    }}
    td.signals, th.signals-header {{
        text-align: left;
        white-space: nowrap;
        padding-left: 20px;
    }}
    th {{
        background: #16213e;
        color: #a0a0a0;
        padding: 12px 8px;
        text-align: left;
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 2px solid #0f3460;
        position: sticky;
        top: 0;
    }}
    td {{
        padding: 6px 8px;
        border-bottom: 1px solid #1f2b45;
    }}
    tr:hover {{
        background: #16213e;
    }}
    .category-row {{
        background: #0f3460 !important;
    }}
    .strat-label {{
        font-weight: 400;
        font-size: 10px;
        color: #888;
        text-transform: none;
        letter-spacing: 0;
        margin-left: 8px;
    }}
    .category-row td {{
        font-weight: 700;
        color: #fff;
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 1px;
        padding: 6px 12px;
        border-bottom: none;
    }}
    .ticker {{
        font-weight: 700;
        color: #fff;
        font-size: 14px;
        white-space: nowrap;
    }}
    .trend-icon {{
        font-size: 10px;
        margin-right: 3px;
    }}
    .timeframe {{
        color: #888;
        font-size: 12px;
    }}
    .state {{
        font-weight: 700;
        font-size: 13px;
    }}
    .bullish {{ color: #00e676; }}
    .bearish {{ color: #ff5252; }}
    .price {{ color: #fff; font-weight: 500; }}
    .above-ema {{ color: #00e676; }}
    .below-ema {{ color: #ff5252; }}
    .mavg, .ott {{ color: #aaa; }}
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
    .fib-title {{
        margin-top: 28px;
        font-size: 18px;
        font-weight: 600;
        color: #e0e0e0;
    }}
    .fib-sub {{ font-size: 0.7em; font-weight: 400; color: #888; margin-left: 8px; }}
    .fib-table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 10px;
        font-size: 13px;
    }}
    .fib-table th {{
        text-align: left;
        padding: 8px 10px;
        color: #888;
        font-weight: 600;
        border-bottom: 1px solid #2a2a44;
        white-space: nowrap;
    }}
    .fib-table td {{
        padding: 8px 10px;
        border-bottom: 1px solid #23233a;
        vertical-align: middle;
    }}
    .fib-scale {{ font-size: 0.8em; font-weight: 400; color: #666; margin-left: 6px; }}
    .fib-range-cell {{ color: #b8b8c8; white-space: nowrap; }}
    .fib-dt {{ color: #777; }}
    .fib-gain {{ color: #00e676; font-weight: 600; }}
    .fib-price {{ color: #e0e0e0; font-weight: 600; white-space: nowrap; }}
    .fib-lv {{ color: #b8b8c8; white-space: nowrap; }}
    .fib-z {{ white-space: nowrap; }}
    .fib-near {{ color: #00e676; font-weight: 600; }}
    .fib-meter-cell {{ white-space: nowrap; }}
    .fib-meter {{
        position: relative;
        display: inline-block;
        width: 180px;
        height: 14px;
        background: #23233a;
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
        margin-top: 20px;
        color: #666;
        font-size: 12px;
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
    {fib_section}
    <div class="legend">
        <span class="signal-pill buy-signal">date</span> = Buy signal &nbsp;
        <span class="signal-pill sell-signal">date</span> = Sell signal &nbsp; | &nbsp;
        <span class="bullish">&#9650;</span> = MAvg above OTT (bullish) &nbsp;
        <span class="bearish">&#9660;</span> = MAvg below OTT (bearish) &nbsp; | &nbsp;
        <span style="font-size:0.9em;">σ = how unusual the current distance from 200d SMA is for this ticker (<span style="color:#888;">&lt;1.5σ normal</span>, <span style="color:#f0d060;">&ge;1.5σ notable</span>, <span style="color:#ffffff;">&ge;2σ unusual</span>)</span>
        <br><span style="font-size:0.9em;">&#9733; buy: analyst buy levels (hover for source &amp; date) &mdash; <span style="color:#c9a227;">pending</span>, <span style="color:#00e676;">reached</span></span>
    </div>
    <div style="margin-top: 20px;"><a href="backtest.html" style="color: #888; font-size: 13px;">View Backtest Results &rarr;</a></div>

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
    fib_lookback = fib_cfg.get("lookback", 104)
    fib_min_gain = fib_cfg.get("min_gain", 0.30)
    fib_reversal = fib_cfg.get("reversal", 0.14)
    fib_levels = fib_cfg.get("levels", [0.382, 0.5, 0.618, 0.786])

    print(f"OTT Dashboard Generator - {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Flatten watchlist for processing
    all_tickers = {}
    for category, tickers in config["watchlist"].items():
        for yf_ticker, display_name in tickers.items():
            all_tickers[yf_ticker] = display_name

    print(f"Fetching data for {len(all_tickers)} tickers...")
    all_data = {}
    for yf_ticker, display_name in all_tickers.items():
        print(f"  {display_name}...", end=" ", flush=True)
        all_data[yf_ticker] = get_ticker_data(
            yf_ticker, ott_period, ott_percent, ema_period,
            fib_lookback=fib_lookback, fib_min_gain=fib_min_gain,
            fib_reversal=fib_reversal, fib_levels=fib_levels,
        )
        print("done")

    html = generate_html(all_data, config)

    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    print(f"\nDashboard written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
