"""Incremental tail update.

Use this for routine refreshes — adds the bars since the last stored bar
without re-walking history.

Algorithm:
  1. Look up the latest stored timestamp for ``(symbol, interval)``.
  2. If nothing's stored yet, defer to ``backfill.backfill_symbol``.
  3. Otherwise, fetch from one bar after the latest stored timestamp up to
     today, in one or two chunks (we never need more than that for an update).
  4. Upsert. ``INSERT OR REPLACE`` means re-fetched bars overwrite cleanly,
     which we want — Fyers occasionally corrects historical bars after the
     fact.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from . import backfill, database, fyers_client, symbols

logger = logging.getLogger(__name__)


def _ts_to_datetime(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def update_symbol(symbol: str, interval: str) -> dict:
    """Top up the database for ``(symbol, interval)`` to today's latest bar.

    Returns ``{ "rows": int, "from": str|None, "to": str|None }``.
    If no bars existed before, this delegates to ``backfill_symbol``.
    """
    alias = symbols.resolve(symbol)
    fyers_sym = symbols.fyers_symbol(alias)

    latest_ts = database.get_latest_timestamp(alias, interval)
    if latest_ts is None:
        # First-time fetch — backfill from scratch.
        logger.info("[update %s %s] no existing bars — running full backfill.",
                    alias, interval)
        result = backfill.backfill_symbol(alias, interval)
        return {"rows": result["rows"], "from": None, "to": None,
                "via": "backfill"}

    last_dt = _ts_to_datetime(latest_ts)
    # Start the day of the last bar so we re-fetch any incomplete day,
    # which prevents a half-day-of-bars gap if the previous run stopped mid-day.
    from_d: date = last_dt.date()
    to_d:   date = datetime.now(tz=timezone.utc).date()

    if from_d > to_d:
        return {"rows": 0, "from": str(from_d), "to": str(to_d),
                "via": "noop"}

    rows = fyers_client.fetch_history(fyers_sym, interval, from_d, to_d)
    n = database.upsert_candles(alias, interval, rows)

    if rows:
        chunk_latest = int(rows[-1][0])
        database.set_backfill_state(alias, interval, latest_ts=chunk_latest)

    logger.info("[update %s %s] %s..%s -> %d rows", alias, interval,
                from_d, to_d, n)
    return {"rows": n, "from": str(from_d), "to": str(to_d), "via": "tail"}


def update_many(
    symbols_iter,
    intervals=("1m", "1d"),
) -> dict[str, dict[str, dict]]:
    """Run ``update_symbol`` across many symbols and intervals.

    A failure on one (symbol, interval) is captured into that pair's summary
    as ``{"error": "...", "rows": 0, ...}`` and the loop continues, so a
    transient Fyers issue on one symbol doesn't prevent the rest from updating.
    """
    out: dict[str, dict[str, dict]] = {}
    for sym in symbols_iter:
        out[sym] = {}
        for iv in intervals:
            try:
                out[sym][iv] = update_symbol(sym, iv)
            except Exception as e:
                logger.exception(
                    "Update of %s %s failed; continuing with remaining pairs.",
                    sym, iv,
                )
                out[sym][iv] = {
                    "error": str(e),
                    "rows": 0,
                    "from": None,
                    "to": None,
                    "via": "error",
                }
    return out
