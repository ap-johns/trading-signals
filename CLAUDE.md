# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated trading alert system for a no-stop, buy-and-hold DCA accumulator. Monitors 24 tickers (17 stocks, 3 indices, 3 crypto, 1 FX reference) using the OTT (Optimized Trend Tracker) indicator plus fib-retracement, z-score and cycle-based dip detection. Sends Telegram alerts and generates an HTML dashboard on GitHub Pages. Runs daily via GitHub Actions at 17:00 UTC (Mon-Fri).

The daily **DCA digest** is the primary output — a ranked, tiered list of what's worth buying today. Individual signal alerts are secondary, and are deliberately kept sparse so the digest stays the thing you read.

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Run signal checker (SENDS TELEGRAM ALERTS + writes cycle_state.json)
python alerts/signal_checker.py

# Regenerate public dashboard
python alerts/dashboard.py

# Private dashboard with Trading 212 holdings (local only, gitignored)
python alerts/dashboard.py --private

# DCA ranking table (no side effects)
python alerts/dca_rank.py

# Run backtest (on-demand, not automated)
python alerts/backtest.py
```

Requires `.env` in `alerts/` with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (or as environment variables). `T212_KEY_ID` / `T212_API_SECRET` are needed only for `--private`.

**No test suite exists.** `backtest.py` serves as manual strategy validation. To verify changes to `signal_checker.py` without sending Telegram messages or mutating committed state, monkeypatch `send_telegram` and `save_cycle_state` to no-ops and call `check_signals(config)` directly — do not just run the script.

## Architecture

Python modules in `alerts/`, no external web framework:

- **indicators.py** — OTT calculation (VAR + trailing stop), EMA/SMA helpers, `calculate_fib_levels` (weekly swing detection), `atr_levels` (IA accumulation bands). The VAR calculation replicates TradingView's Pine Script exactly; OTT signals use `OTT[2]` (a 2-bar shift) and fire on **crossover only**.
- **signal_checker.py** — Main alert entry point. Fetches via yfinance, detects signals, sends Telegram, maintains `cycle_state.json`. Also sends the daily DCA digest.
- **dashboard.py** — Generates self-contained `docs/index.html` (inline CSS/JS). `--private` overlays Trading 212 holdings into gitignored `local-dashboard.html`. Computes its own indicators; does **not** import from `signal_checker.py`.
- **dca_rank.py** — Ranks tickers by DCA favorability; backs the digest and `/js:dca-review`.
- **fib_score.py** — Shared scoring (`favorability`, `tier`, `level_reached`, `fib_params`, `rank_key`) so dashboard and digest never drift apart.
- **backtest.py** — Historical strategy simulation vs buy-and-hold. Carries its **own** copies of strategy rules (including the index 5% dip buy-back) — intentionally independent of what is alerted on.
- **broker.py** — Read-only Trading 212 access. Degrades to `None` if credentials are absent.
- **macro.py**, **seasonality.py** — Informational context banners only. Deliberately **not** fed into the favorability score.

## Strategy Types

Each asset class has distinct entry/exit logic — not one unified strategy. Note that **what is backtested is broader than what is alerted on**:

| | Backtest / dashboard model | Alerted on |
|---|---|---|
| **Stocks** | Buy on OTT or 50 SMA cross; sell on OTT above 200 SMA | Buy on OTT only |
| **Indices** | Always-in; sell on OTT, buy back on OTT or 5% dip | Same (dip deduped) |
| **Crypto** | Buy in cycle windows or dips below 200w EMA; sell ~1mo before projected peak | Same |

## Alert Inventory

Alerts fire on `alert_timeframes` (currently `daily` only — 4h/weekly OTT are dashboard-only). Categories in `alert_exclude_categories` (currently `FX`) are shown on the dashboard but never alerted.

Active buy triggers (~85 armed thresholds total):

| Trigger | Scope | Levels | Dedupe |
|---|---|---|---|
| OTT buy crossover | all 23 alerted | — | cross-only |
| Index 5% dip from last sell | indices | −5% vs last sell | state; see below |
| Z-score below 200d SMA | stocks + indices | −2.5σ/−3.0σ | state; re-arms at −0.5σ (`reset_band`) |
| Crypto cycle buy window | crypto | — | state |
| Below 200w EMA | crypto | −10/−20/−30% | state; resets above EMA |
| Analyst buy level | `analyst_levels.json` | per ticker | state + re-arm |
| Weekly fib retracement | stocks + indices | .382/.5/.618/.786 | **disabled** (`fib_alerts.enabled: false`) |
| IA accumulation bands | stocks | L5/L4/L3 | **disabled** (`ia_level_alerts.enabled: false`) |

Sells: OTT sell above 200 SMA (stocks/crypto), any OTT sell (indices), crypto cycle-peak warning (armed ~1 month before `crypto_cycle.sell_date`).

### The index dip buy-back

The always-in buy-back leg is alerted, but guarded three ways (it used to re-fire every single day price sat below the threshold):

1. Deduped via `index_dip_alerted` / `index_dip_ref` in `cycle_state.json` — fires once per sell reference.
2. Re-arms only when price closes back **above** the threshold.
3. Suppressed entirely once an OTT buy occurs after the reference sell — you're back in, so the dip reference is spent.

### Removed on purpose — do not reinstate without asking

Cut in Aug 2026 for alert fatigue. Their signal is already folded into the DCA favorability score, which reads the same inputs (fib fraction, z-score, 50d distance/direction, 200d/200w distance, weekly OTT):

- `N% below 200d SMA` stock dips (5/10/15/20/25/30%) — was 102 thresholds, the single largest noise source.
- Standalone `crossed above 50 SMA` buy.
- The `−2.0σ` z-score level.
- Weekly fib pings (80 thresholds) — the digest already prints the fib level and retrace % per pick.
- The "no signals detected" daily heartbeat — the DCA digest already proves the run happened.

## The digest tier filter

`in_digest()` in `signal_checker.py` decides which ranked rows reach Telegram. It exists because `favoured` and `cheap_shallow` both require `z <= -0.75`, so an intact-trend name sitting in the golden pocket whose z-score hadn't gone cheap appeared **nowhere** in Telegram once the fib pings were switched off.

- `favoured`, `cheap_shallow` — always shown (🟢 / 🟡)
- `quality_not_cheap` — shown **only** at fib level >= `GOLDEN_POCKET` (0.5) (🔵). The level gate matters: without it this tier matches nearly every name in an uptrend. A 0.382 retrace is deliberately excluded as too shallow.
- `caution`, `broken` — never shown. Trend rolling over, below the 200d, or retraced past the swing low. Excluded by design; do not "fix" this.

Widening this filter is the correct way to surface more setups — it costs no extra notifications, since the digest sends daily regardless. Re-enabling per-level pings is not.

When adding a level-based trigger, persist fired levels in `cycle_state.json` with an explicit re-arm condition. A bare previous-bar cross check is not enough: price oscillating around a threshold re-fires indefinitely.

## Key Files

- `alerts/config.json` — All parameters: OTT period/percent, EMA period, timeframes, `alert_exclude_categories`, z-score/fib/DCA/IA alert settings, sectors, dry-powder sizing rules, macro note, crypto cycle windows with per-ticker overrides, watchlist
- `alerts/cycle_state.json` — Persistent dedupe state per ticker (`zscore_neg`, `index_dip_alerted`, `index_dip_ref`, `alerted_levels`, `analyst_alerted`, `window_alerted`, `sell_alerted`, plus now-dormant `fib_alerted` / `fib_swing_high`). Committed by CI. Stale entries for de-configured levels are harmless — loops only iterate configured levels. Nothing outside `signal_checker.py` reads this file.
- `alerts/analyst_levels.json` — Analyst buy levels (Jacob @ Invest Answers), refreshed via `/js:invest-answers-jacob`
- `docs/index.html` — Generated public dashboard (committed by CI, served by GitHub Pages)
- `local-dashboard.html` — Private holdings view, **gitignored, never commit**
- `.github/workflows/update.yml` — CI: runs signal_checker then dashboard, commits results back

## Slash Commands

- `/js:dca-review` — rank tickers by DCA favorability and explain the picks
- `/js:invest-answers-jacob` — load Jacob's weekly buy levels into `analyst_levels.json`
- `/js:private-dashboard` — build the local dashboard with Trading 212 holdings

## Data Flow

```
config.json → yfinance fetch → OTT / fib / z-score / cycle detection
                                   ├→ Telegram signal alerts (sparse)
                                   ├→ Telegram DCA digest (daily, primary)
                                   ├→ cycle_state.json update
                                   └→ docs/index.html regeneration
```
