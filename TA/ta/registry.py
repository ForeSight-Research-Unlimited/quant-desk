"""Indicator registry -- the plumbing behind custom indicators.

You don't edit this file to add indicators; you edit `ta/library.py`. This just
defines the contract:

    An indicator is a function (df, **params) -> list[Plot].
    The @indicator decorator registers it with where/how it draws.

The server runs every registered indicator and ships generic plot data; the
frontend draws each plot into the price pane (overlay) or its own lower pane.
So adding an indicator is one function in library.py -- no server/JS changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class Plot:
    """One drawable series produced by an indicator.

    key:   unique id for this line (stable across reloads)
    label: shown on the chart legend
    data:  pandas Series aligned to the OHLCV index
    kind:  "line" or "histogram"
    color: hex string
    """
    key: str
    label: str
    data: pd.Series
    kind: str = "line"
    color: str = "#888888"


@dataclass
class IndicatorDef:
    id: str
    name: str
    func: Callable[..., list]
    pane: str          # "price" (overlay on candles) | "lower" (its own pane)
    default_on: bool
    defaults: dict     # default kwargs passed to func


_REGISTRY: dict[str, IndicatorDef] = {}


def indicator(name: str, *, pane: str = "lower", default_on: bool = True, **defaults):
    """Decorator: register an indicator function.

        @indicator(name="EMA Spread", pane="lower")
        def ema_spread(df, periods=(20, 50, 100, 200)):
            ...
            return [Plot("ema_spread", "EMA Spread", series, color="#f7dc6f")]

    pane:       "price" to overlay on the candles, "lower" for its own pane.
    default_on: whether it's enabled before the user touches anything.
    **defaults: default params forwarded to the function on each call.
    """
    if pane not in ("price", "lower"):
        raise ValueError(f"pane must be 'price' or 'lower', got {pane!r}")

    def deco(fn: Callable[..., list]) -> Callable[..., list]:
        ind_id = name.strip().lower().replace(" ", "_")
        _REGISTRY[ind_id] = IndicatorDef(ind_id, name, fn, pane, default_on, defaults)
        return fn

    return deco


def all_indicators() -> list[IndicatorDef]:
    return list(_REGISTRY.values())


def meta() -> list[dict]:
    """Lightweight description for the frontend (no computed data)."""
    return [
        {"id": d.id, "name": d.name, "pane": d.pane, "default_on": d.default_on}
        for d in _REGISTRY.values()
    ]
