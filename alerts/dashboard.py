"""
Generate an HTML dashboard showing OTT signals for all tickers.
"""

import json
import os
from datetime import datetime

import yfinance as yf
import pandas as pd

from indicators import calculate_ott, calculate_ema

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_PATH = os.environ.get("DASHBOARD_OUTPUT", os.path.join(REPO_DIR, "docs", "index.html"))


def load_config():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f)


def get_ticker_data(yf_ticker, ott_period, ott_percent, ema_period):
    """Fetch data and calculate OTT for both timeframes."""
    results = {}

    # Daily
    try:
        t = yf.Ticker(yf_ticker)
        df = t.history(period="365d", interval="1d")
        if not df.empty and len(df) > ott_period + 10:
            src = df["Open"]
            ott_df = calculate_ott(src, period=ott_period, percent=ott_percent)
            ema_200 = calculate_ema(df["Close"], period=ema_period)

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

            results["daily"] = {
                "price": df["Close"].iloc[-1],
                "ema_200": ema_200.iloc[-1],
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
                ema_200 = calculate_ema(df_4h["Close"], period=ema_period)

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
        df = t.history(period="730d", interval="1d")
        if not df.empty:
            df_w = df.resample("W").agg({
                "Open": "first", "High": "max", "Low": "min",
                "Close": "last", "Volume": "sum",
            }).dropna()

            if len(df_w) > ott_period + 10:
                src = df_w["Open"]
                ott_df = calculate_ott(src, period=ott_period, percent=ott_percent)
                ema_200 = calculate_ema(df_w["Close"], period=ema_period)

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
                    "mavg": ott_df["mavg"].iloc[-1],
                    "ott": ott_df["ott"].iloc[-1],
                    "bullish": mavg_above_ott,
                    "signals": recent_signals,
                    "last_date": df_w.index[-1].strftime("%-d %b %y"),
                }
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

    rows = ""
    for category, tickers in config["watchlist"].items():
        rows += f'<tr class="category-row"><td colspan="6">{category}</td></tr>\n'

        for yf_ticker, display_name in tickers.items():
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
                ema_label = "Above" if price > ema_200 else "Below"

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
                rows += f'''<tr class="{row_class}" data-tf="{tf}">
                    <td class="ticker"><span class="trend-icon {state_class}">{trend_arrow}</span> {display_name}</td>
                    <td class="signals">{signals_html}</td>
                    <td class="detail-col price">{fmt_price(price)}</td>
                    <td class="detail-col ema {ema_class}">{fmt_price(ema_200)} ({ema_label})</td>
                    <td class="detail-col mavg">{fmt_price(tf_data["mavg"])}</td>
                    <td class="detail-col ott">{fmt_price(tf_data["ott"])}</td>
                </tr>\n'''

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
                <th class="detail-col">200 EMA</th>
                <th class="detail-col">MAvg</th>
                <th class="detail-col">OTT Line</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    <div class="legend">
        <span class="signal-pill buy-signal">date</span> = Buy signal &nbsp;
        <span class="signal-pill sell-signal">date</span> = Sell signal &nbsp; | &nbsp;
        <span class="bullish">&#9650;</span> = MAvg above OTT (bullish) &nbsp;
        <span class="bearish">&#9660;</span> = MAvg below OTT (bearish)
    </div>
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
        all_data[yf_ticker] = get_ticker_data(yf_ticker, ott_period, ott_percent, ema_period)
        print("done")

    html = generate_html(all_data, config)

    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    print(f"\nDashboard written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
