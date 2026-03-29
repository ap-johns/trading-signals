# OTT Signal Dashboard

**[View Dashboard](https://ap-johns.github.io/trading-signals/)**

Automated stock/crypto signal alerts using the [Optimized Trend Tracker (OTT)](https://www.tradingview.com/script/zVhoDQME/) indicator by KivancOzbilgic.

## What it does

- Monitors 18 tickers (crypto, indices, stocks) for OTT buy/sell crossover signals
- Sends Telegram alerts when new signals fire
- Generates an HTML dashboard viewable on any device

## OTT Settings

| Parameter | Value |
|-----------|-------|
| Source | Open |
| Period | 10 |
| Percent | 3 |
| MA Type | VAR |

These match the TradingView indicator settings and have been verified against it.

## Watchlist

**Crypto:** BTC, SOL
**Indices:** SPX, QQQ, MAGS
**Stocks:** ALAB, TSM, AMD, AVGO, TSLA, PLTR, GOOG, NVDA, ASML, MU, MRVL, MSFT, META

## Dashboard

The dashboard is hosted via GitHub Pages and updated daily at 5pm UK time.

Features:
- Weekly / Daily / 4H timeframe toggle
- Recent signal filtering
- Expandable signal history per ticker
- Optional detail columns (Price, 200 EMA, MAvg, OTT Line)

## Running locally

```bash
pip install -r requirements.txt

# Generate dashboard
cd alerts && python3 dashboard.py

# Send Telegram alerts
cd alerts && python3 signal_checker.py
```

For local Telegram alerts, add your credentials to `alerts/config.json` or set environment variables:
```bash
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id
```

## GitHub Action

The workflow runs Mon-Fri at 5pm UK time:
1. Checks for new OTT signals and sends Telegram alerts
2. Regenerates the dashboard HTML
3. Commits and pushes the updated `docs/index.html`

To trigger manually: Actions tab → "Update OTT Dashboard" → Run workflow

## Secrets

Add these in repo Settings → Secrets → Actions:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
