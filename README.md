# OTT Signal Dashboard

**[View Dashboard](https://ap-johns.github.io/trading-signals/)** | **[View Backtest](https://ap-johns.github.io/trading-signals/backtest.html)**

Automated trading signal alerts using the [Optimized Trend Tracker (OTT)](https://www.tradingview.com/script/zVhoDQME/) indicator by KivancOzbilgic, with different strategies per asset class.

## Strategies

### Stocks (OTT + SMA)
- **Buy:** OTT buy signal OR price crosses above 50 SMA
- **Sell:** OTT sell signal AND price above 200 SMA (only sell into strength)

### Indices (Always-In)
- **Buy:** OTT buy signal OR 5% dip from last sell price
- **Sell:** Any OTT sell signal
- Best for indices like SPX where buy & hold is strong but you want to avoid drawdowns

### Crypto (4-Year Cycle)
- **Buy:** Cycle timing window (±3 months of expected cycle low) OR -10/-20/-30% below 200 week EMA
- **Sell:** Alert 1 month before configured cycle peak (default Nov 2029)
- ETH/SOL use shifted buy windows (3 months after BTC's expected low)
- BTC dip alerts fire anytime; ETH/SOL dip alerts only fire within their buy window

## OTT Settings

| Parameter | Value |
|-----------|-------|
| Source | Open |
| Period | 10 |
| Percent | 3 |
| MA Type | VAR |

These match the TradingView indicator settings and have been verified against it.

## Watchlist (19 tickers)

**Crypto:** BTC, ETH, SOL
**Indices:** SPX, QQQ, MAGS
**Stocks:** ALAB, TSM, AMD, AVGO, TSLA, PLTR, GOOG, NVDA, ASML, MU, MRVL, MSFT, META

## Dashboard

Hosted via GitHub Pages, updated daily at 5pm UK time.

- Signals shown per strategy per asset class
- Recent signal highlighting (last 7 days)
- Expandable signal history per ticker
- Optional detail columns (Price, 200 SMA, MAvg, OTT Line)
- Weekly / Daily / 4H timeframe toggle

## Backtest

Separate backtest page comparing strategies against buy & hold:
- **OTT Only** vs **OTT + SMA** vs **Always-In** for stocks/indices
- **Crypto 4-Year Cycle** with historical trade details
- 1yr / 2yr / 5yr period toggle
- Max drawdown comparison

## Running locally

```bash
pip install -r requirements.txt

# Generate dashboard
cd alerts && python3 dashboard.py

# Send Telegram alerts
cd alerts && python3 signal_checker.py

# Generate backtest (separate, run manually)
cd alerts && python3 backtest.py
```

For local Telegram alerts, create `alerts/.env`:
```
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

## GitHub Action

Runs Mon-Fri at 5pm UK time:
1. Checks for new signals and sends Telegram alerts
2. Regenerates the dashboard HTML
3. Commits and pushes the updated `docs/index.html`

To trigger manually: Actions tab → "Update OTT Dashboard" → Run workflow

## Secrets

Add these in repo Settings → Secrets → Actions:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
