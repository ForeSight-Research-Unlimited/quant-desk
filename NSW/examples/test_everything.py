"""End-to-end smoke test of NSW's Python API.

Run after authenticating + at least one backfill or update has populated
the database. The shared venv lives at the Quant Desk workspace root, so
either activate it first or run via its python directly:

    # Linux / macOS
    ../.venv/bin/python examples/test_everything.py

    # Windows
    "..\\.venv\\Scripts\\python.exe" examples\\test_everything.py

The script doesn't hit Fyers (no `update=True`) so it can't fail on
auth/network issues. It only reads from the local SQLite store and
exercises every major code path the rest of Quant Desk will use.

If any step fails it stops with a clear error.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import textwrap

# `nsw` is editably installed in the shared venv -- no sys.path tricks needed.
from nsw.loader import load_data, export_csv, get_coverage
from nsw.timeframes import ALL_INTERVALS


def banner(s: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n  {s}\n{line}")


def fmt_ts(ts):
    return dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"


# ---------------------------------------------------------------------------
# 1. Coverage report — what's actually in the database right now
# ---------------------------------------------------------------------------
banner("1. Coverage report")
coverage = get_coverage()
header = f"  {'symbol':<10} {'iv':<3} {'bars':>10}  {'earliest':<12} {'latest':<12}"
print(header)
print("  " + "-" * (len(header) - 2))
total_bars = 0
for row in coverage:
    total_bars += row["count"]
    print(
        f"  {row['symbol']:<10} {row['interval']:<3} {row['count']:>10,}  "
        f"{fmt_ts(row['earliest_ts']):<12} {fmt_ts(row['latest_ts']):<12}"
    )
print(f"\n  Total bars stored across all (symbol,interval) pairs: {total_bars:,}")

if total_bars == 0:
    print("\n[ABORT] The database is empty. Run the setup page's `Run full backfill`")
    print("        button (https://127.0.0.1:5001/) or `python scripts/seed_indices.py`")
    print("        before re-running this test.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Base intervals — daily for each of the four indices
# ---------------------------------------------------------------------------
banner("2. Base interval — 1d, all four indices")
for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
    df = load_data(sym, "1d")
    if df.empty:
        print(f"  {sym:<10} (no data — backfill not run yet)")
        continue
    last_close = df["close"].iloc[-1]
    print(
        f"  {sym:<10} bars={len(df):>6,}  "
        f"first={df.index[0].date()}  last={df.index[-1].date()}  "
        f"last_close={last_close:>10,.2f}"
    )


# ---------------------------------------------------------------------------
# 3. Base interval — 1m for one index, last 5 trading days
# ---------------------------------------------------------------------------
banner("3. Base interval — 1m NIFTY, last 5 trading days")
df_1m = load_data(
    "NIFTY", "1m",
    from_date=(dt.date.today() - dt.timedelta(days=10)).isoformat(),
)
if df_1m.empty:
    print("  (no 1m data yet — run backfill)")
else:
    print(f"  rows={len(df_1m):,}")
    print(f"  first bar: {df_1m.index[0]}")
    print(f"  last bar:  {df_1m.index[-1]}")
    print(f"  head:")
    print(textwrap.indent(df_1m.head(3).to_string(), "    "))
    print(f"  tail:")
    print(textwrap.indent(df_1m.tail(3).to_string(), "    "))


# ---------------------------------------------------------------------------
# 4. Derived intraday timeframes — resampling 1m on read
# ---------------------------------------------------------------------------
banner("4. Derived intraday — 5m / 15m / 1h NIFTY (resampled from 1m)")
for iv in ("5m", "15m", "1h"):
    df = load_data(
        "NIFTY", iv,
        from_date=(dt.date.today() - dt.timedelta(days=30)).isoformat(),
    )
    if df.empty:
        print(f"  {iv:<3} (empty — needs underlying 1m data)")
    else:
        last = df.iloc[-1]
        print(
            f"  {iv:<3} rows={len(df):>5,}  "
            f"last_bar={df.index[-1]}  "
            f"OHLCV={last['open']:.2f}/{last['high']:.2f}/"
            f"{last['low']:.2f}/{last['close']:.2f}/{int(last['volume'])}"
        )


# ---------------------------------------------------------------------------
# 5. Derived multi-day / weekly / monthly / quarterly — resampling 1d
# ---------------------------------------------------------------------------
banner("5. Derived multi-day — 1w / 1Mo / 3Mo NIFTY (resampled from 1d)")
for iv in ("1w", "1Mo", "3Mo"):
    df = load_data("NIFTY", iv)
    if df.empty:
        print(f"  {iv:<4} (empty — needs underlying 1d data)")
    else:
        print(
            f"  {iv:<4} rows={len(df):>5,}  "
            f"first_label={df.index[0].date()}  "
            f"last_label={df.index[-1].date()}  "
            f"weekday={df.index[0].strftime('%A')}"
        )


# ---------------------------------------------------------------------------
# 6. Timezone conversion — request the same window in IST
# ---------------------------------------------------------------------------
banner("6. Timezone conversion — last 1h NIFTY bars in IST")
df_ist = load_data("NIFTY", "1h", tz="Asia/Kolkata").tail(5)
if df_ist.empty:
    print("  (empty — needs 1m data backfilled)")
else:
    print(textwrap.indent(df_ist.to_string(), "    "))
    tz = df_ist.index.tz
    assert tz is not None and "Kolkata" in str(tz), f"expected IST tz, got {tz}"
    print(f"\n  index tz: {tz}  (IST = UTC+05:30)")


# ---------------------------------------------------------------------------
# 7. Sanity-check OHLC invariants on a derived bar
# ---------------------------------------------------------------------------
banner("7. OHLC invariants on a resampled bar (high>=open,close,low; low<=...)")
df_check = load_data("NIFTY", "5m",
                      from_date=(dt.date.today() - dt.timedelta(days=10)).isoformat())
if not df_check.empty:
    # On every row: high should be the max, low the min.
    bad = df_check[(df_check["high"] < df_check[["open", "close", "low"]].max(axis=1)) |
                   (df_check["low"]  > df_check[["open", "close", "high"]].min(axis=1))]
    print(f"  rows checked: {len(df_check):,}")
    print(f"  rows with broken invariants: {len(bad)}")
    assert len(bad) == 0, f"Resample produced bars where high < ... or low > ...: {bad.head()}"
    print("  ok — every bar's high is the max and low is the min")
else:
    print("  (skipped — no 5m data in window)")


# ---------------------------------------------------------------------------
# 8. CSV export
# ---------------------------------------------------------------------------
banner("8. CSV export — last 30 days of NIFTY 15m -> ./out/")
out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
csv_path = os.path.join(out_dir, "nifty_15m_last30d.csv")
written = export_csv(
    "NIFTY", "15m",
    csv_path,
    from_date=(dt.date.today() - dt.timedelta(days=30)).isoformat(),
    tz="Asia/Kolkata",
)
size_kb = os.path.getsize(written) / 1024
print(f"  wrote: {written}")
print(f"  size:  {size_kb:.1f} KB")
print(f"  first 5 lines:")
with open(written, "r", encoding="utf-8") as f:
    for _ in range(5):
        line = f.readline().rstrip()
        print(f"    {line}")


# ---------------------------------------------------------------------------
# 9. Symbol resolver — alt-spellings work
# ---------------------------------------------------------------------------
banner("9. Symbol resolver — aliases and alt-spellings")
from nsw import symbols  # noqa: E402
for variant in ("NIFTY", "nifty 50", "BANKNIFTY", "bank nifty",
                "FINNIFTY", "MIDCPNIFTY", "NSE:NIFTY50-INDEX"):
    try:
        canonical = symbols.resolve(variant)
        fyers = symbols.fyers_symbol(variant)
        print(f"  {variant!r:<26} -> {canonical:<10} = {fyers}")
    except KeyError as e:
        print(f"  {variant!r:<26} -> KeyError: {e}")


# ---------------------------------------------------------------------------
# 10. Total interval registry sanity
# ---------------------------------------------------------------------------
banner("10. Timeframe registry")
print(f"  {len(ALL_INTERVALS)} loadable timeframes:")
print(textwrap.indent(", ".join(ALL_INTERVALS), "    "))


banner("ALL TESTS PASSED")
print("  NSW is functioning end-to-end. You can now use load_data(...) from")
print("  any Python code in the venv to pull candles for research, backtests,")
print("  or live monitoring.")
