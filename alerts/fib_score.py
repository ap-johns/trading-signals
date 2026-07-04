"""
Buy-and-hold DCA "favorability" scoring for the fib retracement setups.

Shared by dashboard.py (the fib table + summary) and dca_rank.py (the CLI behind
the /dca-review slash command) so the ranking never drifts between them.

The score rewards, in order of importance for a no-stop buy-and-hold accumulator:
  1. Long-term trend intact  — weekly OTT bullish (+3), price above 200-week EMA (+1)
                               and a falling 50-day is penalised (-1.5)
  2. Cheapness               — negative z-score vs the 200-day SMA (more negative = cheaper)
  3. Pullback depth          — the 0.5-0.618 golden pocket scores highest; 0.382 is a
                               shallow dip, 0.786 is deep/risky (near invalidation)
  4. Confluence              — price within 5% of horizontal support / a rising 50-day

A broken setup (price at/below the swing low, retrace >= 100%) scores None — skip it.
"""

RATIOS = (0.382, 0.5, 0.618, 0.786)
LEVEL_POINTS = {0.0: 0.0, 0.382: 1.0, 0.5: 2.0, 0.618: 2.5, 0.786: 1.5}


def level_reached(frac):
    """Deepest fib ratio the retracement fraction has reached (0.0 if shallower than 0.382)."""
    reached = [r for r in RATIOS if frac >= r]
    return max(reached) if reached else 0.0


def favorability(frac, z, s50_dist, s50_dir, sup_dist, w200_pct, wk_bull):
    """Composite DCA favorability score. Returns None if the setup is broken.

    Args:
        frac:      current retracement fraction (0 = at high, 1 = at swing low)
        z:         z-score of price vs its 200-day SMA distance (negative = cheap)
        s50_dist:  % of price above(+)/below(-) the 50-day SMA
        s50_dir:   "up" | "down" | "flat" | None  (50-day slope)
        sup_dist:  % of price above the nearest horizontal support
        w200_pct:  % of price above(+)/below(-) the 200-week EMA (None if unknown)
        wk_bull:   weekly OTT bullish (bool)
    """
    if frac is None or frac >= 1.0:
        return None  # trend structure broken

    s = 0.0
    if wk_bull:
        s += 3.0
    if w200_pct is not None and w200_pct > 0:
        s += 1.0
    if s50_dir == "down":
        s -= 1.5
    if z is not None:
        s += max(0.0, -z) * 1.5
    s += LEVEL_POINTS.get(level_reached(frac), 0.0)
    if sup_dist is not None and abs(sup_dist) <= 5:
        s += 1.0
    if s50_dist is not None and abs(s50_dist) <= 5 and s50_dir == "up":
        s += 1.0
    return round(s, 1)


def tier(frac, z, w200_pct, wk_bull):
    """Coarse category for the auto summary."""
    if frac is None or frac >= 1.0:
        return "broken"
    if not wk_bull or (w200_pct is not None and w200_pct <= 5):
        return "caution"          # trend rolling over / barely above 200w — value-trap risk
    lvl = level_reached(frac)
    cheap = z is not None and z <= -0.75
    if cheap and lvl >= 0.5:
        return "favoured"         # cheap + golden-pocket + trend intact
    if cheap:
        return "cheap_shallow"    # cheap but only a shallow pullback
    return "quality_not_cheap"    # good trend, not on sale yet
