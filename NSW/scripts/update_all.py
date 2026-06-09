"""Routine incremental update.

Run once a day (or before a research session) after authenticating:

    python scripts/update_all.py

Pulls only bars after the latest stored bar per (symbol, interval).
"""

from __future__ import annotations

import argparse
import logging

# `nsw` is editably installed in the shared venv (see start_nsw.bat) so
# we can import it from anywhere without sys.path tricks.
from nsw import database, symbols, update


def main():
    parser = argparse.ArgumentParser(
        description="Tail-update the local NSW database for the four indices.",
    )
    parser.add_argument("--symbols", nargs="+", default=symbols.all_aliases())
    parser.add_argument(
        "--intervals", nargs="+", default=list(database.BASE_INTERVALS),
        choices=list(database.BASE_INTERVALS),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    database.init_db()

    out = update.update_many(args.symbols, intervals=args.intervals)
    print()
    for sym, by_interval in out.items():
        for iv, res in by_interval.items():
            print(f"  {sym:<10s} {iv:<3s}  rows={res['rows']:<6d}  "
                  f"{res['from']} -> {res['to']}  via={res['via']}")


if __name__ == "__main__":
    main()
