"""
Read-only Trading 212 account access (cash + open positions).

Used only by the *private* local dashboard view (dashboard.py --private) — never
by the public CI run. Requires T212_KEY_ID and T212_API_SECRET in alerts/.env
(or the environment). Auth is HTTP Basic: base64(KEY_ID:SECRET).

Everything degrades gracefully: if credentials are missing or a request fails,
functions return None so callers can simply skip the holdings overlay.
"""

import base64
import json
import os
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Live ISA/Invest by default; override with T212_ENV=demo for the practice account.
BASE_URLS = {
    "live": "https://live.trading212.com",
    "demo": "https://demo.trading212.com",
}

# yfinance/watchlist display name for a T212 instrument whose base symbol differs.
TICKER_ALIASES = {"GOOGL": "GOOG"}


def _load_env():
    """Mirror signal_checker's .env loader (local runs); env vars win if already set."""
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


def _auth_header():
    """Build the Basic auth header from KEY_ID:SECRET, or None if not configured."""
    _load_env()
    key_id = os.environ.get("T212_KEY_ID")
    secret = os.environ.get("T212_API_SECRET")
    if not (key_id and secret):
        return None
    token = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    return "Basic " + token


def _get(path):
    """GET a JSON endpoint; returns parsed body or None on any failure."""
    auth = _auth_header()
    if not auth:
        return None
    base = BASE_URLS.get(os.environ.get("T212_ENV", "live"), BASE_URLS["live"])
    req = urllib.request.Request(base + path, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return None


def _base_symbol(t212_ticker):
    """'GOOGL_US_EQ' -> 'GOOG' (via alias) / 'NVDA'. Strips the exchange suffix."""
    sym = (t212_ticker or "").split("_", 1)[0].upper()
    return TICKER_ALIASES.get(sym, sym)


def get_account():
    """Fetch cash + open positions. Returns a dict, or None if unavailable.

    {
      "cash": {free, total, invested, ppl, result, ...},   # raw T212 fields
      "holdings": {display_symbol: {"qty": float, "ppl": float}},
      "owned": set(display_symbol, ...),
    }
    """
    if not _auth_header():
        return None
    cash = _get("/api/v0/equity/account/cash")
    portfolio = _get("/api/v0/equity/portfolio")
    if cash is None or portfolio is None:
        return None
    holdings = {}
    for pos in portfolio:
        raw = pos.get("ticker") or ""
        sym = _base_symbol(raw)
        qty = pos.get("quantity") or 0.0
        price = pos.get("currentPrice") or 0.0
        holdings[sym] = {
            "qty": qty,
            "avg": pos.get("averagePrice"),   # average cost per share (position ccy)
            "price": price,                    # current price per share
            "ppl": pos.get("ppl"),             # unrealised P/L (account ccy)
            "value": qty * price,              # current market value (position ccy)
            "ccy": "USD" if "_US_" in raw else "GBP",  # instrument currency
        }
    return {"cash": cash, "holdings": holdings, "owned": set(holdings)}


if __name__ == "__main__":
    acct = get_account()
    if not acct:
        print("No Trading 212 account data (missing T212_KEY_ID/T212_API_SECRET, "
              "or the request failed).")
    else:
        c = acct["cash"]
        print(f"Free cash: {c.get('free')}  |  Invested: {c.get('invested')}  |  "
              f"Total: {c.get('total')}  |  Open P/L: {c.get('ppl')}")
        print(f"Holdings ({len(acct['owned'])}): {', '.join(sorted(acct['owned']))}")
