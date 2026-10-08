---
description: Add a ticker to the watchlist (verifies the Yahoo symbol, sets sector, rebuilds and pushes)
---

Add the ticker(s) given in `$ARGUMENTS` to the watchlist, correctly keyed for Yahoo
Finance, then rebuild and publish the dashboard.

Steps:

1. Verify what the symbol resolves to before touching config — bare symbols can be
   the wrong instrument (e.g. `COPA` on Yahoo is a US miners ETF; the London copper
   ETC is `COPA.L`):

   ```
   python3 -c "
   import yfinance as yf; t=yf.Ticker('SYMBOL'); i=t.info; h=t.history(period='max')
   print(i.get('longName'), '|', i.get('quoteType'), i.get('exchange'), i.get('currency'), '| sector', i.get('sector'), '| mcap', i.get('marketCap'))
   print('bars', len(h), 'from', h.index[0].date() if len(h) else '-', '| options expiries', len(t.options))"
   ```

   If the name doesn't match what the user means, say so and ask which listing they
   want. Prefer the listing with the **longest history** for signals (the repo added
   `000660.KS` alongside SKHY for that reason); if the user will buy a different line
   (e.g. a GBP line in the ISA), add a `buy_as` note so the dashboard and digest
   remind them (`config.buy_as`, e.g. `"COPX": "COPG (GBP line, LSE)"`).

2. Edit `alerts/config.json`:
   - `watchlist.<Category>`: `"YF_SYMBOL": "DISPLAY_NAME"` — Stocks unless told
     otherwise; crypto proxies (treasury companies) still go in Stocks.
   - `sectors`: `"DISPLAY_NAME": "Sector"` — reuse an existing sector label where one
     fits (Semis, Internet, Software, Auto/EV, Copper, Space, Drones, Crypto treasury).
   - If it's a crypto treasury company, also add a `treasury_companies` entry
     (asset, holdings, updated date, bands, alt) — ask for the holdings figure if
     the user hasn't given one.
   Keep the JSON valid (`python3 -c "import json;json.load(open('alerts/config.json'))"`).

3. Rebuild and publish with the same steps as `/js:regen-dashboard` (pull, build,
   check for `Error:` rows, commit config + generated files, push, rebase-and-merge
   if CI pushed meanwhile). Commit message: `Add <TICKER> (<what it is>) to the
   stocks watchlist`.

4. Report: what the symbol resolved to, which category/sector it went in, how much
   history it has (under ~200 bars means no 200d SMA yet; under ~104 weeks no 200w
   EMA; under ~2 years no 2x ETP verdict), whether it has an options chain (so it
   appears on the LEAP panel), and where it landed in the DCA tiers today.

To remove a ticker: delete it from `watchlist` and `sectors` (and `buy_as` /
`treasury_companies` if present), drop its `cycle_state.json` entry, rebuild, push.
