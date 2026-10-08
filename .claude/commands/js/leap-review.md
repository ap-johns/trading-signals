---
description: Review today's LEAP candidates (Strong setup / Setup) and pick the contract to buy, with the 2x ETP alternative
---

Review the watchlist for LEAP entries the way the dashboard's LEAP Candidates panel
does, and if anything qualifies, walk through the exact contract to buy.

Steps:

1. Rank the watchlist and find the candidates:

   ```
   python3 alerts/dca_rank.py
   ```

   Candidates are rows with tier `favoured` (→ **Strong setup**) or `cheap_shallow`
   (→ **Setup**). `quality_not_cheap`, `caution`, `broken` are not LEAP entries.
   If none, say so and stop — the right answer most days is "nothing today".

2. For each candidate pull the chain:

   ```
   cd alerts && python3 -c "
   import yfinance as yf, leaps, json
   t='TICKER'; h=yf.Ticker(t).history(period='1y')['Close'].dropna()
   print(json.dumps(leaps.fetch_leap_snapshot(t, float(h.iloc[-1]), close_series=h), indent=1))"
   ```

   Then apply the flag rule (`leaps.leap_flag`): premium not rich (IV/RV ≤ 1.3) and
   open interest ≥ 250. Strong setup = favoured + both; Setup = cheap_shallow + both.

3. Choosing the strike — the panel targets delta 0.78, but adjust:
   - If IV is high (≳ 80%), go one strike deeper so time value is ≤ ~25% of the
     premium; check breakeven and open interest on neighbouring strikes.
   - Prefer the January LEAP cycle (most liquid). Skip strikes with OI < 250 or a
     spread > 8%.
   - Report: strike, expiry, mid, delta, intrinsic vs time value, breakeven, OI,
     spread, and the outlay per contract in USD and GBP (mid × 100).

4. Say whether the 2x ETP is the better vehicle. The panel's verdict
   (`leaps.etp_stats` / `leaps.etp_verdict` on max daily history, with
   `leaps.ETP_TICKERS` for the London line) applies: for names marked **suitable**
   with a London 2x line (e.g. MSFT, GOOG, AMZN, SPX) the ISA ETP usually beats the
   LEAP — tax-free, no expiry, fractional sizing. The LEAP is for names with no 2x
   product, names marked avoid for 2x (volatility), or a defined-risk one-off bet.

5. Framing: the Favoured tier is the trigger; Setup is DCA-grade, not LEAP-grade.
   Size for a total loss you'd shrug at — one contract for a first trade. Buy with a
   limit at the mid, never market. Restate the exit plan in one line (roll at 6
   months; profit at Δ0.90 or +40%; exit on OTT sell above 200d or caution <9 months).

Not financial advice; the sizing and the decision are the user's.
