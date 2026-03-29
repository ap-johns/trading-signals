"""
OTT Backtest

Backtests OTT signals against historical data for all tickers.
Pairs buy→sell signals as trades and calculates performance stats.
Supports multiple strategies: OTT only, OTT + 200 EMA filters.
"""

import json
import os

import yfinance as yf
import pandas as pd

from indicators import calculate_ott, calculate_ema

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f)


def backtest_ticker(df, ott_period, ott_percent, ema_filter=None):
    """
    Run OTT on a dataframe and return a list of completed trades.

    ema_filter options:
      None     - take all OTT signals (original)
      "trend"  - only buy above 200 EMA, only sell below 200 EMA
      "contra" - only buy below 200 EMA, only sell above 200 EMA
    """
    if df.empty or len(df) < max(ott_period + 10, 200):
        return []

    src = df["Open"]
    ott_df = calculate_ott(src, period=ott_period, percent=ott_percent)
    ema_200 = calculate_ema(df["Close"], period=200)

    # Extract signal dates with EMA context
    signals = []
    for i in range(len(ott_df)):
        sig = ott_df["signal"].iloc[i]
        if sig != 0:
            price = df["Close"].iloc[i]
            ema_val = ema_200.iloc[i]
            above_ema = price > ema_val
            signals.append({
                "date": df.index[i],
                "type": "BUY" if sig == 1 else "SELL",
                "price": price,
                "above_ema": above_ema,
            })

    # Pair buy→sell as trades with optional EMA filter
    trades = []
    in_trade = False
    buy_info = None

    for sig in signals:
        if sig["type"] == "BUY" and not in_trade:
            # Check if we should take this buy
            take_buy = True
            if ema_filter == "trend" and not sig["above_ema"]:
                take_buy = False  # Only buy above EMA
            elif ema_filter == "contra" and sig["above_ema"]:
                take_buy = False  # Only buy below EMA

            if take_buy:
                buy_info = sig
                in_trade = True

        elif sig["type"] == "SELL" and in_trade:
            # Check if we should take this sell
            take_sell = True
            if ema_filter == "trend" and sig["above_ema"]:
                take_sell = False  # Only sell below EMA
            elif ema_filter == "contra" and not sig["above_ema"]:
                take_sell = False  # Only sell above EMA

            if take_sell:
                ret = (sig["price"] - buy_info["price"]) / buy_info["price"] * 100
                duration = (sig["date"] - buy_info["date"]).days
                trades.append({
                    "buy_date": buy_info["date"],
                    "sell_date": sig["date"],
                    "buy_price": buy_info["price"],
                    "sell_price": sig["price"],
                    "return_pct": ret,
                    "duration_days": duration,
                })
                in_trade = False

    return trades


def summarize_trades(trades):
    """Calculate summary stats from a list of trades."""
    if not trades:
        return {
            "trades": 0,
            "win_rate": 0,
            "avg_return": 0,
            "total_return": 0,
            "best_trade": 0,
            "worst_trade": 0,
            "avg_duration": 0,
        }

    returns = [t["return_pct"] for t in trades]
    wins = sum(1 for r in returns if r > 0)
    durations = [t["duration_days"] for t in trades]

    return {
        "trades": len(trades),
        "win_rate": wins / len(trades) * 100,
        "avg_return": sum(returns) / len(returns),
        "total_return": sum(returns),
        "best_trade": max(returns),
        "worst_trade": min(returns),
        "avg_duration": sum(durations) / len(durations),
    }


def calc_max_drawdown_bh(df):
    """Calculate max drawdown for buy & hold over the full period."""
    close = df["Close"]
    peak = close.cummax()
    drawdown = (close - peak) / peak * 100
    return drawdown.min()  # Most negative = worst drawdown


def calc_max_drawdown_strategy(df, trades):
    """
    Calculate max drawdown experienced while in OTT trades.
    Tracks cumulative equity across all trades.
    """
    if not trades:
        return 0

    # Build equity curve: start at 100, compound trade returns
    equity = [100.0]
    for t in trades:
        # During trade, track the worst intra-trade drawdown
        new_eq = equity[-1] * (1 + t["return_pct"] / 100)
        equity.append(new_eq)

    # Max drawdown of the equity curve
    peak = 0
    max_dd = 0
    for val in equity:
        peak = max(peak, val)
        dd = (val - peak) / peak * 100
        max_dd = min(max_dd, dd)

    return max_dd


def run_backtest(config, years=2, ema_filter=None):
    """Run backtest for all tickers on daily timeframe."""
    ott_period = config["ott"]["period"]
    ott_percent = config["ott"]["percent"]
    results = {}

    all_tickers = {}
    for category, tickers in config["watchlist"].items():
        for yf_ticker, display_name in tickers.items():
            all_tickers[yf_ticker] = (display_name, category)

    for yf_ticker, (display_name, category) in all_tickers.items():
        try:
            t = yf.Ticker(yf_ticker)
            df = t.history(period=f"{years}y", interval="1d")
            if not df.empty:
                trades = backtest_ticker(df, ott_period, ott_percent, ema_filter=ema_filter)
                summary = summarize_trades(trades)
                summary["ticker"] = display_name
                summary["category"] = category
                summary["buy_hold"] = (df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100
                summary["max_dd_bh"] = calc_max_drawdown_bh(df)
                summary["max_dd_ott"] = calc_max_drawdown_strategy(df, trades)
                results[display_name] = summary
        except Exception as e:
            print(f"  Error backtesting {display_name}: {e}")

    return results


def generate_backtest_html(all_results, config):
    """Generate a standalone backtest HTML page."""
    from datetime import datetime
    now = datetime.now().strftime("%-d %b %y %H:%M")

    rows = ""
    for label, results in all_results.items():
        parts = label.split("_", 1)
        years = parts[0]
        strat = parts[1]
        for category, tickers in config["watchlist"].items():
            rows += f'<tr class="category-row bt-row" data-bt-period="{years}" data-bt-strat="{strat}"><td colspan="9">{category}</td></tr>\n'
            for yf_ticker, display_name in tickers.items():
                stats = results.get(display_name)
                if not stats or stats["trades"] == 0:
                    bh = stats.get("buy_hold", 0) if stats else 0
                    bh_class = "pos" if bh >= 0 else "neg"
                    dd_bh = stats.get("max_dd_bh", 0) if stats else 0
                    rows += f'<tr class="bt-row" data-bt-period="{years}" data-bt-strat="{strat}"><td class="ticker">{display_name}</td><td colspan="5" class="muted">No trades</td><td class="{bh_class}">{bh:+.1f}%</td><td>-</td><td class="neg">{dd_bh:.1f}%</td></tr>\n'
                    continue
                wr_class = "pos" if stats["win_rate"] >= 50 else "neg"
                avg_class = "pos" if stats["avg_return"] >= 0 else "neg"
                tot_class = "pos" if stats["total_return"] >= 0 else "neg"
                bh = stats.get("buy_hold", 0)
                bh_class = "pos" if bh >= 0 else "neg"
                dd_ott = stats.get("max_dd_ott", 0)
                dd_bh = stats.get("max_dd_bh", 0)
                dd_ott_class = "pos" if dd_ott > dd_bh else "neg"
                dd_bh_class = "pos" if dd_bh > dd_ott else "neg"
                rows += f'''<tr class="bt-row" data-bt-period="{years}" data-bt-strat="{strat}">
                    <td class="ticker">{display_name}</td>
                    <td>{stats["trades"]}</td>
                    <td class="{wr_class}">{stats["win_rate"]:.0f}%</td>
                    <td class="{avg_class}">{stats["avg_return"]:+.1f}%</td>
                    <td class="{tot_class}">{stats["total_return"]:+.1f}%</td>
                    <td>{stats["avg_duration"]:.0f}d</td>
                    <td class="{bh_class}">{bh:+.1f}%</td>
                    <td class="{dd_ott_class}">{dd_ott:.1f}%</td>
                    <td class="{dd_bh_class}">{dd_bh:.1f}%</td>
                </tr>\n'''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OTT Backtest Results</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 12px; }}
    h1 {{ color: #fff; font-size: 20px; margin-bottom: 4px; }}
    .updated {{ color: #888; font-size: 13px; margin-bottom: 8px; }}
    .params {{ color: #666; font-size: 12px; margin-bottom: 12px; }}
    .controls {{ display: flex; gap: 15px; margin-bottom: 12px; flex-wrap: wrap; }}
    .tf-toggle {{ display: flex; gap: 4px; }}
    .tf-btn {{ padding: 6px 18px; border: 1px solid #333; border-radius: 6px; background: #16213e; color: #888; font-size: 13px; font-weight: 600; cursor: pointer; }}
    .tf-btn:hover {{ background: #1f2b45; color: #ccc; }}
    .tf-btn.active {{ background: #0f3460; color: #fff; border-color: #0f3460; }}
    table {{ width: auto; border-collapse: collapse; font-size: 13px; }}
    th {{ background: #16213e; color: #a0a0a0; padding: 8px; text-align: left; font-size: 11px; text-transform: uppercase; border-bottom: 2px solid #0f3460; }}
    td {{ padding: 6px 8px; border-bottom: 1px solid #1f2b45; }}
    tr:hover {{ background: #16213e; }}
    .category-row {{ background: #0f3460 !important; }}
    .category-row td {{ font-weight: 700; color: #fff; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; padding: 6px 8px; border-bottom: none; }}
    .ticker {{ font-weight: 700; color: #fff; font-size: 14px; white-space: nowrap; }}
    .pos {{ color: #00e676; }}
    .neg {{ color: #ff5252; }}
    .muted {{ color: #555; }}
    .back-link {{ color: #888; font-size: 13px; margin-bottom: 15px; display: block; }}
    .back-link:hover {{ color: #ccc; }}
</style>
</head>
<body>
    <a class="back-link" href="index.html">&larr; Back to Dashboard</a>
    <h1>OTT Backtest Results</h1>
    <div class="updated">Generated: {now}</div>
    <div class="params">OTT Period: {config["ott"]["period"]} | OTT Percent: {config["ott"]["percent"]} | Source: Open | MA Type: VAR</div>
    <div class="controls">
        <div class="tf-toggle">
            <button class="tf-btn bt-period-btn" onclick="setBtPeriod(1, this)">1 Year</button>
            <button class="tf-btn bt-period-btn active" onclick="setBtPeriod(2, this)">2 Years</button>
            <button class="tf-btn bt-period-btn" onclick="setBtPeriod(5, this)">5 Years</button>
        </div>
        <div class="tf-toggle">
            <button class="tf-btn bt-strat-btn active" onclick="setBtStrat('ott', this)">OTT Only</button>
            <button class="tf-btn bt-strat-btn" onclick="setBtStrat('contra', this)">OTT + 200 EMA</button>
        </div>
    </div>
    <table>
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Trades</th>
                <th>Win Rate</th>
                <th>Avg Return</th>
                <th>Total Return</th>
                <th>Avg Duration</th>
                <th>Buy &amp; Hold</th>
                <th>Max DD (OTT)</th>
                <th>Max DD (B&amp;H)</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    <script>
    let btPeriod = '2';
    let btStrat = 'ott';
    function applyBtFilters() {{
        document.querySelectorAll('.bt-row').forEach(row => {{
            row.style.display = (row.dataset.btPeriod == btPeriod && row.dataset.btStrat == btStrat) ? '' : 'none';
        }});
    }}
    function setBtPeriod(years, btn) {{
        btPeriod = years;
        document.querySelectorAll('.bt-period-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        applyBtFilters();
    }}
    function setBtStrat(strat, btn) {{
        btStrat = strat;
        document.querySelectorAll('.bt-strat-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        applyBtFilters();
    }}
    applyBtFilters();
    </script>
</body>
</html>"""


def main():
    """Run backtest and generate standalone HTML page."""
    config = load_config()
    repo_dir = os.path.dirname(SCRIPT_DIR)
    output_path = os.path.join(repo_dir, "docs", "backtest.html")

    strategies = [("ott", None), ("contra", "contra")]
    all_results = {}

    print("Running OTT Backtests...")
    for years in [1, 2, 5]:
        for strat_key, ema_filter in strategies:
            label = f"{years}_{strat_key}"
            print(f"  {years}yr {strat_key}...", end=" ", flush=True)
            all_results[label] = run_backtest(config, years=years, ema_filter=ema_filter)
            print("done")

    html = generate_backtest_html(all_results, config)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"\nBacktest written to: {output_path}")


if __name__ == "__main__":
    main()
