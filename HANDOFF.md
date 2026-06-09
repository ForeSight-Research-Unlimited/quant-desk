# Quant Desk — Handoff Brief for a Fresh Chat Instance

Paste this whole document into a new Claude conversation as your first
message. It contains everything the new instance needs to pick up
where the previous one left off without re-asking basics.

---

## Who I am, what I'm building

I'm KCF at KCF Capital / Foresight Research Unlimited
(`foresightresearchunlimited@gmail.com`). I'm building a quant
trading stack — a monorepo of modules that together cover data
ingest, indicators, backtesting, visualisation, and live
execution.

**OS:** The project was originally built on Windows. As of
2026-05-18 the codebase has been made cross-platform: `.sh`
launchers added alongside the `.bat` ones, VSCode settings
de-Windows-ified, all Python was already portable. Intended
primary OS going forward is Ubuntu Linux; Windows still works
as a fallback.

I have a legacy codebase at
`D:\KCF Capital\FRU\Claude\Claude Co-Work\Quant Desk\Project1 - Original\`
that I'm revamping in chunks. **Don't modify Project1** — it's
reference material only. The full overview of what it contained
is in `Project1 - Original_OVERVIEW.md` at the workspace root.

## Workspace layout (as of this handoff)

```
D:\KCF Capital\FRU\Claude\Claude Co-Work\Quant Desk\        <-- monorepo root
├── .venv\                          shared Python venv, used by every module
├── .vscode\settings.json           pins VSCode interpreter at the shared venv
├── README.md                       monorepo overview, how shared venv works
├── KNOWN_BUGS.md                   8 footguns with symptoms + exact fixes
├── NSW_CODE_REVIEW.md              recent deep-dive review of NSW
├── HANDOFF.md                      this file
├── Project1 - Original_OVERVIEW.md old-codebase reference map
├── requirements-dev.txt            shared research libs (matplotlib, scipy, etc.)
├── test1.py                        my scratch script — uses nsw.loader.load_data
│
├── NSW\                            data layer (done, production-ready)
│   ├── pyproject.toml              installable as `nsw`, editable in shared venv
│   ├── start_nsw.bat / .sh         one-click launcher (Windows / Linux)
│   ├── backup.bat / .sh            one-click git push to private GitHub
│   ├── diagnostic.bat / .sh        shell sanity check
│   ├── nsw\                        the package
│   ├── candles.db                  SQLite store (NSW-owned, gitignored)
│   ├── config.json                 LIVE Fyers credentials (gitignored)
│   ├── README.md, MANUAL.md        NSW docs
│   └── ...
│
├── TA\                             technical analysis (NEXT — discussion phase)
│   ├── ta\                         empty placeholder
│   └── examples\                   empty placeholder
│
├── Project1 - Original\            legacy, untouched, reference only
└── trading-dashboard\              older sibling project, not Quant Desk
```

## What's already built and working

**NSW (data layer)** — battle-tested. Stores 1m and 1d candles for
NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY in SQLite at
`NSW\candles.db`. Derives all 24 user-facing timeframes (5m, 15m,
1h, 1w, 3Mo etc.) on read via pandas resample with closed-left
/ label-left / Monday-anchored / OHLCV-correct aggregation. Fyers
v3 API integration with OAuth, chunked backfill walking backwards,
incremental tail update, browser-based setup page at
`https://127.0.0.1:5001/`. Default tz is Asia/Kolkata. Backed up
(with the whole monorepo) to private repo
`ForeSight-Research-Unlimited/quant-desk`.

**Public API I use from any Python script:**
```python
from nsw.loader import load_data, export_csv, get_coverage
df = load_data("NIFTY", "15m", from_date="2024-01-01", tz="Asia/Kolkata")
```

**Shared venv at `Quant Desk\.venv\`** — every module installs into
this single venv. NSW is editably installed there
(`pip install -e .` triggered by `start_nsw.bat`). VSCode is
pre-pointed at it via `.vscode/settings.json`.

## Architecture decisions already locked in (don't re-litigate)

1. **Monorepo, nested modules.** Each module is its own folder with
   its own `pyproject.toml`, editably installed into the shared
   venv. NSW today, future modules: `quantdesk` (backtester),
   `ta` (technical analysis — current focus), `viz`, `live`.
2. **NSW stores only 1m + 1d.** Every other timeframe is derived on
   read. Single source of truth.
3. **Default tz is Asia/Kolkata.** Override per call with
   `tz="UTC"` if needed.
4. **Backtester architecture (planned, not built):** signal
   generation vectorised in pandas, execution simulation
   event-driven. Strategy class carries a `FrictionModel` for
   fee/impact-aware signal filtering. First strategy to port: EMA
   Relative Slope from Project1.
5. **Backups: one monorepo.** The whole workspace backs up to
   `ForeSight-Research-Unlimited/quant-desk` via `./backup.sh` at the
   workspace root. (Superseded the old per-module repos.)

## Communication style — what works for me

- **Be terse.** Long text blocks lose me. Prefer short paragraphs
  and small lists.
- **Have opinions and push back.** If I propose something dumb,
  tell me. Use phrases like "my lean is X because Y" — I want
  your read, not just options.
- **No premature abstraction.** Build the thing once, refactor when
  the second use-case shows up.
- **No unit-test maximalism (yet).** Smoke tests are fine. We're
  still in the research phase.
- **Save memory aggressively.** Use the auto-memory system so future
  conversations don't re-derive context. Save user preferences,
  project state, leaked-credential warnings, decisions made.
- **Educate as you go.** When you fix `_jobs` memory leak, also
  explain *what `_jobs` is and why it's leaking* — I'm learning.
- **No emoji unless I ask.** Don't pepper responses with them.
- **Casual cursing is fine.** I curse freely. You don't have to,
  but don't filter me.
- **Use the AskUserQuestion tool sparingly.** Only for genuine
  forks where I need to decide. Don't ask permission for things
  you can just do.
- **Trust but verify.** When you write code, re-read the file you
  just wrote. When you claim a fix works, smoke-test it.

## Workflow pattern

I run Python on my machine (Ubuntu Linux as of the 2026-05-18
migration; Windows still works). You write/edit code from a
sandbox that mounts my workspace folder. The sandbox **cannot
reliably run Python against the mounted files** due to mount
permission and `__pycache__` issues — so:

1. You edit files via the Edit/Write tools.
2. I run the result on my machine (terminal on Linux,
   CMD/VSCode F5 on Windows).
3. I paste the output back. You diagnose from that.

## Reference docs the new instance should know about

Read these as needed before answering anything substantial:

- `Quant Desk\README.md` — monorepo overview, first-time setup.
- `Quant Desk\KNOWN_BUGS.md` — symptoms + fixes for 9 known
  footguns we've already hit (numpy bytecode-cache, stale .pyc,
  .bat encoding, NameError vs ModuleNotFoundError, aiohttp on
  Python 3.13, empty config.json 500, Fyers no_data soft-empty,
  daily token expiry, debugpy cold-start KeyboardInterrupt).
  Most of #1, #2, #3, #5 are Windows-flavoured and largely go
  away on Linux.
- `Quant Desk\NSW_CODE_REVIEW.md` — recent deep-dive review of
  NSW with severity-tagged findings. We've already fixed all the
  IMPT items except update.py auto-delegate-to-backfill (deferred
  by me).
- `Quant Desk\NSW\README.md` — quick start, one-click launcher
  workflow.
- `Quant Desk\NSW\MANUAL.md` — comprehensive NSW reference, 18
  sections covering architecture, storage, OAuth, backfill,
  resampling, public API, browser GUI, CLI scripts, backups,
  troubleshooting, extension points.
- `Quant Desk\Project1 - Original_OVERVIEW.md` — what the legacy
  codebase contained, module by module. Useful when porting.

## Sensitive info / security notes

- `NSW\config.json` contains live Fyers `app_id`, `secret_key`,
  `access_token`. **Gitignored.** Never commit. Never paste in
  chat.
- `Project1 - Original\live_trading\` has hardcoded Upstox
  credentials committed in plaintext. If we ever push Project1
  anywhere, rotate first.
- Fyers tokens expire daily. Re-auth via the setup page each
  trading day. This is part of normal operation, not a bug.

## UPDATE (2026-06-09) — read this first; the section below is now history

Two big things happened since this handoff was written:

1. **Migrated to Ubuntu and de-fragmented setup.** Windows `.bat` files
   deleted (Ubuntu-only now). A new **`first_install/`** folder owns the
   shared venv — run `./first_install/install.sh` once to build `.venv` and
   editable-install every module in `first_install/modules.txt` (NSW + TA) plus
   research libs. Module launchers (`NSW/start_nsw.sh`, `TA/start_ta.sh`) only
   run their server now; they don't touch the venv.

2. **TA module v1 is BUILT and working** — and it did NOT go the matplotlib
   route this handoff proposed. KCF rejected matplotlib as slow/clunky, so TA is
   a **Flask web app rendering TradingView Lightweight Charts** (reusing his old
   `trading-dashboard` stack), fed by NSW. Price pane (OHLC + EMA overlays +
   volume) + a lower derivatives pane; indicators computed in Python
   (`ta.indicators`); colors/EMAs persisted to `TA/preferences.json`; Alt+I/Alt+R
   hotkeys. Runs on `http://127.0.0.1:5002/` via `TA/start_ta.sh`. NSW was also
   extended with timeframes 6h/8h/12h/12Mo.

This project now uses the **auto-memory system** (not the paste-this-doc flow).
The authoritative current state lives in the memory files — see the
`project-ta-module`, `project-ubuntu-env`, `project-quantdesk-state` memories.
The original TA-discussion notes below are kept for history only.

## Current state of play — what we were about to do (HISTORICAL — see update above)

We were just starting a new chunk: **the TA module** (Technical
Analysis), which revamps Project1's `fin_stocks_analysis.py` (806
lines) and `drawer.py` (626 lines).

I asked Claude to "get a sense of how fin_analysis worked, then
tell me how we can revamp it." Claude wrote up a substantial
proposal. I said "let's discuss first, we'll get to making the
actual module later." Claude paused before any TA code touches
disk.

**What `fin_stocks_analysis.py` did (so the new instance knows
without re-reading):** procedural script that prompted for a
ticker, fetched yfinance history, computed a stack of indicators
(DMA, EMA, RSI, BB, Stoch, Vol, Candle Strength, Trend Strength,
1st/2nd diffs), then **opened ~17 separate matplotlib windows** —
OHLC alone, OHLC+trend strength, close-only line, OHLC+DMA
overlay, OHLC+fast/slow DMA with diffs, OHLC+DMA-difference bars
(MACD-style), same suite for EMA, OHLC+MACD multi-EMA, OHLC+volume
with mean/std, standardised close, OHLC+RSI with thresholds,
OHLC+Bollinger, OHLC+Stoch Osc, OHLC+volatility relative. Each
chart attached a `Drawer(ax, fig)` and a `MultiCursor` for
crosshair sync. After all 17 figures closed, dropped into
`code.interact(local=locals())` for ad-hoc exploration.

**What `drawer.py` did:** one `Drawer(ax, fig)` class that
decorated a matplotlib axes with interactive markup — line drawer,
horizontal/vertical lines, rectangle, long-position rectangle with
auto 1/3 R:R, short-position rectangle, Fibonacci retracement (0
/ 14.6 / 23.6 / 38.2 / 61.8 / 100 / 161.8 %), and a regression-line
drawer (double-click points then click button to fit). Checkbox
toolbar hard-positioned at figure-normalised `[0.85, ...]` coords.
Uses blocking `plt.ginput(1)` for the second click of a drag.

**Proposed TA revamp shape (not yet built):**

```python
from ta.session import ChartSession

session = ChartSession("NIFTY", "1d", from_date="2020-01-01")
session.plot_ohlc()
session.plot_ema_overlay()
session.plot_macd(fast=10, slow=25)
session.plot_rsi()
session.plot_bollinger_bands()
session.plot_volume()
session.plot_volatility()

# or batch
session.plot_preset("standard_research")

# save instead of show
fig = session.plot_macd(show=False); fig.savefig("nifty_macd.png")
session.export_all_to_pdf("nifty_analysis.pdf")
```

Proposed folder layout:

```
TA/
├── pyproject.toml                  installable as `ta`, depends on nsw
├── ta/
│   ├── session.py                  ChartSession class
│   ├── indicators.py               vectorised indicator math
│   ├── primitives/                 ohlc.py, overlay.py, subplot.py, derivative.py
│   ├── drawer.py                   (optional) rewritten interactive toolbar
│   ├── presets.py                  named chart sets
│   └── export.py                   save_png / save_pdf
└── examples/analyse_nifty.py
```

Things to drop from the original: input() ticker prompt,
yfinance direct fetch (use NSW), bare except + halt-and-wait, the
17-window auto-blast, `code.interact`, hardcoded widget coords,
blocking `plt.ginput`, `import inline` / `import keyboard`.

Things to add: multi-symbol overlay, multi-timeframe overlay,
notebook-friendly Figures, annotation persistence (save/load
drawn shapes as JSON), PDF export of multi-chart sessions.

**Five open questions I (SJ) need to answer before any TA code is
written:**

1. **Drawer scope.** (a) Port faithfully — all 8 tools, fix bugs.
   (b) Reduce — just line / horizontal / rect / Fibonacci for v1.
   (c) Defer entirely — TA v1 is static charts only.
   *Claude's lean: (c) defer.*

2. **Plot library.** matplotlib + mplfinance (what the original
   used), lightweight-charts (TradingView-style, what
   trading-dashboard used), or plotly?
   *Claude's lean: matplotlib + mplfinance for v1.*

3. **Chart coverage.** Full 17 views vs curated ~8 (OHLC, EMA
   overlay, MACD, RSI, Bollinger, Stoch, Volume, Volatility)?
   *Claude's lean: curated 8.*

4. **Indicators ownership.** Own copy in `ta.indicators` now,
   extract to shared `quantdesk.indicators` when the backtester
   needs them; or pre-emptively shared from day one?
   *Claude's lean: own copy now, extract later.*

5. **Anything I (SJ) specifically want preserved** from the
   original (candle-strength indicator, standardised-close chart,
   volume-with-mean-std bands, the long/short R:R rectangles,
   the regression-line drawer)?
   *Need user input.*

## Most useful next prompts the new instance should expect from me

- "I want to answer the TA questions: 1 is X, 2 is Y, ..."
- "Build the TA v1 now."
- "Wait — first I want to talk about (some other chunk)."
- "Fix this bug in NSW: <error>"
- "Update the backup workflow to also do X."

## Working agreement summary

- I write the goals, you propose the design, I push back, you
  implement.
- Don't auto-implement large modules without confirming the
  shape with me first.
- For small fixes (one or two files, clear bug), just do it and
  show me the diff.
- Always verify your own work — re-read the file after editing,
  smoke-test logic in the sandbox where possible.
- Save useful memories so the next chat already knows this.

---

*Handoff written 2026-05-17. Next chunk: TA module discussion → implementation.*
