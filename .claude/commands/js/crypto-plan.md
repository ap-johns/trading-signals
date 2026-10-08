---
description: Check the Q4 2026 crypto deployment plan (tranches, pull-forward and give-up rules) against current prices
---

Check where BTC, ETH and SOL sit against the deployment plan agreed on 2026-10-03,
and say what, if anything, the rules call for today.

The plan (for the ~25% of allocation earmarked for crypto):
- **Half deployed in October 2026**, a quarter in November, a quarter across
  December 2026 – January 2027. That spans the config buy windows: BTC centred
  2026-12-01, ETH and SOL centred 2027-03-01, ±3 months.
- **Pull-forward rule**: any coin down 15%+ from its early-October level buys the
  next tranche immediately. Reference levels (2026-10-03): BTC ~$84,600, ETH ~$2,680,
  SOL ~$119.
- **Give-up rule**: if BTC takes out its October 2025 high (~$124,750) before the
  tranches are done, deploy the remainder — the bear is unambiguously over.
- Allocation shape: BTC 75%+ (core IB1T in the ISA; leveraged slice MSTR), SOL
  (core native on the hardware wallet; FWDI for a leveraged slice), HYPE (core native
  via Tangem; PURR in the ISA as the leveraged slice, to be sold first if its premium
  exceeds ~2.5x).

Steps:

1. Pull current state:

   ```
   cd alerts && python3 -c "
   import yfinance as yf
   from indicators import calculate_ott, calculate_ema
   ref={'BTC-USD':84600,'ETH-USD':2680,'SOL-USD':119}
   for s,r in ref.items():
       d=yf.Ticker(s).history(period='2y'); w=yf.Ticker(s).history(period='max',interval='1wk')
       p=float(d.Close.iloc[-1]); e=float(calculate_ema(w.Close,200).iloc[-1])
       od=calculate_ott(d.Open,10,3.0); ow=calculate_ott(w.Open,10,3.0)
       print(s, f'{p:,.0f}', f'vs ref {p/r-1:+.0%}', f'vs 200w EMA {p/e-1:+.0%}', 'dailyOTT', 'bull' if od.mavg.iloc[-1]>od.ott.iloc[-1] else 'bear', 'weeklyOTT', 'bull' if ow.mavg.iloc[-1]>ow.ott.iloc[-1] else 'bear', f'ATH {float(d.Close.max()):,.0f}')"
   ```

2. Apply the rules in order: give-up rule (BTC above ~$124,750?) → pull-forward
   (any coin ≤ −15% vs reference?) → otherwise the calendar tranche due this month.
   State the month we're in and which tranche that is.

3. Report in a few lines: a three-row table (price, vs reference, vs 200w EMA, daily
   and weekly OTT), then the instruction: "deploy next tranche now", "calendar tranche
   due", or "nothing to do". Also run `/js:treasury-premiums` logic for PURR/MSTR/FWDI
   if the user asks about the leveraged slices.

Not financial advice; the plan is the user's and they may override it.
