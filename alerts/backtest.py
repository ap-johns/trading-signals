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

from indicators import calculate_ott, calculate_sma, calculate_ema

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f)


def compute_rsi(close, period=14):
    """Calculate RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period, min_periods=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def backtest_ticker(df, ott_period, ott_percent, strategy=None,
                    zscore_buy=None, zscore_window=52):
    """
    Run OTT on a dataframe and return a list of completed trades.

    strategy options:
      None          - take all OTT signals (original)
      "trend"       - only buy above 200 SMA, only sell below 200 SMA
      "contra"      - only buy below 200 SMA, only sell above 200 SMA
      "hybrid"      - buy on all OTT buys, only sell above 200 SMA
      "hybrid_rsi"  - hybrid + also buy when RSI < 30 (even without OTT buy)
      "hybrid_dip"  - hybrid + also buy when price drops 10% from sell price
      "hybrid_sma50"- hybrid + also buy when price crosses above 50 SMA
      "always_in"   - start invested, sell above 200 SMA, buy back on OTT buy or 5% dip from sell

    zscore_buy: optional float (e.g. -2.0). When set, adds an extra BUY entry
      whenever the 200d-SMA distance z-score crosses DOWN through this level.
      Exits are unchanged (handled by `strategy`). This is a buy-only overlay.
      zscore_window matches the live signal's effective stats window: the live
      system fetches 365d and computes the 200d SMA within that slice, leaving
      ~52 bars with a defined SMA, so mean/std are over ~52 trading days. We
      replicate that causally (trailing rolling window) to avoid look-ahead.
    """
    if df.empty or len(df) < max(ott_period + 10, 200):
        return []

    src = df["Open"]
    ott_df = calculate_ott(src, period=ott_period, percent=ott_percent)
    sma_200 = calculate_sma(df["Close"], period=200)
    sma_50 = calculate_sma(df["Close"], period=50)
    rsi = compute_rsi(df["Close"], period=14)

    close = df["Close"]
    is_hybrid = strategy and strategy.startswith("hybrid")

    # Causal z-score of distance from 200d SMA (no look-ahead): at each bar,
    # mean/std are taken over the trailing `zscore_window` bars only.
    zscore = None
    if zscore_buy is not None:
        pct_from_sma = (close - sma_200) / sma_200 * 100
        roll_mean = pct_from_sma.rolling(zscore_window, min_periods=zscore_window).mean()
        roll_std = pct_from_sma.rolling(zscore_window, min_periods=zscore_window).std()
        zscore = (pct_from_sma - roll_mean) / roll_std

    # Day-by-day simulation
    trades = []
    in_trade = strategy == "always_in"  # Start invested for always_in
    buy_price = close.iloc[0] if in_trade else 0
    buy_date = df.index[0] if in_trade else None
    entry_via = "base"
    last_sell_price = None

    for i in range(1, len(df)):
        price = close.iloc[i]
        sig = ott_df["signal"].iloc[i]
        above_200 = price > sma_200.iloc[i] if pd.notna(sma_200.iloc[i]) else False
        above_50 = price > sma_50.iloc[i] if pd.notna(sma_50.iloc[i]) else False
        rsi_val = rsi.iloc[i] if pd.notna(rsi.iloc[i]) else 50

        if not in_trade:
            # Check for buy
            ott_buy = sig == 1
            take_buy = False

            if strategy is None:
                take_buy = ott_buy
            elif strategy == "trend":
                take_buy = ott_buy and above_200
            elif strategy == "contra":
                take_buy = ott_buy and not above_200
            elif strategy == "hybrid":
                take_buy = ott_buy
            elif strategy == "hybrid_rsi":
                take_buy = ott_buy or rsi_val < 30
            elif strategy == "hybrid_dip":
                dip_buy = last_sell_price and price < last_sell_price * 0.90
                take_buy = ott_buy or dip_buy
            elif strategy == "hybrid_sma50":
                # Buy on OTT buy, or when price crosses above 50 SMA
                crossed_50 = above_50 and close.iloc[i-1] <= sma_50.iloc[i-1] if pd.notna(sma_50.iloc[i-1]) else False
                take_buy = ott_buy or crossed_50
            elif strategy == "always_in":
                # Buy on OTT buy, or 5% dip from last sell price
                dip_buy = last_sell_price and price < last_sell_price * 0.95
                take_buy = ott_buy or dip_buy

            # Z-score buy overlay: fires when z crosses DOWN through the level
            z_triggered = False
            if zscore is not None:
                zi, zprev = zscore.iloc[i], zscore.iloc[i - 1]
                if pd.notna(zi) and pd.notna(zprev) and zprev > zscore_buy and zi <= zscore_buy:
                    z_triggered = True

            if take_buy or z_triggered:
                buy_price = price
                buy_date = df.index[i]
                in_trade = True
                # Attribute to the z-overlay only when the base strategy
                # wouldn't have bought on this bar anyway.
                entry_via = "z" if (z_triggered and not take_buy) else "base"

        else:
            # Check for sell
            ott_sell = sig == -1
            take_sell = False

            if strategy is None:
                take_sell = ott_sell
            elif strategy == "trend":
                take_sell = ott_sell and not above_200
            elif strategy == "contra":
                take_sell = ott_sell and above_200
            elif is_hybrid:
                # Hybrid: only sell above 200 SMA
                take_sell = ott_sell and above_200
            elif strategy == "always_in":
                # Always-in: sell on any OTT sell signal
                take_sell = ott_sell

            if take_sell:
                ret = (price - buy_price) / buy_price * 100
                duration = (df.index[i] - buy_date).days
                trades.append({
                    "buy_date": buy_date,
                    "sell_date": df.index[i],
                    "buy_price": buy_price,
                    "sell_price": price,
                    "return_pct": ret,
                    "duration_days": duration,
                    "entry_via": entry_via,
                })
                last_sell_price = price
                in_trade = False

    # For always_in, count unrealised position at end
    if strategy == "always_in" and in_trade:
        ret = (close.iloc[-1] - buy_price) / buy_price * 100
        duration = (df.index[-1] - buy_date).days
        trades.append({
            "buy_date": buy_date,
            "sell_date": df.index[-1],
            "buy_price": buy_price,
            "sell_price": close.iloc[-1],
            "return_pct": ret,
            "duration_days": duration,
            "entry_via": entry_via,
        })

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


def run_backtest(config, years=2, ema_filter=None, strategy=None):
    """Run backtest for all tickers on daily timeframe.
    strategy param takes priority over ema_filter for backwards compat."""
    strat = strategy or ema_filter
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
                trades = backtest_ticker(df, ott_period, ott_percent, strategy=strat)
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


def compounded_return(trades):
    """Compounded equity return (%) from a list of trades (more honest than summing %)."""
    eq = 1.0
    for t in trades:
        eq *= (1 + t["return_pct"] / 100)
    return (eq - 1) * 100


def run_zscore_sweep(config, years=5, thresholds=(-1.5, -2.0, -2.5),
                     zscore_window=52, scope=("Stocks", "Indices")):
    """Compare the z-score buy overlay at several thresholds against the
    native per-class strategy (no overlay) and buy & hold."""
    ott_period = config["ott"]["period"]
    ott_percent = config["ott"]["percent"]
    base_for = {"Stocks": "hybrid_sma50", "Indices": "always_in"}

    tickers = []
    for cat in scope:
        for yf_ticker, name in config["watchlist"].get(cat, {}).items():
            tickers.append((yf_ticker, name, cat))

    print(f"Fetching {len(tickers)} tickers ({years}y daily)...")
    data = {}
    for yf_ticker, name, cat in tickers:
        try:
            df = yf.Ticker(yf_ticker).history(period=f"{years}y", interval="1d")
            if not df.empty and len(df) >= 250:
                data[name] = (df, cat)
        except Exception as e:
            print(f"  {name}: {e}")

    variants = [("baseline", None)] + [(f"{t:+.1f}", t) for t in thresholds]
    per = {}   # (name, vlabel) -> stats
    bh = {}
    for name, (df, cat) in data.items():
        base = base_for[cat]
        bh[name] = (df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100
        for vlabel, thr in variants:
            trades = backtest_ticker(df, ott_period, ott_percent, strategy=base,
                                     zscore_buy=thr, zscore_window=zscore_window)
            per[(name, vlabel)] = {
                "comp": compounded_return(trades),
                "n": len(trades),
                "dd": calc_max_drawdown_strategy(df, trades),
                "z": [t for t in trades if t.get("entry_via") == "z"],
            }

    names = sorted(data, key=lambda n: data[n][1])  # group by category

    print(f"\n{'='*72}")
    print(f" Z-SCORE BUY OVERLAY SWEEP  |  {years}y  |  window={zscore_window} bars (~live)")
    print(f" Base: Stocks=hybrid_sma50, Indices=always_in. Buy-only overlay; exits unchanged.")
    print('='*72)

    # --- A) Are the z-entries themselves good trades? (pooled across tickers) ---
    print("\nA) Quality of the z-triggered entries themselves (pooled, completed trades):")
    print(f"   {'level':>6} {'#entries':>9} {'win%':>6} {'avg ret%':>9} {'median%':>8} {'avg days':>9}")
    for vlabel, thr in variants[1:]:
        zt = [t for name in data for t in per[(name, vlabel)]["z"]]
        closed = [t for t in zt if not t.get("open")]
        if not closed:
            print(f"   {vlabel:>6} {len(zt):>9} {'-':>6} {'-':>9} {'-':>8} {'-':>9}")
            continue
        rets = sorted(t["return_pct"] for t in closed)
        win = sum(1 for r in rets if r > 0) / len(rets) * 100
        avg = sum(rets) / len(rets)
        med = rets[len(rets) // 2]
        dur = sum(t["duration_days"] for t in closed) / len(closed)
        print(f"   {vlabel:>6} {len(zt):>9} {win:>5.0f}% {avg:>+9.1f} {med:>+8.1f} {dur:>8.0f}d")

    # --- B) Does the overlay help the portfolio vs baseline? ---
    print("\nB) Portfolio impact vs baseline (mean per-ticker compounded return & max DD):")
    print(f"   {'variant':>8} {'mean ret%':>10} {'vs base':>9} {'mean DD%':>9} {'#improved':>10} {'#worse':>7}")
    base_comps = {n: per[(n, 'baseline')]["comp"] for n in data}
    base_mean = sum(base_comps.values()) / len(base_comps)
    base_dd = sum(per[(n, 'baseline')]["dd"] for n in data) / len(data)
    print(f"   {'baseline':>8} {base_mean:>+10.1f} {'-':>9} {base_dd:>+9.1f} {'-':>10} {'-':>7}")
    for vlabel, thr in variants[1:]:
        comps = [per[(n, vlabel)]["comp"] for n in data]
        mean = sum(comps) / len(comps)
        dd = sum(per[(n, vlabel)]["dd"] for n in data) / len(data)
        imp = sum(1 for n in data if per[(n, vlabel)]["comp"] > base_comps[n] + 0.01)
        wor = sum(1 for n in data if per[(n, vlabel)]["comp"] < base_comps[n] - 0.01)
        print(f"   {vlabel:>8} {mean:>+10.1f} {mean - base_mean:>+9.1f} {dd:>+9.1f} {imp:>10} {wor:>7}")

    # --- C) Per-ticker compounded return ---
    print("\nC) Per-ticker compounded return (%):")
    hdr = f"   {'ticker':>7} {'cat':>8} {'base':>8}" + "".join(f"{v:>8}" for v, _ in variants[1:]) + f"{'B&H':>9}"
    print(hdr)
    for n in names:
        cat = data[n][1][:7]
        line = f"   {n:>7} {cat:>8} {per[(n,'baseline')]['comp']:>+8.0f}"
        for vlabel, _ in variants[1:]:
            line += f"{per[(n,vlabel)]['comp']:>+8.0f}"
        line += f"{bh[n]:>+9.0f}"
        print(line)
    print()


def backtest_crypto_cycle(config):
    """
    Backtest the crypto 4-year cycle strategy:
    Buy trigger 1: Entering a cycle buy window (±3 months of expected low)
    Buy trigger 2: Price drops -10%, -20%, -30% below 200 week EMA (anytime)
    Sell: ~1 month before the 4-year cycle peak (configurable).
    Uses max available weekly data.

    Historical cycle peaks used for backtesting:
    - Nov 2013, Dec 2017, Nov 2021, (configured future date)
    """
    crypto_tickers = config["watchlist"].get("Crypto", {})
    cycle_config = config.get("crypto_cycle", {})
    future_sell = cycle_config.get("sell_date", "2029-11-01")
    alert_months = cycle_config.get("alert_months_before", 1)
    default_windows = cycle_config.get("buy_windows", [])
    ticker_overrides = cycle_config.get("ticker_overrides", {})

    from datetime import datetime, timedelta

    def build_buy_ranges(windows):
        ranges = []
        for w in windows:
            center = datetime.strptime(w["center"], "%Y-%m-%d")
            half = timedelta(days=w["months"] * 30)
            ranges.append((center - half, center + half))
        return ranges

    # Historical cycle sell dates (1 month before known peaks)
    cycle_sell_dates = [
        datetime(2013, 10, 1),   # ~1 month before Nov 2013 peak
        datetime(2017, 11, 1),   # ~1 month before Dec 2017 peak
        datetime(2021, 10, 1),   # ~1 month before Nov 2021 peak
        datetime(2025, 9, 1),    # ~1 month before Oct 2025 peak
    ]
    future_dt = datetime.strptime(future_sell, "%Y-%m-%d")
    cycle_sell_dates.append(future_dt - timedelta(days=alert_months * 30))

    results = {}

    for yf_ticker, display_name in crypto_tickers.items():
        try:
            # Use ticker-specific windows if configured, otherwise default
            override = ticker_overrides.get(yf_ticker, {})
            windows = override.get("buy_windows", default_windows)
            buy_ranges = build_buy_ranges(windows)

            t = yf.Ticker(yf_ticker)
            df = t.history(period="max", interval="1wk")
            if df.empty or len(df) < 200:
                continue

            close = df["Close"]
            ema_200w = calculate_ema(close, period=200)

            # Simulate: buy on cycle timing or EMA dip, sell at cycle peak dates
            trades = []
            bought_levels = {}  # level -> buy_price, buy_date

            # Start from week 50 (EMA is usable much earlier than SMA)
            start_week = min(50, len(df) - 1)
            for i in range(start_week, len(df)):
                price = close.iloc[i]
                current_date = df.index[i].to_pydatetime().replace(tzinfo=None)
                ema_val = ema_200w.iloc[i]
                if pd.isna(ema_val):
                    continue

                pct_from_ema = (price - ema_val) / ema_val * 100

                # Check if we've hit a cycle sell date
                for sell_dt in cycle_sell_dates:
                    if bought_levels and current_date >= sell_dt and current_date < sell_dt + timedelta(days=7):
                        for level, buy_info in bought_levels.items():
                            ret = (price - buy_info["price"]) / buy_info["price"] * 100
                            duration = (df.index[i] - buy_info["date"]).days
                            trades.append({
                                "buy_date": buy_info["date"],
                                "sell_date": df.index[i],
                                "buy_price": buy_info["price"],
                                "sell_price": price,
                                "return_pct": ret,
                                "duration_days": duration,
                                "level": level,
                            })
                        bought_levels = {}
                        break

                # Buy trigger 1: cycle timing window
                in_buy_window = any(start <= current_date <= end for start, end in buy_ranges)
                if in_buy_window and "window" not in bought_levels:
                    bought_levels["window"] = {"price": price, "date": df.index[i]}

                # Buy trigger 2: EMA dip levels
                # For tickers with dip_only_in_window, only fire within buy window
                dip_allowed = in_buy_window if override.get("dip_only_in_window", False) else True
                if pct_from_ema < 0 and dip_allowed:
                    for level in [-10, -20, -30]:
                        if pct_from_ema <= level and level not in bought_levels:
                            bought_levels[level] = {"price": price, "date": df.index[i]}

            # Count unrealised positions
            for level, buy_info in bought_levels.items():
                ret = (close.iloc[-1] - buy_info["price"]) / buy_info["price"] * 100
                duration = (df.index[-1] - buy_info["date"]).days
                trades.append({
                    "buy_date": buy_info["date"],
                    "sell_date": df.index[-1],
                    "buy_price": buy_info["price"],
                    "sell_price": close.iloc[-1],
                    "return_pct": ret,
                    "duration_days": duration,
                    "level": level,
                    "open": True,
                })

            summary = summarize_trades(trades)
            summary["ticker"] = display_name
            summary["buy_hold"] = (close.iloc[-1] - close.iloc[200]) / close.iloc[200] * 100
            summary["max_dd_bh"] = calc_max_drawdown_bh(df.iloc[200:])
            summary["max_dd_ott"] = calc_max_drawdown_strategy(df, trades)
            summary["trades_detail"] = trades
            results[display_name] = summary

        except Exception as e:
            print(f"  Error backtesting crypto cycle {display_name}: {e}")

    return results


def generate_backtest_html(all_results, config, crypto_cycle_results=None):
    """Generate a standalone backtest HTML page."""
    from datetime import datetime
    now = datetime.now().strftime("%-d %b %y %H:%M")

    # Crypto cycle rows
    crypto_rows = ""
    if crypto_cycle_results:
        for display_name, stats in crypto_cycle_results.items():
            if stats["trades"] == 0:
                crypto_rows += f'<tr><td class="ticker">{display_name}</td><td colspan="8" class="muted">No trades (never below 200w SMA)</td></tr>\n'
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
            crypto_rows += f'''<tr>
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
            # Show individual trades
            for t in stats.get("trades_detail", []):
                is_open = t.get("open", False)
                t_class = "pos" if t["return_pct"] >= 0 else "neg"
                level_label = f"SMA" if t.get("level", 0) == 0 else f"{t.get('level', 0)}%"
                status = " (open)" if is_open else ""
                crypto_rows += f'''<tr style="color: #666; font-size: 12px;">
                    <td style="padding-left: 20px;">Entry: {level_label}</td>
                    <td colspan="2">{t["buy_date"].strftime("%-d %b %y")} &rarr; {t["sell_date"].strftime("%-d %b %y")}{status}</td>
                    <td class="{t_class}">{t["return_pct"]:+.1f}%</td>
                    <td colspan="2">${t["buy_price"]:.0f} &rarr; ${t["sell_price"]:.0f}</td>
                    <td colspan="3">{t["duration_days"]}d</td>
                </tr>\n'''

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
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: var(--sans); background: var(--bg); color: var(--ink); padding: 28px 24px 48px; max-width: 1280px; margin: 0 auto; line-height: 1.5; -webkit-font-smoothing: antialiased; }}
    ::selection {{ background: var(--accent); color: var(--bg); }}
    h1 {{ color: var(--ink); font-size: 28px; font-weight: 600; letter-spacing: -0.02em; margin-bottom: 4px; }}
    .updated {{ color: var(--ink-soft); font-size: 13px; margin-bottom: 8px; }}
    .params {{ color: var(--ink-faint); font-family: var(--mono); font-size: 12px; margin-bottom: 12px; }}
    .controls {{ display: flex; gap: 15px; margin-bottom: 12px; flex-wrap: wrap; }}
    .tf-toggle {{ display: flex; gap: 2px; background: var(--surface); padding: 4px; border-radius: var(--radius); }}
    .tf-btn {{ padding: 6px 16px; border: none; border-radius: 6px; background: transparent; color: var(--ink-soft); font-family: var(--sans); font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; }}
    .tf-btn:hover {{ color: var(--ink); }}
    .tf-btn.active {{ background: var(--surface-raised); color: var(--ink); }}
    table {{ width: auto; border-collapse: collapse; font-size: 13px; background: var(--surface); border-radius: var(--radius); overflow: hidden; margin-bottom: 6px; }}
    th {{ background: var(--surface-raised); color: var(--ink-soft); padding: 10px 8px; text-align: left; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; border-bottom: 1px solid var(--line); }}
    td {{ padding: 7px 8px; border-bottom: 1px solid var(--line-soft); }}
    tr:hover {{ background: var(--surface-hover); }}
    .category-row {{ background: var(--surface-raised) !important; }}
    .category-row td {{ font-weight: 600; color: var(--accent); font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; padding: 7px 8px; border-bottom: none; }}
    .ticker {{ font-weight: 600; color: var(--ink); font-size: 14px; white-space: nowrap; }}
    .pos {{ color: #00e676; }}
    .neg {{ color: #ff5252; }}
    .muted {{ color: var(--ink-faint); }}
    .strat-desc {{ color: var(--ink-soft); font-size: 12px; margin-bottom: 12px; line-height: 1.5; }}
    .strat-desc b {{ color: var(--ink); }}
    a {{ color: var(--accent); text-decoration: none; border-bottom: 1px solid transparent; }}
    a:hover {{ border-bottom-color: var(--accent); }}
    .back-link {{ color: var(--accent); font-size: 13px; margin-bottom: 15px; display: block; }}
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
            <button class="tf-btn bt-strat-btn" onclick="setBtStrat('hybrid_sma50', this)">OTT + SMA</button>
            <button class="tf-btn bt-strat-btn" onclick="setBtStrat('always_in', this)">Always-In</button>
        </div>
    </div>
    <div id="strat-desc" class="strat-desc"></div>
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

    <h2 style="color: #fff; font-size: 16px; margin-top: 30px; margin-bottom: 8px;">Crypto 4-Year Cycle (200 Week SMA)</h2>
    <div class="strat-desc">Buy when price drops below 200 week SMA (and at -10%, -20%, -30% levels). Sell when price crosses back above. Uses max available history.</div>
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
                <th>Max DD (Strat)</th>
                <th>Max DD (B&amp;H)</th>
            </tr>
        </thead>
        <tbody>
            {crypto_rows}
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
    const stratDescs = {{
        'ott': '<b>OTT Only</b> — Buy on all OTT buy signals. Sell on all OTT sell signals.',
        'hybrid_sma50': '<b>OTT + SMA</b> — Buy on OTT buy signal <b>or</b> price crosses above 50 SMA. Sell on OTT sell only when above 200 SMA.',
        'always_in': '<b>Always-In</b> — Start invested. Sell on OTT sell only when above 200 SMA. Buy back on OTT buy <b>or</b> 5% dip from sell price. Best for indices like SPX.',
    }};
    function updateStratDesc() {{
        document.getElementById('strat-desc').innerHTML = stratDescs[btStrat] || '';
    }}
    function setBtStrat(strat, btn) {{
        btStrat = strat;
        document.querySelectorAll('.bt-strat-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        updateStratDesc();
        applyBtFilters();
    }}
    updateStratDesc();
    applyBtFilters();
    </script>
</body>
</html>"""


def main():
    """Run backtest and generate standalone HTML page."""
    config = load_config()
    repo_dir = os.path.dirname(SCRIPT_DIR)
    output_path = os.path.join(repo_dir, "docs", "backtest.html")

    strategies = [
        ("ott", None),
        ("hybrid_sma50", "hybrid_sma50"),
        ("always_in", "always_in"),
    ]
    all_results = {}

    print("Running OTT Backtests...")
    for years in [1, 2, 5]:
        for strat_key, ema_filter in strategies:
            label = f"{years}_{strat_key}"
            print(f"  {years}yr {strat_key}...", end=" ", flush=True)
            all_results[label] = run_backtest(config, years=years, strategy=ema_filter)
            print("done")

    print("Running Crypto Cycle Backtest...")
    crypto_cycle = backtest_crypto_cycle(config)
    print(f"  {len(crypto_cycle)} tickers done")

    html = generate_backtest_html(all_results, config, crypto_cycle_results=crypto_cycle)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"\nBacktest written to: {output_path}")


if __name__ == "__main__":
    main()
