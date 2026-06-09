# NSW Code Review — Deep Dive

Comprehensive review of every module in NSW as of 2026-05-16. Findings
are tagged by severity:

- **[CRIT]** Will bite. Fix.
- **[IMPT]** Latent issue / sloppy pattern. Fix soon.
- **[MINR]** Nice to have / micro-improvement.
- **[STYL]** Preference / readability.

---

## Executive summary

NSW is in **good shape**. It does one job well: serves clean OHLCV
DataFrames out of a local SQLite store, transparently fed from Fyers.
The architecture is clean (one job per module, swappable broker seam,
single source of truth for base intervals), the data path is robust
(atomic config writes, WAL-mode SQLite, idempotent backfills with API-
floor caching, soft-empty handling for `no_data`), and the UX is real
(one-click launcher, auto-recovery on corrupt config, default-tz IST).

There are **zero critical bugs**. There are 5-6 important issues, all
small, all fixable in well under an hour each. The rest is polish.

The biggest non-bug concern is **no unit tests**. There's a smoke test
(`examples/test_everything.py`) that exercises the public API
end-to-end, but no isolated tests for individual functions. For a
research tool that's tolerable; as we start building the backtester
on top of NSW, regression tests will matter.

---

## Strengths (what's working well)

1. **Module boundaries are clean.** Each file has one job. `symbols`
   maps names. `database` is the SQLite layer. `timeframes` is
   resample math. `fyers_client` is the broker wrapper. `loader` is
   the public face. Replacing any one of them is a contained change.

2. **The broker seam is swappable.** `fyers_client.py` is one file. To
   add Upstox / Zerodha later, you rewrite this one file and nothing
   else changes.

3. **Single source of truth for OHLCV.** Storing only 1m + 1d and
   deriving the other 22 timeframes on read means a historical
   correction propagates everywhere automatically. The resample
   primitives are OHLC-correct (`first/max/min/last/sum`), closed-left
   label-left, Monday-anchored for weeks. TradingView convention.

4. **Atomic config writes.** `save_config` uses `tempfile.mkstemp` +
   `os.replace`. A crash mid-write can't corrupt the file.

5. **`no_data` soft-empty handling.** `fetch_history` distinguishes
   "Fyers said no data available" (return `[]`, let backfill stop and
   record the API floor) from genuine errors (retry up to 3 times,
   then raise). This was a real bug for several iterations and is now
   well-fixed.

6. **Defensive `upsert_candles`.** Raises `ValueError` if asked to
   store a derived interval. Enforces the "base-only" invariant at
   the storage boundary, not just in docs.

7. **Auto-recovery on corrupt config.** `ensure_config_exists`
   renames the broken file to `config.json.corrupt-<ts>.bak` and
   recreates from the template. What was a 500 is now a soft reset.

8. **Lazy SDK import.** `_fyers_module()` defers the
   `from fyers_apiv3 import fyersModel` so the module is importable
   for tests / linting without the SDK installed.

9. **The launcher is bulletproof.** `start_nsw.bat` handles fresh
   PCs, dependency changes (hashes both `requirements.txt` and
   `pyproject.toml`), editable install of `nsw`, stale bytecode
   cleanup, self-signed cert generation, missing `config.json`. Every
   failure path pauses so you can read the error.

10. **WAL-mode SQLite + thread-local connections.** Concurrent reads
    from the REPL while a background backfill writes — no blocking.
    `wal_checkpoint(TRUNCATE)` on `init_db` keeps the journal file
    from growing without bound.

---

## Findings by file

### `nsw/__init__.py`

Trivial. Version + docstring. Nothing to flag.

---

### `nsw/config.py`

**[IMPT] `datetime.utcnow()` is deprecated** in Python 3.12+ and is
slated for removal. Used at:

- Line 71: `ts = int(datetime.utcnow().timestamp())`
- Line 174: `cfg["fyers"]["access_token_issued_at"] = datetime.utcnow().isoformat() + "Z"`

Replace with `datetime.now(timezone.utc)`. The behaviour is identical
today but the deprecation warning will become an error eventually.

**[MINR] Placeholder set is recomputed on every `_is_real_value` call.**
Line 189:

```python
return v.strip() != "" and v.strip().upper() not in {p.upper() for p in _PLACEHOLDER_VALUES}
```

The set comprehension runs on every call. Hoist to module level:

```python
_PLACEHOLDER_VALUES_UPPER = frozenset(p.upper() for p in _PLACEHOLDER_VALUES)

def _is_real_value(v: str) -> bool:
    s = v.strip()
    return s != "" and s.upper() not in _PLACEHOLDER_VALUES_UPPER
```

**[STYL] BOM detection uses the BOM character literal** (line 59-60).
Works but a bit cryptic. `﻿` is the explicit form.

**[STYL] `set_fyers_credentials` compares unstripped values** (lines
153, 156). If the caller passes `"ABC "` and storage has `"ABC"`,
they're treated as different (so the access token gets cleared
unnecessarily). Strip before comparing, or just always clear the
token when this function is called — that's defensive but simpler.

---

### `nsw/symbols.py`

Clean. The reverse-lookup loop in `resolve` is O(n) but n=4. Fine
forever. When stocks land, n will jump to ~50-500, still fine for a
hash-by-lower-cased-alias replacement.

**[MINR]** When you add stocks later, the `INDEX_SYMBOLS` dict will
get unwieldy. Consider loading from a CSV at module import. Not
needed today.

---

### `nsw/database.py`

**[MINR] PRAGMA statements run on every new thread-local connection**
(lines 47-50). `journal_mode=WAL` is database-wide (persists once set
on disk). `synchronous=NORMAL` is per-connection but only needs to be
set once per connection — which is what happens, since the PRAGMA
runs only when the connection is created. So this is actually fine;
I was wrong to flag it on first pass. Disregard.

**[IMPT] `set_backfill_state` is read-then-write** (lines 233-253).
Two concurrent calls can race: both read the same prior state, both
compute a new state, the second `INSERT OR REPLACE` wins, the first's
update is lost. In practice, only the backfill loop writes this and
backfills are single-threaded per-pair, so the race is impossible
today. But if we ever parallelize backfill across pairs, it becomes a
real bug. Either:

- Use a `UPDATE … WHERE` against a single row with the merge expressed
  in SQL.
- Document "single writer per (symbol, interval) only" explicitly.

For now the docstring should at least mention the constraint.

**[STYL] `import time as _time`** inside `set_backfill_state` (line
232). Hoist to module-level.

**[STYL] `get_earliest_timestamp` and `get_latest_timestamp`** are
separate queries. They could be one query (`SELECT MIN(ts), MAX(ts)
FROM …`). Same with `coverage_summary` which makes 3 queries per
(symbol, interval) pair — could be 1 with `GROUP BY`. Negligible at
4 symbols × 2 intervals = 24 queries; matters when symbol count
grows.

---

### `nsw/timeframes.py`

Clean. Aggregation rules are correct, anchors are correct,
multi-month stride is sensible. Nothing to flag.

---

### `nsw/fyers_client.py`

**[IMPT] `last_error` is mixed-type** (lines 199, 223, 230). Sometimes
a Fyers response dict, sometimes an Exception. It's embedded in the
final f-string which works fine, but a caller catching `RuntimeError`
gets a stringified blob. Consider preserving structured info — e.g.
attach the original response dict or exception as an attribute on a
custom `FyersHistoryError` subclass.

**[IMPT] Retry backoff is linear, not exponential.** Sleeps are
`2 × 1 = 2s`, `2 × 2 = 4s` between attempts, total ~6s. For
rate-limited transient errors (429s), exponential backoff (2, 4, 8,
16) would be friendlier to the API and more likely to succeed.
Tunable via the kwarg, but the default should match Fyers' published
guidance.

**[MINR] `no_data` substring check** (line 214) does both an `in`
tuple check AND a substring `"no data" in status`. The substring
check makes the tuple redundant — `"no data" in "no_data"` is True
since `"no_data"` contains the substring "no_data" not "no data"
(underscore vs space). Wait, `"no data" in "no_data"` is False
because of the underscore. So both checks are needed. Keep as is.

**[STYL] Auth check order in `_new_session`** reads creds (line 73)
before checking completeness (line 74). Either order is fine; this
way ensures we surface the placeholder warning before SDK gets
involved.

---

### `nsw/backfill.py`

**[STYL] `import time` inside the loop body** (line 157). Hoist to
module-level (or use `from time import sleep`).

**[MINR] `progress_cb` invocation on the empty-chunk path** (line
119) passes `rows: 0` for both the `from`/`to` AND `chunk` count.
The progress message in the setup-page log will say "chunk 34: ... 0
rows" which is fine, but might confuse a user reading it ("did chunk
34 actually happen?"). Consider a distinct event type, e.g.
`{"event": "floor_reached", ...}`. Minor UX polish.

**[IMPT] `floor_ts` fallback when `earliest_seen_ts` is None** (line
109-111) sets the floor to `end_d`'s start-of-day. That's the "first
chunk returned empty, we have nothing" case. The floor recorded
should arguably be `end_d + 1 day` (we don't even have data for
today). The current behavior means a re-run will try to fetch from
the floor backwards immediately and get another empty chunk, wasting
one API call. Cheap to fix: set floor to `end_d + timedelta(days=1)`
in the no-data-at-all branch.

**[STYL] `backfill_many`'s try/except** (your edit) is good defensive
coding. Matches `update_many`. Worth a docstring example showing the
"error" shape consumers can expect.

---

### `nsw/update.py`

**[STYL] Top-of-file comment** says "in one or two chunks" but the
implementation does a single `fetch_history` call (line 58) — which
could cover up to 100 days for 1m or 366 for 1d. If updates are run
daily, this is always a single tiny call. If someone goes a year
between updates, the 1m update would exceed Fyers' per-call window
and fail. Add a safeguard: if `(to_d - from_d).days` exceeds
`MAX_DAYS_PER_CALL[interval]`, delegate to `backfill.backfill_symbol`
instead. Currently relies on the user updating frequently enough.

**[STYL] `update_many`'s try/except** (your edit) is good.

---

### `nsw/loader.py`

**[IMPT] Empty-DataFrame path skips tz conversion** (lines 132-135).
Early return on `df.empty` bypasses the `effective_tz` block. Result:
an empty DataFrame's index has no tz, but a non-empty one has IST. If
downstream code does `df.index.tz_convert(...)`, it'll fail on the
empty case. Fix: apply tz to the empty frame too, or just don't
early-return until after tz is applied.

**[IMPT] The `to_date + 86399` trick is UTC-day-inclusive, not
IST-day-inclusive** (line 130). If you ask for `to_date="2024-01-31"`
expecting "everything up through Jan 31 IST", you get everything up
through Jan 31 23:59:59 UTC, which excludes Jan 31 23:30 IST onwards.
For Indian-market data (market closes 15:30 IST = 10:00 UTC) this
doesn't matter. Worth a docstring note.

**[STYL] `update` kwarg shadows the `update` module** (line 89, 24,
122). Worked around with `from . import update as update_mod`
inside the function. Cleaner: rename the kwarg to `refresh` or
`fetch_fresh`. Minor breaking change so do it before more code calls
`load_data(...,  update=True)`.

**[MINR] `_date_to_ts(td) + 86399`** is a magic number. Define
`_END_OF_DAY_SECONDS = 86399` at module level for readability.

---

### `nsw/server.py`

**[IMPT] `datetime.utcnow()` is deprecated.** Used in `_ensure_cert`
at lines 89, 90. Same fix as `config.py` — `datetime.now(timezone.utc)`.

**[IMPT] `_jobs` global dict never garbage-collected.** Every
backfill/update click adds an entry. Each entry is small (~100 bytes
of metadata) but in a multi-hour session you can rack up dozens. For
a server kept running for days, this matters. Fix: bound to last N
(e.g. `collections.OrderedDict` with eviction at N=100) or expire
by `updated_at`.

**[IMPT] Job IDs use `int(datetime.now().timestamp())`** (lines 221,
234). Two clicks in the same second collide. Use `uuid.uuid4().hex`
or a global counter + lock. With single-user localhost this is
mostly theoretical, but the symptom (two job IDs map to the same
entry, second overwrites first's progress) would be confusing.

**[IMPT] `/callback` returns exception details** (line 186) as the
HTTP body when token exchange fails. Could leak token-related error
text. Localhost-only so the impact is bounded, but logging the
detail server-side and returning a generic message client-side is
better practice.

**[MINR] No CSRF protection on POST endpoints.** Localhost-only, so
the impact is bounded — but if you ever expose the server to LAN, a
malicious page that calls `/api/credentials` could overwrite your
Fyers keys. Add a simple secret header check if we ever go LAN.

**[MINR] Werkzeug dev server.** Documented limitation. For a research
tool, fine. If we ever expose it broadly, swap to `waitress` or
`gunicorn`.

**[STYL] `webbrowser.open(url)` catches `Exception` broadly** (line
286-288). Specific exceptions (no display, etc.) would be cleaner,
but the broad catch is harmless.

---

### `pyproject.toml`

**[MINR] `nsw = ["py.typed"]` package-data entry** references a file
that doesn't exist. Either:

- Create an empty `nsw/py.typed` to signal to type checkers that the
  package is fully type-annotated, OR
- Remove the line.

Currently it's a harmless no-op but misleading.

---

### `requirements.txt` vs `pyproject.toml` dependencies

**[STYL] Duplicate declaration.** Both files list the same 7
packages. `pip install -e .` (from pyproject) installs them; the
launcher then also runs `pip install -r requirements.txt` (same
list). Functionally identical but unnecessary work and a maintenance
risk (someone adds a dep to one and forgets the other).

Two clean options:

- Drop `requirements.txt` entirely. The launcher's
  `pip install -e .` reads pyproject and pulls deps. Single source of
  truth.
- Keep `requirements.txt` for pip beginners but auto-generate it from
  pyproject in CI / a pre-commit hook.

Option 1 is cleaner. Try it.

---

### `start_nsw.bat`

Solid. Three small things:

**[MINR] `setlocal enabledelayedexpansion`** is set but only used in
the hash comparison (line 97). Fine either way.

**[STYL] `set "VENV_DIR=..\.venv"`** is correct but using
`"%~dp0..\.venv"` would give an absolute path, which is more robust
in edge cases (e.g. if some sub-command changes cwd). Minor.

**[STYL] The `pip install --upgrade pip`** runs every time
requirements change. pip upgrades are slow and rarely needed. Skip it
unless we hit a known-old-pip bug.

---

### `backup.bat`

Clean. One observation:

**[STYL] `wmic` is deprecated** in Windows 11 24H2+ (officially
removed in future versions). The timestamped-default-commit-message
relies on `wmic os get LocalDateTime`. Replace with PowerShell:

```cmd
for /f "delims=" %%I in ('powershell -NoProfile -Command "(Get-Date -Format yyyy-MM-dd_HH:mm)"') do set "STAMP=%%I"
```

Or just let Python compute it. Future-proofing — wmic still works
today but won't forever.

---

### `scripts/seed_indices.py` and `scripts/update_all.py`

**[MINR] `sys.path.insert(0, …)`** at the top (line 19 / 17) is
leftover from before the editable install. Now redundant — `nsw` is
pip-installed into the shared venv, so `from nsw import …` works
without path tweaking. Remove the `sys.path` line.

**[STYL] `noqa: E402`** comments next to imports are no longer needed
once the `sys.path.insert` is gone.

---

### `examples/load_example.py` and `examples/test_everything.py`

Same `sys.path.insert` leftover. Remove for the same reason.

`test_everything.py` is a solid smoke test. Not a proper unit test
(no isolation, no mocking) but it's a real end-to-end exerciser and
that's valuable.

---

### `templates/setup.html`

Read it earlier in the project — clean single-page UI with
embedded JS. Three observations:

**[MINR] App ID is a text input,** Secret Key is a password input.
Consistent — App ID isn't sensitive, Secret Key is. Good.

**[STYL] Inline JavaScript** in a `<script>` tag at the bottom. Fine
for a single-page admin UI; if it grows, move to `static/js/`.

**[STYL] Coverage table timestamps** are rendered server-side as raw
ints (lines using `{{ row.earliest_ts | int }}`) and then re-rendered
client-side with `new Date(n * 1000)`. Two formats coexist briefly on
page load. Mild visual flicker. Fine.

---

## Architectural observations

### Strengths reinforced by the review

1. The **layering is honest**. NSW does data, nothing else. No
   indicator math, no strategy logic, no plotting. The temptation to
   add a "load_data_with_emas" convenience was resisted. Good.

2. The **`load_data` function is the entire public surface.** Other
   modules are internal (well, they're importable, but the README
   tells users to call only loader). This is the right granularity.

3. The **base-interval restriction** prevents an entire class of bugs
   (stored 5m vs derived 5m drifting). Strong design choice.

### Weaknesses / debt

1. **No tests.** `test_everything.py` is a smoke test, not a unit
   test suite. For NSW today it's tolerable. As we build the
   backtester on top, we want unit tests for resample math, OHLC
   invariants, the backfill walk-backwards loop, and the soft-empty
   handling. Cheap to add later but compound interest.

2. **No CI / linting.** No `ruff`, no `mypy`, no GitHub Actions. For
   a one-person project this is fine. The day a second person
   contributes (or you come back to it in 6 months and forget the
   conventions), CI saves you.

3. **`_jobs` server state.** Memory leak in long-running server.
   Mentioned above.

4. **No way to inspect / debug the SQLite store from inside NSW.** No
   `nsw inspect` CLI showing "what's in the DB right now?" Not a
   missing feature, just a future ergonomic improvement.

5. **No retry budget shared across calls.** Each `fetch_history` has
   its own retry counter. A bulk backfill that hits transient errors
   on every chunk would silently burn through `chunks × retries × 3
   seconds`. A circuit breaker at `backfill_many` level would be a
   nice addition.

---

## Security

| Item | Status |
|---|---|
| `config.json` gitignored | ✓ |
| Real credentials in `config.example.json` | ✗ (placeholders only — correct) |
| Server bound to 127.0.0.1 only | ✓ |
| Self-signed cert documented | ✓ |
| `cert.pem` / `key.pem` gitignored | ✓ |
| CSRF on POST endpoints | ✗ (acceptable for localhost) |
| Error messages leak token exchange details | ✗ (low impact, localhost only) |
| Logs scrub credentials | not checked — `fyersApi.log` may contain auth headers, worth a one-time inspection |

---

## Action items (recommended order)

Quick wins, ~1-2 hours total:

1. **[IMPT] Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`**
   in `config.py` (2 places) and `server.py` (2 places).
2. **[IMPT] Fix the `load_data` empty-DataFrame tz inconsistency.**
   Apply tz to the empty frame too.
3. **[IMPT] Bound `_jobs` in `server.py`** to last 100 entries via
   `OrderedDict` + eviction.
4. **[IMPT] Use UUID-based job IDs** instead of unix timestamps.
5. **[MINR] Drop `requirements.txt`** in favor of `pyproject.toml`
   alone; update `start_nsw.bat` to do only `pip install -e .` (which
   pulls deps automatically).
6. **[MINR] Remove `sys.path.insert`** from `scripts/*.py` and
   `examples/*.py` now that editable install is in place.
7. **[MINR] Hoist `import time`** to module level in `backfill.py`
   and `database.py`.
8. **[MINR] Floor-fallback in `backfill.py`** when no data at all —
   record floor as `end_d + 1` instead of `end_d`.

Slightly bigger, ~half a day:

9. **[IMPT] Update.py: detect when the update window exceeds
   `MAX_DAYS_PER_CALL`** and delegate to backfill.
10. **[STYL] wmic → PowerShell** in `backup.bat`.
11. **[MINR] Empty `nsw/py.typed`** to back up the package-data
    declaration in `pyproject.toml`, OR remove the line.

Future-proofing, weekend project:

12. Add unit tests (`pytest`) covering: symbol resolver, timeframe
    base lookup, resample math, OHLC invariants, backfill walk-
    backwards mock'd against a fake Fyers, config auto-recovery.
13. Add a `ruff` config + a `make lint` target.
14. Add a tiny `nsw doctor` CLI that inspects the SQLite store and
    reports anomalies (gaps in 1m data, OHLC violations, stale
    backfill_state).

---

## Verdict

NSW is **production-quality for a research tool**. The active bugs
are zero. The latent issues are real but small. The architecture is
right and supports the backtester / viz / live modules cleanly.

Recommended next move: knock out items 1-4 above (~30 min), then back
up the changes, then start the backtester. Don't let perfect become
the enemy of good.

---

*Reviewer: Claude · 2026-05-16*
