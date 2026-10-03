"""
Crypto treasury companies: mNAV (market value / net asset value) tracking.

A treasury company (Strategy, Hyperliquid Strategies, ...) is a listed shell
around a pile of coin. Its share price trades at a multiple of the coin it
holds — the mNAV. Premiums expand in bull runs (MSTR hit ~4x in 2024-25) and
collapse in bears (the Solana treasuries went to 0.6x in 2026). For a holder
the premium is the lever: buy when it is near or below 1x, derisk into the
coin or an ETP when it gets rich, sell when it gets silly.

Two multiples are reported:
  basic  = market cap / coin value
  ev     = (market cap + debt + other claims - cash) / coin value
EV is the honest one for MSTR, whose converts and preferred stock sit ahead of
equity. The alert thresholds use EV.

Inputs: price, share count, debt and cash from yfinance; coin holdings and
any claims yfinance can't see (MSTR's preferreds) from config, refreshed by
hand from the companies' filings — the dashboard flags stale holdings.
"""

from datetime import date, datetime

import yfinance as yf

STALE_DAYS = 45          # holdings older than this get a warning on the dashboard


def _info(t):
    try:
        return t.info or {}
    except Exception:  # noqa: BLE001
        return {}


def _last_close(sym):
    h = yf.Ticker(sym).history(period="10d")["Close"].dropna()
    return float(h.iloc[-1]) if len(h) else None


def compute_mnav(ticker, cfg):
    """Return a dict of mNAV figures for one treasury company, or None if the
    price feed fails. `cfg` is the ticker's entry in config['treasury_companies']."""
    t = yf.Ticker(ticker)
    info = _info(t)
    price = info.get("currentPrice") or info.get("regularMarketPrice") or _last_close(ticker)
    if not price:
        return None
    shares = cfg.get("shares") or info.get("impliedSharesOutstanding") or info.get("sharesOutstanding")
    if not shares:
        return None
    coin_px = _last_close(cfg["asset"])
    if not coin_px:
        return None
    holdings = float(cfg["holdings"])
    debt = float(cfg.get("debt_usd") if cfg.get("debt_usd") is not None else (info.get("totalDebt") or 0))
    cash = float(cfg.get("cash_usd") if cfg.get("cash_usd") is not None else (info.get("totalCash") or 0))
    other = float(cfg.get("other_claims_usd") or 0)      # e.g. preferred stock notional

    mcap = price * shares
    nav = holdings * coin_px
    ev = mcap + debt + other - cash
    basic = mcap / nav if nav else None
    ev_mnav = ev / nav if nav else None
    nav_per_share = nav / shares
    updated = cfg.get("updated")
    try:
        age = (date.today() - datetime.strptime(updated, "%Y-%m-%d").date()).days if updated else None
    except ValueError:
        age = None
    return {
        "ticker": ticker, "name": cfg.get("name", ticker), "asset": cfg["asset"],
        "asset_label": cfg.get("asset_label", cfg["asset"]),
        "price": float(price), "shares": float(shares), "mcap": mcap,
        "coin_px": coin_px, "holdings": holdings, "nav": nav, "nav_per_share": nav_per_share,
        "debt": debt, "cash": cash, "other": other, "ev": ev,
        "mnav_basic": basic, "mnav_ev": ev_mnav,
        "updated": updated, "age_days": age, "stale": (age is not None and age > STALE_DAYS),
        "alt": cfg.get("alt"),
        "cheap_below": cfg.get("cheap_below", 1.0),
        "derisk_above": cfg.get("derisk_above", 2.0),
        "sell_above": cfg.get("sell_above", 2.5),
    }


def status(m):
    """'cheap' / 'fair' / 'derisk' / 'sell' from the EV mNAV against the bands."""
    x = m.get("mnav_ev")
    if x is None:
        return None
    if x >= m["sell_above"]:
        return "sell"
    if x >= m["derisk_above"]:
        return "derisk"
    if x <= m["cheap_below"]:
        return "cheap"
    return "fair"


STATUS_LABEL = {
    "cheap":  ("Cheap", "#00e676", "trades at or below the value of its coin"),
    "fair":   ("Fair", "#a8a59c", "premium within the normal band"),
    "derisk": ("Derisk", "#e8925d", "premium rich: move some into the coin or an ETP"),
    "sell":   ("Sell", "#ff5252", "premium at mania levels"),
}
