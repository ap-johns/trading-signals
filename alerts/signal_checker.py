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

from indicators import calculate_ott, calculate_ema

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
                ema_200 = calculate_ema(df["Close"], period=ema_period)

                # Check the latest completed candle
                latest_signal = ott_df["signal"].iloc[-1]
                if latest_signal != 0:
                    price = df["Close"].iloc[-1]
                    ema_val = ema_200.iloc[-1]
                    ema_relation = "above" if price > ema_val else "below"
                    signal_type = "BUY" if latest_signal == 1 else "SELL"
                    date_str = df.index[-1].strftime("%Y-%m-%d %H:%M")

                    signals.append({
                        "type": signal_type,
                        "ticker": display_name,
                        "category": category,
                        "timeframe": tf,
                        "price": price,
                        "ema_200": ema_val,
                        "ema_relation": ema_relation,
                        "date": date_str,
                    })

            except Exception as e:
                print(f"  Error processing {display_name} ({tf}): {e}")

    return signals


def format_signal(sig: dict) -> str:
    """Format a signal as a Telegram message."""
    emoji = "\U0001f7e2" if sig["type"] == "BUY" else "\U0001f534"
    tf_label = "Daily" if sig["timeframe"] == "daily" else "4H"
    return (
        f"{emoji} <b>{sig['type']} Signal: {sig['ticker']}</b> ({tf_label})\n"
        f"OTT crossover detected\n"
        f"Price: ${sig['price']:.2f} | 200 EMA: ${sig['ema_200']:.2f} ({sig['ema_relation']})\n"
        f"{sig['category']} | {sig['date']}"
    )


def main():
    config = load_config()
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
