"""Seed the database with full historical 1m and 1d candles for the four indices.

Run once after authenticating in the setup server:

    python scripts/seed_indices.py

Idempotent: re-running fills only the parts that aren't already there. Safe to
ctrl-C and resume — chunks already upserted stay in the DB.
"""

from __future__ import annotations

import argparse
import logging

# `nsw` is editably installed in the shared venv (see start_nsw.bat) so
# we can import it from anywhere without sys.path tricks.
from nsw import backfill, database, symbols


def main():
    parser = argparse.ArgumentParser(
        description="Seed NSW with full historical 1m and 1d candles for the four indices.",
    )
    parser.add_argument(
        "--symbols", nargs="+", default=symbols.all_aliases(),
        help="Symbol aliases to backfill. Default: all four indices.",
    )
    parser.add_argument(
        "--intervals", nargs="+", default=list(database.BASE_INTERVALS),
        choices=list(database.BASE_INTERVALS),
        help="Base intervals to backfill.",
    )
    parser.add_argument(
        "--max-chunks", type=int, default=200,
        help="Hard cap on chunks per (symbol, interval). Safety against runaway calls.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    database.init_db()

    print(f"Seeding: symbols={args.symbols}  intervals={args.intervals}")
    summary = backfill.backfill_many(
        args.symbols,
        intervals=args.intervals,
        max_chunks=args.max_chunks,
    )

    print()
    print("Done.")
    for sym, by_interval in summary.items():
        for iv, res in by_interval.items():
            print(f"  {sym:<10s} {iv:<3s}  "
                  f"chunks={res['chunks']:<3d}  rows={res['rows']:<8d}  "
                  f"earliest_ts={res['earliest_ts']}")


if __name__ == "__main__":
    main()
