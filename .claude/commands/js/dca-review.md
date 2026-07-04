---
description: Rank stocks by buy-and-hold DCA favorability and explain the picks
---

Produce a buy-and-hold DCA (dollar-cost-averaging) review of the watchlist stocks,
ranked by how favorable a buy level each is right now.

Steps:

1. Run the scoring CLI to get current, live data:

   ```
   python3 alerts/dca_rank.py
   ```

   It prints a ranked plain-text table and a JSON blob. Use the JSON for exact
   values. Each row has: score, sector, retrace %, fib level reached, z-score (vs
   200-day SMA; negative = cheap), 50-day SMA distance + slope, % above the 200-day
   SMA (below = medium-term regime broken), nearest support distance, % above the
   200-week EMA, weekly OTT (bull/bear), gain of the uptrend, swing low/high, and a
   tier (favoured / cheap_shallow / quality_not_cheap / caution / broken).

   The CLI groups output by asset class (e.g. Stocks, then Indices) — each has its
   own `=== Category ===` header and is ranked within itself. The JSON rows carry a
   `category` field.

2. Present the analysis grouped by asset class — a concise ranked table per category
   (Stocks and Indices separately, most favorable first). Indices are less volatile,
   so their retracements are shallower; when an index still climbs toward "favoured"
   it signals a genuine broad-market dip worth adding to the core.

3. Then write the analysis, grouped into tiers, in this spirit:
   - **Favoured now** — long-term trend intact (weekly OTT up + above 200-week) AND
     genuinely cheap (negative z) AND a meaningful pullback (0.5–0.618 golden pocket).
     These are the DCA candidates. Name the top 1–2.
   - **Cheap but shallow** — stretched below trend (negative z) but only a small fib
     pullback; second-tier.
   - **Quality, not on sale** — strong trend but positive/flat z and shallow retrace;
     good to own, not at a discount today (call this out explicitly for names the
     user likes, e.g. ARM if it appears here).
   - **Caution** — deep retracement but weekly trend rolling over or barely above the
     200-week; value-trap risk under a no-stop buy-and-hold plan.
   - **Skip** — broken (price below the swing low).

4. Framing rules:
   - The scoring is trend-gate-heavy on purpose: for no-stop buy-and-hold, "is the
     long-term trend intact" matters more than raw discount. Say so.
   - Prefer scaling in over single entries; a deeper drop in a favoured name is an
     opportunity to add, not a stop-out.
   - **Check sector concentration**: if the top favoured / cheap names cluster in one
     sector (e.g. Semis), call it out — they move together, so DCAing into two of them
     is concentration, not diversification. Suggest pairing one with a non-cluster name.
   - End with a brief caveat: this is a heuristic ranking (my weights) and a snapshot
     that shifts with price — not financial advice; the allocation call is theirs.

Keep it tight and decision-useful, matching the depth of a good analyst note.
