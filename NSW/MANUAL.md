# NSW — Manual & Reference

A complete guide to what NSW is, how it works, how to operate it day-to-day, and how to extend it. Pair this with `README.md` (the 90-second quick-start) for the full picture.

---

## Table of contents

1. [What NSW is, in one paragraph](#1-what-nsw-is-in-one-paragraph)
2. [The four ideas you need to hold in your head](#2-the-four-ideas-you-need-to-hold-in-your-head)
3. [The end-to-end flow, narrated](#3-the-end-to-end-flow-narrated)
4. [Folder layout](#4-folder-layout)
5. [Storage layer — what's on disk and why](#5-storage-layer--whats-on-disk-and-why)
6. [Authentication — the Fyers OAuth handshake](#6-authentication--the-fyers-oauth-handshake)
7. [Backfill — chunked walk-backwards](#7-backfill--chunked-walk-backwards)
8. [Update — incremental tail-fetch](#8-update--incremental-tail-fetch)
9. [Timeframes & resampling](#9-timeframes--resampling)
10. [Public Python API](#10-public-python-api)
11. [The browser setup / status page](#11-the-browser-setup--status-page)
12. [CLI scripts](#12-cli-scripts)
13. [The launchers (`start_nsw.bat` & `backup.bat`)](#13-the-launchers-start_nswbat--backupbat)
14. [Backup to GitHub](#14-backup-to-github)
15. [Operational notes](#15-operational-notes)
16. [Troubleshooting catalogue](#16-troubleshooting-catalogue)
17. [Extending NSW](#17-extending-nsw)
18. [What NSW deliberately is NOT](#18-what-nsw-deliberately-is-not)

---

## 1. What NSW is, in one paragraph

NSW is the **local market-data layer** of the Quant Desk stack. It pulls historical OHLCV candles for the four NSE indices (`NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`) from the Fyers v3 API, stores them in a single local SQLite file, and serves them to the rest of your code as clean pandas DataFrames in any of 24 timeframes — without your code ever talking to Fyers directly. Think of it as the boundary between "the world out there" (broker APIs, network, rate limits) and "the world in here" (research notebooks, backtests, live strategies). Above the line: deterministic, instant, queryable. Below the line: dealt with once, kept fresh on demand.

---

## 2. The four ideas you need to hold in your head

Everything else is plumbing around these four design choices.

**(i) Cache first, network on demand.** Reads are SQLite-only by default. The only time NSW touches Fyers is when you explicitly ask it to (`update=True` on a load, or clicking a button on the setup page, or running a backfill / update script). Research code can run with the network unplugged and get the same answer it got yesterday.

**(ii) Two stored timeframes, twenty-four loadable timeframes.** NSW writes only `1m` and `1d` to the database. Every other timeframe (`5m`, `15m`, `1h`, `1w`, `3Mo`, …) is computed on the fly from one of those bases by `pandas.resample(...)` with strict OHLCV-correct aggregation. This is a deliberate "single source of truth" choice — if Fyers ever corrects an old bar, the correction propagates to every derived view automatically.

**(iii) Walk the API floor backwards.** Fyers caps a single history call at 100 days for sub-day intervals and 366 days for daily-and-up. To pull years of history NSW walks **backwards** from today in chunks of that size, upserting each chunk and stopping when Fyers replies `no_data` (= "we don't have older data"). The earliest date Fyers will give us is recorded as the **API floor** so future backfills know where to stop without having to rediscover it.

**(iv) Two failure modes, two responses.** A `no_data` reply is **not** an error — it's the legitimate "you've reached the floor" signal, and the loop responds by recording the floor and moving on cleanly. A genuine error (auth failure, malformed response, network timeout) raises through `fetch_history`, which is then caught at the `backfill_many` / `update_many` level and recorded as a per-pair error so one bad pair doesn't kill the whole job.

---

## 3. The end-to-end flow, narrated

What actually happens, in time-order, when you go from cold to "I have a DataFrame in my Python REPL":

```
[ you double-click start_nsw.bat ]
              │
              ▼
   creates .venv if missing
   pip install -r requirements.txt if needed
   copies config.example.json → config.json if missing
   wipes nsw\__pycache__ (defensive)
              │
              ▼
   python -B -m nsw.server
              │
              ▼
   Flask app boots on https://127.0.0.1:5001/
   (auto-generates self-signed cert on first run)
   browser opens to that URL
              │
              ▼
   ┌──────────────────────────────────────┐
   │ setup page in the browser            │
   │  - paste App ID + Secret Key         │
   │  - click "Open Fyers Login"          │
   │  - approve in the new tab            │
   │  - Fyers redirects to /callback      │
   │  - server swaps auth_code for token  │
   │  - token saved to config.json        │
   │  - you're back on /, "Connected"     │
   └──────────────────────────────────────┘
              │
              ▼
   click "Run full backfill" (first time)
              │
              ▼
   for each (symbol, interval) pair:
     walk backwards in 100d / 366d chunks
     upsert each chunk into candles.db
     stop on no_data, record API floor
              │
              ▼
   in your Python REPL (venv active):
     >>> from nsw.loader import load_data
     >>> df = load_data("NIFTY", "5m")     # cached read, no network
     >>> df = load_data("NIFTY", "5m", update=True)  # tops up tail first
```

After this, the daily flow is just `start_nsw.bat` → click **Open Fyers Login** to refresh the daily token → click **Update tail** → use Python.

---

## 4. Folder layout

```
NSW/
├─ MANUAL.md                this document
├─ README.md                quick-start landing page
├─ requirements.txt         pinned deps
├─ config.example.json      committed credential template
├─ config.json              gitignored, real Fyers credentials
├─ candles.db               gitignored, the SQLite store (auto-created)
├─ candles.db-wal           WAL journal (transient, gitignored)
├─ candles.db-shm           shared-memory file (transient, gitignored)
├─ cert.pem                 self-signed HTTPS cert (gitignored, auto-generated)
├─ key.pem                  matching private key (gitignored)
├─ fyersApi.log             Fyers SDK's log (gitignored)
├─ fyersRequests.log        Fyers SDK's HTTP log (gitignored)
├─ start_nsw.bat            one-click launcher (Windows)
├─ backup.bat               one-click GitHub push
├─ .gitignore               excludes secrets, DB files, .venv, *.pem, *.log
│
├─ nsw/                     the package
│  ├─ __init__.py           version + public-API hint
│  ├─ config.py             read/write config.json (atomic, placeholder-aware)
│  ├─ symbols.py            alias map: NIFTY ↔ NSE:NIFTY50-INDEX
│  ├─ database.py           SQLite layer (schema, upsert, range query, watermarks)
│  ├─ fyers_client.py       Fyers SDK wrapper (auth + history fetch)
│  ├─ timeframes.py         24-timeframe map + resample primitives
│  ├─ backfill.py           chunked walk-backwards historical fetch
│  ├─ update.py             incremental tail-fetch
│  ├─ loader.py             load_data / export_csv / get_coverage  ← public API
│  └─ server.py             Flask app: setup page, OAuth callback, jobs API
│
├─ templates/
│  └─ setup.html            the single-page browser UI
│
├─ scripts/
│  ├─ seed_indices.py       CLI: full backfill of all 4 indices × 1m,1d
│  └─ update_all.py         CLI: incremental tail-update across all pairs
│
└─ examples/
   └─ load_example.py       smoke test that exercises load_data + export_csv
```

---

## 5. Storage layer — what's on disk and why

### Database: `candles.db` (SQLite, WAL mode)

Two tables.

**`candles`** — the only place OHLCV is stored.

| column     | type    | notes                                |
|------------|---------|--------------------------------------|
| symbol     | TEXT    | NSW alias (`"NIFTY"`, …)             |
| interval   | TEXT    | only ever `"1m"` or `"1d"`           |
| timestamp  | INTEGER | epoch seconds, UTC, **bar open time**|
| open       | REAL    |                                      |
| high       | REAL    |                                      |
| low        | REAL    |                                      |
| close      | REAL    |                                      |
| volume     | INTEGER |                                      |

Primary key: `(symbol, interval, timestamp)` — the same bar can never be inserted twice; `INSERT OR REPLACE` upserts cleanly. `WITHOUT ROWID` storage halves the row-overhead vs the default rowid table.

Index `idx_candles_lookup` on `(symbol, interval, timestamp)` powers the range queries in `get_candles()`.

**`backfill_state`** — per-pair watermarks, separate from the bar data.

| column        | type    | notes                                                   |
|---------------|---------|---------------------------------------------------------|
| symbol        | TEXT    |                                                         |
| interval      | TEXT    |                                                         |
| earliest_ts   | INTEGER | smallest timestamp ever upserted for this pair          |
| latest_ts     | INTEGER | largest timestamp ever upserted                         |
| api_floor_ts  | INTEGER | earliest date Fyers will give us (`no_data` boundary)   |
| updated_at    | INTEGER | when this row was last touched                          |

`api_floor_ts` is the magic — once known, future backfills don't bother walking past it.

### WAL journal

We turn on `PRAGMA journal_mode=WAL` and `synchronous=NORMAL`. This means many readers and one writer can run concurrently without blocking each other (which the Flask server + your REPL + a backfill thread will). On `init_db()` we run `PRAGMA wal_checkpoint(TRUNCATE)` to consolidate the WAL into the main file and shrink it back to zero — this prevents the multi-hundred-MB WAL we saw on the trading-dashboard.

### Threading

SQLite connections aren't thread-safe. `database.get_connection()` returns a `threading.local`-scoped connection, so the Flask request thread, a background backfill thread, and a REPL all get their own independent connection.

### What NEVER goes in the database

- Resampled timeframes — those are computed at read time.
- Indicators (EMAs, RSI, etc.) — those belong above NSW, not in it.
- Trades, signals, portfolio state — out of scope.

---

## 6. Authentication — the Fyers OAuth handshake

Fyers uses an OAuth 2.0 authorization-code flow with a daily-expiring access token.

```
  user                    NSW (server.py)               Fyers
   │                            │                          │
   │  click "Open Fyers Login"  │                          │
   │ ─────────────────────────► │                          │
   │                            │  build consent URL       │
   │                            │ ◄────────────────────────│
   │  consent URL opens in tab  │                          │
   │ ◄─────────────────────────►│                          │
   │  approve consent screen    │                          │
   │  (this is on Fyers's site) │                          │
   │ ────────────────────────────────────────────────────► │
   │                            │  302 redirect with       │
   │                            │  ?auth_code=...          │
   │ ◄────────────────────────────────────────────────────┤
   │  (browser navigates to)    │                          │
   │   /callback?auth_code=...  │                          │
   │ ─────────────────────────► │                          │
   │                            │  POST /token             │
   │                            │ ────────────────────────►│
   │                            │ ◄────────────────────────│
   │                            │  access_token            │
   │                            │  → saved to config.json  │
   │  302 redirect back to "/"  │                          │
   │ ◄───────────────────────── │                          │
```

Token lifetime: **one trading day**. NSW doesn't try to refresh it automatically (Fyers doesn't issue refresh tokens for this flow); you re-auth each morning. The access token + issue timestamp are persisted to `config.json` via an atomic temp-file write so a crash mid-write can't corrupt the file.

**Placeholder protection.** `config.example.json` contains `"YOUR_FYERS_APP_ID_HERE"` and `"YOUR_FYERS_SECRET_KEY_HERE"` as placeholders. The credential check in `nsw/config.py::credentials_are_complete()` recognises these as "not set" — so a freshly-templated `config.json` doesn't accidentally look like valid credentials.

---

## 7. Backfill — chunked walk-backwards

Implemented in `nsw/backfill.py`. Two functions: `backfill_symbol(symbol, interval)` and `backfill_many(symbols, intervals)`.

### Algorithm

```
end_d = today
loop:
  start_d = end_d - days_per_chunk + 1
  if api_floor_ts is known and start_d < api_floor_d:
      start_d = api_floor_d   # don't ask for ranges we've proved unavailable
      if start_d > end_d: break
  rows = fyers_client.fetch_history(symbol, interval, start_d, end_d)
  if rows is empty:
      # Fyers said no_data — we've found the floor.
      record api_floor_ts in backfill_state
      break
  upsert rows into candles.db
  update earliest_ts / latest_ts watermarks
  end_d = start_d - 1   # step backwards one day before the chunk we just got
  sleep chunk_pause_seconds
```

### Why backwards?

You don't have to know how far back Fyers' history goes. The "stop" condition is whatever the API tells you — empty chunk = floor — so the algorithm self-discovers the depth on first run, records it, and is a near no-op after that.

### Per-call window

| stored interval | days per call | source |
|-----------------|---------------|--------|
| 1m              | 100           | Fyers API limit |
| 1d              | 366           | Fyers API limit |

These live in `nsw/fyers_client.MAX_DAYS_PER_CALL` — not duplicated elsewhere.

### Safety stops

- `max_chunks` (default 100, exposed by `seed_indices.py` as `--max-chunks 200`): hard cap so a misconfigured backfill can't drain the daily 10K-call API budget.
- `chunk_pause_seconds` (default 0.25): brief sleep between chunks. Cheap politeness against rate limits.

### Soft empty vs genuine error

`fetch_history` distinguishes them:

- `s == "ok"` → return the candles list (possibly empty).
- `s` matches `"no_data"` / `"no data"` (case-insensitive, substring) → log INFO, return `[]`. Backfill loop interprets this as "stop, record floor."
- Anything else → log WARNING, retry up to 3 times with linear backoff, then `raise RuntimeError(...)`.

`backfill_many` and `update_many` catch that `RuntimeError` per-pair and continue with the rest of the work, recording `{"error": "..."}` for the failed pair.

---

## 8. Update — incremental tail-fetch

Implemented in `nsw/update.py`.

```
update_symbol(symbol, interval):
  latest_ts = database.get_latest_timestamp(symbol, interval)
  if latest_ts is None:
      → fall through to backfill_symbol (nothing to top up)
  from_d = date(latest_ts)   # day-of-last-bar, on purpose
  to_d   = today
  rows = fyers_client.fetch_history(...)
  upsert rows into candles.db
  bump latest_ts watermark
```

Two subtleties worth knowing.

**(a) `from_d = day-of-latest-stored-bar` (not `latest_ts + 1`).** This re-fetches today's incomplete bar (and any same-day bars that came in after the last update). Without this, an update started mid-day would forever leave a half-day-shaped gap.

**(b) Re-fetched bars overwrite cleanly.** Because the candles table has a UNIQUE `(symbol, interval, timestamp)` constraint and we use `INSERT OR REPLACE`, re-fetching a bar Fyers has corrected since first publication updates it in place — no duplicates, no stale data.

---

## 9. Timeframes & resampling

`nsw/timeframes.py` is the single place that knows about all 24 user-facing intervals.

### Registry

| Group          | Loadable                                                                 | Stored as | Resample rule        |
|----------------|--------------------------------------------------------------------------|-----------|----------------------|
| Sub-day        | `1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m, 45m, 1h, 90m, 2h, 3h, 4h`           | `1m`      | pandas `Nmin`        |
| Multi-day      | `1d, 2d, 3d`                                                             | `1d`      | pandas `ND`          |
| Multi-week     | `1w, 2w, 3w` (anchored to Monday)                                        | `1d`      | pandas `NW-MON`      |
| Monthly        | `1Mo`                                                                    | `1d`      | pandas `MS`          |
| Multi-month    | `2Mo, 3Mo, 6Mo`                                                          | `1d`      | step over `MS` frame |

### Aggregation rules

Every resample uses **closed-left, label-left** semantics — a bar covers `[t, t+Δ)` and is timestamped `t`. The OHLCV aggregation for each window is:

```
open   = first
high   = max
low    = min
close  = last
volume = sum
```

These are the only OHLC-correct rules; anything else (mean, median) silently breaks the invariants.

### Holiday handling (e.g. weekly bars when Monday is a holiday)

NSW follows the TradingView convention: the **label** stays at the calendar Monday, and the OHLC aggregates only the trading days that actually fell in the week. Empty windows (Sat, Sun, full holidays) are dropped via `dropna(subset=["open"])` so you don't see all-NaN rows.

Worked example, week of Republic Day 2026 (NSE closed Mon Jan 26):

| Label (Monday)   | Open                 | High         | Low          | Close                | Volume        |
|------------------|----------------------|--------------|--------------|----------------------|---------------|
| 2026-01-26       | Tue Jan 27 open      | max Tue–Fri  | min Tue–Fri  | Fri Jan 30 close     | sum Tue–Fri   |

This is the convention every charting platform uses.

### Multi-month bars

pandas has `MS` ("month-start") natively, but no built-in "every N months from month-start" alias. We resample to `MS` first, then stride by N: `monthly.iloc[::step]`. So `3Mo` is just every third monthly bar starting at the first available month, and the labels are calendar-aligned.

### Why store only 1m + 1d?

- **Single source of truth.** If Fyers corrects a historical bar, the correction propagates to every derived view automatically.
- **Storage stays small.** A separate stored 5m, 15m, 30m, 1h table per symbol would multiply disk by ~4-5×.
- **API stays small.** Backfilling N stored intervals would mean N times the chunks per symbol.
- **Resample is fast enough.** Even resampling 10 years of 1m to 5m takes <1 s on modern hardware.

If profiling later shows resampling on hot paths is slow, we can add a transparent cache layer (memoise by `(symbol, interval, from_date, to_date)`). It's not needed yet.

---

## 10. Public Python API

The whole API surface is `nsw.loader`. Three functions:

### `load_data(symbol, interval, from_date=None, to_date=None, *, update=False, tz=None) → DataFrame`

The one call to remember.

- `symbol` — case-insensitive alias (`"NIFTY"`, `"BANKNIFTY"`, `"FINNIFTY"`, `"MIDCPNIFTY"`) or any known alt-spelling.
- `interval` — any of the 24 in the registry.
- `from_date`, `to_date` — `"YYYY-MM-DD"`, `date`, `datetime`, or `None`. Inclusive. `to_date` is interpreted as end-of-day.
- `update=True` — top up the appropriate base interval (`1m` or `1d`) before reading. Hits Fyers.
- `tz` — IANA timezone string for the index (e.g. `"Asia/Kolkata"`). Default is UTC.

Returns a DataFrame indexed by tz-aware datetime with columns `open, high, low, close, volume`. Empty DataFrame if no data.

```python
from nsw.loader import load_data
df = load_data("NIFTY", "1d")
df = load_data("BANKNIFTY", "15m", from_date="2025-11-09", update=True, tz="Asia/Kolkata")
```

### `export_csv(symbol, interval, path, ...)`

Equivalent to `load_data(...).to_csv(path)`, but creates the parent directory if it doesn't exist and returns the path.

```python
from nsw.loader import export_csv
export_csv("NIFTY", "1h", "out/nifty_1h.csv", from_date="2026-01-01")
```

### `get_coverage(symbols=None, intervals=("1m", "1d")) → list[dict]`

What's stored, by `(symbol, base-interval)`. Returns a list of dicts: `{symbol, interval, count, earliest_ts, latest_ts}`. Empty pairs are still included so you can see what hasn't been backfilled.

```python
from nsw.loader import get_coverage
for row in get_coverage():
    print(row)
```

### Lower-level entry points (use directly only if you need to)

- `nsw.update.update_symbol(symbol, interval)` / `update_many(symbols, intervals)`
- `nsw.backfill.backfill_symbol(symbol, interval, max_chunks=...)` / `backfill_many(...)`
- `nsw.database.upsert_candles / get_candles / get_backfill_state / set_backfill_state`
- `nsw.fyers_client.fetch_history / get_auth_url / exchange_auth_code / check_token`

These are deliberately not the recommended way — call `load_data` / `export_csv` and let NSW orchestrate. The lower-level entry points are the seams for extension.

---

## 11. The browser setup / status page

Lives at `https://127.0.0.1:5001/`. One page, three sections.

**Section 1 — Fyers credentials.** Three fields (App ID, Secret Key, Redirect URL). **Save credentials** writes to `config.json`. Changing App ID or Secret Key clears the access_token automatically.

**Section 2 — Authenticate.** Shows a status badge (Connected / Invalid-or-expired / Not authenticated) and the token's issue timestamp. **Open Fyers Login** opens the consent screen in a new tab; after approval, Fyers redirects to `/callback`, which exchanges the auth code for a token and bounces you back here. **Re-check token** validates the saved token by hitting Fyers' profile endpoint.

**Section 3 — Local database.** A coverage table per `(symbol, base-interval)` plus two action buttons:

- **Update tail** — incremental tail-fetch for all four indices × `1m, 1d`. Cheap.
- **Run full backfill** — chunked walk-backwards. First run is slow; subsequent runs near no-op because of the API-floor cache.

Both buttons enqueue background jobs and stream chunk-by-chunk progress into the log box. The coverage table refreshes when the job finishes.

### API endpoints (for scripting / automation)

| Method | Path                  | Purpose                                                          |
|--------|------------------------|------------------------------------------------------------------|
| GET    | `/`                    | Render the page                                                  |
| POST   | `/api/credentials`     | Save App ID / Secret / Redirect URL                              |
| GET    | `/api/auth/url`        | Return the Fyers consent URL                                     |
| GET    | `/callback`            | OAuth redirect target                                            |
| GET    | `/api/token/check`     | Validate saved token via profile API                             |
| GET    | `/api/coverage`        | JSON of per-pair coverage stats                                  |
| POST   | `/api/update`          | Kick off `update_many` (returns a job_id)                        |
| POST   | `/api/backfill`        | Kick off `backfill_many` (returns a job_id)                      |
| GET    | `/api/job/<job_id>`    | Poll job state (`queued` / `running` / `done` / `error`)         |

---

## 12. CLI scripts

Two thin wrappers around the public API; both take `--symbols` and `--intervals`.

**`scripts/seed_indices.py`** — full backfill of all four indices × `1m, 1d`. Idempotent: re-running fills only what's missing. Use for first-time data load (or when you want a deeper pull than the GUI default).

```cmd
python scripts/seed_indices.py
python scripts/seed_indices.py --symbols NIFTY --intervals 1d
python scripts/seed_indices.py --max-chunks 200
```

**`scripts/update_all.py`** — incremental tail update for all pairs. Run before a research session if the GUI isn't already open.

```cmd
python scripts/update_all.py
python scripts/update_all.py --symbols NIFTY BANKNIFTY
```

Both scripts call `database.init_db()` first so they work on a fresh checkout too.

---

## 13. The launchers (`start_nsw.bat` & `backup.bat`)

### `start_nsw.bat`

The one-click launcher. On first run: creates `.venv`, installs deps, copies `config.example.json` → `config.json`, generates self-signed cert, opens browser. On subsequent runs: skips everything that's already done and launches in ~1 second. Always wipes `nsw\__pycache__` to dodge the bytecode-staleness gotcha. Always launches with `python -B` so future runs don't write new `.pyc` files. SHA-256-hashes `requirements.txt` and only re-runs `pip install` when the file changes.

### `backup.bat`

The one-click GitHub push. Shows `git status --short` before doing anything. If nothing's changed, just pushes any unpushed local commits and exits. Otherwise asks for a commit message (default: `backup YYYY-MM-DD HH:MM`), stages everything, commits, pushes. Guards against missing remote / not-a-repo / push failure with clear error messages.

Pin shortcuts of both to your desktop.

---

## 14. Backup to GitHub

Repo: <https://github.com/ForeSight-Research-Unlimited/quant-desk-nsw> (private). Initial commit `0a9f179` (19 files, ~2400 lines).

### What's tracked vs what isn't

Tracked: source code (`nsw/*.py`), `templates/`, `scripts/`, `examples/`, `requirements.txt`, `config.example.json`, `start_nsw.bat`, `backup.bat`, `README.md`, `MANUAL.md`, `.gitignore`.

Excluded by `.gitignore`: `config.json` (live Fyers credentials), `candles.db*` (the SQLite store and journal files — large and rebuildable), `cert.pem` / `key.pem` (the self-signed cert pair), `*.log` (Fyers SDK logs and our own), `.venv/`, `__pycache__/`, `*.py[cod]`, OS / editor cruft.

### Routine backup workflow

Either run `./backup.sh` (Linux/macOS) or click `backup.bat` (Windows), or run the steps manually:

```bash
# Linux / macOS
cd "<your-path>/Quant Desk/NSW"
git add -A
git commit -m "<short message>"
git push
```

```cmd
:: Windows
cd "<your-path>\Quant Desk\NSW"
git add -A
git commit -m "<short message>"
git push
```

### If you ever leak a secret

`config.json` is gitignored, but accidents happen. If a real `client_secret` or `access_token` lands in a commit:

1. Rotate `secret_key` in the Fyers developer dashboard at <https://myapi.fyers.in>.
2. Revoke the leaked access token.
3. Don't bother just `git rm`-ing — the secret is in history. Use `git filter-repo` (preferred over the deprecated `git filter-branch`) to rewrite history removing that file across all commits, then force-push and rotate any other developers' clones.

---

## 15. Operational notes

**API budget.** Fyers limits: ~10 000 calls / day. A full first-time backfill across all four indices × both base intervals is ~200 calls. Daily updates are ~8 calls (4 symbols × 2 intervals). You have orders of magnitude of headroom.

**Storage.** 1m candles for one index across ~10 years ≈ 750 K rows ≈ ~50 MB in SQLite. Four indices ≈ 200 MB. Daily candles are negligible. The WAL file gets truncated at every `init_db()`.

**Token expiry.** Fyers access tokens expire daily (typically end of trading day, midnight India time). NSW will refuse `update`-mode loads with a clear error once expired; re-auth via the setup page.

**Time zones.** Stored timestamps are epoch seconds, treated as UTC. The DataFrame returned by `load_data(...)` is UTC by default; pass `tz="Asia/Kolkata"` for IST. Indian market hours are 09:15–15:30 IST, which is 03:45–10:00 UTC.

**Concurrency.** WAL mode lets your REPL read while the Flask server's background thread writes. Don't open two `start_nsw.bat` instances pointing at the same `candles.db` — only one Flask process at a time.

**Crash safety.** SQLite + WAL is fully crash-safe — power-loss mid-upsert leaves the DB in a consistent state. `config.json` writes are atomic (temp-file + `os.replace`).

**Logs.** `fyersApi.log` and `fyersRequests.log` are written by the Fyers SDK itself; both are gitignored. NSW's own logs go to stdout (the CMD window the launcher runs in).

---

## 16. Troubleshooting catalogue

**"Job backfill-XXXXXXX failed: Fyers history failed after 3 attempts ... no_data"**
Old `.pyc` from before the no_data fix. Close the server, run: `rmdir /s /q nsw\__pycache__`, restart with `start_nsw.bat`. The launcher does this automatically going forward.

**Browser shows "Your connection is not private"**
Self-signed cert. Click **Advanced → Proceed**. Once accepted, the browser remembers for the session.

**"No Fyers access_token. Authenticate via the setup page first."**
Token expired or never set. Open `start_nsw.bat`, click **Open Fyers Login**, complete consent.

**"App ID / Secret Key not set (or still on placeholder values)."**
Edit `config.json` directly, or fill the fields on the setup page and click **Save credentials**.

**"Fyers history failed after 3 attempts ... 'invalid_token'"**
Token expired mid-job. Re-auth and re-run.

**Setup page won't load / "site can't be reached"**
Server isn't running. Check the CMD window from `start_nsw.bat` — if it crashed, the error is at the bottom. Most common cause: port 5001 already in use by another process.

**Port 5001 conflict**
If something else is on 5001, edit `nsw/server.py::DEFAULT_PORT` and **also** update the redirect URL in your Fyers app settings to match.

**`pip install` fails on cryptography wheel**
Install Microsoft Visual C++ Build Tools, then re-run. Or pin an older `cryptography` version in `requirements.txt` that has a prebuilt wheel for your Python.

**`git push` rejected**
Most likely the remote has a newer commit (you backed up from another machine). `git pull --rebase` first, then `git push`.

**`load_data("NIFTY", "5m")` returns empty DataFrame**
You haven't backfilled yet. Click **Run full backfill** on the setup page or run `python scripts/seed_indices.py`.

---

## 17. Extending NSW

### Add another index

`nsw/symbols.py`:

```python
INDEX_SYMBOLS["VIX"] = "NSE:INDIAVIX-INDEX"
```

That's it. Backfill it: `python scripts/seed_indices.py --symbols VIX`.

### Add stocks (NSE equity)

Symbols like `NSE:RELIANCE-EQ`, `NSE:TCS-EQ`. Adding ~50 of them is fine. The `INDEX_SYMBOLS` dict can hold them too — there's nothing index-specific in the schema. If the list grows past a couple hundred you'd want to load it from a CSV instead of hardcoding.

### Add a new base interval (e.g. 5s)

1. `nsw/fyers_client.py`: add `"5s": "5S"` to `RESOLUTION` and `"5s": 30` to `MAX_DAYS_PER_CALL`.
2. `nsw/database.BASE_INTERVALS`: add `"5s"`.
3. `nsw/timeframes.py`: re-route any sub-minute aliases that should derive from `5s` instead of `1m`.

### Switch broker (e.g. Upstox, Zerodha)

Replace `nsw/fyers_client.py` with a thin wrapper around the new broker's history endpoint, exposing the same three callables: `get_auth_url()`, `exchange_auth_code(code)`, `fetch_history(symbol, interval, from_date, to_date)`. Update `RESOLUTION` and `MAX_DAYS_PER_CALL` to match the new API's limits. Nothing else changes — the database, resampler, loader, and GUI are broker-agnostic.

### Plug NSW into research code above

Anything that needs candles should `from nsw.loader import load_data`. Stop using `yfinance` from the old Project1 layer. The output shape (DataFrame with `open, high, low, close, volume`) is intentionally identical to what `yf.Ticker(...).history()` returns, so most of the old code only needs the import line changed.

---

## 18. What NSW deliberately is NOT

- **Not a backtester.** That's a layer above this one. Backtesters call `load_data(...)` and run the strategy logic.
- **Not an execution engine.** No order placement, no position tracking. NSW is read-only against the broker.
- **Not an indicator library.** No EMA, RSI, ATR. Those compute on top of `load_data(...)` output.
- **Not a real-time feed.** It's a polled cache. Update granularity is "as fresh as your last update call." For tick-level data you'd need a websocket and a different architecture.
- **Not multi-broker simultaneously.** One broker at a time, swappable. If you need cross-broker data fusion that's a different design problem.
- **Not asynchronous.** Backfill / update run on a background thread for the Flask server, but the actual fetches are synchronous. Good enough for daily-cadence operations on four symbols.

---

*Document version: 0.1.0 · Updated 2026-05-10 · Pair with `README.md` for quick-start.*
