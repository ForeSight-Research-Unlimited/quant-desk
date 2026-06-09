"""Indicator definitions -- THIS is the file you edit to add indicators.

Write a function that takes the OHLCV DataFrame (columns: open/high/low/close/
volume, a DatetimeIndex) and returns a list of Plot(...). Decorate it with
@indicator(name=..., pane="price" | "lower"). Build the math from the primitives
in ta.indicators (or just write pandas inline). The chart picks it up
automatically -- no server or JS changes needed.

    @indicator(name="My Thing", pane="lower")
    def my_thing(df):
        series = df["close"].rolling(20).mean()      # any pandas you like
        return [Plot("my_thing", "My Thing", series, color="#abcdef")]

pane="price"  -> drawn on top of the candles (overlay)
pane="lower"  -> drawn in its own pane stacked below, with its own y-scale
Return several Plots to draw several lines (e.g. bands, or a line + histogram).
"""

from __future__ import annotations

import pandas as pd

from .indicators import derivative, ema
from .registry import Plot, indicator


@indicator(name="Trend State", pane="lower", default_on=True)
def ema_spread(df, periods=(20, 50, 100, 200)):
    """max(EMAs) - min(EMAs): how fanned-out the EMA ribbon is.

    Wide spread = strong trend (EMAs separated); near zero = EMAs coiled
    together (chop / regime change).
    """
    emas = pd.concat([ema(df["close"], p) for p in periods], axis=1)
    spread = emas.max(axis=1) - emas.min(axis=1)

    plots = [Plot("ema_spread", "EMA Spread", spread, color="#2962ff")]

    # EMA smoothings of the spread, each its own colour. Add/remove a line by
    # editing this map -- period: colour.
    spread_emas = {20: "#ba0e0e", 50: "#c66e07", 100: "#0b94c7", 200: "#ffffff"}
    for p, color in spread_emas.items():
        plots.append(Plot(f"EMAspread_{p}EMA", f"EMA Spread EMA{p}", ema(spread, p), color=color))

    return plots


@indicator(name="EMA Derivatives", pane="lower", default_on=False)
def ema_derivatives(df, period=20):
    """1st & 2nd derivative (slope & acceleration) of the EMA."""
    e = ema(df["close"], period)
    return [
        Plot("ema_d1", "EMA'", derivative(e, 1), color="#45b7d1"),
        Plot("ema_d2", "EMA''", derivative(e, 2), color="#bb8fce"),
    ]
