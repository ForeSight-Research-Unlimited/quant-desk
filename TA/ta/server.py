"""TA chart server -- serves the page + computes candles, EMAs, and indicators.

Routes:
    GET /               -> the chart page
    GET /api/candles    -> JSON: candles + EMA overlays + registry indicators
    GET/POST /api/preferences

Data comes from NSW (`load_data`). EMAs are a built-in overlay family with their
own toggle/color UI. Everything else is a registered indicator (see
ta/library.py + ta/registry.py): the server runs each one and ships generic plot
data tagged with its pane ("price" overlay or "lower" own-pane). The browser
just draws what we send.

Time convention: bar timestamps are UTC epoch seconds; the frontend adds a fixed
IST offset so the x-axis reads Asia/Kolkata.
"""

from __future__ import annotations

import math

from flask import Flask, jsonify, render_template, request

from nsw.loader import load_data

from . import indicators, prefs, registry
from . import library  # noqa: F401  -- importing runs the @indicator decorators

app = Flask(__name__)

SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
TIMEFRAMES = [
    "1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m", "45m", "90m", "1h",
    "2h", "3h", "4h", "6h", "8h", "12h",
    "1d", "2d", "3d", "1w", "2w", "3w", "1Mo", "2Mo", "3Mo", "6Mo", "12Mo",
]

# Built-in EMA overlay family (special toggle/color UI). Single source: prefs.py.
EMA_PERIODS = prefs.EMA_PERIODS


def _epoch_utc(index) -> list[int]:
    """tz-aware DatetimeIndex -> UTC epoch seconds (frontend adds IST).

    Per-bar Timestamp.timestamp() because under pandas 3.0 the index can be
    non-nanosecond resolution, so the int64 view isn't reliably nanoseconds.
    """
    return [int(ts.timestamp()) for ts in index]


def _line(epochs, series, keep_gaps=False) -> list[dict]:
    """[{timestamp, value}, ...]. NaN -> dropped, or kept as {timestamp} (a
    whitespace point) when keep_gaps -- lower panes need full-length, gapped
    series so their bar indices stay aligned with the price chart for sync.
    """
    out = []
    for ts, val in zip(epochs, series.to_numpy()):
        if val is None or (isinstance(val, float) and math.isnan(val)):
            if keep_gaps:
                out.append({"timestamp": ts})
        else:
            out.append({"timestamp": ts, "value": float(val)})
    return out


@app.route("/")
def index():
    return render_template(
        "chart.html",
        symbols=SYMBOLS,
        timeframes=TIMEFRAMES,
        ema_periods=EMA_PERIODS,
        indicators=registry.meta(),
    )


@app.route("/api/preferences", methods=["GET"])
def get_preferences():
    resp = jsonify(prefs.load_prefs())
    resp.headers["Cache-Control"] = "no-store"  # always fetch fresh prefs
    return resp


@app.route("/api/preferences", methods=["POST"])
def save_preferences():
    return jsonify(prefs.save_prefs(request.get_json(silent=True) or {}))


@app.route("/api/candles")
def candles():
    symbol = request.args.get("symbol", "NIFTY")
    tf = request.args.get("tf", "1d")

    bars_raw = request.args.get("bars", "").strip()
    try:
        bars = int(bars_raw)
    except ValueError:
        bars = 0
    bars = bars if bars > 0 else None

    df_full = load_data(symbol, tf)
    if df_full.empty:
        return jsonify({"symbol": symbol, "tf": tf, "candles": [], "emas": {}, "overlays": [], "panes": []})

    closes = df_full["close"]
    emas_full = {p: indicators.ema(closes, p) for p in EMA_PERIODS}

    # Run every registered indicator on the full history (so it's warmed up).
    # A buggy indicator must not 500 the whole chart -- log and skip it.
    results = []  # (IndicatorDef, list[Plot])
    for d in registry.all_indicators():
        try:
            plots = d.func(df_full, **d.defaults)
        except Exception as e:  # noqa: BLE001 -- one indicator shouldn't kill the rest
            app.logger.warning("indicator %s failed: %s", d.id, e)
            plots = []
        results.append((d, plots))

    # Keep the most-recent `bars` rows (or all), aligned by index.
    df = df_full if bars is None else df_full.tail(bars)
    idx = df.index
    epochs = _epoch_utc(idx)

    o, h, low, c, v = (df[col].to_numpy() for col in ("open", "high", "low", "close", "volume"))
    candle_rows = [
        {"timestamp": epochs[i], "open": float(o[i]), "high": float(h[i]),
         "low": float(low[i]), "close": float(c[i]), "volume": int(v[i])}
        for i in range(len(epochs))
    ]

    emas_out = {str(p): _line(epochs, emas_full[p].reindex(idx)) for p in EMA_PERIODS}

    overlays, panes = [], []
    for d, plots in results:
        group = {
            "id": d.id,
            "name": d.name,
            "plots": [
                {
                    "key": p.key, "label": p.label, "kind": p.kind, "color": p.color,
                    "data": _line(epochs, p.data.reindex(idx), keep_gaps=(d.pane == "lower")),
                }
                for p in plots
            ],
        }
        (overlays if d.pane == "price" else panes).append(group)

    return jsonify({
        "symbol": symbol, "tf": tf,
        "candles": candle_rows,
        "emas": emas_out,
        "overlays": overlays,
        "panes": panes,
    })


def main():
    print("=" * 60)
    print(" TA chart server -- http://127.0.0.1:5002/")
    print(" Ctrl+C to stop.")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5002, debug=False)


if __name__ == "__main__":
    main()
