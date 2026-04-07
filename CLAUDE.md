# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated trading alert system using the OTT (Optimized Trend Tracker) indicator. Monitors 19 tickers across crypto, indices, and stocks. Sends Telegram alerts on signal changes and generates an HTML dashboard on GitHub Pages. Runs daily via GitHub Actions at 5pm UK time (Mon-Fri).

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Run signal checker (sends Telegram alerts)
python alerts/signal_checker.py

# Regenerate dashboard
python alerts/dashboard.py

# Run backtest (on-demand, not automated)
python alerts/backtest.py
```

Requires `.env` in `alerts/` with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (or set as environment variables). No test suite exists; backtest.py serves as manual validation.

## Architecture

Four Python modules in `alerts/`, no external web framework:

- **indicators.py** — OTT indicator calculation (VAR + trailing stop), plus EMA/SMA helpers. All functions operate on pandas Series/DataFrames. The VAR calculation replicates TradingView's Pine Script implementation exactly.
- **signal_checker.py** — Main entry point for alerts. Fetches data via yfinance, runs OTT across timeframes, detects signals, sends Telegram messages. Maintains `cycle_state.json` to prevent duplicate crypto alerts.
- **dashboard.py** — Generates self-contained `docs/index.html` with inline CSS/JS. Shows OTT state, recent signals, and crypto cycle info for all tickers grouped by asset class.
- **backtest.py** — Historical strategy simulation. Supports multiple strategy variants (trend, contra, hybrid, always_in, etc.) and compares against buy-and-hold.

## Three Strategy Types

Each asset class in `config.json` has distinct entry/exit logic — not a single unified strategy:

- **Stocks (OTT + SMA):** Buy on OTT signal or 50 SMA cross; sell on OTT signal above 200 SMA
- **Indices (Always-In):** Always invested; sell on OTT, buy back on OTT or 5% dip
- **Crypto (4-Year Cycle):** Buy during cycle windows or at dip levels below 200w EMA; sell ~1 month before projected cycle peak

## Key Files

- `alerts/config.json` — All parameters: OTT period/percent, EMA period, timeframes, watchlist, crypto cycle windows with per-ticker overrides
- `alerts/cycle_state.json` — Persistent state tracking which crypto dip levels and buy windows have already been alerted (committed by CI)
- `docs/index.html` — Generated dashboard output (committed by CI, served by GitHub Pages)
- `.github/workflows/update.yml` — CI/CD: runs signal_checker then dashboard, commits results back to repo

## Data Flow

```
config.json → yfinance fetch → OTT/SMA calculation → signal detection
                                                       ├→ Telegram alert
                                                       ├→ cycle_state.json update
                                                       └→ docs/index.html regeneration
```
