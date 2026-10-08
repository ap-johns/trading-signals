"""
Read-only IBKR access via the Flex Web Service.

A Flex Query is a saved report in IBKR Account Management; the web service
lets a script fetch it with a token — no gateway, no login session, no
trading permissions. This module pulls open option positions (and the
trades that opened them) and maps them onto the leap_positions.json
schema, so held LEAPs are picked up automatically.

Setup (once, in Account Management → Performance & Reports → Flex Queries):
  1. Create an Activity Flex Query, format XML, period "Last 365 Calendar Days".
     Sections: Open Positions (Account ID, Symbol, Underlying Symbol, Asset
     Class, Strike, Expiry, Put/Call, Quantity, Open Price, Cost Basis Price,
     Mark Price, Multiplier, Open Date/Time, Currency) and Trades (Symbol,
     Underlying Symbol, Asset Class, Trade Date, Buy/Sell, Quantity, Trade
     Price, IB Commission, Strike, Expiry, Put/Call). Note the Query ID.
  2. Reporting → Flex Web Service → Configure: enable it and copy the token
     (tokens expire; the default is a year).
  3. Put IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in alerts/.env locally and in
     the repo's Actions secrets for CI.

Protocol: SendRequest returns a reference code; GetStatement with that code
returns the report, or an "in progress" error to retry after a few seconds.
"""

import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
TIMEOUT = 30


def _load_env():
    """Mirror signal_checker's .env loader; real env vars win."""
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def credentials():
    _load_env()
    tok, qid = os.environ.get("IBKR_FLEX_TOKEN"), os.environ.get("IBKR_FLEX_QUERY_ID")
    return (tok, qid) if tok and qid else (None, None)


def _get(url, params):
    req = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": "trading-signals/1.0"})
    with urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def fetch_report(token, query_id, retries=6, wait=5):
    """Return the Flex report XML text. Raises RuntimeError on a Flex error."""
    first = ET.fromstring(_get(f"{BASE}/SendRequest", {"t": token, "q": query_id, "v": 3}))
    if (first.findtext("Status") or "").lower() != "success":
        raise RuntimeError(f"Flex SendRequest failed: {first.findtext('ErrorCode')} {first.findtext('ErrorMessage')}")
    ref = first.findtext("ReferenceCode")
    url = first.findtext("Url") or f"{BASE}/GetStatement"
    for _ in range(retries):
        text = _get(url, {"q": ref, "t": token, "v": 3})
        if "<FlexQueryResponse" in text:
            return text
        # Not ready yet (error 1019) or another transient error.
        if "1019" in text or "in progress" in text.lower():
            time.sleep(wait)
            continue
        raise RuntimeError(f"Flex GetStatement failed: {text[:200]}")
    raise RuntimeError("Flex report not ready after retries")


def _date(s):
    """'20280121' or '20261008;162934' -> 'YYYY-MM-DD'."""
    if not s:
        return None
    s = s.split(";")[0].replace("-", "")
    try:
        return datetime.strptime(s[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_positions(xml_text):
    """Open long call options -> list of leap_positions.json records.
    Commission and entry date come from the Trades section when present."""
    root = ET.fromstring(xml_text)
    trades = {}
    for t in root.iter("Trade"):
        if (t.get("assetCategory") or "") != "OPT" or (t.get("putCall") or "") != "C":
            continue
        key = (t.get("underlyingSymbol") or t.get("symbol", "").split()[0], _date(t.get("expiry")), float(t.get("strike") or 0))
        rec = trades.setdefault(key, {"commission": 0.0, "first_date": None, "qty": 0.0})
        if (t.get("buySell") or "").upper().startswith("BUY"):
            rec["commission"] += abs(float(t.get("ibCommission") or 0))
            d = _date(t.get("tradeDate") or t.get("dateTime"))
            if d and (rec["first_date"] is None or d < rec["first_date"]):
                rec["first_date"] = d
            rec["qty"] += abs(float(t.get("quantity") or 0))
    out = []
    for p in root.iter("OpenPosition"):
        if (p.get("assetCategory") or "") != "OPT" or (p.get("putCall") or "") != "C":
            continue
        qty = float(p.get("position") or 0)
        if qty <= 0:
            continue                                   # long calls only
        under = p.get("underlyingSymbol") or p.get("symbol", "").split()[0]
        expiry = _date(p.get("expiry"))
        strike = float(p.get("strike") or 0)
        key = (under, expiry, strike)
        tr = trades.get(key, {})
        entry_price = float(p.get("openPrice") or p.get("costBasisPrice") or 0)
        out.append({
            "ticker": under, "expiry": expiry, "strike": strike, "contracts": int(qty),
            "entry_price": round(entry_price, 4),
            "entry_date": tr.get("first_date") or _date(p.get("openDateTime")),
            "commission": round(tr.get("commission", 0.0), 2),
            "account": f"IBKR {p.get('accountId', '')}".strip(),
            "mark": float(p.get("markPrice") or 0) or None,
            "source": "ibkr_flex",
        })
    return out


def fetch_positions():
    """Live positions from IBKR, or None if credentials are absent."""
    token, qid = credentials()
    if not token:
        return None
    return parse_positions(fetch_report(token, qid))


if __name__ == "__main__":
    import json
    pos = fetch_positions()
    print(json.dumps(pos, indent=2) if pos is not None else "no IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID set")
