"""Public load API — the one module the rest of Quant Desk should import.

Three things here:

* ``load_data(symbol, interval, ...)`` — return a pandas DataFrame for any of
  the registered timeframes, optionally updating the local store first.
* ``export_csv(symbol, interval, path, ...)`` — write that DataFrame to disk.
* ``get_coverage(symbols, intervals)`` — quick "what do we have stored?" report
  used by the setup page.

This is the only module that knows how to compose database lookups, resampling,
and (optionally) tail updates into a single user-facing call.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Iterable

import pandas as pd

from . import database, symbols, timeframes, update

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Default timezone
# ------------------------------------------------------------------
# Loaded DataFrames have their DatetimeIndex converted to this timezone
# unless the caller passes a different ``tz=`` to ``load_data``.
#
# We default to Asia/Kolkata because NSW currently serves Indian-market
# instruments (NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY). If you ever
# move NSW to a different market, change this one constant — every load
# call that doesn't override ``tz`` will follow.
#
# To get raw UTC for a single call, pass ``tz="UTC"``.
DEFAULT_TZ: str = "Asia/Kolkata"


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _coerce_to_date(d) -> date | None:
    """Accept str / date / datetime / None and return a ``date`` or None."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        return datetime.strptime(d, "%Y-%m-%d").date()
    raise TypeError(f"Cannot coerce {d!r} to date")


# Seconds-from-midnight to the very last second of the same UTC day.
# Used to extend `to_date` end-of-day inclusive when slicing the candle table.
_END_OF_DAY_SECONDS: int = 86399  # 24 * 3600 - 1


# NSE continuous-trading session bounds, in minutes-from-midnight IST. The
# market opens 09:15 = 555 min; the last 1m bar of a regular session is
# stamped 15:29 = 929 min (closed-left labelling — the 15:29 bar covers
# 15:29:00-15:29:59 IST, and 15:30 itself is the close boundary, not a bar).
# These bounds are also correct for any intraday timeframe anchored at
# market open: 1h bars 09:15..15:15, 4h bars 09:15/13:15, etc. — their
# timestamps all fall inside [555, 929].
_NSE_SESSION_OPEN_MIN: int = 555
_NSE_SESSION_LAST_BAR_MIN: int = 929


def _date_to_ts(d: date) -> int:
    """Calendar date -> epoch seconds (UTC, midnight)."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def _rows_to_frame(rows: list[dict]) -> pd.DataFrame:
    """Convert SQLite rows to a tidy DataFrame indexed by UTC datetime.

    Even when there are no rows we still return a DataFrame with a tz-aware
    (UTC) empty DatetimeIndex so downstream code can call
    ``df.index.tz_convert(...)`` without special-casing the empty case.
    """
    if not rows:
        return pd.DataFrame(
            columns=_OHLCV_COLUMNS,
            index=pd.DatetimeIndex([], tz="UTC", name=None),
        )
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.set_index("timestamp").sort_index()
    df.index.name = None  # cleaner display
    return df[_OHLCV_COLUMNS]


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def load_data(
    symbol: str,
    interval: str,
    from_date=None,
    to_date=None,
    *,
    update: bool = False,
    tz: str | None = None,
    session_only: bool = False,
) -> pd.DataFrame:
    """Return OHLCV candles for ``(symbol, interval)`` as a DataFrame.

    Args:
        symbol: NSW alias (``"NIFTY"``, ``"BANKNIFTY"``, etc.) — case-insensitive,
            also accepts known alternative spellings.
        interval: one of the registered timeframes, e.g. ``"5m"``, ``"1h"``,
            ``"1d"``, ``"3Mo"``. See ``nsw.timeframes.ALL_INTERVALS``.
        from_date / to_date: inclusive date bounds. Strings (``"YYYY-MM-DD"``),
            ``date``, ``datetime``, or None for "no bound".
        update: if True, run an incremental tail update for the appropriate
            base interval before reading. Use this when you want fresh bars.
        tz: IANA timezone string to convert the index to. If left as None,
            the module-level ``DEFAULT_TZ`` is used (currently ``Asia/Kolkata``,
            change it at the top of this file for a different default).
            Pass ``tz="UTC"`` explicitly to get raw UTC.
        session_only: when True and the requested interval derives from the
            1m base (any intraday timeframe), restrict the returned bars to
            NSE's regular continuous-trading session, 09:15-15:29 IST
            inclusive under closed-left labelling. Drops Fyers archive
            artefacts like the 2017 pre-open snapshot bars, the annual
            Diwali Muhurat session, and any other out-of-session bars
            Fyers emits. For 1d / weekly / monthly intervals (derived from
            the 1d base) this flag is a no-op — those bars are
            day-stamped, not time-of-day-stamped. Default False, i.e. the
            DataFrame is returned exactly as Fyers archived it.

    Returns:
        DataFrame indexed by tz-aware datetime, with columns
        ``open, high, low, close, volume``. Empty DataFrame if no data.
    """
    alias = symbols.resolve(symbol)

    if not timeframes.is_known(interval):
        raise ValueError(
            f"Unknown interval {interval!r}. "
            f"Valid: {timeframes.ALL_INTERVALS}"
        )
    base_interval = timeframes.base_interval_for(interval)

    if update:
        from . import update as update_mod  # avoid name clash with kwarg
        update_mod.update_symbol(alias, base_interval)

    fd = _coerce_to_date(from_date)
    td = _coerce_to_date(to_date)
    rows = database.get_candles(
        alias, base_interval,
        from_ts=_date_to_ts(fd) if fd else None,
        to_ts=_date_to_ts(td) + _END_OF_DAY_SECONDS if td else None,
    )
    df = _rows_to_frame(rows)

    # Resample if we're asking for a derived timeframe. Pandas handles an
    # empty input gracefully (returns an empty resampled frame with the same
    # tz-aware index), so we don't need a special case.
    if interval != base_interval:
        df = timeframes.resample(df, interval)

    # Apply timezone uniformly. Explicit kwarg wins; otherwise the module
    # default. tz_convert on an empty tz-aware index is a cheap no-op.
    effective_tz = tz if tz is not None else DEFAULT_TZ
    if effective_tz:
        df.index = df.index.tz_convert(effective_tz)

    # Optional NSE-session filter. We always compute the time-of-day in IST
    # regardless of the user's chosen tz so the bounds stay semantically
    # correct ("09:15 IST" doesn't move if the caller asked for UTC output).
    if session_only and base_interval == "1m" and not df.empty:
        ist_idx = df.index.tz_convert("Asia/Kolkata")
        tod_min = ist_idx.hour * 60 + ist_idx.minute
        mask = (tod_min >= _NSE_SESSION_OPEN_MIN) & (tod_min <= _NSE_SESSION_LAST_BAR_MIN)
        df = df[mask]

    return df


def export_csv(
    symbol: str,
    interval: str,
    path: str,
    from_date=None,
    to_date=None,
    *,
    update: bool = False,
    tz: str | None = None,
    session_only: bool = False,
) -> str:
    """``load_data`` followed by ``DataFrame.to_csv(path)``. Returns the path."""
    df = load_data(
        symbol, interval, from_date, to_date,
        update=update, tz=tz, session_only=session_only,
    )
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    df.to_csv(path)
    logger.info("Wrote %d rows of %s %s -> %s", len(df), symbol, interval, path)
    return path


def get_coverage(
    symbols_iter: Iterable[str] | None = None,
    intervals: Iterable[str] = database.BASE_INTERVALS,
) -> list[dict]:
    """Return per-(symbol, base-interval) coverage stats.

    Used by the setup page to render a "what's stored" table. By default
    reports both base intervals across all known indices.
    """
    if symbols_iter is None:
        symbols_iter = symbols.all_aliases()
    return database.coverage_summary(list(symbols_iter), list(intervals))
