"""SQLite layer for NSW's local candle store.

Schema reasoning
----------------
We deliberately store only **base** intervals: ``1m`` and ``1d``. Every other
timeframe the user might ask for (5m, 15m, 1h, 1w, 3Mo, etc.) is derived from
one of those by pandas resample (see ``timeframes.py``). One source of truth
per category, no risk of "stored 5m" drifting from "5m resampled from stored
1m" if the upstream provider corrects historical bars.

A single ``candles`` table is keyed on ``(symbol, interval, timestamp)`` with a
UNIQUE constraint so re-fetching the same range upserts cleanly.

A ``backfill_state`` table tracks the earliest and latest bar we've actually
managed to fetch per (symbol, interval), separate from any gaps inside that
range. The backfiller uses this to avoid hammering the API for ranges we've
already proved unavailable.

Threading
---------
SQLite connections are not thread-safe; we hand each thread its own connection
via ``threading.local``. WAL mode lets readers and writers proceed concurrently.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Iterable, Sequence

from . import config

DB_PATH = os.path.join(config.PROJECT_ROOT, "candles.db")

# Intervals stored as base. Everything else is derived.
BASE_INTERVALS: tuple[str, ...] = ("1m", "1d")

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating one if needed."""
    if getattr(_local, "conn", None) is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # WAL: many concurrent readers + a single writer without blocking each other.
        conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL is the safe-ish, fast-ish default. FULL is paranoid; OFF is reckless.
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return _local.conn


def close_connection() -> None:
    """Close the calling thread's connection (used in tests/teardown)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init_db() -> None:
    """Create tables and indices if they don't exist. Idempotent."""
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS candles (
            symbol     TEXT    NOT NULL,
            interval   TEXT    NOT NULL,
            timestamp  INTEGER NOT NULL,        -- epoch seconds, UTC
            open       REAL    NOT NULL,
            high       REAL    NOT NULL,
            low        REAL    NOT NULL,
            close      REAL    NOT NULL,
            volume     INTEGER NOT NULL,
            PRIMARY KEY (symbol, interval, timestamp)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS idx_candles_lookup
            ON candles(symbol, interval, timestamp);

        CREATE TABLE IF NOT EXISTS backfill_state (
            symbol         TEXT NOT NULL,
            interval       TEXT NOT NULL,
            earliest_ts    INTEGER,             -- earliest bar we've ever seen
            latest_ts      INTEGER,             -- latest bar we've ever seen
            api_floor_ts   INTEGER,             -- earliest the API will give us
            updated_at     INTEGER NOT NULL,    -- epoch seconds, when we last touched
            PRIMARY KEY (symbol, interval)
        );
        """
    )
    conn.commit()

    # Keep the WAL file from growing unboundedly across sessions. The
    # trading-dashboard had this happen — 155 MB WAL alongside a 288 MB DB.
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass


# ------------------------------------------------------------------
# Candle CRUD
# ------------------------------------------------------------------


def upsert_candles(
    symbol: str,
    interval: str,
    candles: Sequence[Sequence],
) -> int:
    """Insert or replace candles. Returns the count of rows touched.

    ``candles`` is a sequence of rows in Fyers' native shape:
        ``[timestamp, open, high, low, close, volume]``
    Timestamps must already be epoch seconds (UTC).
    """
    if interval not in BASE_INTERVALS:
        raise ValueError(
            f"Refusing to store interval {interval!r}: only base intervals "
            f"{BASE_INTERVALS} are stored. Derived intervals are computed on read."
        )
    if not candles:
        return 0

    rows = [
        (symbol, interval, int(c[0]), float(c[1]), float(c[2]), float(c[3]),
         float(c[4]), int(c[5]))
        for c in candles
    ]
    conn = get_connection()
    conn.executemany(
        """
        INSERT OR REPLACE INTO candles
            (symbol, interval, timestamp, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def get_candles(
    symbol: str,
    interval: str,
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> list[dict]:
    """Return stored candles for a symbol+interval window, oldest-first.

    Both bounds are inclusive. Each row is returned as a dict with keys
    ``timestamp, open, high, low, close, volume``.
    """
    conn = get_connection()
    query = (
        "SELECT timestamp, open, high, low, close, volume "
        "FROM candles WHERE symbol = ? AND interval = ?"
    )
    params: list = [symbol, interval]

    if from_ts is not None:
        query += " AND timestamp >= ?"
        params.append(int(from_ts))
    if to_ts is not None:
        query += " AND timestamp <= ?"
        params.append(int(to_ts))

    query += " ORDER BY timestamp ASC"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_earliest_timestamp(symbol: str, interval: str) -> int | None:
    """Return the smallest stored timestamp for symbol+interval (or None)."""
    row = get_connection().execute(
        "SELECT MIN(timestamp) AS ts FROM candles "
        "WHERE symbol = ? AND interval = ?",
        (symbol, interval),
    ).fetchone()
    return row["ts"] if row and row["ts"] is not None else None


def get_latest_timestamp(symbol: str, interval: str) -> int | None:
    """Return the largest stored timestamp for symbol+interval (or None)."""
    row = get_connection().execute(
        "SELECT MAX(timestamp) AS ts FROM candles "
        "WHERE symbol = ? AND interval = ?",
        (symbol, interval),
    ).fetchone()
    return row["ts"] if row and row["ts"] is not None else None


def count_candles(symbol: str, interval: str) -> int:
    """Number of stored bars for symbol+interval."""
    row = get_connection().execute(
        "SELECT COUNT(*) AS n FROM candles WHERE symbol = ? AND interval = ?",
        (symbol, interval),
    ).fetchone()
    return int(row["n"]) if row else 0


# ------------------------------------------------------------------
# Backfill state
# ------------------------------------------------------------------


def get_backfill_state(symbol: str, interval: str) -> dict | None:
    """Return the persisted backfill state row, or None if there isn't one."""
    row = get_connection().execute(
        "SELECT earliest_ts, latest_ts, api_floor_ts, updated_at "
        "FROM backfill_state WHERE symbol = ? AND interval = ?",
        (symbol, interval),
    ).fetchone()
    return dict(row) if row else None


def set_backfill_state(
    symbol: str,
    interval: str,
    *,
    earliest_ts: int | None = None,
    latest_ts: int | None = None,
    api_floor_ts: int | None = None,
) -> None:
    """Upsert the backfill watermark for a symbol+interval.

    Any field passed as None is preserved from the existing row (if any).
    ``updated_at`` is stamped on every call.

    NOTE: This is read-then-write, not atomic. Safe today because only the
    backfill loop writes here, and backfills are single-threaded per pair.
    If we ever parallelize backfill across pairs, switch to an UPDATE with
    COALESCE per column, or take an explicit lock.
    """
    existing = get_backfill_state(symbol, interval) or {}

    new = {
        "earliest_ts": earliest_ts if earliest_ts is not None else existing.get("earliest_ts"),
        "latest_ts": latest_ts if latest_ts is not None else existing.get("latest_ts"),
        "api_floor_ts": api_floor_ts if api_floor_ts is not None else existing.get("api_floor_ts"),
        "updated_at": int(time.time()),
    }

    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO backfill_state
            (symbol, interval, earliest_ts, latest_ts, api_floor_ts, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (symbol, interval,
         new["earliest_ts"], new["latest_ts"],
         new["api_floor_ts"], new["updated_at"]),
    )
    conn.commit()


# ------------------------------------------------------------------
# Coverage reports (for the setup page)
# ------------------------------------------------------------------


def coverage_summary(symbols: Iterable[str], intervals: Iterable[str]) -> list[dict]:
    """Return one row per (symbol, interval) with count, earliest, latest.

    Used by the setup page's status table. Empty rows (count == 0) are still
    included so the user can see what hasn't been backfilled yet.
    """
    rows: list[dict] = []
    for sym in symbols:
        for iv in intervals:
            rows.append({
                "symbol": sym,
                "interval": iv,
                "count": count_candles(sym, iv),
                "earliest_ts": get_earliest_timestamp(sym, iv),
                "latest_ts": get_latest_timestamp(sym, iv),
            })
    return rows
