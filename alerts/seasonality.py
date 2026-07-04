"""
Empirical S&P 500 monthly seasonality — informational context only.

Seasonality is a weak, market-wide tilt (it hits every ticker roughly the same, so
it can't rank names against each other) and timing DCA by season partly defeats the
point of DCA. So this is surfaced as *context* for sizing/patience — a banner on the
dashboard and a line in the weekly digest — and deliberately does NOT feed the
favorability score.
"""

import yfinance as yf

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
STRONG_WINDOW = {11, 12, 1, 2, 3, 4}  # Nov–Apr "best six months"


def _month_stats():
    """Average monthly % return and win-rate for the S&P 500, by calendar month."""
    close = yf.Ticker("^GSPC").history(period="max", interval="1mo")["Close"].dropna()
    ret = (close.pct_change().dropna() * 100)
    stats = {}
    for m in range(1, 13):
        r = ret[ret.index.month == m]
        if len(r):
            stats[m] = {"avg": float(r.mean()), "win": float((r > 0).mean() * 100)}
    return stats, int(close.index[0].year)


def seasonality_context(month):
    """Context for the given calendar month (1-12). Returns None on failure."""
    try:
        stats, since = _month_stats()
    except Exception:
        return None
    if month not in stats:
        return None

    # Rank-based label: 3 weakest months -> weak, 4 strongest -> strong, else average.
    ranked = sorted(stats, key=lambda m: stats[m]["avg"])
    weak = set(ranked[:3])
    strong = set(ranked[-4:])
    label = "weak" if month in weak else "strong" if month in strong else "average"

    window = ("Nov–Apr strong window" if month in STRONG_WINDOW
              else "May–Oct softer window")
    return {
        "month": MONTHS[month - 1],
        "avg": stats[month]["avg"],
        "win": stats[month]["win"],
        "label": label,
        "window": window,
        "since": since,
    }


def seasonality_line(ctx):
    """One-line plain/HTML text for the Telegram digest."""
    if not ctx:
        return ""
    return (f"\U0001f4c5 Seasonality: {ctx['month']} avg {ctx['avg']:+.1f}% "
            f"({ctx['win']:.0f}% positive) — {ctx['label']} month, {ctx['window']}")


def seasonality_banner_html(ctx):
    """Subtle context card for the dashboard (returns '' if unavailable)."""
    if not ctx:
        return ""
    color = {"weak": "#d97a6c", "strong": "#5fb87a"}.get(ctx["label"], "#a8a59c")
    return (
        f'<div class="season-banner">'
        f'<span class="season-icon">&#128197;</span> '
        f'<b>Seasonality</b> (S&amp;P 500, since {ctx["since"]}): '
        f'{ctx["month"]} avg <b style="color:{color};">{ctx["avg"]:+.1f}%</b> '
        f'({ctx["win"]:.0f}% positive) &middot; '
        f'<span style="color:{color};">{ctx["label"]} month</span> &middot; {ctx["window"]}. '
        f'<span class="season-note">Market-wide tilt &mdash; context for sizing, not a ranking factor.</span>'
        f'</div>'
    )
