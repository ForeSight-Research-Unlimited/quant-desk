"""User preferences for TA -- colors, which EMAs are on, etc.

Persisted to ``TA/preferences.json`` so your chart looks the same across
restarts and browsers (the old dashboard kept this in SQLite; a JSON file is
simpler and matches NSW's config.json pattern). Writes are atomic
(tempfile + os.replace) so a crash mid-write can't corrupt the file.

This module is also the single source of truth for the EMA period list, so the
server and the defaults below can't drift.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile

# Overlay EMAs offered in the Indicators dropdown.
EMA_PERIODS = [10, 20, 50, 100, 200, 400]

# TA/preferences.json (this file is TA/ta/prefs.py -> up two levels = TA/).
PREFS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "preferences.json")

DEFAULT_PREFS = {
    "colors": {
        # main (price) pane
        "background": "#131722",
        "grid": "#1e2230",
        "candle_up": "#4ecdc4",
        "candle_down": "#e94560",
        # lower indicator panes -- themed independently of the main pane.
        # (Per-indicator line colors come from each indicator's definition in
        # library.py; these are just the pane background/grid.)
        "pane_background": "#131722",
        "pane_grid": "#1e2230",
        "ema": {
            "10": "#ff6b6b",
            "20": "#4ecdc4",
            "50": "#45b7d1",
            "100": "#ffa07a",
            "200": "#98d8c8",
            "400": "#f7dc6f",
        },
    },
    "ui": {
        "ema_on": [20, 50, 100, 200],
        # log price scale, default ON for both the main pane and lower panes.
        "log_main": True,
        "log_panes": True,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    """Recursively overlay `over` onto a copy of `base` (dicts only)."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_prefs() -> dict:
    """Return saved prefs deep-merged over the defaults (defaults fill any gaps).

    A missing or corrupt file degrades gracefully to defaults rather than
    erroring -- prefs are cosmetic, never worth a 500.
    """
    if not os.path.exists(PREFS_PATH):
        return copy.deepcopy(DEFAULT_PREFS)
    try:
        with open(PREFS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_PREFS)
    return _deep_merge(DEFAULT_PREFS, saved)


def save_prefs(incoming: dict) -> dict:
    """Merge `incoming` over current prefs, write atomically, return the result."""
    merged = _deep_merge(load_prefs(), incoming or {})
    directory = os.path.dirname(PREFS_PATH) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".preferences.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        os.replace(tmp, PREFS_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return merged
