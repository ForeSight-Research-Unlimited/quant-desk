"""Timeframe map + on-demand resampling.

NSW stores only ``1m`` and ``1d`` candles. Every other timeframe the user might
ask for is derived from one of those by ``DataFrame.resample(...)``.

Aggregation rules
-----------------
For each derived bar:
    open   = first 1m/1d open in the window
    high   = max  high
    low    = min  low
    close  = last close
    volume = sum  volume

These are the same rules every charting platform uses. Anything else (mean,
median) would silently corrupt the OHLC invariants.

Anchor rules
------------
Every resample is **closed-left, label-left**: a bar covers ``[t, t+Δ)`` and is
stamped with ``t``. That way if you ask for "5m bars from 09:15 to 10:00" you
get exactly nine bars: 09:15, 09:20, …, 09:55. (TradingView's default.)

Intraday bars are anchored to **NSE market open at 09:15 IST** (= 03:45 UTC).
Without this anchor, pandas defaults to UTC midnight (= 05:30 IST), which makes
1h bars land at 08:30, 09:30, 10:30 IST — off by 45 minutes from market open.
With the anchor, 1h bars land at 09:15, 10:15, ..., 15:15 IST; 2h at 09:15,
11:15, 13:15, 15:15; 4h at 09:15, 13:15; etc. All intraday timeframes line up
to market open instead of an arbitrary timezone artefact.

Weekly bars are anchored to Monday (``W-MON``) — the NSE convention.
Monthly/quarterly/half-yearly bars are anchored to the start of each calendar
month (``MS``); these are derived by stepping over the resampled monthly frame.
"""

from __future__ import annotations

import pandas as pd

# --- Public timeframe registry -------------------------------------------------

# Every timeframe NSW knows how to load. Keys are the user-facing aliases.
# Values are (base_interval, pandas_offset_or_step).
#
# - For sub-day frames the value is the pandas resample rule (e.g. "5min")
#   applied to the 1m table.
# - For 1d the value is None (no resampling needed).
# - For multi-day-but-sub-month frames the rule is the pandas alias applied
#   to the 1d table.
# - Multi-month frames (2Mo, 3Mo, 6Mo) are handled by ``_resample_multi_month``
#   instead of a plain pandas rule.

_INTRADAY_RULES: dict[str, str] = {
    "1m":  "1min",
    "2m":  "2min",
    "3m":  "3min",
    "5m":  "5min",
    "10m": "10min",
    "15m": "15min",
    "20m": "20min",
    "30m": "30min",
    "45m": "45min",
    "1h":  "60min",
    "90m": "90min",
    "2h":  "120min",
    "3h":  "180min",
    "4h":  "240min",
    "6h":  "360min",
    "8h":  "480min",
    "12h": "720min",
}
# NSE's regular session is 6h15m (09:15-15:30 IST), and intraday bars anchor to
# 09:15. So 8h and 12h collapse to ONE bar per trading day (the whole session) --
# effectively a daily bar timestamped at 09:15. They exist for symbols/sessions
# that run longer than 6h (added later). 6h is just under the session length, so
# each NSE day splits into a 6h bar (09:15-15:15) + a 15-minute stub (15:15-15:30).

_MULTIDAY_RULES: dict[str, str] = {
    "1d":  "1D",
    "2d":  "2D",
    "3d":  "3D",
    "1w":  "W-MON",   # week anchored to Monday — NSE-friendly
    "2w":  "2W-MON",
    "3w":  "3W-MON",
    "1Mo": "MS",      # month-start
}

# These need a step over the monthly frame because pandas has no built-in
# "every 2 months from month start" alias.
_MULTI_MONTH_STEPS: dict[str, int] = {
    "2Mo": 2,
    "3Mo": 3,
    "6Mo": 6,
    "12Mo": 12,
}

ALL_INTERVALS: tuple[str, ...] = (
    *_INTRADAY_RULES.keys(),
    *_MULTIDAY_RULES.keys(),
    *_MULTI_MONTH_STEPS.keys(),
)


def base_interval_for(interval: str) -> str:
    """Which stored base table feeds this user-facing timeframe."""
    if interval in _INTRADAY_RULES:
        return "1m"
    if interval in _MULTIDAY_RULES or interval in _MULTI_MONTH_STEPS:
        return "1d"
    raise ValueError(
        f"Unknown interval {interval!r}. "
        f"Known: {ALL_INTERVALS}"
    )


def is_known(interval: str) -> bool:
    """True iff ``interval`` is one of the registered timeframes."""
    return interval in ALL_INTERVALS


# --- Resample primitives -------------------------------------------------------

_OHLCV_AGG: dict[str, str] = {
    "open":   "first",
    "high":   "max",
    "low":    "min",
    "close":  "last",
    "volume": "sum",
}

# Anchor for sub-day resamples — see the module docstring.
# Any historical 09:15-IST moment works; pandas marches the grid forward from
# this point in fixed-width steps regardless of date. We pick 2017-01-02 09:15
# IST (a Monday, just for tidiness) and express it in UTC so the resample —
# which happens before tz_convert in loader.py — can use it directly.
_INTRADAY_ORIGIN_UTC = pd.Timestamp("2017-01-02 03:45:00", tz="UTC")


def _resample_with_rule(
    df: pd.DataFrame, rule: str, *, origin=None,
) -> pd.DataFrame:
    """Plain pandas resample, closed-left/label-left, OHLCV-correct.

    ``origin`` is forwarded to ``DataFrame.resample`` only when supplied —
    intraday rules pass ``_INTRADAY_ORIGIN_UTC`` so the grid lines up with
    NSE market open; daily/weekly/monthly rules leave it None to let pandas
    use its default (which is correct for those).
    """
    kwargs = dict(label="left", closed="left")
    if origin is not None:
        kwargs["origin"] = origin
    out = (
        df.resample(rule, **kwargs)
          .agg(_OHLCV_AGG)
          .dropna(subset=["open"])  # drop empty windows (weekends, halts)
    )
    return out


def _resample_multi_month(df: pd.DataFrame, step: int) -> pd.DataFrame:
    """Resample to 1 month, then keep every ``step``-th bar starting from the first.

    pandas has no built-in "every N months from month start" alias, so we lean on
    the monthly resample (which IS well-defined) and stride.
    """
    monthly = _resample_with_rule(df, "MS")
    if monthly.empty:
        return monthly
    return monthly.iloc[::step].copy()


def resample(df: pd.DataFrame, target_interval: str) -> pd.DataFrame:
    """Resample a base DataFrame (1m or 1d) into the target user-facing interval.

    The input must have a DatetimeIndex (UTC or naive — caller decides) and
    the columns ``open, high, low, close, volume``. If the target interval IS
    a base interval, the input is returned unchanged.
    """
    if df.empty:
        return df

    if target_interval == "1m" or target_interval == "1d":
        return df

    if target_interval in _INTRADAY_RULES:
        return _resample_with_rule(
            df, _INTRADAY_RULES[target_interval],
            origin=_INTRADAY_ORIGIN_UTC,
        )

    if target_interval in _MULTIDAY_RULES:
        return _resample_with_rule(df, _MULTIDAY_RULES[target_interval])

    if target_interval in _MULTI_MONTH_STEPS:
        return _resample_multi_month(df, _MULTI_MONTH_STEPS[target_interval])

    raise ValueError(f"Unknown interval {target_interval!r}")
