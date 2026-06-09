# Project1 - Original — Codebase Overview

A reference snapshot built from a full read-through of the codebase on 2026-05-09. Use this as a shared mental model heading into the chunked revamp.

## What this codebase is

A research-and-execution stack for systematic trading, built incrementally in plain Python (~21K lines across ~100 files). It targets the Indian markets — primarily the Nifty 50 index (`^NSEI`) and Bank Nifty, with some ETF and single-stock work. There are three layers stacked together:

1. **Research / backtest** — pulls historical OHLC from `yfinance`, computes indicators, runs strategies bar-by-bar, scores them with a performance-analytics module, and renders charts.
2. **Live test (paper trade)** — same logic loop but driven by polling `yfinance` data on a timer. Never connected to a broker.
3. **Live trading** — a separate, production-style flow that authenticates against the Upstox v2 REST API, fetches LTPs, places market orders, persists per-day state in JSON, and runs day-specific strategies (the "Dhan Vibhor" series for Mon→Tue, Tue→Wed, and Thu).

The author's working hypothesis appears to be that the **EMA Relative Slope** signal — `(EMA - EMA.shift(1)) / EMA` — combined with carefully chosen buy/sell thresholds is the edge. Most of the backtest variants explore that one idea: long-only, short-only, long-short, with one signal length, two signal lengths, with a rolling re-fit window, with train/test split, with second-signal confirmation, and so on. Other strategy families (Bollinger Band breakout, EMA crossover, EMA slope without the relative term, day-specific overnight Dhan-Vibhor scalp) live alongside it.

## Top-level layout

```
Project1 - Original/
├─ data_functions/        OHLC fetch + indicator library + portfolio save (foundation)
├─ database/              CSV cache (currently empty; populated on first run)
├─ MPT/                   Mean-variance portfolio optimisation (random-portfolio Sharpe sort)
├─ ML/                    Single MLPRegressor experiment on Nifty
├─ analysis/              Standalone studies: drawer (matplotlib annotation tool),
│                          gate_study, indexMaxxing, returns_analysis
├─ backtest/              The strategy zoo — see below
├─ rolling_strategies/    Rolling-window re-evaluation of EMA rel-slope
├─ live_testing/          yfinance-polled paper-trading loop
├─ live_trading/          Upstox-API live execution + Dhan-Vibhor day strategies
├─ trading_system/        Near-duplicate of live_trading (dead/older fork)
├─ performance_analysis/  run_analysis.py (older), run_analysis_v2.py (active)
├─ graphing_functions/    QtChart/lightweight-charts dashboards + matplotlib helpers
├─ fin_stocks_analysis/   Interactive single-stock study tool with drawing GUI
├─ experiments/           Scratch pad — early ideas, fin_stocks_analysis_org (1983 lines), tradingview_dash
├─ Reports/               One sub-folder of .docx writeups (EMA Relative Slope train/test)
└─ results/               Strategy-portfolio CSV outputs (per ticker)
```

Root level holds entry stubs (`analysis.py`, `buffer.py`), a tiny `requirements.txt` (numpy, pandas, matplotlib, yfinance, scipy, mplfinance, scikit-learn), a one-line `read_me.txt` ("Infrastructure for retrieval of data and efficient backtesting"), and a few placeholder files.

## Data flow

**Backtest path:** `data_functions/get_data.py::tickerData()` wraps `yf.Ticker(...).history(...)` with a CSV cache under `./database/{symbol}-{period}-{date}-{interval}.csv`. `data_functions/get_indicators.py` exposes pure functions for DMA, EMA, EMA Net Movement, RSI, Bollinger Bands, rolling and EW volatility, Stochastic Oscillator, Candle Strength, Trend Strength, MFI (stub), and Histogram. A strategy script imports these, builds a `portfolio` and `marketPortfolio` DataFrame with columns `[Value, AssetNum, Cash, bought, sold]`, iterates over the price index, and at each bar applies the entry/exit rule and updates cash/holdings. After the loop, it constructs a `performance_analysis.run_analysis_v2.analytics(...)` object and calls `get_results()` for the metric printout, then plots via `graphing_functions/plotPortfolio` and `analyze_trades`.

**Live path:** `live_trading/setup.py` runs the OAuth code-grant against Upstox, opens the consent URL in the browser, and writes `live_trading/database/curr_session.json` with `client_id`, `client_secret`, `access_token`, `auth_code`, and `curr_time`. `live_trading/tradeFunc.py` defines a `trade_sys` class that wraps the Upstox endpoints: `get_ltp`, `get_OHLC`, `market_order`, `order_details`, `get_funds`, `get_positions`, `get_holdings`, plus an NSE instrument-symbol↔key mapping loaded from `NSE.csv`. `live_trading/updateDatabase.py` periodically refreshes 1m / 30m / day candles for NIFTY50, BANKNIFTY, and NIFTYMOMENTUM into `live_trading/database/<symbol>/<symbol>-<interval>.csv`. The Dhan-Vibhor scripts (`live_DVStrat_long_mon_tue.py` etc.) run as scheduled jobs: each day they read/write a per-date JSON in `live_trading/strategy_trades/<strat>/<YYYY-MM-DD>.json` to remember whether the leg has fired, and place a `MARKET` order at the right side of the right window.

## Performance analytics (`performance_analysis/run_analysis_v2.py`)

A single `analytics` class accepting `(data1, ticker, interval, portfolio, marketPortfolio, profits, losses, riskFreeRate)`. Methods compute portfolio returns, CAGR (portfolio / market / excess), market-deviation stats, AUC ratio, Sharpe ratio (annualised, day-step), drawdown, profit/loss ratios, alpha (CAPM-style with covar/var beta), and 95%/99% Value at Risk. `get_results()` aggregates everything into a metrics dict and prints a formatted block. There is a composite "profitability" score: `avgProfLossRatio · numProfNumLossRatio · AUCRatio · (CAGR_port/CAGR_market) · (1 + alpha%)`. The class header lists desired-but-unbuilt metrics: Sortino, Calmar, capture, holding period, rolling perf, correlation, Monte Carlo, MAE/MFE, turnover.

## Strategy zoo in `backtest/`

* **`ema_strats/`** is the densest folder — 30-plus files, many `…copy.py` / `…copy 2.py` / `…copy 5.py` siblings, indicating live experimentation. The canonical pair is `ema_rel_slope_L_strat.py` (driver) and `ema_rel_slope_L_strat_func.py` (parameter-sweep grid optimiser, sweeps signal lengths × buy/sell thresholds drawn from mean ± 3σ of the rel-slope distribution). Variants: long-only (`_L_`), short-only (`_S_`), long-short (`_LS_`), two-signal long (`_2S_L_`), with confirmation (`_2Sig`), with explicit signal logging (`_signals`), with train/test split (`_tt_split`).
* **`bollinger_band_strats/`** — breakout-vs-band strategy on `^NSEI 1h`.
* **`market_closed_strats/`** — overnight scalps. `DV_L.py` always longs prev-close → next-open. `DV_LS_day_specific.py` longs Mon→Tue and Tue→Wed (close→open) and shorts Thursday open→close. The fee model is `min(₹30, notional × 0.05)` per side.
* **`rolling_strategies/`** — runs the EMA rel-slope strat across rolling 250-day windows and writes a per-window metrics CSV under `results/<ticker>/rolling/`.

## Modeling experiments

* **`MPT/`** is a self-contained mean-variance toy: pulls daily returns for a small basket (Nifty + ETFs, or a hand-picked stock list), generates 100K random portfolios, scores by Sharpe (with `risk_free_rate = 0.07`), averages weights of the top-100 highest-Sharpe portfolios, and renders the efficient-frontier scatter via Plotly plus a PyQt/lightweight-charts portfolio plot. It re-implements `getData` and `getIndicators` locally rather than reusing `data_functions/`.
* **`ML/ml_test1.py`** is a single MLPRegressor (5-layer dense, ReLU, Adam) predicting next-bar `Close` for Nifty from a feature stack of prior-bar OHLC, EMAs, EMA rel-slope, Stochastic Oscillator, RSI, BB, and volatility. It trades a one-step-ahead direction signal and reports MSE/R²/MAE plus profit/loss summary. No proper walk-forward, no feature scaling, no cross-validation.
* **`analysis/`** — three small studies: `gate_study/gates_analysis.py` (load tickers from an Excel of "successful gates", fetch multi-timeframe history, compute log-returns), `indexMaxxing/analysis.py` (cumulative all-time-high study with SIP), `returns_analysis/analysis_1.py` (1d/1wk/1mo log-return histograms with mean ± n·σ markers).

## Visualisation

Two co-existing stacks. The matplotlib-based one (`analysis/drawer.py`, `graphing_functions/drawer.py`, `fin_analysis_copy.py` at 1635 lines) builds an interactive single-stock study app with line/horizontal/vertical/rectangle/Fibonacci-retracement/long-short-position drawing tools and a regression-line drawer using mpl widgets. The PyQt + lightweight-charts stack (`plotPortfolio.py`, `analyze_trades.py`, `mptPortfolio.py`, `experiments/plot_stock_qt.py`, `experiments/plot_stock_qt_2.py`) renders strategy-vs-benchmark equity curves and OHLC sub-charts in a Qt window. There is also a Streamlit + TradingView-embed prototype in `experiments/tradingview_dash.py`.

## Observations relevant to the revamp

The codebase has clearly grown by accretion — an idea was tried, copied, evolved in the copy, and the original was kept "just in case." That gives you a rich library of attempts but also a lot of weight to carry. Things worth knowing before we start cutting:

**Layout and packaging.** Every file does `sys.path.append("..")` and then imports as `Project1.something.module`. This relies on the CWD being one level above `Project1 - Original/`, and on the folder being renamed to `Project1`. There is no `pyproject.toml` / `setup.py`, no installable package, no tests, and no CI. Strategy scripts are run as `__main__`, not orchestrated.

**Duplication.** `live_trading/` and `trading_system/` are near-identical forks of the same Upstox wrapper — `trading_system/setup.py` even still leaks the same OAuth secret into `setup.py` literals. `MPT/get_data.py` and `MPT/get_indicators.py` are forks of the `data_functions/` versions. The EMA-rel-slope family has more than ten "copy" files in `backtest/ema_strats/`. There's also `live_trading/database/` and `live_trading/database - Copy/`. These are the natural first targets for consolidation.

**Hardcoded paths.** Backslash Windows paths like `r".\database\..."`, `r".\live_trading\strategy_trades\..."` are everywhere. They depend on the script being launched from one specific CWD and won't run on Linux without changes.

**Performance.** Most metrics in `run_analysis_v2.py` (Sharpe, VaR, drawdown, market-dev) iterate the index in pure Python with `+ relativedelta(days=1)` membership checks. On hourly data over 700 days that's tolerable; on long daily histories it is slow and on intraday minute data it would be painful. Vectorising these is low-hanging fruit.

**Error handling.** Most modules wrap their entire body in `try: ... except: print(traceback); input("\nError BC.\n")`. The `input()` makes any failure block a process — fine for an interactive desktop session, fatal for a scheduled job. Many files end with `code.interact(local=locals())` for ad-hoc inspection — also a process-blocker.

**Single source of truth.** The same EMA-rel-slope decision logic is reimplemented in `backtest/ema_strats/ema_rel_slope_L_strat.py`, in `backtest/rolling_strategies/ema_rel_slope_roll_func.py`, in `live_testing/ema_rel_slope_L_live.py`, and partially in the live-trading scripts. Right now they can drift independently. A small `Strategy` interface that both backtest and live execution call into would unify them.

**Data abstractions.** `tickerData` mixes "fetch" with "cache" with "format" and uses different filename schemas in different code paths (some include the date, some don't, some use period, some use start/end). There's no centralised store, no schema, and the main `database/` directory is currently empty. The Upstox-side OHLC store under `live_trading/database/<symbol>/` does have data but it's keyed by interval-as-string ("1minute", "30minute", "day") which differs from the yfinance side.

**Security — flag this immediately.** `live_trading/database/curr_session.json` and `live_trading/setup.py` contain a hardcoded Upstox `client_id`, `client_secret`, `access_token`, and `auth_code` in plaintext, committed inside the project folder I just read. Even though the Upstox token has expiry, the `client_secret` does not. Before we share or push this anywhere, those credentials need to be rotated in the Upstox dashboard and moved to a `.env` / OS keychain / vault. The same secret is duplicated in `trading_system/setup.py`. I won't repeat the values back; just flagging that they are present in the repo.

**Library hygiene.** `requirements.txt` lists only seven packages but the code imports `yfinance`, `pytz`, `keyboard`, `pickle`, `mplfinance`, `lightweight_charts`, `PyQt5`, `plotly`, `requests`, `tqdm`, `scipy`, `streamlit`, `tensorflow`-adjacent ML, and even `import inline` (which is a Jupyter-era artefact and will fail on a fresh install). There's also `import sklearn as sk` next to `import sklearn` — minor but indicative.

## Suggested mental model for the revamp (for discussion, not a plan)

If we're carving this into chunks, the natural seams I see are:

1. **Foundation** — a clean `quantdesk` package with `data/` (one OHLC store + one indicator library), `metrics/` (vectorised performance analytics), and `strategy/` (a base class). Replaces `data_functions/`, `performance_analysis/`, the duplicated `MPT/get_*`.
2. **Backtest engine** — one event loop that takes `(data, strategy, fees)` and returns `(portfolio, trades, metrics)`. Replaces every `*_strat.py` with a small strategy class.
3. **Strategy library** — port the survivors from `backtest/ema_strats/`, `bollinger_band_strats/`, `market_closed_strats/`, deduplicate the "copy" siblings, drop dead variants.
4. **Optimiser** — port `*_strat_func.py` and `rolling_strategies/` into a parameter-sweep harness.
5. **Live execution** — collapse `live_trading/` and `trading_system/` into one broker module, push secrets to env/secret store, replace per-day JSON state with something testable.
6. **Visualisation** — pick one stack (matplotlib for static, lightweight-charts for interactive) and remove the other.
7. **Modeling** — decide whether `MPT/` and `ML/` survive, and if so, rebuild them on the new foundation.

This ordering means we always have a working backtest while we go.

---

Generated by Claude on 2026-05-09 from a full read of the project tree. If anything below diverges from your understanding of the project's intent, say so before we pick the first chunk to revamp.
