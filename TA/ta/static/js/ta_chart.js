/**
 * TA renderer (TradingView Lightweight Charts v4).
 *
 * Price chart (candles + volume + EMA overlays + registry "price" overlays) plus
 * a dynamic stack of lower panes -- ONE pane per enabled "lower" indicator, each
 * with its own y-scale. All charts share time scale + crosshair (N-way sync).
 *
 * Indicators are computed in Python and arrive as generic plot data
 * ({overlays, panes} in /api/candles); this file just draws them. New indicators
 * (library.py) need zero changes here. Backend sends UTC epoch; we add IST_OFFSET
 * so the x-axis reads IST.
 *
 * Hotkeys: Alt+G go to date · Alt+I invert price scale · Alt+R reset view
 */

const IST_OFFSET = 19800;

const FALLBACK_PREFS = {
    colors: {
        background: '#131722', grid: '#1e2230',
        candle_up: '#4ecdc4', candle_down: '#e94560',
        pane_background: '#131722', pane_grid: '#1e2230',
        ema: { 10: '#ff6b6b', 20: '#4ecdc4', 50: '#45b7d1', 100: '#ffa07a', 200: '#98d8c8', 400: '#f7dc6f' },
    },
    ui: { ema_on: [20, 50, 100, 200], log_main: true, log_panes: true },
};

const LINE_OPTS = { lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };

let prefs = FALLBACK_PREFS;
let priceChart, candleSeries, volumeSeries;
const emaSeriesByPeriod = {};         // period -> series
let overlaySeriesById = {};           // indicator id -> [series]
let panes = [];                       // [{id, el, chart, ro, anchorSeries, valueByTime}]
let lastData = null;

let isRangeSyncing = false, isCrosshairSyncing = false, inverted = false, saveTimer = null;
let loadedTimes = [];
const priceByTime = new Map();        // chart-time -> close (price crosshair anchor)

// ── Preferences ────────────────────────────────────────────────────

async function fetchPrefs() {
    // no-store: never let the browser hand us a cached (stale) prefs response.
    try { return await (await fetch('/api/preferences', { cache: 'no-store' })).json(); }
    catch (e) { console.warn('prefs load failed, fallback:', e); return FALLBACK_PREFS; }
}
function postPrefs() {
    saveTimer = null;
    const body = JSON.stringify(prefs);
    // sendBeacon is delivered by the browser even if the page is navigating away
    // (a refresh would abort a normal fetch -- that's what made changes "not
    // stick"). keepalive fetch is the fallback for the rare no-beacon browser.
    if (navigator.sendBeacon) {
        navigator.sendBeacon('/api/preferences', new Blob([body], { type: 'application/json' }));
    } else {
        fetch('/api/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true })
            .catch(e => console.warn('prefs save failed:', e));
    }
}
function savePrefs() { clearTimeout(saveTimer); saveTimer = setTimeout(postPrefs, 300); }
function flushPrefs() { if (saveTimer) { clearTimeout(saveTimer); postPrefs(); } }

// ── Layout / colors ────────────────────────────────────────────────

function layoutOptsFor(bgKey, gridKey) {
    const col = prefs.colors;
    return {
        layout: { background: { type: 'solid', color: col[bgKey] }, textColor: '#888', fontSize: 11 },
        grid: { vertLines: { color: col[gridKey] }, horzLines: { color: col[gridKey] } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#1e2230' },
        timeScale: { borderColor: '#1e2230', timeVisible: true, secondsVisible: false },
    };
}

function applyChartColors() {
    const col = prefs.colors;
    priceChart.applyOptions(layoutOptsFor('background', 'grid'));
    panes.forEach(p => p.chart.applyOptions(layoutOptsFor('pane_background', 'pane_grid')));
    document.body.style.background = col.background;
    candleSeries.applyOptions({
        upColor: col.candle_up, downColor: col.candle_down,
        borderUpColor: col.candle_up, borderDownColor: col.candle_down,
        wickUpColor: col.candle_up, wickDownColor: col.candle_down,
    });
    for (const [period, s] of Object.entries(emaSeriesByPeriod)) s.applyOptions({ color: col.ema[period] });
}

// Linear vs logarithmic price scale, set independently for the main pane and
// the lower panes. Default is log (prefs.ui.log_main / log_panes).
function scaleMode(isLog) {
    return isLog ? LightweightCharts.PriceScaleMode.Logarithmic : LightweightCharts.PriceScaleMode.Normal;
}
function applyScaleModes() {
    priceChart.priceScale('right').applyOptions({ mode: scaleMode(prefs.ui.log_main !== false) });
    panes.forEach(p => p.chart.priceScale('right').applyOptions({ mode: scaleMode(prefs.ui.log_panes !== false) }));
}

// ── Build price chart ──────────────────────────────────────────────

function buildPriceChart() {
    const el = document.getElementById('priceChart');
    const col = prefs.colors;

    priceChart = LightweightCharts.createChart(el, {
        ...layoutOptsFor('background', 'grid'),
        rightPriceScale: { borderColor: '#1e2230', scaleMargins: { top: 0.1, bottom: 0.25 } },
    });

    // Draw order = creation order: volume, EMAs, then candles LAST (on top).
    volumeSeries = priceChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'volume' });
    priceChart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    document.querySelectorAll('.ema-toggle').forEach(cb => {
        const period = cb.dataset.period;
        emaSeriesByPeriod[period] = priceChart.addLineSeries({ ...LINE_OPTS, color: col.ema[period], title: `EMA ${period}` });
    });

    candleSeries = priceChart.addCandlestickSeries({
        upColor: col.candle_up, downColor: col.candle_down,
        borderUpColor: col.candle_up, borderDownColor: col.candle_down,
        wickUpColor: col.candle_up, wickDownColor: col.candle_down,
    });

    wireSyncFor(priceChart);
    new ResizeObserver(() => priceChart.applyOptions({ width: el.clientWidth, height: el.clientHeight })).observe(el);
}

// ── N-way sync (time scale + crosshair) ────────────────────────────

function getAllCharts() { return [priceChart, ...panes.map(p => p.chart)]; }

function anchorFor(chart) {
    if (chart === priceChart) return { series: candleSeries, map: priceByTime };
    const p = panes.find(p => p.chart === chart);
    return p ? { series: p.anchorSeries, map: p.valueByTime } : null;
}

function wireSyncFor(chart) {
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (!range || isRangeSyncing) return;
        isRangeSyncing = true;
        getAllCharts().forEach(ch => { if (ch !== chart) ch.timeScale().setVisibleLogicalRange(range); });
        isRangeSyncing = false;
    });
    chart.subscribeCrosshairMove((param) => {
        if (isCrosshairSyncing) return;
        isCrosshairSyncing = true;
        getAllCharts().forEach(ch => {
            if (ch === chart) return;
            if (param.time === undefined) { ch.clearCrosshairPosition(); return; }
            const a = anchorFor(ch);
            if (!a || !a.series) return;
            const price = a.map.get(param.time);
            ch.setCrosshairPosition(price === undefined ? 0 : price, param.time, a.series);
        });
        isCrosshairSyncing = false;
    });
}

// Hide redundant time axes: show it only on the bottom-most chart.
function updateTimeAxes() {
    const hasPanes = panes.length > 0;
    priceChart.timeScale().applyOptions({ visible: !hasPanes });
    panes.forEach((p, i) => p.chart.timeScale().applyOptions({ visible: i === panes.length - 1 }));
}

// ── Drawing plots ──────────────────────────────────────────────────

function toLine(arr) {
    // {timestamp, value?} -> {time, value?}; missing value => whitespace point.
    return arr.map(d => (d.value === undefined
        ? { time: d.timestamp + IST_OFFSET }
        : { time: d.timestamp + IST_OFFSET, value: d.value }));
}

function addPlotSeries(chart, plot) {
    const opts = { ...LINE_OPTS, color: plot.color, title: plot.label };
    const series = plot.kind === 'histogram'
        ? chart.addHistogramSeries({ color: plot.color, priceLineVisible: false, lastValueVisible: false })
        : chart.addLineSeries(opts);
    series.setData(toLine(plot.data));
    return series;
}

function isIndEnabled(id) {
    const cb = document.querySelector(`.ind-toggle[data-id="${id}"]`);
    return cb ? cb.checked : false;
}

// Price-pane overlays (registry pane="price"): recreated each load, visibility per toggle.
function rebuildOverlays() {
    for (const list of Object.values(overlaySeriesById)) list.forEach(s => priceChart.removeSeries(s));
    overlaySeriesById = {};
    for (const group of (lastData.overlays || [])) {
        overlaySeriesById[group.id] = group.plots.map(p => {
            const s = addPlotSeries(priceChart, p);
            s.applyOptions({ visible: isIndEnabled(group.id) });
            return s;
        });
    }
}

// Lower panes (registry pane="lower"): ONE chart per enabled indicator.
function rebuildPanes() {
    panes.forEach(p => { p.ro.disconnect(); p.chart.remove(); p.el.remove(); });
    panes = [];

    const container = document.getElementById('panes');
    for (const group of (lastData.panes || [])) {
        if (!isIndEnabled(group.id)) continue;

        const el = document.createElement('div');
        el.className = 'pane';
        container.appendChild(el);

        const chart = LightweightCharts.createChart(el, layoutOptsFor('pane_background', 'pane_grid'));
        const seriesList = group.plots.map(p => addPlotSeries(chart, p));

        // value lookup for crosshair anchoring (first plot)
        const valueByTime = new Map();
        if (group.plots[0]) for (const d of group.plots[0].data) if (d.value !== undefined) valueByTime.set(d.timestamp + IST_OFFSET, d.value);

        const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth, height: el.clientHeight }));
        ro.observe(el);

        const pane = { id: group.id, el, chart, ro, anchorSeries: seriesList[0], valueByTime };
        panes.push(pane);
        wireSyncFor(chart);
    }
    updateTimeAxes();
    applyScaleModes();
    syncPanesToPrice();
}

function syncPanesToPrice() {
    const r = priceChart.timeScale().getVisibleLogicalRange();
    if (r) panes.forEach(p => p.chart.timeScale().setVisibleLogicalRange(r));
}

// ── Controls ───────────────────────────────────────────────────────

function initControls() {
    const emaOn = new Set((prefs.ui.ema_on || []).map(Number));
    document.querySelectorAll('.ema-toggle').forEach(cb => {
        const period = cb.dataset.period;
        cb.checked = emaOn.has(Number(period));
        emaSeriesByPeriod[period].applyOptions({ visible: cb.checked });
        cb.addEventListener('change', () => {
            emaSeriesByPeriod[period].applyOptions({ visible: cb.checked });
            prefs.ui.ema_on = [...document.querySelectorAll('.ema-toggle')].filter(x => x.checked).map(x => Number(x.dataset.period));
            savePrefs();
        });
    });

    document.querySelectorAll('.ema-color').forEach(inp => {
        const period = inp.dataset.period;
        inp.value = prefs.colors.ema[period];
        inp.addEventListener('input', () => {
            prefs.colors.ema[period] = inp.value;
            emaSeriesByPeriod[period].applyOptions({ color: inp.value });
            savePrefs();
        });
    });

    // Registry indicators: enabled = saved pref if present, else the def default.
    const savedOn = prefs.ui.indicators_on;
    document.querySelectorAll('.ind-toggle').forEach(cb => {
        cb.checked = Array.isArray(savedOn) ? savedOn.includes(cb.dataset.id) : (cb.dataset.defaultOn === 'true');
        cb.addEventListener('change', () => {
            prefs.ui.indicators_on = [...document.querySelectorAll('.ind-toggle')].filter(x => x.checked).map(x => x.dataset.id);
            if (cb.dataset.pane === 'price') {
                (overlaySeriesById[cb.dataset.id] || []).forEach(s => s.applyOptions({ visible: cb.checked }));
            } else {
                rebuildPanes();
            }
            savePrefs();
        });
    });

    document.querySelectorAll('.color-pref').forEach(inp => {
        const key = inp.dataset.key;
        inp.value = prefs.colors[key];
        inp.addEventListener('input', () => {
            prefs.colors[key] = inp.value;
            applyChartColors();
            savePrefs();
        });
    });

    const logMain = document.getElementById('logMain');
    logMain.checked = prefs.ui.log_main !== false;
    logMain.addEventListener('change', () => { prefs.ui.log_main = logMain.checked; applyScaleModes(); savePrefs(); });

    const logPanes = document.getElementById('logPanes');
    logPanes.checked = prefs.ui.log_panes !== false;
    logPanes.addEventListener('change', () => { prefs.ui.log_panes = logPanes.checked; applyScaleModes(); savePrefs(); });
}

const PANELS = [
    ['indicatorBtn', 'indicatorPanel'],
    ['settingsBtn', 'settingsPanel'],
    ['paneSettingsBtn', 'paneSettingsPanel'],
    ['gotoBtn', 'gotoPanel'],
];
function closeAllPanels() { PANELS.forEach(([, id]) => document.getElementById(id).classList.add('hidden')); }
function wireDropdowns() {
    PANELS.forEach(([btnId, panelId]) => {
        const btn = document.getElementById(btnId), panel = document.getElementById(panelId);
        btn.addEventListener('click', (e) => { e.stopPropagation(); panel.classList.toggle('hidden'); });
        panel.addEventListener('click', (e) => e.stopPropagation());
    });
    document.addEventListener('click', closeAllPanels);
}

// ── Go to date ─────────────────────────────────────────────────────

function inputToChartTime(value) {
    const [datePart, timePart] = value.split('T');
    const [y, mo, d] = datePart.split('-').map(Number);
    const [h, mi] = (timePart || '00:00').split(':').map(Number);
    return Math.floor(Date.UTC(y, mo - 1, d, h || 0, mi || 0) / 1000);
}
function chartTimeToInput(t) {
    const d = new Date(t * 1000), p = n => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
function nearestIndex(times, t) {
    if (!times.length) return -1;
    if (t <= times[0]) return 0;
    if (t >= times[times.length - 1]) return times.length - 1;
    let lo = 0, hi = times.length - 1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (times[mid] === t) return mid; if (times[mid] < t) lo = mid + 1; else hi = mid - 1; }
    return (times[lo] - t) < (t - times[hi]) ? lo : hi;
}
function gotoChartTime(chartTime) {
    const status = document.getElementById('status');
    const idx = nearestIndex(loadedTimes, chartTime);
    if (idx < 0) { status.textContent = 'no data loaded'; return; }
    const cur = priceChart.timeScale().getVisibleLogicalRange();
    let span = cur ? (cur.to - cur.from) : 120;
    if (!isFinite(span) || span <= 0) span = 120;
    priceChart.timeScale().setVisibleLogicalRange({ from: idx - span / 2, to: idx + span / 2 });
    status.textContent = `→ ${chartTimeToInput(loadedTimes[idx]).replace('T', ' ')}`;
}
function doGoto() {
    const v = document.getElementById('gotoInput').value;
    if (!v) return;
    gotoChartTime(inputToChartTime(v));
    document.getElementById('gotoPanel').classList.add('hidden');
}
function openGoto() {
    closeAllPanels();
    document.getElementById('gotoPanel').classList.remove('hidden');
    const inp = document.getElementById('gotoInput');
    if (loadedTimes.length && !inp.value) inp.value = chartTimeToInput(loadedTimes[loadedTimes.length - 1]);
    inp.focus(); inp.select && inp.select();
}
function wireGoto() {
    document.getElementById('gotoGo').addEventListener('click', doGoto);
    document.getElementById('gotoInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doGoto(); } });
}

// ── Hotkeys ────────────────────────────────────────────────────────

function wireKeyboard() {
    document.addEventListener('keydown', (e) => {
        if (!e.altKey) return;
        if (e.code === 'KeyG') { e.preventDefault(); openGoto(); }
        else if (e.code === 'KeyI') { e.preventDefault(); toggleInvert(); }
        else if (e.code === 'KeyR') { e.preventDefault(); resetView(); }
    });
}
function toggleInvert() {
    inverted = !inverted;
    priceChart.priceScale('right').applyOptions({ invertScale: inverted });
}
function resetView() {
    getAllCharts().forEach(ch => { ch.timeScale().fitContent(); ch.priceScale('right').applyOptions({ autoScale: true }); });
}

// ── Data ───────────────────────────────────────────────────────────

async function load() {
    const symbol = document.getElementById('symbol').value;
    const tf = document.getElementById('tf').value;
    const bars = document.getElementById('bars').value;
    const status = document.getElementById('status');

    status.textContent = 'loading…';
    try {
        lastData = await (await fetch(`/api/candles?symbol=${symbol}&tf=${tf}&bars=${bars}`)).json();

        const ohlc = lastData.candles.map(d => ({ time: d.timestamp + IST_OFFSET, open: d.open, high: d.high, low: d.low, close: d.close }));
        const vol = lastData.candles.map(d => ({
            time: d.timestamp + IST_OFFSET, value: d.volume,
            color: d.close >= d.open ? 'rgba(78,205,196,0.3)' : 'rgba(233,69,96,0.3)',
        }));
        candleSeries.setData(ohlc);
        volumeSeries.setData(vol);
        for (const [period, series] of Object.entries(emaSeriesByPeriod)) series.setData(toLine(lastData.emas[period] || []));

        rebuildOverlays();
        rebuildPanes();

        priceByTime.clear();
        ohlc.forEach(d => priceByTime.set(d.time, d.close));
        loadedTimes = ohlc.map(d => d.time);

        priceChart.timeScale().fitContent();
        syncPanesToPrice();
        status.textContent = `${lastData.candles.length} bars · ${symbol} ${tf}`;
    } catch (e) {
        status.textContent = 'error: ' + e.message;
        console.error(e);
    }
}

// ── Init ───────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
    prefs = await fetchPrefs();
    buildPriceChart();
    applyChartColors();
    initControls();
    applyScaleModes();
    wireDropdowns();
    wireGoto();
    wireKeyboard();
    // Flush any pending debounced save before the page goes away, so a quick
    // refresh after a change still persists it.
    window.addEventListener('beforeunload', flushPrefs);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushPrefs(); });
    document.getElementById('loadBtn').addEventListener('click', load);
    load();
});
