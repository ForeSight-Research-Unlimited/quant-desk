# TA — technical analysis + charting

The visualization/indicator layer for Quant Desk. Reads candles from NSW,
computes indicators in Python, and renders them in the browser with
TradingView **Lightweight Charts** (the same stack as the old options
dashboard, re-pointed at NSW).

## v1 scope (barebones, static)

- One **price chart**: OHLC candles + EMA overlay + volume panel.
- One **derivatives pane** below it: 1st and 2nd derivative of the EMA,
  time-synced to the price chart.
- Symbol / timeframe / bar-count controls (all 28 NSW timeframes).
- **Indicators dropdown:** EMA 10/20/50/100/200/400 — toggle on/off and recolor each.
- **Settings dropdown:** colors for background, grid, candle up/down, and the two
  derivative lines.
- **Preferences persist** to `TA/preferences.json` (colors + which EMAs are on),
  so the chart looks the same across restarts/browsers. Changes apply live and save
  automatically. The file is gitignored (per-machine).
- **Hotkeys:** `Alt+I` invert the price scale · `Alt+R` reset the view (fit + autoscale).
- **Static only** — loads history on demand. No live updating yet (later chunk).
- No interactive drawing tools yet (the "drawer" — later chunk).

## Run

The shared venv must exist first (built once by `first_install/install.sh`,
which also installs TA — see the manifest `first_install/modules.txt`).

```bash
cd TA
./start_ta.sh
```

Then open <http://127.0.0.1:5002/>. Pick a symbol/timeframe, hit **Load**.

> Make sure NSW's `candles.db` has data for the symbol/timeframe (run NSW's
> backfill/update first). TA only reads it via `nsw.loader.load_data`.

## Layout

```
TA/
├── pyproject.toml          installable as `ta` (sibling of nsw in the shared venv)
├── start_ta.sh             launch the chart server (mirrors NSW/start_nsw.sh)
├── ta/
│   ├── indicators.py       pure-Python indicator math (EMA, derivatives, rel-slope)
│   ├── server.py           Flask: serves the page + /api/candles
│   ├── templates/chart.html
│   └── static/
│       ├── css/styles.css
│       └── js/
│           ├── ta_chart.js                          the renderer (adapted)
│           └── lightweight-charts.standalone.production.js   (v4.1.3, vendored)
└── examples/
```

## Design notes

- **Indicators live in Python** (`ta.indicators`), not JS. The browser just
  draws what the server sends. Reason: the backtester will need the same math
  and can't import JavaScript — one source of truth.
- **Time handling:** the server sends UTC epoch seconds; `ta_chart.js` adds a
  fixed `IST_OFFSET` (+19800s) so the x-axis reads Asia/Kolkata. Don't split
  that differently — mixing tz handling backend/frontend caused bugs before.
- **Lightweight Charts v4.1.3** is vendored locally. Don't bump to v5 without
  porting the series API (`addCandlestickSeries` → `addSeries(...)`).
- **Panes:** v4 has no native multi-pane, so the derivatives pane is a second
  chart instance with its time scale synced to the price chart. Multi-pane /
  multi-window strategy is a later decision.
