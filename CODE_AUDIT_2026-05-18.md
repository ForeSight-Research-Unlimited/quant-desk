# Quant Desk — Full Codebase Audit (2026-05-18)

Scope: every file in the workspace root, the NSW module, and the entire
`Project1 - Original` legacy tree. The TA module is empty and excluded.
Findings are severity-tagged:

- **CRIT** — will bite, fix now (or before any external exposure)
- **HIGH** — latent issue, fix soon
- **MED** — nice-to-have / micro-improvement
- **LOW** — preference / style
- **INFO** — observation, not a defect

This audit is fresh from a file-by-file read, but it also cross-checks
the prior `NSW_CODE_REVIEW.md` (2026-05-16) to confirm which items were
actually fixed vs. which slipped through.

---

## Executive summary

**NSW is in very good shape.** All four of the prior review's IMPT
items in the Python code have been fixed and verified at specific
line numbers (datetime.utcnow → timezone.utc, UUID job IDs,
OrderedDict-bounded `_jobs`, empty-DataFrame tz applied uniformly).
What remains is a small set of HIGH/MED issues — one structural
(update.py auto-delegate, deferred by the user), the rest are
local refactors that take minutes each.

**The build / scaffolding is solid** with two leftover items: an
unused `requirements.txt` stub that still lives next to a deprecated
notice, and a declared-but-missing `nsw/py.typed` marker. Both are
trivial.

**Project1 - Original carries one CRIT item** — committed live
Upstox credentials (client_id, client_secret, access tokens, auth
codes) in `live_trading/setup.py`, `trading_system/setup.py`, and
both modules' `database/curr_session.json`. This is the only item
in this audit that needs action before the folder is ever pushed,
shared, or backed up. The auto-memory already notes this; this
audit confirms it.

Beyond that one CRIT, Project1's other findings are not "bugs to
fix" — they're a risk register for the revamp: a list of patterns
that look like features but will hurt you if ported. Block-on-error
`input()` traps. `code.interact()` at script ends. Hardcoded
Windows backslash paths. Eleven near-identical copies of the EMA
relative slope strategy. A `live_trading/` ↔ `trading_system/` fork
that is the same code with different folder names.

The single highest-leverage cross-cutting takeaway: the legacy
codebase grew by **copying-and-evolving** rather than refactoring.
NSW already broke that pattern. The TA module is the next chance
to keep it broken. The audit's recommendations cluster around
"don't import these habits."

---

## Part 1 — NSW package (`NSW/nsw/*.py`)

Status of prior review's IMPT items, verified line-by-line:

| Prior IMPT | Location now | Status |
|---|---|---|
| `datetime.utcnow()` deprecation | config.py:71,175 / server.py:85,92 | **FIXED** — uses `datetime.now(timezone.utc)` |
| `_jobs` unbounded growth | server.py:127-151 | **FIXED** — OrderedDict, `_JOBS_MAX=100`, popitem(last=False) on overflow |
| Job-ID collision (unix-timestamp clash) | server.py:134 | **FIXED** — `uuid.uuid4().hex` |
| `load_data` empty-DataFrame skips tz | loader.py:148-160 | **FIXED** — `_rows_to_frame` returns tz-aware empty index; tz_convert applied uniformly after resample |
| `set_backfill_state` read-then-write race | database.py:233-253 | Open (still single-writer-only, docstring annotation pending) |
| `update.py` window-size delegate | update.py:30-67 | **OPEN BY DESIGN** — user deferred. Still only delegates when no data exists. A 200-day gap with 1m interval will fail. |
| `last_error` mixed-type in fyers_client | fyers_client.py:~199,223,230 | Open (no custom exception class yet) |
| Linear retry backoff (2s,4s,6s) | fyers_client.py:236-237 | Open (still linear) |
| `floor_ts` fallback when first chunk empty | backfill.py:114-120 | **FIXED** — now records `end_d + 1` rather than `end_d` |

### New / still-open findings, by file

#### `nsw/__init__.py`

INFO — Trivial (version + docstring). Nothing to flag.

#### `nsw/config.py`

**HIGH — `set_fyers_credentials` compares unstripped values** (lines
153, 156). If the stored `app_id` is `"ABC"` and the caller passes
`"ABC "` (trailing space — easy with copy-paste from the Fyers
dashboard), the function treats them as different and clears the
access token unnecessarily. Strip both sides before comparing, or
just always clear the token on this code path and re-auth — the
latter is simpler and defensive.

INFO — `_PLACEHOLDER_VALUES_UPPER` is now hoisted to module level
(was a per-call set comprehension). Fixed cleanly.

LOW — `set_fyers_credentials` still uses an untyped dict for the
loaded config. A `TypedDict` would surface schema drift at type-check
time. Bigger refactor; not urgent.

#### `nsw/symbols.py`

INFO — Clean. The reverse-lookup loop in `resolve` is O(n) but
n=4. When stocks land (n~50–500), swap to a dict-of-lower-cased-aliases
lookup. Not now.

#### `nsw/database.py`

**HIGH — `set_backfill_state` is read-then-write**, no SQL-level
merge. Two concurrent writers for the same `(symbol, interval)`
will lose one update. Today the backfill loop is single-writer-per-pair
so this is theoretical. The fix is either:

- Move the merge into SQL: `UPDATE ... WHERE ts < new_ts` style.
- Or just put the constraint in the docstring (`single writer per
  (symbol, interval) only`) and don't ever parallelise per-pair.

The docstring annotation alone is enough for now. Do it before any
parallel-backfill experiment.

MED — `coverage_summary` makes 3 queries per `(symbol, interval)`
pair. For 4×2=24 pairs that's 24×3=72 queries on every setup-page
load. Trivially collapsible to one `SELECT symbol, interval,
COUNT(*), MIN(ts), MAX(ts) FROM candles GROUP BY symbol, interval`.
Not perceptible today; will matter at stock-universe scale.

LOW — `get_earliest_timestamp` and `get_latest_timestamp` could
be one query (`SELECT MIN(ts), MAX(ts)`). Same shape as above.

LOW — `import time as _time` inside `set_backfill_state` (line
~232). Hoist to module level.

#### `nsw/timeframes.py`

INFO — Clean. Aggregation rules correct (`first/max/min/last/sum`
on `o/h/l/c/v`), closed-left, label-left, Monday-anchored. Nothing
to flag.

#### `nsw/fyers_client.py`

**HIGH — `last_error` is mixed-type** (Fyers response dict, or
Exception, or None). It gets stringified into the final
`RuntimeError` message which works, but a caller catching
`RuntimeError` can't programmatically distinguish a rate-limit
from an auth-failure from a malformed response. Worth a small
`FyersHistoryError` subclass that holds the structured payload as
an attribute. Five-minute change.

**HIGH — Retry backoff is linear** (2s, 4s, 6s; total ~12s across
3 attempts). For rate-limit-induced failures (HTTP 429), exponential
(2, 4, 8, 16) is friendlier to the API and more likely to succeed
on the third try. Tunable via the existing kwarg, but the default
should match Fyers' published guidance.

LOW — `no_data` detection uses both a tuple membership check and a
substring check. Kept as-is in the prior review (the underscore-vs-
space distinction makes both checks meaningful). Confirmed correct.

LOW — Lazy SDK import via `_fyers_module()` is good. Module
remains importable for linting / tests without `fyers-apiv3`
installed.

#### `nsw/backfill.py`

INFO — Floor-fallback on the empty-first-chunk path is now correct
(records `end_d + 1`).

INFO — `update_many`-style try/except wrapping `backfill_many` is
in place. Good.

LOW — `import time` inside the loop body (line ~157). Hoist.

LOW — `progress_cb` invocation on the empty-chunk path says
"chunk 34: ... 0 rows" — fine, but if you want a setup-page log
that's less confusing, emit a distinct event type
(`{"event": "floor_reached", ...}`). Cosmetic.

#### `nsw/update.py`

**HIGH (DEFERRED BY USER) — No safeguard when `(to_d - from_d).days >
MAX_DAYS_PER_CALL[interval]`.** Today: a user running daily-or-weekly
updates hits one tiny call. A user who goes 200 days without
running an update on the 1m interval will silently fail because
Fyers' 100-day-per-call window is exceeded. Two options:

- Delegate to `backfill.backfill_symbol` when the window is
  oversized.
- Slice the range into multiple `fetch_history` calls.

The user has deferred this. Keep in the known-open queue.

LOW — Docstring still says "in one or two chunks" but the
implementation is one chunk. Cosmetic.

#### `nsw/loader.py`

INFO — Empty-DataFrame tz path is now uniform. Verified at
lines 148-160 in current code: resample happens first (pandas
handles empty input), then `tz_convert` is applied to the index
unconditionally. The bug the prior review flagged is gone.

LOW — `to_date` is still UTC-day-inclusive (`+ _END_OF_DAY_SECONDS`).
For Indian-market data (close 15:30 IST = 10:00 UTC), this never
truncates any real bar. Docstring at lines 268-272 covers it. Not
a bug, but if NSW ever serves a market that trades past 23:30 UTC
(e.g., 24-hour FX), it bites. Document or convert to IST-day end
on the spot.

LOW — `update` kwarg shadows the `update` module. The internal
workaround (`from . import update as update_mod`) is fine. Renaming
the kwarg to `refresh` would be cleaner but it's a breaking change
to the public API. Do it before more code calls
`load_data(..., update=True)`, not after.

#### `nsw/server.py`

INFO — All four prior-review IMPT items here are fixed:
`utcnow()` replaced, UUID-based job IDs (line 134), `_jobs` bounded
to `_JOBS_MAX=100` with `OrderedDict` eviction (lines 127-151,
also pushes accessed jobs to the end via `move_to_end` so LRU
eviction is correct).

MED — `/callback` still returns exception details verbatim on token
exchange failure. Localhost-only so the blast radius is bounded; log
server-side and return a generic message client-side.

MED — No CSRF protection on POST endpoints. Acceptable for
127.0.0.1 binding. Re-evaluate if the server ever exposes a LAN
port.

MED — Werkzeug dev server. Documented limitation. Swap to
`waitress` if it ever exposes beyond localhost.

LOW — `webbrowser.open(url)` catches `Exception` broadly. Harmless.

#### `nsw/examples/` and `nsw/scripts/`

INFO — `sys.path.insert` hacks removed from all four files
(`scripts/seed_indices.py`, `scripts/update_all.py`,
`examples/load_example.py`, `examples/test_everything.py`). Editable
install does the job.

INFO — `test_everything.py` is a strong end-to-end smoke test.
Not a unit test (no isolation, no fakes for Fyers), but it
exercises the real public API end-to-end including the resampling
path. Keep it; add isolated unit tests around it, don't replace it.

### NSW summary

Zero CRIT findings. Three HIGH findings open (set_fyers_credentials
strip, last_error structured exception, retry backoff exponential).
One HIGH **deferred by user** (update.py window-size delegate).
Everything else is MED/LOW polish.

---

## Part 2 — Build & scaffolding files

#### `NSW/pyproject.toml`

**MED — `nsw = ["py.typed"]` package-data entry references a file
that doesn't exist.** Either create an empty `NSW/nsw/py.typed`
(signals to mypy/pyright that the package is fully typed — and it
nearly is) or remove the line. Currently it's a misleading no-op.
Two-second fix.

INFO — Build-system block uses `setuptools >= 61`. Dependencies
are pinned only at the upper end (`< X`) for fyers, otherwise
loose. Fine for a research tool; consider a lockfile (`pip-tools`
or `uv lock`) once you start sharing the venv across machines.

#### `NSW/requirements.txt`

**MED — Stale-by-design stub still exists.** The file itself
documents that it's deprecated and that `pyproject.toml` is the
source of truth, and `start_nsw.bat` already uses `pip install -e .`
exclusively. But the file is still on disk, still lists every
dependency, and a fresh contributor who types
`pip install -r requirements.txt` will install a copy that can drift
from pyproject. Three options:

- Delete it.
- Leave it but auto-generate from pyproject in a pre-commit or
  `make` target.
- Leave it and accept the drift risk (current state).

Deleting it is the cleanest move. The launcher doesn't read it
anyway.

#### `NSW/.gitignore`

INFO — Covers candles.db, candles.db-wal, candles.db-shm,
config.json, cert.pem, key.pem, *.log, __pycache__, .venv,
nsw.egg-info. Verified complete. Good.

#### `NSW/start_nsw.bat`

INFO — Pure ASCII (confirmed; KNOWN_BUGS.md item #3 stays
relevant for future edits). Hash-based dep-refresh works correctly
on both requirements.txt and pyproject.toml. Editable install via
`pip install -e .`. Self-signed cert generation. Stale `.pyc`
cleanup. Failure paths pause. Solid.

LOW — `pip install --upgrade pip` runs on every refresh-cycle. pip
upgrades are slow and rarely necessary. Skip unless you hit an
old-pip bug.

LOW — `set "VENV_DIR=..\.venv"` is relative. Works because
`cd /d "%~dp0"` anchors first. Could use `%~dp0..\.venv` for
fully-absolute path. Cosmetic.

#### `NSW/backup.bat`

INFO — `wmic` replacement to PowerShell-`Get-Date` has landed (was
flagged in prior review; now confirmed). Pure ASCII. Push step
included.

#### `NSW/diagnostic.bat`

INFO — Tiny (5 lines). Prints venv + Python + nsw install state.
Useful. Nothing to flag.

#### `NSW/config.example.json`

INFO — Placeholder values only (`YOUR_FYERS_APP_ID_HERE`, empty
token fields). No real secrets. ✓

#### `NSW/templates/setup.html`

INFO — Inline JS, no external resources, no `eval`, no
`innerHTML` on user-supplied input. Jinja2 auto-escape on template
variables. CSRF intentionally absent given localhost binding.
Coverage-table timestamps re-rendered client-side; mild flicker on
page load. Acceptable.

LOW — `tr.innerHTML = \`<td>${row.symbol}</td>...\`` (line ~277) is
safe today because the data comes from `/api/coverage` which is
server-generated. If the data source ever becomes user-driven,
escape first. Note for the future, not a fix today.

#### `.vscode/settings.json`

INFO — Points at `${workspaceFolder}\\.venv\\Scripts\\python.exe`.
Correct.

#### `README.md` (workspace root) and `NSW/README.md`

**MED — Both READMEs claim the launcher runs
`pip install -r requirements.txt`.** Current `start_nsw.bat` uses
only `pip install -e .` (which pulls deps via pyproject). Workspace
README at line 41, NSW README at the corresponding section. Update
the wording to match reality. One-line edit each.

#### `requirements-dev.txt`

INFO — Lists matplotlib, scipy, jupyter, etc. — shared research
deps that don't belong to any specific module. Sane.

#### `test1.py`

INFO — Six-line scratch script. Uses the canonical NSW pattern
(`import nsw` + `from nsw.loader import load_data`). Matches
KNOWN_BUGS item #4. Fine.

LOW — `range(len(data1))` for the x-axis throws away the
DatetimeIndex. Cosmetic for a scratch file, but worth changing
to `data1.index` if it ever graduates beyond scratch.

#### `HANDOFF.md`

INFO — Mostly accurate. One claim to flag: it asserts "we've
already fixed all the IMPT items except update.py auto-delegate"
— this audit confirms that's true for the four code-level IMPT
items the launcher cares about, but two additional HIGH items
(`set_fyers_credentials` unstripped compare, `fyers_client`
mixed-type `last_error`, linear retry backoff) remain open. Not
a contradiction; just a sharper accounting.

### Scaffolding summary

No CRIT. Three MED items (requirements.txt stub, py.typed missing,
README launcher description). Everything else is verified clean.

---

## Part 3 — `Project1 - Original` risk register

Reference-only. Do not modify. The findings below are about what
**not to port** into the revamp.

### 3.1 Security — CRIT

**CRIT — Live Upstox credentials committed in plaintext.** Three
files:

- `Project1 - Original/live_trading/setup.py` (around lines 29-30:
  `client_id`, `client_secret`, `state`)
- `Project1 - Original/trading_system/setup.py` (same lines, same
  credentials — `trading_system/` is a fork of `live_trading/`)
- `Project1 - Original/live_trading/database/curr_session.json`
  (full auth bundle: `client_id`, `client_secret`, `access_token`,
  `auth_code`, `curr_time`)
- `Project1 - Original/trading_system/database/curr_session.json`
  (same shape — confirm whether it has the same values or only
  client metadata)

Access tokens may have expired (Upstox tokens are short-lived),
but the **client_secret** does not auto-expire and is a usable
credential indefinitely until rotated in the Upstox dashboard.

**Action required before this folder is ever pushed to GitHub,
shared with anyone, included in a backup that leaves your machine,
or committed to any git repo:**

1. Rotate the Upstox `client_secret` in the Upstox developer
   dashboard. (The auto-memory already flags this; this audit
   confirms it.)
2. Revoke the existing `access_token` from the same dashboard.
3. Scrub these files from the project. Either delete the files
   outright (they're for a defunct paper-trading rig per the
   handoff context) or replace the credential values with
   placeholders matching `config.example.json`'s pattern.
4. **If Project1 is or has ever been in any git repo, rotation is
   non-negotiable** — credentials in git history are reachable
   even after a "delete and commit" pass. Confirm Project1 is
   *not* version-controlled (it's in the workspace folder but
   doesn't appear to have a `.git` of its own; verify).

This is the only CRIT item in the entire audit.

### 3.2 Footguns to NOT port — HIGH

These are patterns that look like features but are bugs in
disguise. None of them should make it into the TA / quantdesk
modules.

**HIGH — Block-on-error `input("Error BC")` pattern.** Catches
every exception, prints traceback, then blocks on user input. Found
in:

- `fin_stocks_analysis/fin_stocks_analysis.py` (multiple `except`
  blocks)
- `trading_system/tradeFunc.py`
- `exception_code.py` (a 9-line snippet that exists only to
  demonstrate this anti-pattern)

Effect: scheduled/headless runs hang forever on any unhandled error.
Drop entirely; use `logging.exception` instead.

**HIGH — `code.interact(local=locals())` at script end.** Drops
the script into an interactive REPL after main work completes.
Found in:

- `analysis.py` (line ~28)
- `live_trading/setup.py` (line ~109)
- `fin_stocks_analysis/fin_stocks_analysis.py` (end of file)

Effect: scripts never exit cleanly. Useful interactively, fatal in
production / scheduled use. Strip during port.

**HIGH — Hardcoded relative Windows paths.** Everywhere, e.g.:

- `r"\database"`, `r"\database\%s"` in `fin_stocks_analysis.py`
- `r".\live_trading\database"` in `live_trading/setup.py`
- `r".\live_trading\database\curr_session.json"` in
  `live_trading/tradeFunc.py`

Effect: only runs from one specific CWD; doesn't run on
Linux/macOS; breaks the moment folders are renamed. Replace with
`pathlib.Path(__file__).parent / "..."` or module-level
`DATA_DIR` constants resolved at import time.

**HIGH — `sys.path.append("..")` import-hack.** Used in
`analysis.py:17`, `live_trading/setup.py:21`,
`trading_system/setup.py:20`, and most strategy scripts. Requires
that the parent of `Project1 - Original/` is on the Python path,
which requires the folder to be renamed to `Project1` (no space, no
"- Original" suffix). NSW already solved this with an editable
install. Don't re-import the hack.

**HIGH — Eleven near-identical EMA-rel-slope strategy files in
`backtest/ema_strats/`.** The canonical pair is
`ema_rel_slope_L_strat.py` + `ema_rel_slope_L_strat_func.py`.
Siblings:

- `ema_rel_slope_L_strat copy.py`, `... copy 2.py`, `... copy 4.py`,
  `... copy 5.py`
- `ema_rel_slope_L_strat_org.py`, `... _org copy.py`
- `ema_rel_slope_L_strat_2Sig.py` (with confirmation)
- `ema_rel_slope_L_strat_signals.py` (with logging)
- `ema_rel_slope_L_strat_tt_split.py` (with train/test split)

Plus the `_S_` (short-only) and `_LS_` (long-short) variants in
parallel. Don't port them as 11 files. Port the latest canonical
variant as a parameterised `Strategy` class. The "copy" files are
git-via-Finder; let `git log` carry that history once we're in
git.

**HIGH — `live_trading/` ↔ `trading_system/` near-identical fork.**
Same Upstox wrapper, same OAuth flow, same secret. `trading_system/`
appears to be an older fork that didn't get updates. Pick one
(probably `live_trading/`); confirm what unique logic — if any —
lives only in `trading_system/`; then drop the other.

### 3.3 Drift / duplication — MED

**MED — `live_trading/database/` and `live_trading/database -
Copy/`.** Parallel OHLC CSVs. The "- Copy" folder is a manual
backup, not version control. Once NSW owns OHLC, both go away.

**MED — `fin_stocks_analysis/fin_stocks_analysis copy.py` and
`... copy 2.py`** alongside the canonical file. Same pattern as
the EMA strategy files. Port one (the most recent / most-used),
not three.

**MED — `MPT/get_data.py` and `MPT/get_indicators.py` are
forks of `data_functions/*`.** Don't port them. The shared
`data` and `indicators` layer (NSW + future `quantdesk.indicators`)
covers what MPT needs.

### 3.4 Dead / inert files — LOW

- `analysis.py` (root, 28 lines, ends with `code.interact()`) —
  unused entry stub. Delete during port.
- `buffer.py` (58 bytes) — empty placeholder. Delete.
- `banana.txt` (12 bytes) — actual `banana.txt`. Delete.
- `read_me.txt` (63 bytes, one-line description) — superseded by
  any modern README. Delete.
- `libs_install.py` — attempts to `pip install math`, `time`,
  `datetime` (all stdlib). Broken setup script. Delete.
- `exception_code.py` (94 bytes) — demonstrates the input-on-error
  anti-pattern. Delete; it's documentation of a thing not to do.
- `experiments/` — ad-hoc scratch (`exp1.py`, `exp2.py`,
  `test.py`, `plot_stock_qt*.py`, `fin_stocks_analysis_org.py`,
  `tradingview_dash.py`, `open_close_analysis.py`). Skim each for
  salvageable ideas, archive or delete in bulk.

### 3.5 Dependency reality — MED

`Project1 - Original/requirements.txt` declares only seven packages
(numpy, pandas, matplotlib, yfinance, scipy, mplfinance,
scikit-learn). Actually imported elsewhere in the tree:

- `requests`, `urllib.parse` — live_trading
- `python-dateutil` (`relativedelta`) — performance_analysis,
  several strategies
- `keyboard` — drawer.py, fin_stocks_analysis
- `inline` — fin_stocks_analysis, drawer.py. **This package
  doesn't exist on PyPI;** it's a Jupyter-era artefact that some
  IDEs used to fake. A fresh install will fail.
- `pytz` — `analysis/indexMaxxing/`
- `PyQt5`, `lightweight_charts`, `plotly`, `tqdm`, `streamlit` —
  graphing/experiments

Net: a fresh `pip install -r requirements.txt` would import-error
on most modules. Not relevant to fix (this is reference code),
just *important context for porting* — if we ever try to "just run
the old code to compare," we'll spend an hour on dependency
plumbing first.

### 3.6 OHLC store inconsistency — MED

Three distinct CSV-naming schemas across the legacy tree:

1. **Ticker / interval folders** (`live_trading/database/`):
   `BANKNIFTY/BANKNIFTY-1minute.csv`, `BANKNIFTY-30minute.csv`,
   `BANKNIFTY-day.csv` — uses `"1minute"`, `"30minute"`, `"day"`
   as interval strings.
2. **Backtest cache** (`database/`, currently empty):
   `{symbol}-{period}-{date}-{interval}.csv` — uses `yfinance`-
   style intervals (`"1h"`, `"1d"`, `"1wk"`).
3. **Results portfolio CSVs** (`results/^NSEI/`):
   `Portfolio-^NSEI-1h-2024-05-03-91-EMA Relative Slope Strategy.csv`
   — embeds strategy name in filename, mixes `1h` and `1D` (case
   inconsistency).

NSW has already normalised this for OHLC (one schema, derived
intervals on read). The lesson for the next chunks: pick the
canonical interval-string set once (NSW uses `1m`, `5m`, ..., `1d`,
`1w`, `1Mo`, `3Mo`) and route everything through it.

### 3.7 Other observations — INFO

- **No tests anywhere in Project1.** Not a finding (it's research
  code), but a reason to add tests early in the new modules so we
  don't repeat the pattern.
- **All logging is `print()`.** No `logging` module use anywhere in
  the legacy tree. NSW uses `logging` correctly; keep that.
- **CSVs read with type-inferred `pd.read_csv`** with no schema
  pinning. Easy silent data corruption surface. NSW's SQLite +
  explicit columns is the right answer; keep it.
- **No CI, no linting, no type hints.** Whole-tree statement, not a
  finding. NSW already has type hints; add `ruff` + `mypy` to NSW
  and any new module from day one.

---

## Part 4 — Cross-cutting takeaways

### What's working

1. **NSW's architecture is right.** Single responsibility per
   module, base-only storage with read-time resampling, atomic
   config writes, WAL-mode SQLite with thread-local connections,
   bounded server-side job state. The prior code review's IMPT
   list has been closed cleanly. Don't second-guess the structure;
   build on it.

2. **The monorepo / shared-venv discipline is paying off.** Every
   module installs editable into one venv. `from nsw.loader import
   load_data` works from anywhere. The TA module can drop into
   this with minimal ceremony.

3. **The launcher is genuinely production-grade for a desktop
   tool.** Self-signed cert generation, hash-based dep refresh,
   stale-pyc cleanup, failure-path pause. The same template will
   work for `start_ta.bat`, `start_quantdesk.bat`.

### What to actively avoid

1. **Don't grow new modules by copy-and-evolve.** The EMA-rel-slope
   eleven-copies tax is real. When a new variant is needed, do a
   small refactor that parameterises the difference and writes one
   file. If you can't refactor cheaply, write a separate file with
   a clearer name.

2. **Don't wrap whole scripts in bare `except` + `input()`.** Every
   chunk we port has to make a deliberate choice on its error
   model. The path of least resistance is `logging.exception`
   under a single top-level handler.

3. **Don't `code.interact()` at script ends.** Use a REPL externally
   (`python -i your_script.py`) when you want post-mortem
   inspection.

4. **Don't import secrets.** This audit found one set of committed
   credentials. The remediation is to keep secrets out of source
   forever — Fyers credentials in `config.json` (gitignored, the
   NSW pattern), Upstox-or-equivalent credentials the same way.

5. **Don't add new code to `Project1 - Original/`.** It's reference.
   When porting needs a comparison run, fork into a temp folder
   outside the workspace, rotate any secrets first.

### Things worth investing in before the backtester lands

1. **Unit tests for NSW's resample math** (`timeframes.py`). The
   property is "an N-minute candle from base 1m matches Fyers'
   own N-minute candle to within OHLC tolerance." This is testable
   without a network: fixture 100 minutes of synthetic 1m bars,
   resample, compare. Two hours of work, infinite value.

2. **Unit tests for the soft-empty / `no_data` path.** Mock Fyers,
   feed `{"s": "no_data"}`, confirm the floor is recorded at
   `end_d + 1` and the loop stops. Half a day's work.

3. **`ruff` + `mypy` config at workspace root.** Lints every
   module the same way. Surfaces drift early.

4. **A small `nsw doctor` CLI** that prints what's in the DB and
   any anomalies (gaps in 1m series, OHLC violations, stale
   `backfill_state`). Saves debugging trips into `sqlite3` directly.

None of these are blocking the next chunk; all of them compound.

---

## Part 5 — Recommended action ladder

**Do today (before anything else):**

1. **Rotate the Upstox `client_secret`** in the Upstox developer
   dashboard. Confirm Project1 is not in any git repo. (5 minutes
   of dashboard clicking.)

**Quick wins, ~30 minutes total:**

2. Create empty `NSW/nsw/py.typed` (or remove the line from
   `pyproject.toml`).
3. Delete `NSW/requirements.txt` (launcher doesn't read it).
4. Fix `Quant Desk/README.md` line 41 and `NSW/README.md` to say
   `pip install -e .` instead of `pip install -r requirements.txt`.
5. Strip values before comparing in
   `nsw/config.py::set_fyers_credentials`.

**Slightly bigger, ~1 hour total:**

6. Add a `FyersHistoryError` exception class in `fyers_client.py`
   that holds the structured payload; raise it instead of plain
   `RuntimeError`.
7. Switch retry backoff to exponential
   (`base * 2 ** (attempt - 1)`) with a sane cap.
8. Add a single-writer docstring note on
   `nsw/database.py::set_backfill_state`.

**Already deferred by user — keep on the open list:**

9. `update.py` window-size delegate to backfill.

**Future-proofing (weekend project, do once TA is moving):**

10. Unit tests around `timeframes.resample`,
    `backfill.backfill_symbol` (mocked), `loader.load_data` edge
    cases.
11. `ruff` + `mypy` config at workspace root, applied to NSW.
12. `nsw doctor` CLI for store introspection.

**Project1 — only when actually porting that chunk:**

13. Don't port the eleven EMA-rel-slope copies, the
    `live_trading`/`trading_system` fork, the `database - Copy/`,
    or any of the dead-code files listed in §3.4. Port the
    canonical variant of each strategy into a `quantdesk.strategy`
    class.

---

## Verdict

The NSW data layer is **production-quality** for a single-user
research tool. The build scaffolding around it is **solid** with
three trivial cleanups outstanding. The legacy `Project1 - Original`
tree carries **one CRIT item** (committed Upstox credentials) that
needs action before any external share, and a long tail of
patterns that should *not* be ported into the revamp.

Reading this audit and then doing the action ladder's "today" and
"quick wins" lines puts the codebase in a position where the only
open structural item is the deferred `update.py` window-size guard.
Everything else is small-bore polish that can land alongside the
TA module work without blocking it.

Recommended next move: handle the CRIT (rotate Upstox secret),
knock the quick wins, then move on to the TA module discussion.

---

*Auditor: Claude · 2026-05-18 · Workspace: `D:\KCF Capital\FRU\Claude\Claude Co-Work\Quant Desk\`*
