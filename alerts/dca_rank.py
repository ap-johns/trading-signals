#!/usr/bin/env python3
"""
Rank stocks by buy-and-hold DCA "favorability" using the same signals as the
dashboard fib table (weekly fib retracement + trend / cheapness / confluence).

Prints a plain-text table sorted by score. Intended to be run by the
/dca-review slash command, which then narrates the result. Also useful stand-alone:

    python3 alerts/dca_rank.py
"""

import json
import os
import sys

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from indicators import calculate_sma, calculate_ema, calculate_ott, calculate_fib_levels
from fib_score import favorability, tier, level_reached, fib_params
from dashboard import nearest_support
import yfinance as yf


def load_config():
    with open(os.path.join(SCRIPT_DIR, "config.json")) as f:
        return json.load(f)


def analyse():
    cfg = load_config()
    fc = cfg.get("fib_alerts", {})
    categories = fc.get("categories", ["Stocks"])

    tickers = []
    for cat in categories:
        for yf_ticker, name in cfg["watchlist"].get(cat, {}).items():
            tickers.append((yf_ticker, name, cat))

    rows = []
    for yf_ticker, name, cat in tickers:
        try:
            fp = fib_params(fc, cat)
            d = yf.Ticker(yf_ticker).history(period="365d", interval="1d")  # match dashboard window
            dw = yf.Ticker(yf_ticker).history(period="max", interval="1wk").dropna()
            if d.empty or dw.empty:
                continue
            price = d["Close"].iloc[-1]
            fib = calculate_fib_levels(dw["High"], dw["Low"], lookback=fp["lookback"],
                                       min_gain=fp["min_gain"], reversal=fp["reversal"],
                                       ratios=fp["levels"])
            if not fib:
                continue
            sl, sh = fib["swing_low"], fib["swing_high"]
            frac = (sh - price) / (sh - sl)

            ema200d = calculate_sma(d["Close"], 200)
            pc = ((d["Close"] - ema200d) / ema200d * 100).dropna()
            z = float((pc.iloc[-1] - pc.mean()) / pc.std()) if len(pc) > 1 and pc.std() > 0 else None

            s50 = calculate_sma(d["Close"], 50)
            s50v = s50.iloc[-1]
            has50 = pd.notna(s50v)
            s50_dist = (price - s50v) / s50v * 100 if has50 else None
            if has50 and len(s50) > 21 and pd.notna(s50.iloc[-21]):
                chg = (s50v - s50.iloc[-21]) / s50.iloc[-21] * 100
                s50_dir = "up" if chg > 0.5 else ("down" if chg < -0.5 else "flat")
            else:
                s50_dir = None

            sup = nearest_support(d["Low"], price)
            sup_dist = (price - sup) / price * 100 if sup else None

            ema200w = calculate_ema(dw["Close"], 200).iloc[-1] if len(dw) >= 104 else None
            w200 = (price - ema200w) / ema200w * 100 if ema200w else None

            ow = calculate_ott(dw["Open"], 10, 3.0)
            wk_bull = bool(ow["mavg"].iloc[-1] > ow["ott"].iloc[-1])

            score = favorability(frac, z, s50_dist, s50_dir, sup_dist, w200, wk_bull)
            rows.append({
                "name": name, "category": cat, "price": round(float(price), 2), "retrace_pct": round(frac * 100),
                "level": level_reached(frac), "z": round(z, 1) if z is not None else None,
                "sma50_dist_pct": round(s50_dist) if s50_dist is not None else None,
                "sma50_dir": s50_dir,
                "support_dist_pct": round(sup_dist) if sup_dist is not None else None,
                "above_200w_pct": round(w200) if w200 is not None else None,
                "weekly_ott_bull": wk_bull,
                "gain_pct": round(fib["gain"] * 100),
                "swing_low": round(sl, 2), "swing_high": round(sh, 2),
                "score": score, "tier": tier(frac, z, w200, wk_bull),
            })
        except Exception as e:
            print(f"# skip {name}: {e!r}", file=sys.stderr)

    # Rank within each category (score desc; broken last).
    rows.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))
    return rows


def _print_group(rows):
    hdr = (f'{"#":>2} {"Tkr":5} {"score":>5} {"retr":>5} {"lvl":>5} {"z":>6} '
           f'{"50d":>9} {"sup":>6} {"200w":>6} {"wk":>3} {"tier":16}')
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(rows, 1):
        s50 = (f'{r["sma50_dist_pct"]:+d}%{ {"up":"^","down":"v","flat":"-"}.get(r["sma50_dir"],"?") }'
               if r["sma50_dist_pct"] is not None else "-")
        sup = f'{r["support_dist_pct"]:+d}%' if r["support_dist_pct"] is not None else "-"
        w = f'{r["above_200w_pct"]:+d}%' if r["above_200w_pct"] is not None else "new"
        z = f'{r["z"]:+.1f}s' if r["z"] is not None else "-"
        sc = f'{r["score"]:.1f}' if r["score"] is not None else "skip"
        print(f'{i:>2} {r["name"]:5} {sc:>5} {r["retrace_pct"]:>4}% {r["level"]:>5} {z:>6} '
              f'{s50:>9} {sup:>6} {w:>6} {"UP" if r["weekly_ott_bull"] else "dn":>3} {r["tier"]:16}')


def main():
    rows = analyse()
    # Group by category, preserving the config category order.
    seen = []
    for r in rows:
        if r["category"] not in seen:
            seen.append(r["category"])
    for cat in seen:
        print(f"\n=== {cat} ===")
        _print_group([r for r in rows if r["category"] == cat])
    # Also emit JSON so the caller can parse exact values if needed.
    print("\nJSON:")
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
