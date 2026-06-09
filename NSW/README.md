# NSW — Local Market Data Layer (Fyers-backed)

A local, deduplicated, queryable historical-candle store for Indian indices, fed from the Fyers v3 API and exposed as pandas DataFrames or CSV.

NSW is the foundation of the Quant Desk revamp. Every research, backtest, and live module above it should call `nsw.loader.load_data(...)` and never touch the broker API directly.

## What it does

- Authenticates against Fyers (OAuth code flow, browser-based) and persists the access token.
- Backfills as much history as Fyers will give for each symbol, in chunks, walking backwards from today.
- Stores **base** candles (1-minute and 1-day) in SQLite. Every other timeframe (2m, 5m, 15m, 1h, 1w, 3Mo, etc.) is derived on demand by pandas resample. One source of truth per category, no drift.
- Updates incrementally on request — only fetches bars after the last stored bar.
- Serves data through a single `load_data()` call that returns a DataFrame, with optional pre-load update and CSV export.
- Provides a small browser GUI for credential entry, OAuth kickoff, and triggering updates/backfills.

## Initial scope

- **Symbols:** NIFTY 50, BANKNIFTY, FINNIFTY, MIDCPNIFTY (extensible — see `nsw/symbols.py`).
- **Stored timeframes:** `1m` and `1d`.
- **Loadable timeframes:** `1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m, 45m, 1h, 90m, 2h, 3h, 4h, 6h, 8h, 12h, 1d, 2d, 3d, 1w, 2w, 3w, 1Mo, 2Mo, 3Mo, 6Mo, 12Mo`. (Sub-day timeframes are derived from `1m`; multi-day timeframes from `1d`.) Note: NSE's session is 6h15m and intraday bars anchor to 09:15 IST, so `8h`/`12h` are one bar per trading day (whole session) and `6h` splits each day into a 6h bar + a 15-min stub. Intraday timeframes only reach back as far as stored `1m` history (shorter than `1d`).

## Quick start

**One-time:** bootstrap the shared environment from the workspace root
(builds `.venv`, installs NSW + research libs). This is *not* NSW's job —
it's owned by `first_install/`:

```bash
./first_install/install.sh
```

**Every time:** launch the NSW setup/data server:

```bash
cd NSW
./start_nsw.sh
```

`start_nsw.sh` does one thing now: verify the shared venv exists, then
launch `python -B -m nsw.server` serving `https://127.0.0.1:5001/`. It does
**not** create or touch the venv (that's `first_install/install.sh`), and
it doesn't copy `config.json` — NSW creates that from `config.example.json`
on startup if it's missing (`nsw.config.ensure_config_exists`).

The first time you visit the page Chrome/Firefox will warn about the
self-signed cert — click **Advanced → Proceed**. On the page you'll see
three sections: Fyers credentials, Authenticate, Local database.

If you run `./start_nsw.sh` before bootstrapping, it'll tell you to run
`first_install/install.sh` first and exit.

### Authenticate with Fyers (first time, and again each trading day)

On the setup page:

- Fill in App ID and Secret Key if they aren't saved already.
- Click **Open Fyers Login** — Fyers' consent screen opens in a new tab.
- Approve. Fyers redirects to `https://127.0.0.1:5001/callback`, the server captures the auth code, exchanges it for an access token, and bounces you back to the page showing **Connected**.

Access tokens expire daily; re-auth via the same page each trading day.

### Backfill the indices

Click **Run full backfill** on the setup page (or run `python scripts/seed_indices.py` from the venv). It pulls every available bar of 1m and 1d for NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY, in chunks, until Fyers stops returning data. First run takes a few minutes; re-runs are near no-ops because the chunks already in the DB are skipped and the API floor is remembered.

### Use the data

```python
from nsw.loader import load_data, export_csv

# Daily candles, all stored history, no API call
df = load_data("NIFTY", "1d")

# 15-minute candles, last 6 months, refresh tail first
df = load_data("BANKNIFTY", "15m", update=True,
               from_date="2025-11-09", to_date="2026-05-09")

# Restrict to NSE regular session (09:15-15:29 IST), drop Muhurat /
# pre-open archive quirks. Default is False — Fyers data as-served.
df = load_data("NIFTY", "1h", session_only=True)

# Write to disk
export_csv("NIFTY", "1h", "nifty_1h.csv")
```

Intraday timeframes (`1m`, `5m`, `1h`, `4h`, …) are anchored to NSE
market open (`09:15 IST`), so `1h` bars land at `09:15, 10:15, …, 15:15`
each session.

### Manual setup (if you skip the scripts)

```bash
# from the workspace root -- build the shared venv + install NSW
python3 -m venv .venv
.venv/bin/pip install -e NSW
# then run the server
.venv/bin/python -m nsw.server
```

In practice just use `./first_install/install.sh` (which does the venv +
all modules + research libs) followed by `cd NSW && ./start_nsw.sh`.

## Layout

```
NSW/
├─ config.example.json     template — copy to config.json (gitignored)
├─ requirements.txt
├─ candles.db              SQLite store (auto-created, gitignored)
├─ cert.pem, key.pem       self-signed cert for HTTPS callback (gitignored)
├─ nsw/                    main package
│  ├─ config.py            load/save config.json
│  ├─ database.py          SQLite layer
│  ├─ fyers_client.py      Fyers API wrapper (auth + history)
│  ├─ symbols.py           index symbol map
│  ├─ timeframes.py        timeframe map + resample logic
│  ├─ backfill.py          chunked historical fetch
│  ├─ update.py            incremental tail update
│  ├─ loader.py            public load_data / export_csv API
│  └─ server.py            Flask setup/status GUI
├─ templates/
│  └─ setup.html           credentials + status + actions page
├─ scripts/
│  ├─ seed_indices.py      first-time backfill of 1m + 1d for the 4 indices
│  └─ update_all.py        routine incremental update
└─ examples/
   └─ load_example.py
```

## Fyers API setup

1. Go to <https://myapi.fyers.in> and create an app.
2. Set Redirect URL to `https://127.0.0.1:5001/callback` (note **5001**, not 5000 — that port is the trading-dashboard's).
3. Copy App ID and Secret Key into `config.json` or the setup page.

## Notes

- API limits: ~10 000 calls / day on Fyers. A full 4-symbol × 1m backfill walks ~50 chunks × 4 symbols = ~200 calls. Plenty of headroom.
- Per-call window: Fyers allows `100 days` per call for sub-day intervals and `366 days` per call for daily-and-up. The backfiller respects both.
- Storage footprint: 1m for one index × ~10 years ≈ 750k rows ≈ ~50 MB in SQLite. Four indices ≈ 200 MB. Daily is negligible.
- The token is short-lived; the `client_secret` is not. `config.json` is gitignored — never commit it.
