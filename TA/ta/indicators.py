"""Indicator math for TA -- pure pandas, no plotting, no I/O.

This is the single source of truth for indicator calculations. The backtester
will import the same functions later (that's the Q4=A decision: own copy in TA
now, extract to a shared module when a second user appears).

Everything takes and returns pandas Series aligned to the input's index, so
callers can line results up against the OHLCV frame from `nsw.loader.load_data`.
"""

from __future__ import annotations

import pandas as pd


def ema(close: pd.Series, period: int) -> pd.Series:
    """Exponential moving average.

    Uses pandas' recursive EWM seeded with the first value (`adjust=False`),
    which is the standard "trading" EMA. (The old dashboard's JS seeded with an
    SMA of the first `period` bars; the two converge within a few bars and the
    difference is negligible for charts. When the backtester needs an exact
    convention we pin it here, in one place.)
    """
    return close.ewm(span=period, adjust=False).mean()


def derivative(series: pd.Series, order: int = 1) -> pd.Series:
    """n-th discrete difference of a series.

    order=1 -> rate of change (slope), order=2 -> acceleration. Leading values
    are NaN (no prior bar to diff against); the server drops those before
    sending to the chart.
    """
    out = series
    for _ in range(order):
        out = out.diff()
    return out


def relative_slope(series: pd.Series) -> pd.Series:
    """(x - x.shift(1)) / x -- the EMA Relative Slope signal from Project1.

    Kept here because it's KCF's thesis signal; the backtester will want the
    exact same definition. Not used by the barebones chart yet, but it lives
    where it belongs.
    """
    return series.diff() / series
