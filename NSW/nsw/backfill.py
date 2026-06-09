"""Chunked historical backfill.

Strategy
--------
Fyers limits a single history call to ``MAX_DAYS_PER_CALL[interval]`` days
(100 for 1m, 366 for 1d). To pull years of history we walk **backwards** from
today in chunks of that size, upserting each chunk as we go.

We stop when:
  * Fyers returns an empty chunk (we've gone past the API's earliest-available
    date), OR
  * we hit a hard ``earliest_floor`` we've already discovered for this symbol
    (persisted in ``backfill_state.api_floor_ts``), OR
  * ``max_chunks`` is reached (a safety cap so a misconfigured backfill can't
    burn the entire daily API budget).

Going backwards, not forwards, matters: it lets us see how deep the API goes
without having to know the date in advance, and it makes "stop early" cheap.

Incremental top-up — fetching only bars after the latest stored bar — lives in
``update.py``, which is the right tool for routine refreshes. Use this module
for first-time fills.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from . import database, fyers_client, symbols

logger = logging.getLogger(__name__)


def _ts_to_date(ts: int) -> date:
    """Epoch seconds -> calendar date (UTC)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).date()


def _chunk_count_estimate(years: float, days_per_chunk: int) -> int:
    """Rough estimate of how many chunks an N-year backfill will take."""
    return int((years * 365.25) / days_per_chunk) + 1


def backfill_symbol(
    symbol: str,
    interval: str,
    *,
    max_chunks: int = 100,
    chunk_pause_seconds: float = 0.25,
    progress_cb=None,
) -> dict:
    """Walk backwards from today, fetching one chunk at a time, until empty.

    Args:
        symbol: NSW alias (e.g. ``"NIFTY"``) — resolved to a Fyers symbol.
        interval: ``"1m"`` or ``"1d"``.
        max_chunks: hard upper bound on chunks fetched in one call. Safety
            against runaway loops or API misbehaviour.
        chunk_pause_seconds: brief pause between chunks to be polite to the
            rate limiter.
        progress_cb: optional ``callable(state_dict)`` invoked after every
            chunk for the setup-page UI. Passed:
                ``{ "chunk": int, "from": "YYYY-MM-DD", "to": "YYYY-MM-DD",
                    "rows": int, "total_rows": int }``

    Returns:
        Summary dict ``{ "chunks": int, "rows": int, "earliest_ts": int|None }``.
    """
    alias = symbols.resolve(symbol)
    fyers_sym = symbols.fyers_symbol(alias)
    days_per_chunk = fyers_client.MAX_DAYS_PER_CALL[interval]

    state = database.get_backfill_state(alias, interval) or {}
    api_floor_ts = state.get("api_floor_ts")

    # Walk backwards starting from today; stop when we hit an empty chunk
    # (= past API's earliest-available) or when we've already found the floor.
    end_d: date = datetime.now(tz=timezone.utc).date()
    total_rows = 0
    chunks_done = 0
    earliest_seen_ts: int | None = state.get("earliest_ts")

    for chunk_idx in range(1, max_chunks + 1):
        start_d = end_d - timedelta(days=days_per_chunk - 1)

        # If we already know the API floor, don't go beyond it.
        if api_floor_ts is not None:
            api_floor_d = _ts_to_date(api_floor_ts)
            if start_d < api_floor_d:
                start_d = api_floor_d
            if start_d > end_d:
                # Already past the floor — nothing left to fetch.
                logger.info(
                    "[backfill %s %s] reached known API floor %s — stopping.",
                    alias, interval, api_floor_d,
                )
                break

        rows = fyers_client.fetch_history(
            fyers_sym, interval, start_d, end_d,
        )
        chunks_done += 1

        if not rows:
            # Empty chunk = we've gone past Fyers' earliest-available.
            # Persist that floor so future backfills don't rediscover it.
            if earliest_seen_ts is not None:
                # We've successfully fetched some bars. Floor = the oldest of
                # those (one bar earlier would be empty by definition).
                floor_ts = earliest_seen_ts
            else:
                # First chunk returned empty -- Fyers has NOTHING for this pair.
                # Record the floor as tomorrow so the next backfill run skips
                # this range entirely instead of burning another API call.
                floor_d = end_d + timedelta(days=1)
                floor_ts = int(datetime(floor_d.year, floor_d.month, floor_d.day,
                                        tzinfo=timezone.utc).timestamp())
            database.set_backfill_state(
                alias, interval, api_floor_ts=floor_ts,
            )
            logger.info(
                "[backfill %s %s] empty chunk at [%s..%s] — API floor recorded.",
                alias, interval, start_d, end_d,
            )
            if progress_cb:
                progress_cb({
                    "chunk": chunk_idx, "from": str(start_d), "to": str(end_d),
                    "rows": 0, "total_rows": total_rows,
                })
            break

        n = database.upsert_candles(alias, interval, rows)
        total_rows += n

        # Track watermarks
        chunk_earliest = int(rows[0][0])
        chunk_latest = int(rows[-1][0])
        earliest_seen_ts = (
            chunk_earliest if earliest_seen_ts is None
            else min(earliest_seen_ts, chunk_earliest)
        )
        latest_seen_ts = max(chunk_latest, state.get("latest_ts") or 0) or chunk_latest
        database.set_backfill_state(
            alias, interval,
            earliest_ts=earliest_seen_ts,
            latest_ts=latest_seen_ts,
        )

        logger.info(
            "[backfill %s %s] chunk %d: %s..%s -> %d rows (total %d)",
            alias, interval, chunk_idx, start_d, end_d, n, total_rows,
        )
        if progress_cb:
            progress_cb({
                "chunk": chunk_idx, "from": str(start_d), "to": str(end_d),
                "rows": n, "total_rows": total_rows,
            })

        # Step back one day before the chunk we just fetched.
        end_d = start_d - timedelta(days=1)

        if chunk_pause_seconds:
            time.sleep(chunk_pause_seconds)

    return {
        "chunks": chunks_done,
        "rows": total_rows,
        "earliest_ts": earliest_seen_ts,
    }


def backfill_many(
    symbols_iter: Iterable[str],
    intervals: Iterable[str] = ("1m", "1d"),
    **kwargs,
) -> dict[str, dict[str, dict]]:
    """Backfill several symbols × intervals. Returns nested summary dicts.

    A failure on one (symbol, interval) — Fyers outage, malformed response,
    auth issue, anything — is captured into that pair's summary as
    ``{"error": "...", "chunks": int, "rows": int}`` and the loop continues.
    Reaching Fyers' history floor is **not** treated as a failure (see
    ``fyers_client.fetch_history``); only genuine errors land here.
    """
    out: dict[str, dict[str, dict]] = {}
    for sym in symbols_iter:
        out[sym] = {}
        for iv in intervals:
            logger.info("=== Backfill %s %s ===", sym, iv)
            try:
                out[sym][iv] = backfill_symbol(sym, iv, **kwargs)
            except Exception as e:
                logger.exception(
                    "Backfill of %s %s failed; continuing with remaining pairs.",
                    sym, iv,
                )
                out[sym][iv] = {
                    "error": str(e),
                    "chunks": 0,
                    "rows": 0,
                    "earliest_ts": None,
                }
    return out
