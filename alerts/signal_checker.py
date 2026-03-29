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

from indicators import calculate_ott, calculate_sma, calculate_ema

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f)


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
    signals = []

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

            except Exception as e:
                print(f"  Error processing {display_name} ({tf}): {e}")

    # Crypto 4-year cycle alerts
    cycle_state = load_cycle_state()
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

    save_cycle_state(cycle_state)

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
    return (
        f"{emoji} <b>{sig['type']} Signal: {sig['ticker']}</b> ({tf_label})\n"
        f"{sig['reason']}\n"
        f"Price: ${sig['price']:.2f} | 200 SMA: ${sig['sma_200']:.2f} ({sig['sma_relation']})\n"
        f"{sig['category']} | {sig['date']}"
    )


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


if __name__ == "__main__":
    main()
