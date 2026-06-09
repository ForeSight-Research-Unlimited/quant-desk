"""TA -- technical-analysis + charting layer for Quant Desk.

Reads candles from NSW (`nsw.loader.load_data`), computes indicators in
`ta.indicators` (pure Python -- one source of truth the backtester can reuse),
and renders them in the browser with TradingView Lightweight Charts via a small
Flask app (`ta.server`).

v1 scope: static charts only (no live updates). One price chart (OHLC + EMA
overlay + volume) plus a derivatives pane below it.
"""

__version__ = "0.1.0"
