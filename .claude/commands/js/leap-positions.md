---
description: Status of held LEAPs from IBKR against the exit rules (roll, delta, gain, OTT sell, caution)
---

Report on the LEAP call options currently held, as the daily digest would, and say
plainly whether any exit rule applies. Positions come from IBKR's Flex Web Service
(`IBKR_FLEX_TOKEN` / `IBKR_FLEX_QUERY_ID` in `alerts/.env`), merged with the
git-ignored `alerts/leap_positions.json`. The Flex statement runs to the previous
business day, so a contract bought today shows from the local file until tomorrow.

Steps:

1. Pull live status:

   ```
   cd alerts && python3 leap_positions.py
   ```

   For each contract it prints months left, the option mid vs the entry price with
   P&L, delta, the stock's move since entry, DCA tier, and any ⚠️ exit-rule lines.
   If it prints `no positions`, check the Flex pull directly with
   `python3 ibkr_flex.py` and that `.env` holds both IBKR_FLEX values. Do not print
   the token.

2. Present a short table per position: contract, entry, mid, P&L, months left,
   delta, stock move, tier. Then the verdict, one line per contract.

3. The exit rules, in the order to apply them (agreed 2026-09-26):
   - **Roll** at ≤ 6 months to expiry, whatever the stock is doing. Roll "up and
     out" if the stock has risen (later expiry, higher strike, cash off the table).
   - **Take profit / roll up** when delta ≥ 0.90 or the stock is ≥ 40% above entry:
     the leverage is spent, so roll back to ~0.78 delta or convert to shares.
   - **Exit** on a daily OTT sell above the 200d SMA occurring after the entry date.
   - **Exit** if the DCA tier is caution/broken with under 9 months left.
   - Otherwise hold. "Hold" is the normal answer; say it without hedging.
   Don't invent extra triggers. If a rule has fired, also remind: sell with a limit
   at the mid; roll as a single spread order; a deep-ITM call can always be exercised
   to capture intrinsic value if the bid is absurd.

4. Record-keeping: these sit in the taxable IBKR account. On any sale or roll,
   remind the user the IBKR Activity Statement (6 Apr–5 Apr, base currency GBP) has
   the CGT figures.

Keep it short — this is a daily-check command, not an essay.
