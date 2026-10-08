"""
LEAP positions held: daily status and exit prompts.

Positions live in a git-ignored JSON file (the repo is public) and, for the
CI run, in the LEAP_POSITIONS_JSON secret — same content. Nothing here is
ever written to the public dashboard; output goes to the Telegram digest,
to one-off alerts when an exit rule first trips, and to the --private
dashboard.

Position record (one per contract line):
  {"ticker": "UMAC", "expiry": "2028-01-21", "strike": 12.5, "contracts": 1,
   "entry_price": 12.60, "entry_date": "2026-10-08", "entry_spot": 22.0,
   "commission": 0.14, "account": "IBKR U29078547", "note": "first LEAP"}

Exit rules (agreed 2026-09-26, see CLAUDE.md):
  roll      <= 6 months to expiry: roll or close, whatever the stock is doing
  delta     delta >= 0.90: leverage gone, roll up or convert to shares
  gain      stock >= +40% from entry: same as above
  ott_sell  a daily OTT sell crossover after the entry date, with price above
            the 200d SMA (the stock sell rule, applied once you're in)
  caution   DCA tier caution/broken with < 9 months left: a dated instrument
            on a stalled name
"""

import json
import os
from datetime import date, datetime

import yfinance as yf

import leaps
from indicators import calculate_ott, calculate_sma

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSITIONS_PATH = os.path.join(SCRIPT_DIR, "leap_positions.json")

ROLL_DAYS = 182          # ~6 months
CAUTION_DAYS = 270       # ~9 months
DELTA_EXIT = 0.90
GAIN_EXIT = 0.40

RULE_LABEL = {
    "roll":     "ROLL: under 6 months to expiry",
    "delta":    "TAKE PROFIT: delta at or above 0.90, leverage spent",
    "gain":     "TAKE PROFIT: stock up 40%+ from entry",
    "ott_sell": "EXIT: daily OTT sell above the 200d",
    "caution":  "EXIT: tier caution/broken with under 9 months left",
}


def _local_positions(path):
    raw = os.environ.get("LEAP_POSITIONS_JSON")
    if raw and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else data.get("positions", [])
        except json.JSONDecodeError:
            print("LEAP_POSITIONS_JSON is not valid JSON; ignoring")
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("positions", [])
    return []


def _gbpusd_on(entry_date):
    """GBPUSD close on (or just after) a date, for the sterling cost."""
    try:
        h = yf.Ticker("GBPUSD=X").history(start=entry_date, period=None, interval="1d")["Close"].dropna()
        return round(float(h.iloc[0]), 5) if len(h) else None
    except Exception:  # noqa: BLE001
        return None


def _gbpusd_now():
    try:
        h = yf.Ticker("GBPUSD=X").history(period="5d")["Close"].dropna()
        return float(h.iloc[-1]) if len(h) else None
    except Exception:  # noqa: BLE001
        return None


def _entry_spot(ticker, entry_date):
    """Underlying close on the entry date (yfinance), for the +40% rule."""
    try:
        h = yf.Ticker(ticker).history(start=entry_date, period=None, interval="1d")
        h = h.dropna(subset=["Close"])
        return round(float(h["Close"].iloc[0]), 4) if len(h) else None
    except Exception:  # noqa: BLE001
        return None


def load_positions(path=POSITIONS_PATH):
    """Positions from IBKR via Flex when IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID are
    set, merged with any hand-kept extras (entry_spot, note) from the local file
    or LEAP_POSITIONS_JSON; otherwise the local data alone. When Flex is used
    locally the merged result is written back to the file as a cache/fallback."""
    local = _local_positions(path)
    try:
        import ibkr_flex
        live = ibkr_flex.fetch_positions()
    except Exception as e:  # noqa: BLE001
        print(f"IBKR Flex unavailable ({e}); using local positions")
        live = None
    if live is None:
        return local
    by_id = {position_id(p): p for p in local}
    merged = []
    for p in live:
        extra = by_id.get(position_id(p), {})
        for k in ("entry_spot", "note", "account"):
            if extra.get(k) and not p.get(k):
                p[k] = extra[k]
        if extra.get("entry_spot"):
            p["entry_spot"] = extra["entry_spot"]
        if not p.get("entry_spot") and p.get("entry_date"):
            p["entry_spot"] = _entry_spot(p["ticker"], p["entry_date"])
        if extra.get("entry_gbpusd"):
            p["entry_gbpusd"] = extra["entry_gbpusd"]
        if not p.get("entry_gbpusd") and p.get("entry_date"):
            p["entry_gbpusd"] = _gbpusd_on(p["entry_date"])
        merged.append(p)
    # The Flex statement runs to the previous business day, so a contract
    # bought today (or over a weekend) isn't in it yet. Keep local entries
    # whose entry_date is recent; anything older that IBKR no longer lists
    # is treated as closed and dropped.
    live_ids = {position_id(p) for p in live}
    for p in local:
        if position_id(p) in live_ids or not p.get("entry_date"):
            continue
        try:
            age = (date.today() - date.fromisoformat(p["entry_date"])).days
        except ValueError:
            age = 0
        if age <= 4:
            merged.append(p)
    if not os.environ.get("GITHUB_ACTIONS"):
        try:
            save_positions(merged, path)
        except OSError:
            pass
    return merged


def save_positions(positions, path=POSITIONS_PATH):
    with open(path, "w") as f:
        json.dump(positions, f, indent=2)
        f.write("\n")


def position_id(p):
    return f"{p['ticker']}-{p['expiry']}-{p['strike']:g}"


def _chain_quote(t, expiry, strike):
    """(bid, ask, mid, iv) for one call strike, or Nones if missing."""
    try:
        calls = t.option_chain(expiry).calls
    except Exception:  # noqa: BLE001
        return None, None, None, None
    row = calls[calls["strike"] == float(strike)]
    if row.empty:
        return None, None, None, None
    r = row.iloc[0]
    bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else (float(r.get("lastPrice") or 0) or None)
    iv = float(r.get("impliedVolatility") or 0)
    return bid, ask, mid, (iv if 0.02 < iv < 5 else None)


def evaluate(positions, config, tier_lookup=None):
    """Return one status dict per position. `tier_lookup(ticker) -> row|None`
    optionally supplies the DCA ranking row (tier) so it isn't recomputed."""
    out = []
    today = date.today()
    fx_now = _gbpusd_now()
    for p in positions:
        tk = p["ticker"]
        t = yf.Ticker(tk)
        d = t.history(period="365d", interval="1d").dropna(subset=["Close"])
        if d.empty:
            out.append({"pos": p, "id": position_id(p), "error": "no price data"})
            continue
        spot = float(d["Close"].iloc[-1])
        dte = (date.fromisoformat(p["expiry"]) - today).days
        years = max(dte, 0) / 365.0
        bid, ask, mid, iv = _chain_quote(t, p["expiry"], p["strike"])
        delta = leaps.bs_call_delta(spot, float(p["strike"]), years, iv) if (iv and years > 0) else None
        intrinsic = max(spot - float(p["strike"]), 0.0)
        n = int(p.get("contracts", 1))
        cost = float(p["entry_price"]) * 100 * n + float(p.get("commission", 0))
        value = (mid * 100 * n) if mid else None
        pnl = (value - cost) if value is not None else None
        entry_spot = p.get("entry_spot")
        stock_move = (spot / float(entry_spot) - 1) if entry_spot else None
        fx_entry = p.get("entry_gbpusd") or _gbpusd_on(p["entry_date"]) if p.get("entry_date") else None
        cost_gbp = (cost / fx_entry) if fx_entry else None
        value_gbp = (value / fx_now) if (value is not None and fx_now) else None
        pnl_gbp = (value_gbp - cost_gbp) if (value_gbp is not None and cost_gbp is not None) else None

        # Stock sell rule, applied from the entry date onwards: the most recent
        # daily OTT crossover *after* entry is a sell, and price is above the
        # 200d SMA. (Checking the bare state would fire on the day you buy a
        # dip, since a Favoured entry usually comes with the daily OTT bearish.)
        ott = calculate_ott(d["Open"], config["ott"]["period"], config["ott"]["percent"])
        ott_bear = bool(ott["mavg"].iloc[-1] < ott["ott"].iloc[-1])
        sma200 = calculate_sma(d["Close"], 200).iloc[-1]
        above_200 = bool(spot > sma200) if sma200 == sma200 else False   # NaN-safe
        entry_dt = datetime.strptime(p["entry_date"], "%Y-%m-%d")
        idx = d.index.tz_localize(None) if getattr(d.index, "tz", None) is not None else d.index
        sig_after = ott["signal"][(idx > entry_dt) & (ott["signal"] != 0)]
        ott_sell_after_entry = bool(len(sig_after) and sig_after.iloc[-1] == -1)

        tier = None
        if tier_lookup:
            try:
                row = tier_lookup(tk)
                tier = row.get("tier") if row else None
            except Exception:  # noqa: BLE001
                tier = None

        flags = []
        if dte <= ROLL_DAYS:
            flags.append("roll")
        if delta is not None and delta >= DELTA_EXIT:
            flags.append("delta")
        if stock_move is not None and stock_move >= GAIN_EXIT:
            flags.append("gain")
        if ott_sell_after_entry and above_200:
            flags.append("ott_sell")
        if tier in ("caution", "broken") and dte < CAUTION_DAYS:
            flags.append("caution")

        out.append({
            "pos": p, "id": position_id(p), "spot": spot, "dte": dte, "months": dte / 30.4,
            "bid": bid, "ask": ask, "mid": mid, "iv": iv, "delta": delta,
            "intrinsic": intrinsic, "extrinsic": (mid - intrinsic) if mid else None,
            "cost": cost, "value": value, "pnl": pnl, "pnl_pct": (pnl / cost) if (pnl is not None and cost) else None,
            "fx_entry": fx_entry, "fx_now": fx_now, "cost_gbp": cost_gbp, "value_gbp": value_gbp, "pnl_gbp": pnl_gbp,
            "stock_move": stock_move, "ott_bear": ott_bear, "above_200": above_200, "tier": tier,
            "flags": flags,
        })
    return out


def format_digest_lines(statuses):
    """Lines for the Telegram digest: one per position plus any exit prompts."""
    if not statuses:
        return []
    lines = ["\U0001f4bc <b>LEAP positions</b>"]
    for s in statuses:
        p = s["pos"]
        exp = datetime.strptime(p["expiry"], "%Y-%m-%d").strftime("%b %y")
        head = f"• {p['ticker']} ${p['strike']:g}C {exp}"
        if "error" in s:
            lines.append(f"{head} — {s['error']}")
            continue
        bits = [f"{s['months']:.0f}mo left"]
        cost_txt = f"cost ${s['cost']:,.0f}" + (f" (£{s['cost_gbp']:,.0f})" if s.get("cost_gbp") else "")
        bits.append(cost_txt)
        if s["mid"]:
            pnl_txt = f"{s['pnl_pct']:+.0%}, ${s['pnl']:+,.0f}" + (f" / £{s['pnl_gbp']:+,.0f}" if s.get("pnl_gbp") is not None else "")
            bits.append(f"mid ${s['mid']:.2f} vs ${float(p['entry_price']):.2f} in ({pnl_txt})")
        if s["delta"] is not None:
            bits.append(f"Δ{s['delta']:.2f}")
        if s["stock_move"] is not None:
            bits.append(f"stock {s['stock_move']:+.0%} since entry")
        if s["tier"]:
            bits.append(f"tier {s['tier']}")
        if s["ott_bear"]:
            bits.append("daily OTT bear")
        lines.append(f"{head} — " + " · ".join(bits))
        for f in s["flags"]:
            lines.append(f"   ⚠️ {RULE_LABEL[f]}")
    lines.append("")
    return lines


def format_alert(s, flag):
    p = s["pos"]
    exp = datetime.strptime(p["expiry"], "%Y-%m-%d").strftime("%b %y")
    body = [f"\U0001f4bc <b>LEAP exit rule: {p['ticker']} ${p['strike']:g}C {exp}</b>", RULE_LABEL[flag]]
    if s.get("mid"):
        gbp = f" / £{s['pnl_gbp']:+,.0f}" if s.get("pnl_gbp") is not None else ""
        body.append(f"Mid ${s['mid']:.2f} vs ${float(p['entry_price']):.2f} entry · P&L {s['pnl_pct']:+.0%} (${s['pnl']:+,.0f}{gbp}) · cost ${s['cost']:,.0f}" + (f" (£{s['cost_gbp']:,.0f})" if s.get("cost_gbp") else ""))
    extra = [f"{s['months']:.0f} months left"]
    if s.get("delta") is not None:
        extra.append(f"Δ{s['delta']:.2f}")
    if s.get("stock_move") is not None:
        extra.append(f"stock {s['stock_move']:+.0%} since entry")
    if s.get("tier"):
        extra.append(f"tier {s['tier']}")
    body.append(" · ".join(extra))
    return "\n".join(body)


def status_html(statuses):
    """Private-dashboard panel. Never included in the public page."""
    if not statuses:
        return ""
    rows = ""
    for s in statuses:
        p = s["pos"]
        exp = datetime.strptime(p["expiry"], "%Y-%m-%d").strftime("%b %y")
        if "error" in s:
            rows += f'<tr><td class="ticker">{p["ticker"]} ${p["strike"]:g}C {exp}</td><td colspan="8" class="error">{s["error"]}</td></tr>\n'
            continue
        flags = " ".join(f'<span class="leap-flag" style="color:#ff5252;border-color:#ff5252;" title="{RULE_LABEL[f]}">{f.replace("_", " ")}</span>' for f in s["flags"]) or '<span class="leap-flag" style="color:#00e676;border-color:#00e676;">hold</span>'
        gbp_pnl = f' / &pound;{s["pnl_gbp"]:+,.0f}' if s.get("pnl_gbp") is not None else ""
        pnl = (f'<span style="color:{"#00e676" if s["pnl"] >= 0 else "#ff5252"};font-weight:700;">{s["pnl_pct"]:+.0%}</span> <span class="fib-dt">${s["pnl"]:+,.0f}{gbp_pnl}</span>'
               if s["pnl"] is not None else '<span class="fib-dt">&mdash;</span>')
        outlay = f'${s["cost"]:,.0f}' + (f' / &pound;{s["cost_gbp"]:,.0f}' if s.get("cost_gbp") else "")
        mcol = "#ff5252" if s["dte"] <= ROLL_DAYS else ("#f0d060" if s["dte"] <= CAUTION_DAYS else "var(--ink)")
        dl = f'{s["delta"]:.2f}' if s["delta"] is not None else "&mdash;"
        dcol = "#ff5252" if (s["delta"] or 0) >= DELTA_EXIT else "var(--ink)"
        mv = f'{s["stock_move"]:+.0%}' if s["stock_move"] is not None else "&mdash;"
        mid = f'${s["mid"]:.2f} <span class="fib-dt">{s["bid"]:.2f}&ndash;{s["ask"]:.2f}</span>' if s["mid"] else "&mdash;"
        ott_html = ' · <span style="color:#ff5252;">OTT bear</span>' if s["ott_bear"] else ""
        rows += (f'<tr><td>{flags}</td><td class="ticker">{p["ticker"]} ${p["strike"]:g}C {exp}'
                 f'<span class="fib-sector">{p.get("account", "")}</span></td>'
                 f'<td>{int(p.get("contracts", 1))} @ ${float(p["entry_price"]):.2f} <span class="fib-dt">{p["entry_date"]}</span><br><span class="fib-dt">outlay {outlay}</span></td>'
                 f'<td>{mid}</td><td>{pnl}</td><td style="color:{mcol};">{s["months"]:.1f} mo</td>'
                 f'<td style="color:{dcol};">{dl}</td><td>${s["spot"]:.2f} <span class="fib-dt">{mv}</span></td>'
                 f'<td>{s["tier"] or "&mdash;"}{ott_html}</td></tr>\n')
    return f'''
    <h2 class="fib-title">LEAP Positions <span class="fib-sub">private view only &middot; exit rules: roll at 6 months, take profit at &Delta;0.90 or stock +40%, exit on OTT sell above the 200d or caution tier under 9 months</span></h2>
    <div class="leap-scroll"><table class="fib-table leap-table"><thead><tr>
      <th>Action</th><th>Contract</th><th>Entry</th><th>Mid &middot; bid&ndash;ask</th><th>P&amp;L</th><th>Left</th><th>Delta</th><th>Stock</th><th>Tier</th>
    </tr></thead><tbody>
{rows}</tbody></table></div>'''


if __name__ == "__main__":
    import sys
    sys.path.insert(0, SCRIPT_DIR)
    cfg = json.load(open(os.path.join(SCRIPT_DIR, "config.json")))
    st = evaluate(load_positions(), cfg)
    print("\n".join(format_digest_lines(st)) or "no positions")
