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

# Ranking order: group by tier quality first, then by score within the tier. This
# keeps regime-broken "caution" names below the buyable tiers regardless of how
# high their raw (cheapness-driven) score is — a deep, cheap dip in a broken trend
# is not a better DCA level than a shallow dip in a healthy one.
TIER_ORDER = {"favoured": 0, "cheap_shallow": 1, "quality_not_cheap": 2, "caution": 3, "broken": 4}


def rank_key(tier_name, score):
    """Sort key for ranking fib setups: (tier rank, then score descending)."""
    return (TIER_ORDER.get(tier_name, 5), -(score if score is not None else 0))


def fib_params(fib_cfg, category):
    """Resolve fib detection params for a category, applying category_overrides.

    Indices, for example, use a lower min_gain / reversal than volatile single
    stocks (their uptrends are more modest and corrections shallower)."""
    ov = fib_cfg.get("category_overrides", {}).get(category, {})
    return {
        "lookback": ov.get("lookback", fib_cfg.get("lookback", 104)),
        "min_gain": ov.get("min_gain", fib_cfg.get("min_gain", 0.30)),
        "reversal": ov.get("reversal", fib_cfg.get("reversal", 0.14)),
        "levels": tuple(ov.get("levels", fib_cfg.get("levels", RATIOS))),
    }


def level_reached(frac):
    """Deepest fib ratio the retracement fraction has reached (0.0 if shallower than 0.382)."""
    reached = [r for r in RATIOS if frac >= r]
    return max(reached) if reached else 0.0


def favorability(frac, z, s50_dist, s50_dir, sup_dist, w200_pct, wk_bull, d200_pct=None):
    """Composite DCA favorability score. Returns None if the setup is broken.

    Args:
        frac:      current retracement fraction (0 = at high, 1 = at swing low)
        z:         z-score of price vs its 200-day SMA distance (negative = cheap)
        s50_dist:  % of price above(+)/below(-) the 50-day SMA
        s50_dir:   "up" | "down" | "flat" | None  (50-day slope)
        sup_dist:  % of price above the nearest horizontal support
        w200_pct:  % of price above(+)/below(-) the 200-week EMA (None if unknown)
        wk_bull:   weekly OTT bullish (bool)
        d200_pct:  % of price above(+)/below(-) the 200-day SMA (None if unknown).
                   Below the 200-day = medium-term regime broken → penalised.
    """
    if frac is None or frac >= 1.0:
        return None  # trend structure broken

    s = 0.0
    if wk_bull:
        s += 3.0
    if w200_pct is not None and w200_pct > 0:
        s += 1.0
    if d200_pct is not None and d200_pct < 0:
        s -= 1.5                  # below the 200-day SMA — regime broken
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


def tier(frac, z, w200_pct, wk_bull, d200_pct=None):
    """Coarse category for the auto summary."""
    if frac is None or frac >= 1.0:
        return "broken"
    below_200d = d200_pct is not None and d200_pct < 0
    if not wk_bull or below_200d or (w200_pct is not None and w200_pct <= 5):
        return "caution"          # trend rolling over / below 200d / barely above 200w
    lvl = level_reached(frac)
    cheap = z is not None and z <= -0.75
    if cheap and lvl >= 0.5:
        return "favoured"         # cheap + golden-pocket + trend intact
    if cheap:
        return "cheap_shallow"    # cheap but only a shallow pullback
    return "quality_not_cheap"    # good trend, not on sale yet
