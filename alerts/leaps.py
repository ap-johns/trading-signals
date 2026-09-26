"""
LEAP (long-dated call option) opportunity scanner — informational only.

A LEAP is a call option with 12+ months to expiry. Buying a deep in-the-money
LEAP is a leveraged, time-limited stand-in for owning the stock ("stock
replacement"). A good LEAP entry needs two things at once:

  1. The *underlying* is cheap — the DCA favourability tier already measures
     this, so it is reused rather than re-derived here.
  2. The *option premium* is cheap — implied volatility (IV) is the price of
     the option in vol terms. This module measures IV against realised
     volatility (what the stock has actually done) and against its own
     history (IV rank), which is the half the dashboard was missing.

Nothing here feeds alerts or the favourability score. It is a per-ticker
snapshot rendered as a dashboard panel, plus a daily IV history file so IV
rank becomes meaningful over time.

Data source: yfinance option chains (Yahoo). IV values are Yahoo's own
model figures from the last trade and can be stale on illiquid strikes —
hence the open-interest and bid/ask checks.
"""

import json
import math
import os
from datetime import date

import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IV_HISTORY_PATH = os.path.join(SCRIPT_DIR, "iv_history.json")

# Index tickers have no listed options under the yfinance symbol; use the
# liquid ETF that tracks them instead.
OPTION_PROXY = {"^GSPC": "SPY"}

# Contract-selection defaults. Stock replacement usually targets delta 0.70–0.85:
# high enough that the call moves nearly 1:1 with the stock, low enough that
# the premium isn't almost all intrinsic (i.e. you still get some leverage).
TARGET_DELTA = 0.78
MIN_MONTHS = 15          # nearest expiry at least this far out
RISK_FREE = 0.04
MIN_IV_HISTORY = 60      # trading days before IV rank is shown
IV_RATIO_GOOD = 1.0      # IV/RV at or below this = premium not pricing in extra risk
IV_RATIO_OK = 1.3
MIN_OI = 250             # open interest floor for a usable contract


# ---------------------------------------------------------------- maths

def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call_delta(spot, strike, years, sigma, r=RISK_FREE):
    """Black-Scholes call delta: how much the option price moves per $1 of stock."""
    if years <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        return None
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * years) / (sigma * math.sqrt(years))
    return _norm_cdf(d1)


def realised_vol(close, n=90):
    """Annualised standard deviation of daily log returns over the last n bars."""
    close = pd.Series(close).dropna()
    if len(close) < n + 1:
        return None
    r = np.log(close).diff().dropna().iloc[-n:]
    return float(r.std() * math.sqrt(252))


# ---------------------------------------------------------------- IV history

def load_iv_history(path=IV_HISTORY_PATH):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save_iv_history(hist, path=IV_HISTORY_PATH):
    with open(path, "w") as f:
        json.dump(hist, f, indent=1, sort_keys=True)
        f.write("\n")


def record_iv(hist, name, iv, when=None, keep_days=400):
    """Append today's ATM LEAP IV for a ticker; trim to ~1.5 years."""
    when = (when or date.today()).isoformat()
    series = hist.setdefault(name, {})
    series[when] = round(float(iv), 4)
    if len(series) > keep_days:
        for k in sorted(series)[:-keep_days]:
            del series[k]
    return hist


def iv_rank(hist, name, iv_today):
    """Percentile of today's IV within this ticker's recorded history.

    0 = cheapest IV seen, 100 = most expensive. Returns (rank, n_obs); rank is
    None until at least MIN_IV_HISTORY observations exist.
    """
    series = hist.get(name, {})
    vals = [v for k, v in series.items() if v is not None]
    n = len(vals)
    if n < MIN_IV_HISTORY:
        return None, n
    below = sum(1 for v in vals if v < iv_today)
    return round(below / n * 100), n


# ---------------------------------------------------------------- chain fetch

def _pick_expiry(expiries, min_months=MIN_MONTHS, today=None):
    today = today or date.today()
    min_days = int(min_months * 30.4)
    far = [e for e in expiries if (date.fromisoformat(e) - today).days >= min_days]
    if far:
        return far[0]
    # Fall back to the furthest listed expiry if it's at least a year out.
    ok = [e for e in expiries if (date.fromisoformat(e) - today).days >= 365]
    return ok[-1] if ok else None


def _mid(row):
    bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2, bid, ask
    last = float(row.get("lastPrice") or 0)
    return (last if last > 0 else None), bid, ask


def fetch_leap_snapshot(yf_ticker, spot, close_series=None, ticker_obj=None,
                        target_delta=TARGET_DELTA, min_months=MIN_MONTHS):
    """Pull one LEAP expiry's call chain and summarise it for the dashboard.

    Returns None when the name has no listed options or no usable expiry.
    Raises on network/parse errors so the caller can record them.
    """
    import yfinance as yf

    sym = OPTION_PROXY.get(yf_ticker, yf_ticker)
    t = ticker_obj if (ticker_obj is not None and sym == yf_ticker) else yf.Ticker(sym)
    expiries = list(t.options or [])
    if not expiries:
        return None
    expiry = _pick_expiry(expiries, min_months)
    if expiry is None:
        return None

    calls = t.option_chain(expiry).calls
    if calls is None or calls.empty:
        return None
    calls = calls.copy()
    calls["strike"] = calls["strike"].astype(float)
    calls["impliedVolatility"] = calls["impliedVolatility"].astype(float)

    today = date.today()
    dte = (date.fromisoformat(expiry) - today).days
    years = dte / 365.0

    # If we were handed a proxy (SPY for ^GSPC) the spot must be the proxy's own.
    if sym != yf_ticker:
        h = t.history(period="5d")["Close"].dropna()
        if h.empty:
            return None
        spot = float(h.iloc[-1])

    # ATM implied vol: the cleanest single read of "how expensive are options".
    atm = calls.iloc[(calls["strike"] - spot).abs().argsort().iloc[:1]].iloc[0]
    atm_iv = float(atm["impliedVolatility"])
    if not (0.02 < atm_iv < 5.0):
        return None

    # Deep-ITM candidate: strike whose Black-Scholes delta is nearest the target.
    # Use each row's own IV; fall back to ATM IV where Yahoo reports junk.
    def row_delta(r):
        iv = float(r["impliedVolatility"])
        if not (0.02 < iv < 5.0):
            iv = atm_iv
        return bs_call_delta(spot, float(r["strike"]), years, iv)

    calls["delta"] = calls.apply(row_delta, axis=1)
    itm = calls[(calls["strike"] < spot) & calls["delta"].notna()]
    if itm.empty:
        return None
    # Prefer a liquid strike: among those within ±0.05 delta of the target take
    # the highest open interest, otherwise fall back to the nearest delta.
    near = itm[(itm["delta"] - target_delta).abs() <= 0.05]
    near = near[near["openInterest"].fillna(0) >= MIN_OI] if not near.empty else near
    if not near.empty:
        cand = near.sort_values("openInterest", ascending=False).iloc[0]
    else:
        cand = itm.iloc[(itm["delta"] - target_delta).abs().argsort().iloc[:1]].iloc[0]

    mid, bid, ask = _mid(cand)
    strike = float(cand["strike"])
    intrinsic = max(spot - strike, 0.0)
    extrinsic = (mid - intrinsic) if mid is not None else None
    spread_pct = ((ask - bid) / mid * 100) if (mid and bid > 0 and ask > 0) else None
    oi = int(cand.get("openInterest") or 0)

    rv90 = realised_vol(close_series, 90) if close_series is not None else None
    iv_ratio = (atm_iv / rv90) if (rv90 and rv90 > 0) else None

    return {
        "symbol": sym,
        "expiry": expiry,
        "dte": dte,
        "spot": spot,
        "atm_iv": atm_iv,
        "rv90": rv90,
        "iv_ratio": iv_ratio,
        "strike": strike,
        "delta": float(cand["delta"]),
        "mid": mid,
        "bid": bid,
        "ask": ask,
        "intrinsic": intrinsic,
        "extrinsic": extrinsic,
        "extrinsic_pct": (extrinsic / spot * 100) if extrinsic is not None else None,
        "spread_pct": spread_pct,
        "oi": oi,
        "breakeven": (strike + mid) if mid is not None else None,
        "leverage": (spot / mid) if mid else None,
        "cost_pct": (mid / spot * 100) if mid else None,
    }


# ---------------------------------------------------------------- assessment

def iv_ratio_band(ratio):
    """'good' / 'ok' / 'rich' / None for the IV-vs-realised ratio."""
    if ratio is None:
        return None
    if ratio <= IV_RATIO_GOOD:
        return "good"
    if ratio <= IV_RATIO_OK:
        return "ok"
    return "rich"


def leap_flag(tier, snap):
    """Single-word verdict combining the underlying's tier with premium cost.

    'strong'  — underlying in the favoured tier (cheap + golden-pocket retrace
                + trend intact) AND premium not rich AND contract liquid.
                The first-trade grade: a deeper entry lowers breakeven and
                buys more recovery per unit of time value.
    'setup'   — as above but the stock is only cheap_shallow: cheap versus
                its 200d but a small pullback. Fine for DCA, thin margin for
                a dated instrument.
    'watch'   — underlying cheap but premium is rich, or trend intact & premium
                cheap but stock not on sale yet.
    'avoid'   — trend broken / rolling over: a dated instrument on a name
                that may go nowhere for a year is the worst case for a LEAP.
    'thin'    — contract too illiquid to rely on the numbers.
    """
    if snap is None:
        return None
    if tier in ("broken", "caution"):
        return "avoid"
    if snap.get("oi", 0) < MIN_OI or snap.get("mid") is None:
        return "thin"
    band = iv_ratio_band(snap.get("iv_ratio"))
    cheap_prem = band in ("good", "ok")
    if tier == "favoured" and cheap_prem:
        return "strong"
    if tier == "cheap_shallow" and cheap_prem:
        return "setup"
    return "watch"


def rank_key(item):
    """Sort: strong, setup, watch, thin, avoid; within a group cheaper premium first."""
    order = {"strong": 0, "setup": 1, "watch": 2, "thin": 3, "avoid": 4, None: 5}
    snap = item.get("snap") or {}
    ratio = snap.get("iv_ratio")
    return (order.get(item.get("flag"), 4), ratio if ratio is not None else 9.0)


# ---------------------------------------------------------------- 2x daily-reset ETP suitability

ETP_LEVERAGE = 2
ETP_WINDOW = 378            # ~18 months of trading days
ETP_DRAG = 0.11             # fees + financing per unit of borrowed exposure, per year
ETP_MIN_WINDOWS = 500       # ~2 years of rolling windows before the stats are trusted
ETP_SINCE = "2010-01-01"    # common sample start so verdicts are comparable across names

# London-listed 2x daily long ETPs per watchlist name, verified via yfinance on
# 2026-09-26: (USD line, GBP line, issuer). Leverage Shares list both currency
# lines under mirrored tickers. None = no 2x product found in London; the note
# says what does exist. Check ISA/SIPP eligibility of the exact line with the
# provider before relying on it.
ETP_TICKERS = {
    "NVDA": ("NVD2", "2NVD", "Leverage Shares"),
    "MSFT": ("MSF2", "2MSF", "Leverage Shares"),
    "AMZN": ("AMZ2", "2AMZ", "Leverage Shares"),
    "GOOG": ("GOO2", "2GOO", "Leverage Shares"),
    "AMD":  ("AMD2", "2AMD", "Leverage Shares"),
    "TSLA": ("TSL2", "2TSL", "Leverage Shares"),
    "META": ("FB2",  "2FB",  "Leverage Shares"),
    "MU":   ("MU2",  "2MU",  "Leverage Shares"),
    "SPX":  ("XS2D", None,   "Xtrackers UCITS ETF"),
}
ETP_NOTES = {
    "QQQ":  "no 2x in London; 3x only (QQQ3 / LQQ3, WisdomTree)",
    "TSM":  "no 2x in London; 3x only (TSM3, Leverage Shares)",
    "AVGO": "no 2x in London; 3x only (3AVG, Leverage Shares)",
}


def etp_simulate(close, leverage=ETP_LEVERAGE, drag=ETP_DRAG):
    """Synthetic daily-reset leveraged product from the underlying's own daily
    returns. Financing/fees scale with the borrowed fraction (leverage - 1)."""
    close = pd.Series(close).dropna()
    r = close.pct_change().dropna()
    daily_drag = drag * (leverage - 1) / 2 / 252
    return (1 + leverage * r - daily_drag).cumprod()


def etp_stats(close, leverage=ETP_LEVERAGE, window=ETP_WINDOW, since=ETP_SINCE):
    """Rolling `window`-bar hold statistics for a synthetic leveraged product vs
    holding the stock, over a common sample starting at `since` (or listing).
    `n` is the number of windows; treat < ETP_MIN_WINDOWS as thin."""
    close = pd.Series(close).dropna()
    idx = close.index.tz_localize(None) if getattr(close.index, "tz", None) is not None else close.index
    close = close[idx >= pd.Timestamp(since)]
    start_year = int(close.index[0].year) if len(close) else None
    r1y = np.log(close).diff().dropna().iloc[-252:]
    vol1y = float(r1y.std() * math.sqrt(252)) if len(r1y) >= 120 else None
    if len(close) < window + 20:
        return {"n": 0, "vol1y": vol1y, "since": start_year}
    etp = etp_simulate(close, leverage)
    re = etp.pct_change(window).dropna()
    ru = close.pct_change(window).dropna()
    j = pd.concat([re.rename("e"), ru.rename("u")], axis=1).dropna()
    if j.empty:
        return {"n": 0, "vol1y": vol1y, "since": start_year}
    return {
        "n": int(len(j)),
        "since": start_year,
        "vol1y": vol1y,
        "beat_pct": float((j.e > j.u).mean() * 100),
        "halved_pct": float((j.e < -0.5).mean() * 100),
        "lose_while_up_pct": float(((j.e < 0) & (j.u > 0)).mean() * 100),
        "etp_median": float(j.e.median() * 100),
        "stock_median": float(j.u.median() * 100),
        "worst": float(j.e.min() * 100),
        # Expected annual volatility drag of an L× daily-reset product ≈ σ²·(L²−L)/2
        "vol_drag": (vol1y ** 2 * (leverage ** 2 - leverage) / 2 * 100) if vol1y else None,
    }


def etp_verdict(st):
    """'suitable' / 'marginal' / 'avoid' / 'thin' for holding a 2x daily-reset
    ETP ~18 months. With thin history, fall back to realised vol alone: the
    daily reset feeds on volatility, so a very volatile name is an avoid
    regardless of how its short history happened to play out."""
    if not st:
        return None
    vol = st.get("vol1y")
    if st.get("n", 0) < ETP_MIN_WINDOWS:
        if vol is not None and vol >= 0.65:
            return "avoid"
        return "thin"
    beat, halved = st["beat_pct"], st["halved_pct"]
    if (beat >= 65 and halved <= 10) or (beat >= 60 and halved <= 5):
        return "suitable"
    if beat <= 50 or halved >= 20:
        return "avoid"
    return "marginal"
