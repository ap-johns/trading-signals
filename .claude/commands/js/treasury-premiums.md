---
description: Crypto treasury stocks (MSTR, FWDI, BMNR, PURR) — current mNAV against the cheap / derisk / sell bands
---

Report the premium each tracked crypto treasury company trades at versus the coin it
holds, and whether any band has been reached. Companies and bands live in
`config.treasury_companies`; the maths is in `alerts/treasury.py`.

Steps:

1. Compute live figures:

   ```
   cd alerts && python3 -c "
   import json, treasury
   cfg=json.load(open('config.json'))['treasury_companies']
   for tk,e in cfg.items():
       if not isinstance(e, dict) or tk.startswith('_'): continue
       m=treasury.compute_mnav(tk,e)
       print(tk, f\"price {m['price']:.2f} | {m['holdings']:,.0f} {m['asset_label']} NAV {m['nav_per_share']:.2f}/sh | basic {m['mnav_basic']:.2f}x EV {m['mnav_ev']:.2f}x -> {treasury.status(m)} | holdings as of {m['updated']}{' STALE' if m['stale'] else ''} | derisk into {m['alt']}\")"
   ```

2. Present a table: ticker, coin, holdings (and the `updated` date), NAV per share,
   mNAV basic, mNAV EV, status, derisk target. **EV is the honest multiple** (adds
   convertibles / preferreds, subtracts cash) and the one the bands use.

3. Interpret, briefly:
   - **Cheap** (EV ≤ 1.0): shares worth less than the coin — accumulation zone.
     Today's normal state for FWDI and BMNR.
   - **Fair**: no action.
   - **Derisk** (≥ 2.0): move some into the coin or the ETP named (IB1T for BTC,
     spot SOL ETP or native SOL, spot ETH ETP, native HYPE via Tangem) — keep the
     exposure, drop the premium risk.
   - **Sell** (≥ 2.5): mania levels; MSTR peaked ~4x last cycle.
   Note the asymmetry: in the last bear these stocks fell 85–95% while coins fell
   60–75%, so they're the leveraged slice, never the core.

4. Housekeeping: holdings and MSTR's preferred-stock notional are entered by hand
   from filings (Strategy files most Mondays; others quarterly). If any row is
   flagged **stale** (> 45 days), say so and offer to update `config.json` if the
   user has a new figure. Yahoo's share count can lag an issuance by weeks, which
   understates mNAV for an active issuer — treat anything within ~0.1x of a band as
   approximate.

Keep it to a table and a few lines. Not financial advice.
