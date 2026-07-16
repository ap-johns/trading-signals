#!/usr/bin/env python3
"""
OTT Signal Checker

Fetches market data, calculates OTT indicator, and sends Telegram alerts
when buy/sell signals are detected.

Usage: python3 signal_checker.py
"""

import json
import os
import sys
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.parse import urlencode

import yfinance as yf
import pandas as pd

from indicators import calculate_ott, calculate_sma, calculate_ema, calculate_fib_levels, atr_levels
from fib_score import fib_params

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f)


def _fmt_date(idx):
    """Format a DataFrame index label (Timestamp) as a short date, e.g. '3 Jun 25'."""
    if hasattr(idx, "strftime"):
        try:
            return idx.strftime("%-d %b %y")
        except ValueError:
            return idx.strftime("%d %b %y")
    return str(idx)


def send_telegram(bot_token: str, chat_id: str, message: str):
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode()
    req = Request(url, data=data, method="POST")
    with urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_daily_data(ticker: str, days: int = 365) -> pd.DataFrame:
    """Fetch daily OHLCV data."""
    t = yf.Ticker(ticker)
    df = t.history(period=f"{days}d", interval="1d")
    return df


def fetch_weekly_data(ticker: str) -> pd.DataFrame:
    """Fetch weekly OHLCV data (full history)."""
    t = yf.Ticker(ticker)
    return t.history(period="max", interval="1wk").dropna()


def fetch_4h_data(ticker: str) -> pd.DataFrame:
    """Fetch 4h data by resampling 1h candles (yfinance max 730 days for 1h)."""
    t = yf.Ticker(ticker)
    # yfinance allows max 730 days of 1h data
    df = t.history(period="60d", interval="1h")
    if df.empty:
        return df

    # Resample to 4h candles
    df_4h = df.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()

    return df_4h


def check_signals(config: dict) -> list:
    """Check all tickers for OTT signals on all timeframes."""
    ott_period = config["ott"]["period"]
    ott_percent = config["ott"]["percent"]
    ema_period = config["ema_period"]
    timeframes = config.get("alert_timeframes", config["timeframes"])
    zscore_cfg = config.get("zscore_alerts", {})
    zscore_enabled = zscore_cfg.get("enabled", True)
    zscore_levels = zscore_cfg.get("levels", [1.0, 1.5, 2.0, 2.5, 3.0])
    zscore_reset_band = zscore_cfg.get("reset_band", 0.5)
    fib_cfg = config.get("fib_alerts", {})
    fib_enabled = fib_cfg.get("enabled", True)
    fib_categories = fib_cfg.get("categories", ["Stocks"])
    signals = []

    # Persistent alert state (dedupes z-score level + crypto cycle alerts across runs)
    cycle_state = load_cycle_state()

    # Flatten watchlist
    all_tickers = {}
    for category, tickers in config["watchlist"].items():
        for yf_ticker, display_name in tickers.items():
            all_tickers[yf_ticker] = (display_name, category)

    for yf_ticker, (display_name, category) in all_tickers.items():
        for tf in timeframes:
            try:
                if tf == "daily":
                    df = fetch_daily_data(yf_ticker)
                elif tf == "4h":
                    df = fetch_4h_data(yf_ticker)
                else:
                    continue

                if df.empty or len(df) < ott_period + 10:
                    continue

                # OTT uses Open price (matching TradingView settings)
                src = df["Open"]
                ott_df = calculate_ott(src, period=ott_period, percent=ott_percent)
                sma_200 = calculate_sma(df["Close"], period=ema_period)
                sma_50 = calculate_sma(df["Close"], period=50)

                price = df["Close"].iloc[-1]
                sma200_val = sma_200.iloc[-1]
                sma50_val = sma_50.iloc[-1]
                sma200_relation = "above" if price > sma200_val else "below"
                above_200 = price > sma200_val if pd.notna(sma200_val) else False
                above_50 = price > sma50_val if pd.notna(sma50_val) else False
                prev_above_50 = df["Close"].iloc[-2] > sma_50.iloc[-2] if pd.notna(sma_50.iloc[-2]) else False
                date_str = df.index[-1].strftime("%Y-%m-%d %H:%M")

                ott_signal = ott_df["signal"].iloc[-1]
                crossed_above_50 = above_50 and not prev_above_50
                is_index = category == "Indices"

                if is_index:
                    # ALWAYS-IN strategy for indices
                    # Find last sell price (most recent OTT sell above 200 SMA)
                    last_sell_price = None
                    for j in range(len(ott_df) - 2, 0, -1):
                        if ott_df["signal"].iloc[j] == -1:
                            sell_p = df["Close"].iloc[j]
                            sell_sma = sma_200.iloc[j]
                            if pd.notna(sell_sma) and sell_p > sell_sma:
                                last_sell_price = sell_p
                                break

                    # BUY: OTT buy OR 5% dip from last sell
                    dip_buy = last_sell_price and price < last_sell_price * 0.95
                    if ott_signal == 1 or dip_buy:
                        reason = "OTT buy signal" if ott_signal == 1 else f"5% dip from sell (${last_sell_price:.2f})"
                        signals.append({
                            "type": "BUY",
                            "ticker": display_name,
                            "category": category,
                            "timeframe": tf,
                            "price": price,
                            "sma_200": sma200_val,
                            "sma_relation": sma200_relation,
                            "date": date_str,
                            "reason": reason,
                        })

                    # SELL: any OTT sell signal
                    if ott_signal == -1:
                        signals.append({
                            "type": "SELL",
                            "ticker": display_name,
                            "category": category,
                            "timeframe": tf,
                            "price": price,
                            "sma_200": sma200_val,
                            "sma_relation": sma200_relation,
                            "date": date_str,
                            "reason": "OTT sell signal",
                        })

                else:
                    # OTT + SMA strategy for stocks/crypto
                    # BUY: OTT buy signal OR price crosses above 50 SMA
                    if ott_signal == 1 or crossed_above_50:
                        reason = "OTT buy signal" if ott_signal == 1 else "Price crossed above 50 SMA"
                        signals.append({
                            "type": "BUY",
                            "ticker": display_name,
                            "category": category,
                            "timeframe": tf,
                            "price": price,
                            "sma_200": sma200_val,
                            "sma_relation": sma200_relation,
                            "date": date_str,
                            "reason": reason,
                        })

                    # SELL: OTT sell signal AND price above 200 SMA
                    if ott_signal == -1 and above_200:
                        signals.append({
                            "type": "SELL",
                            "ticker": display_name,
                            "category": category,
                            "timeframe": tf,
                            "price": price,
                            "sma_200": sma200_val,
                            "sma_relation": sma200_relation,
                            "date": date_str,
                            "reason": "OTT sell signal (above 200 SMA)",
                        })

                    # SMA DIP signals for stocks: price drops below 200d SMA by 5/10/15/20/25/30%
                    if category == "Stocks" and tf == "daily" and pd.notna(sma200_val) and len(df) >= 2:
                        prev_price = df["Close"].iloc[-2]
                        prev_sma = sma_200.iloc[-2]
                        for dip_pct in [5, 10, 15, 20, 25, 30]:
                            threshold = sma200_val * (1 - dip_pct / 100)
                            prev_threshold = prev_sma * (1 - dip_pct / 100) if pd.notna(prev_sma) else None
                            if price <= threshold and (prev_threshold is None or prev_price > prev_threshold):
                                signals.append({
                                    "type": "BUY",
                                    "ticker": display_name,
                                    "category": category,
                                    "timeframe": tf,
                                    "price": price,
                                    "sma_200": sma200_val,
                                    "sma_relation": sma200_relation,
                                    "date": date_str,
                                    "reason": f"Price {dip_pct}% below 200d SMA (${threshold:.2f})",
                                })

                # FIBONACCI retracement buy alerts (weekly-detected swing) for the
                # configured fib categories (e.g. Stocks + Indices). Fire when the
                # current daily close is at/below a fib level while the trend is intact
                # (price above the swing low). The swing is detected on WEEKLY bars with
                # per-category params (indices use a smaller min_gain/reversal). Position-
                # based (fires on initial state), deduped per level; re-arms once price
                # recovers above a level; resets on a new swing high.
                if fib_enabled and category in fib_categories and tf == "daily" and len(df) >= 2:
                    fp = fib_params(fib_cfg, category)
                    try:
                        df_wk = fetch_weekly_data(yf_ticker)
                    except Exception:
                        df_wk = pd.DataFrame()
                    fib = calculate_fib_levels(
                        df_wk["High"], df_wk["Low"],
                        lookback=fp["lookback"], min_gain=fp["min_gain"],
                        reversal=fp["reversal"], ratios=fp["levels"],
                    ) if not df_wk.empty else None
                    if fib is not None and fib["swing_low"] < price < fib["swing_high"]:
                        fstate = cycle_state.get(display_name, {})
                        fib_alerted = fstate.get("fib_alerted", [])
                        prev_swing_high = fstate.get("fib_swing_high")

                        # New swing high => fresh setup, clear prior fired levels
                        if prev_swing_high is None or fib["swing_high"] > prev_swing_high * 1.001:
                            fib_alerted = []

                        lo_date = _fmt_date(fib["swing_low_date"])
                        hi_date = _fmt_date(fib["swing_high_date"])
                        for r in fp["levels"]:
                            level = fib["levels"][r]
                            # Re-arm: drop levels price has climbed back above
                            if price > level and r in fib_alerted:
                                fib_alerted.remove(r)
                            # Fire whenever price sits at/below the level (deduped)
                            if price <= level and r not in fib_alerted:
                                signals.append({
                                    "type": "BUY",
                                    "ticker": display_name,
                                    "category": category,
                                    "timeframe": tf,
                                    "price": price,
                                    "sma_200": sma200_val,
                                    "sma_relation": f"fib {r}",
                                    "date": date_str,
                                    "reason": (
                                        f"Retraced to {r} fib (${level:.2f}) of +{fib['gain'] * 100:.0f}% uptrend "
                                        f"(low ${fib['swing_low']:.2f} {lo_date} → high ${fib['swing_high']:.2f} {hi_date})"
                                    ),
                                })
                                fib_alerted.append(r)

                        fstate["fib_alerted"] = fib_alerted
                        fstate["fib_swing_high"] = fib["swing_high"]
                        cycle_state[display_name] = fstate

                # Z-SCORE buy alerts: how unusual the current distance below the
                # 200d SMA is, in standard deviations. Fires at each 0.5σ step on
                # the downside only (oversold/dip-buy). Buy-only by design — the
                # backtest validated -σ buys but not +σ sells (which fight the trend).
                # Crypto is excluded (it has its own 200w-EMA dip alerts).
                if zscore_enabled and tf == "daily" and category != "Crypto":
                    pct_series = ((df["Close"] - sma_200) / sma_200 * 100).dropna()
                    if len(pct_series) > 1 and pct_series.std() > 0:
                        zscore = (pct_series.iloc[-1] - pct_series.mean()) / pct_series.std()
                        zstate = cycle_state.get(display_name, {})
                        neg_alerted = zstate.get("zscore_neg", [])

                        # Re-arm once price returns within the reset band of the mean
                        if zscore >= -zscore_reset_band:
                            neg_alerted = []

                        for lvl in zscore_levels:
                            if zscore <= -lvl and lvl not in neg_alerted:
                                signals.append({
                                    "type": "BUY",
                                    "ticker": display_name,
                                    "category": category,
                                    "timeframe": tf,
                                    "price": price,
                                    "sma_200": sma200_val,
                                    "sma_relation": f"{zscore:+.1f}σ",
                                    "date": date_str,
                                    "reason": f"Stretched -{lvl:.1f}σ below 200d SMA (now {zscore:+.1f}σ)",
                                })
                                neg_alerted.append(lvl)

                        zstate["zscore_neg"] = neg_alerted
                        cycle_state[display_name] = zstate

            except Exception as e:
                print(f"  Error processing {display_name} ({tf}): {e}")

    # Crypto 4-year cycle alerts
    crypto_tickers = config["watchlist"].get("Crypto", {})
    dip_levels = [-10, -20, -30]  # percent below 200 week EMA
    cycle_config = config.get("crypto_cycle", {})
    sell_date_str = cycle_config.get("sell_date", "2029-11-01")
    alert_months = cycle_config.get("alert_months_before", 1)
    sell_date = datetime.strptime(sell_date_str, "%Y-%m-%d")
    sell_alert_date = sell_date - timedelta(days=alert_months * 30)

    # Build default buy windows
    default_windows = cycle_config.get("buy_windows", [])
    ticker_overrides = cycle_config.get("ticker_overrides", {})
    now_date = datetime.now()

    def build_buy_ranges(windows):
        ranges = []
        for w in windows:
            center = datetime.strptime(w["center"], "%Y-%m-%d")
            half = timedelta(days=w["months"] * 30)
            ranges.append((center - half, center + half))
        return ranges

    for yf_ticker, display_name in crypto_tickers.items():
        try:
            # Use ticker-specific windows if configured, otherwise default
            override = ticker_overrides.get(yf_ticker, {})
            windows = override.get("buy_windows", default_windows)
            buy_ranges = build_buy_ranges(windows)
            in_buy_window = any(start <= now_date <= end for start, end in buy_ranges)

            t = yf.Ticker(yf_ticker)
            df_w = t.history(period="5y", interval="1wk")
            if df_w.empty or len(df_w) < 200:
                continue

            ema_200w = calculate_ema(df_w["Close"], period=200)
            price = df_w["Close"].iloc[-1]
            ema_val = ema_200w.iloc[-1]
            if pd.isna(ema_val):
                continue

            pct_from_ema = (price - ema_val) / ema_val * 100
            ticker_state = cycle_state.get(display_name, {})
            date_str = df_w.index[-1].strftime("%Y-%m-%d")

            # Signal 1: CYCLE TIMING - alert when entering a buy window
            if in_buy_window and not ticker_state.get("window_alerted", False):
                signals.append({
                    "type": "BUY",
                    "ticker": display_name,
                    "category": "Crypto",
                    "timeframe": "weekly",
                    "price": price,
                    "sma_200": ema_val,
                    "sma_relation": f"{pct_from_ema:+.1f}% from 200w EMA",
                    "date": date_str,
                    "reason": "Entering 4-year cycle buy window",
                })
                ticker_state["window_alerted"] = True

            if not in_buy_window:
                ticker_state["window_alerted"] = False

            # Signal 2: EMA DIP LEVELS - alert at -10%, -20%, -30% below 200w EMA
            # For tickers with dip_only_in_window, only fire within buy window
            dip_allowed = in_buy_window if override.get("dip_only_in_window", False) else True
            if pct_from_ema > 0:
                # Above EMA - reset dip alerts
                ticker_state["alerted_levels"] = []
            elif dip_allowed:
                alerted = ticker_state.get("alerted_levels", [])
                for level in dip_levels:
                    if pct_from_ema <= level and level not in alerted:
                        signals.append({
                            "type": "BUY",
                            "ticker": display_name,
                            "category": "Crypto",
                            "timeframe": "weekly",
                            "price": price,
                            "sma_200": ema_val,
                            "sma_relation": f"{pct_from_ema:+.1f}% from 200w EMA",
                            "date": date_str,
                            "reason": f"Price is {level}% below 200 week EMA (${ema_val:.0f})",
                        })
                        alerted.append(level)
                ticker_state["alerted_levels"] = alerted

            # SELL alert: approaching cycle peak date
            if now_date >= sell_alert_date and not ticker_state.get("sell_alerted", False):
                days_to_peak = (sell_date - now_date).days
                signals.append({
                    "type": "SELL",
                    "ticker": display_name,
                    "category": "Crypto",
                    "timeframe": "weekly",
                    "price": price,
                    "sma_200": ema_val,
                    "sma_relation": f"{pct_from_ema:+.1f}% from 200w EMA",
                    "date": date_str,
                    "reason": f"Approaching cycle peak ({sell_date_str}). {days_to_peak} days remaining.",
                })
                ticker_state["sell_alerted"] = True

            cycle_state[display_name] = ticker_state

        except Exception as e:
            print(f"  Error checking crypto cycle {display_name}: {e}")

    # Analyst buy levels (e.g. Jacob @ Invest Answers, loaded weekly)
    signals.extend(check_analyst_levels(config, cycle_state))
    signals.extend(check_ia_levels(config, cycle_state))

    save_cycle_state(cycle_state)

    return signals


def load_analyst_levels():
    """Load analyst-provided buy levels (e.g. Jacob @ Invest Answers).

    Keyed by display name, updated weekly via the /js:invest-answers-jacob command:
        {"NVDA": {"buy_levels": [120, 100], "source": "...", "date": "YYYY-MM-DD"}}
    """
    path = os.path.join(SCRIPT_DIR, "analyst_levels.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def check_analyst_levels(config: dict, cycle_state: dict) -> list:
    """Fire a BUY alert when the daily close reaches an analyst buy level.

    Each level fires once when price first closes at or below it, and re-arms
    once price closes back above the level (mirrors the SMA-dip dedupe logic).
    """
    analyst_levels = load_analyst_levels()
    if not analyst_levels:
        return []

    # Map display name -> (yf ticker, category)
    name_to_yf = {}
    for category, tickers in config["watchlist"].items():
        for yf_ticker, display_name in tickers.items():
            name_to_yf[display_name] = (yf_ticker, category)

    signals = []
    for display_name, info in analyst_levels.items():
        levels = info.get("buy_levels", [])
        if not levels:
            continue
        if display_name not in name_to_yf:
            print(f"  Analyst level for unknown ticker '{display_name}' - skipping")
            continue

        yf_ticker, category = name_to_yf[display_name]
        source = info.get("source", "Analyst")
        level_date = info.get("date", "")

        try:
            df = fetch_daily_data(yf_ticker)
            if df.empty or len(df) < 2:
                continue

            price = df["Close"].iloc[-1]
            date_str = df.index[-1].strftime("%Y-%m-%d %H:%M")

            state = cycle_state.get(display_name, {})
            alerted = state.get("analyst_alerted", [])
            still_below = []

            for lvl in levels:
                lvl = float(lvl)
                if price > lvl:
                    # Re-armed: price is back above this level
                    continue
                if lvl not in alerted:
                    when = f", set {level_date}" if level_date else ""
                    signals.append({
                        "type": "BUY",
                        "ticker": display_name,
                        "category": category,
                        "timeframe": "daily",
                        "price": price,
                        "sma_200": None,
                        "sma_relation": "analyst buy level",
                        "date": date_str,
                        "reason": f"Reached {source} buy level (${lvl:g}{when})",
                    })
                still_below.append(lvl)

            state["analyst_alerted"] = still_below
            cycle_state[display_name] = state

        except Exception as e:
            print(f"  Error checking analyst level {display_name}: {e}")

    return signals


def check_ia_levels(config: dict, cycle_state: dict) -> list:
    """Fire a BUY alert when the daily close reaches an IA level (the reverse-
    engineered Invest Answers accumulation bands: Level_k = trailing high x
    (1 - fib%)). Watches the configured levels (default L5/L4 = accumulation) for
    the tickers Jacob flags. Levels are recomputed live each run (they trail the
    high), and dedupe is keyed by level NUMBER so it survives that drift: each
    level fires once when price first closes at/below it, re-arming above it."""
    cfg = config.get("ia_level_alerts", {})
    if not cfg.get("enabled", False):
        return []
    watch = cfg.get("levels", [5, 4, 3])
    categories = cfg.get("categories", ["Stocks"])
    # Depth/conviction tag by level (backtest: deeper touches had bigger forward edge)
    depth = {5: "mild dip", 4: "moderate dip", 3: "deep dip — higher conviction",
             2: "very deep", 1: "extreme"}

    watch_tickers = []
    for category in categories:
        for yf_ticker, display_name in config["watchlist"].get(category, {}).items():
            watch_tickers.append((display_name, yf_ticker, category))

    signals = []
    for display_name, yf_ticker, category in watch_tickers:
        try:
            df = fetch_daily_data(yf_ticker)
            if df.empty or len(df) < 2:
                continue
            levels = atr_levels(df["High"])
            if not levels:
                continue
            price = df["Close"].iloc[-1]
            high = levels[6]
            date_str = df.index[-1].strftime("%Y-%m-%d %H:%M")

            state = cycle_state.get(display_name, {})
            alerted = state.get("ia_alerted", [])
            still_below = []
            for lvl in watch:
                level_price = levels.get(lvl)
                if level_price is None or price > level_price:
                    continue  # not reached / re-armed above the level
                if lvl not in alerted:
                    pct_off = (high - level_price) / high * 100 if high else 0
                    signals.append({
                        "type": "BUY",
                        "ticker": display_name,
                        "category": category,
                        "timeframe": "daily",
                        "price": price,
                        "sma_200": None,
                        "sma_relation": f"IA Level {lvl}",
                        "date": date_str,
                        "reason": (f"Reached IA Level {lvl} — {depth.get(lvl, '')} "
                                   f"(${level_price:.2f}, -{pct_off:.0f}% from high)"),
                    })
                still_below.append(lvl)

            state["ia_alerted"] = still_below
            cycle_state[display_name] = state
        except Exception as e:
            print(f"  Error checking IA level {display_name}: {e}")

    return signals


def load_cycle_state():
    """Load crypto cycle alert state (which levels have been alerted)."""
    state_path = os.path.join(SCRIPT_DIR, "cycle_state.json")
    if os.path.exists(state_path):
        with open(state_path) as f:
            return json.load(f)
    return {}


def save_cycle_state(state):
    """Save crypto cycle alert state."""
    state_path = os.path.join(SCRIPT_DIR, "cycle_state.json")
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def format_signal(sig: dict) -> str:
    """Format a signal as a Telegram message."""
    emoji = "\U0001f7e2" if sig["type"] == "BUY" else "\U0001f534"
    tf_map = {"daily": "Daily", "4h": "4H", "weekly": "Weekly"}
    tf_label = tf_map.get(sig["timeframe"], sig["timeframe"])
    lines = [
        f"{emoji} <b>{sig['type']} Signal: {sig['ticker']}</b> ({tf_label})",
        sig["reason"],
    ]
    if sig.get("sma_200") is not None:
        lines.append(
            f"Price: ${sig['price']:.2f} | 200 SMA: ${sig['sma_200']:.2f} ({sig['sma_relation']})"
        )
    else:
        lines.append(f"Price: ${sig['price']:.2f}")
    lines.append(f"{sig['category']} | {sig['date']}")
    return "\n".join(lines)


def format_dca_digest(rows) -> str:
    """DCA digest: the 'favoured now' picks per asset class, with a sector
    concentration note. `rows` is the ranked output of dca_rank.analyse()."""
    lines = ["\U0001f4ca <b>Daily DCA Picks — Favoured Now</b>",
             datetime.now().strftime("%Y-%m-%d"),
             ""]

    cats = []
    for r in rows:
        if r["category"] not in cats:
            cats.append(r["category"])

    any_fav = False
    for cat in cats:
        cat_fav = [r for r in rows if r["tier"] == "favoured" and r["category"] == cat]
        if not cat_fav:
            continue
        any_fav = True
        lines.append(f"<b>{cat}</b>")
        for r in cat_fav:
            sector = f" [{r['sector']}]" if r.get("sector") else ""
            w200 = f" · +{r['above_200w_pct']}% vs 200w" if r.get("above_200w_pct") is not None else ""
            lines.append(
                f"\U0001f7e2 {r['name']}{sector} — {r['level']} fib · "
                f"{r['retrace_pct']}% retrace · {r['z']:+.1f}σ{w200}"
            )
        lines.append("")

    if not any_fav:
        cs = [r["name"] for r in rows if r["tier"] == "cheap_shallow"]
        lines.append("No <b>favoured</b> setups today.")
        if cs:
            lines.append("Closest (cheap but shallow): " + ", ".join(cs))
    else:
        # Concentration warning across the most-actionable names
        actionable = [r for r in rows if r["tier"] in ("favoured", "cheap_shallow") and r.get("sector")]
        counts = {}
        for r in actionable:
            counts[r["sector"]] = counts.get(r["sector"], 0) + 1
        if counts:
            top, n = max(counts.items(), key=lambda kv: kv[1])
            if n >= 2 and n >= len(actionable) / 2:
                lines.append(
                    f"⚠️ {n} of the {len(actionable)} most-actionable names are "
                    f"{top} — pair with a non-{top} name to diversify"
                )

    return "\n".join(lines).strip()


def send_dca_digest(bot_token, chat_id):
    """Compute the DCA ranking and send the 'favoured now' digest."""
    from dca_rank import analyse  # lazy import (pulls dashboard/yfinance)
    rows = analyse()
    msg = format_dca_digest(rows)
    print("Sending DCA digest...")
    send_telegram(bot_token, chat_id, msg)


def main():
    config = load_config()

    # Load .env file if present (for local runs)
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key, val)

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or config["telegram"]["bot_token"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or config["telegram"]["chat_id"]

    print(f"OTT Signal Checker - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Checking {sum(len(t) for t in config['watchlist'].values())} tickers...")
    print()

    signals = check_signals(config)

    if signals:
        print(f"Found {len(signals)} signal(s):\n")
        for sig in signals:
            msg = format_signal(sig)
            print(f"  {sig['type']} {sig['ticker']} ({sig['timeframe']})")
            send_telegram(bot_token, chat_id, msg)
        print(f"\nSent {len(signals)} alert(s) to Telegram.")
    else:
        print("No signals today.")
        # Send a summary so you know it ran
        summary = (
            f"\U0001f50d <b>OTT Scan Complete</b>\n"
            f"No buy/sell signals detected\n"
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        send_telegram(bot_token, chat_id, summary)
        print("Summary sent to Telegram.")

    # DCA digest (favoured-now picks) — runs in the same run as the daily alerts.
    # If "daily" is true it fires every run; otherwise only on the configured
    # weekday (default Monday).
    dca_cfg = config.get("dca_summary", {})
    dca_due = dca_cfg.get("daily", False) or datetime.now().weekday() == dca_cfg.get("weekday", 0)
    if dca_cfg.get("enabled", True) and dca_due:
        try:
            send_dca_digest(bot_token, chat_id)
        except Exception as e:
            print(f"DCA digest error: {e}")


if __name__ == "__main__":
    main()
