"""
OTT (Optimized Trend Tracker) indicator implementation.

Exact replication of TradingView Pine Script by KivancOzbilgic.
Source: https://www.tradingview.com/script/zVhoDQME/
"""

import pandas as pd
import numpy as np


def calculate_var(src: pd.Series, length: int) -> pd.Series:
    """
    VAR (Variable Index Dynamic Average) - exact Pine Script replication.

    Pine Script:
        valpha = 2/(length+1)
        vud1 = src > src[1] ? src - src[1] : 0
        vdd1 = src < src[1] ? src[1] - src : 0
        vUD = sum(vud1, 9)
        vDD = sum(vdd1, 9)
        vCMO = nz((vUD - vDD) / (vUD + vDD))
        VAR = nz(valpha * abs(vCMO) * src) + (1 - valpha * abs(vCMO)) * nz(VAR[1])
    """
    valpha = 2.0 / (length + 1)

    # Up/down differences
    diff = src.diff()
    vud1 = diff.clip(lower=0)
    vdd1 = (-diff).clip(lower=0)

    # Rolling 9-period sums (matching Pine's sum(vud1, 9))
    vUD = vud1.rolling(window=9, min_periods=1).sum()
    vDD = vdd1.rolling(window=9, min_periods=1).sum()

    # CMO
    total = vUD + vDD
    vCMO = pd.Series(0.0, index=src.index, dtype=float)
    mask = total != 0
    vCMO[mask] = ((vUD[mask] - vDD[mask]) / total[mask]).abs()

    # VAR - recursive calculation
    var_out = pd.Series(0.0, index=src.index, dtype=float)
    for i in range(1, len(src)):
        alpha_cmo = valpha * vCMO.iloc[i]
        var_out.iloc[i] = alpha_cmo * src.iloc[i] + (1 - alpha_cmo) * var_out.iloc[i - 1]

    return var_out


def calculate_ott(src: pd.Series, period: int = 10, percent: float = 3.0) -> pd.DataFrame:
    """
    Calculate OTT (Optimized Trend Tracker).

    Exact replication of KivancOzbilgic's Pine Script:
    - MAvg = VAR(src, period)
    - Trailing stop (MT) with long_stop / short_stop
    - OTT = MT adjusted by percent
    - Buy signal: MAvg crosses above OTT[2]
    - Sell signal: MAvg crosses below OTT[2]

    Returns DataFrame with columns: mavg, ott, signal
    """
    mavg = calculate_var(src, period)

    fark = mavg * percent * 0.01

    # Trailing stop calculation
    long_stop = mavg - fark
    short_stop = mavg + fark

    direction = pd.Series(1, index=src.index, dtype=int)
    long_stop_final = long_stop.copy()
    short_stop_final = short_stop.copy()

    for i in range(1, len(src)):
        # Long stop: only ratchets up
        prev_long = long_stop_final.iloc[i - 1]
        if mavg.iloc[i] > prev_long:
            long_stop_final.iloc[i] = max(long_stop.iloc[i], prev_long)
        else:
            long_stop_final.iloc[i] = long_stop.iloc[i]

        # Short stop: only ratchets down
        prev_short = short_stop_final.iloc[i - 1]
        if mavg.iloc[i] < prev_short:
            short_stop_final.iloc[i] = min(short_stop.iloc[i], prev_short)
        else:
            short_stop_final.iloc[i] = short_stop.iloc[i]

        # Direction
        prev_dir = direction.iloc[i - 1]
        if prev_dir == -1 and mavg.iloc[i] > short_stop_final.iloc[i - 1]:
            direction.iloc[i] = 1
        elif prev_dir == 1 and mavg.iloc[i] < long_stop_final.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = prev_dir

    # MT (middle trend)
    mt = pd.Series(0.0, index=src.index, dtype=float)
    for i in range(len(src)):
        mt.iloc[i] = long_stop_final.iloc[i] if direction.iloc[i] == 1 else short_stop_final.iloc[i]

    # OTT line (adjusted by percent)
    ott = pd.Series(0.0, index=src.index, dtype=float)
    for i in range(len(src)):
        if mavg.iloc[i] > mt.iloc[i]:
            ott.iloc[i] = mt.iloc[i] * (200 + percent) / 200
        else:
            ott.iloc[i] = mt.iloc[i] * (200 - percent) / 200

    # Pine Script uses OTT[2] for signals (2-bar shift)
    ott_shifted = ott.shift(2)

    # Detect crossover signals: MAvg vs OTT[2]
    signal = pd.Series(0, index=src.index, dtype=int)
    for i in range(3, len(src)):
        prev_mavg_above = mavg.iloc[i - 1] > ott_shifted.iloc[i - 1]
        curr_mavg_above = mavg.iloc[i] > ott_shifted.iloc[i]
        prev_mavg_below = mavg.iloc[i - 1] < ott_shifted.iloc[i - 1]
        curr_mavg_below = mavg.iloc[i] < ott_shifted.iloc[i]

        if pd.notna(ott_shifted.iloc[i]) and pd.notna(ott_shifted.iloc[i - 1]):
            if curr_mavg_above and not prev_mavg_above:
                signal.iloc[i] = 1  # Buy
            elif curr_mavg_below and not prev_mavg_below:
                signal.iloc[i] = -1  # Sell

    return pd.DataFrame({
        "mavg": mavg,
        "ott": ott_shifted,  # Use the shifted version (matching TradingView display)
        "signal": signal,
    }, index=src.index)


def calculate_ema(close: pd.Series, period: int = 200) -> pd.Series:
    """Standard EMA calculation."""
    return close.ewm(span=period, adjust=False).mean()


def calculate_sma(close: pd.Series, period: int = 200) -> pd.Series:
    """Standard SMA calculation."""
    return close.rolling(window=period, min_periods=period).mean()


def calculate_fib_levels(
    high: pd.Series,
    low: pd.Series,
    lookback: int = 252,
    min_gain: float = 0.30,
    ratios=(0.382, 0.5, 0.618, 0.786),
):
    """
    Detect the dominant uptrend within the last `lookback` bars and return its
    Fibonacci retracement levels.

    The uptrend is defined as the lowest low preceding (on or before) the highest
    high in the window — i.e. the launch point of the move up to its peak. The
    setup only qualifies if the rise from swing low to swing high is at least
    `min_gain` (fractional, e.g. 0.30 = 30%).

    Returns a dict:
        {
            "swing_high": float,
            "swing_low": float,
            "swing_high_date": index label of the swing high bar,
            "swing_low_date": index label of the swing low bar,
            "gain": float,               # fractional rise, e.g. 0.45
            "levels": {ratio: price, ...} # retracement price per ratio
        }
    or None if there is no qualifying uptrend (not enough data or gain too small).
    """
    high = high.dropna()
    low = low.dropna()
    if len(high) < 2 or len(low) < 2:
        return None

    high_window = high.iloc[-lookback:]
    low_window = low.iloc[-lookback:]

    swing_high = high_window.max()
    idx_high = high_window.idxmax()

    # Lowest low on/before the swing high (the launch point of the uptrend)
    low_before_high = low_window.loc[:idx_high]
    if low_before_high.empty:
        return None
    swing_low = low_before_high.min()
    idx_low = low_before_high.idxmin()

    if swing_low <= 0 or swing_high <= swing_low:
        return None

    gain = (swing_high - swing_low) / swing_low
    if gain < min_gain:
        return None

    span = swing_high - swing_low
    levels = {r: swing_high - r * span for r in ratios}

    return {
        "swing_high": float(swing_high),
        "swing_low": float(swing_low),
        "swing_high_date": idx_high,
        "swing_low_date": idx_low,
        "gain": float(gain),
        "levels": {r: float(p) for r, p in levels.items()},
    }
