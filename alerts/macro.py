"""
Macro / cycle context — informational only, never fed into the favorability score.

Two parts:
  1. A hand-maintained `note` from config (e.g. where we are in the ~18-year real
     estate / Kuznets cycle and the business cycle) — judgment that can't be
     computed from price data.
  2. Auto-computed market-based business-cycle gauges from yfinance:
       - Yield curve: 10-year minus 3-month Treasury (inverted = classic recession
         lead indicator).
       - VIX: volatility / fear regime.

Unemployment and PMI (the other classic business-cycle indicators) live on FRED,
not yfinance, so they're left to the manual note rather than adding a dependency.
Like seasonality, all of this is a market-wide backdrop for risk posture / dry
powder — it does not rank names and does not touch the score.
"""

import yfinance as yf


def _last(ticker):
    h = yf.Ticker(ticker).history(period="5d", interval="1d")["Close"].dropna()
    return float(h.iloc[-1]) if len(h) else None


def yield_curve():
    """10Y − 3M Treasury spread (%), with a regime label. None on failure."""
    try:
        ten = _last("^TNX")   # 10-year yield, in percent
        three = _last("^IRX")  # 13-week T-bill, in percent
    except Exception:
        return None
    if ten is None or three is None:
        return None
    spread = ten - three
    if spread < 0:
        label, color = "inverted — recession lead", "#d97a6c"
    elif spread < 0.5:
        label, color = "flat", "#d4a866"
    else:
        label, color = "normal", "#5fb87a"
    return {"spread": spread, "label": label, "color": color}


def vix_level():
    """VIX with a volatility-regime label. None on failure."""
    try:
        v = _last("^VIX")
    except Exception:
        return None
    if v is None:
        return None
    if v < 20:
        label, color = "calm", "#5fb87a"
    elif v < 30:
        label, color = "elevated", "#d4a866"
    else:
        label, color = "stressed", "#d97a6c"
    return {"vix": v, "label": label, "color": color}


def macro_context(config):
    """Assemble the macro context: manual note + computed gauges. None if disabled."""
    cfg = config.get("macro", {})
    if not cfg.get("enabled", True):
        return None
    return {
        "note": cfg.get("note", ""),
        "curve": yield_curve(),
        "vix": vix_level(),
    }


def macro_takeaway(ctx):
    """Plain-English 'what this means' summary generated from the current gauges."""
    if not ctx:
        return ""
    curve, vix = ctx.get("curve"), ctx.get("vix")
    parts = []
    if vix:
        vl = vix["label"]
        parts.append({
            "calm": "markets are calm",
            "elevated": "markets are jittery",
            "stressed": "markets are fearful (for a long-term buyer, spikes like this are often good entry points)",
        }.get(vl, f"volatility is {vl}"))
    if curve:
        cl = curve["label"]
        if cl.startswith("inverted"):
            parts.append("the yield curve is inverted — the classic recession lead, typically 6–24 months ahead")
        elif cl == "flat":
            parts.append("the yield curve is flat, so watch for it inverting")
        else:
            parts.append("the yield curve isn't flagging a recession")

    # Posture from the most cautionary gauge
    if curve and curve["label"].startswith("inverted"):
        posture = "Lean cautious and hold reserve for a possible downturn."
    elif vix and vix["label"] == "stressed":
        posture = "This is when to consider deploying some dry powder into the fear."
    else:
        posture = "No acute stress — a normal backdrop for steady DCA; keep a little reserve for opportunities."

    body = "; ".join(parts)
    body = (body[0].upper() + body[1:] + ".") if body else ""
    return f"{body} {posture}".strip()


def macro_line(ctx):
    """One-line text for the Telegram digest."""
    if not ctx:
        return ""
    bits = []
    if ctx.get("curve"):
        c = ctx["curve"]
        bits.append(f"yield curve {c['spread']:+.1f}% ({c['label'].split(' — ')[0]})")
    if ctx.get("vix"):
        v = ctx["vix"]
        bits.append(f"VIX {v['vix']:.0f} ({v['label']})")
    gauges = " · ".join(bits)
    lines = []
    if gauges:
        lines.append(f"\U0001f30d Macro: {gauges}")
    takeaway = macro_takeaway(ctx)
    if takeaway:
        lines.append(f"→ {takeaway}")
    if ctx.get("note"):
        lines.append(f"Cycle: {ctx['note']}")
    return "\n".join(lines)


def macro_banner_html(ctx):
    """Context card for the dashboard (returns '' if unavailable)."""
    if not ctx:
        return ""
    gauges = []
    if ctx.get("curve"):
        c = ctx["curve"]
        gauges.append(
            f'Yield curve (10Y&minus;3M): <b style="color:{c["color"]};">{c["spread"]:+.2f}%</b> '
            f'<span style="color:{c["color"]};">{c["label"]}</span>')
    if ctx.get("vix"):
        v = ctx["vix"]
        gauges.append(
            f'VIX: <b style="color:{v["color"]};">{v["vix"]:.1f}</b> '
            f'<span style="color:{v["color"]};">{v["label"]}</span>')
    gauge_html = " &nbsp;&middot;&nbsp; ".join(gauges)
    takeaway = macro_takeaway(ctx)
    take_html = f'<div class="macro-take">&rarr; {takeaway}</div>' if takeaway else ""
    note_html = f'<div class="macro-note">Cycle: {ctx["note"]}</div>' if ctx.get("note") else ""
    return (
        f'<div class="macro-banner">'
        f'<span class="season-icon">&#127757;</span> <b>Macro context</b> &nbsp; {gauge_html}'
        f'{take_html}'
        f'{note_html}'
        f'</div>'
    )
