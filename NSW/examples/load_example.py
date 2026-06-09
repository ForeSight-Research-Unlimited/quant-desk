"""Smoke-test the public loader API.

Run after seeding:

    python examples/load_example.py

Prints a head + tail for daily NIFTY, then a derived 15m frame, then exports
both to CSV in this folder.
"""

from __future__ import annotations

import os

# `nsw` is editably installed in the shared venv -- no sys.path tweaking needed.
from nsw.loader import export_csv, get_coverage, load_data


def main():
    print("Coverage:")
    for row in get_coverage():
        print(f"  {row['symbol']:<10s} {row['interval']:<3s}  bars={row['count']}")
    print()

    df_d = load_data("NIFTY", "1d")
    print(f"NIFTY 1d : {len(df_d)} rows")
    if len(df_d):
        print(df_d.head(3))
        print("...")
        print(df_d.tail(3))
    print()

    df_15m = load_data("NIFTY", "15m",
                       from_date="2025-01-01", to_date="2025-03-31",
                       tz="Asia/Kolkata")
    print(f"NIFTY 15m (Jan-Mar 2025, IST) : {len(df_15m)} rows")
    if len(df_15m):
        print(df_15m.head(3))
    print()

    here = os.path.dirname(os.path.abspath(__file__))
    export_csv("NIFTY", "1d",  os.path.join(here, "nifty_1d.csv"))
    export_csv("NIFTY", "15m", os.path.join(here, "nifty_15m_jan_mar_2025.csv"),
               from_date="2025-01-01", to_date="2025-03-31",
               tz="Asia/Kolkata")
    print("Exported nifty_1d.csv and nifty_15m_jan_mar_2025.csv.")


if __name__ == "__main__":
    main()
