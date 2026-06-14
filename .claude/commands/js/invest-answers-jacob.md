---
description: Load Jacob's (Invest Answers) weekly buy-level summary into the trading signals
argument-hint: <paste Jacob's weekly summary>
---

You are updating analyst buy levels for the OTT trading-signals project. The user has pasted this week's summary from **Jacob @ Invest Answers** below.

## Pasted summary

$ARGUMENTS

## Task

1. **Parse** the summary above. For each ticker mentioned, extract the buy / accumulation level(s) Jacob gives. A ticker may have one level or several. Strip `$` and thousands separators — store plain numbers.
   - **Hard prices**: store directly. Only count prices framed as a *buy / accumulation / support* zone — ignore upside targets and break-*above* / breakout pivots (those are resistance, not buy-the-dip levels).
   - **Named moving averages** (e.g. "add into the 200-day MA", "support at the 50-day MA"): compute today's value with the project's `calculate_sma` on daily Close (200d MA → period 200, 50d MA → period 50) and store that number as the buy level. Mention in `notes` that it's the MA value as of the summary date (it drifts). A short script: `python3 -c "import yfinance as yf; from indicators import calculate_sma; df=yf.Ticker('NVDA').history(period='400d',interval='1d'); print(calculate_sma(df['Close'],period=200).iloc[-1])"` (run from `alerts/`).
   - **Proprietary / vague markers** ("Level 5", "key support", "decent value"): you can't resolve these to a number — do **not** guess. List them in your report so the user can supply a price if they want one.

2. **Determine the date.** Use the date stated in the summary. If none is stated, use today's date (in your context). Format `YYYY-MM-DD`.

3. **Map names to the watchlist.** Read `alerts/config.json` and match to the *display names* under `watchlist` (e.g. NVDA, BTC, ETH, SOL, SPX, QQQ, GOOG, AVGO…). Jacob may use a different name or symbol — map sensibly (e.g. "Bitcoin"→BTC, "S&P"/"S&P 500"→SPX, "Google"/"Alphabet"→GOOG, "Broadcom"→AVGO). If a ticker Jacob mentions is **not** in the watchlist, do **not** invent an entry — collect it and report it at the end.

4. **Merge** into `alerts/analyst_levels.json` (create if missing). It is a JSON object keyed by display name:
   ```json
   {
     "NVDA": {
       "buy_levels": [120, 100],
       "source": "Jacob @ Invest Answers",
       "date": "2026-06-14",
       "notes": "optional short context"
     }
   }
   ```
   - **Replace** the entry for each ticker Jacob mentions this week (new levels supersede old).
   - **Preserve** existing entries for tickers Jacob does *not* mention this week.
   - `source` is always `"Jacob @ Invest Answers"`. `notes` is optional.

5. **Regenerate the dashboard** so the levels show up: `python alerts/dashboard.py` (fetches live data, may take a minute).

6. **Report** concisely: tickers/levels added or updated, the date used, and any tickers Jacob mentioned that aren't in the watchlist.

Do **not** run the signal checker or send Telegram alerts — that happens automatically on the next scheduled CI run. Note for the user: commit `alerts/analyst_levels.json` (and the regenerated `docs/index.html`) so CI picks up the new levels.
