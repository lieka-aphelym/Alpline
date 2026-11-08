// fpv3d — battery charts (canvas, no library): the discharge (cell voltage, current, throttle over time), sag vs
// current (the slope is the pack's resistance) and a pack's resistance over its flights. Used by the viewer's
// [battery] tab and the packs page. Colours follow the theme (dark / light).

const css = (k, d) => getComputedStyle(document.documentElement).getPropertyValue(k).trim() || d;
export const COL = {
  get volt() { return css('--t-acc', '#ffd60a'); },
  cur: '#4cc9f0', thr: '#b388ff', bad: '#ff2d55', warn: '#ffb000', good: '#3ddc84',
  get grid() { return css('--t-rule', '#2a313c'); },
  get text() { return css('--t-fg2', '#a9b4c2'); },
  get fg() { return css('--t-fg', '#f2f5f8'); },
};
export const fmtT = (s) => `${s < 0 ? '-' : ''}${Math.floor(Math.abs(s) / 60)}:${String(Math.floor(Math.abs(s) % 60)).padStart(2, '0')}`;

/** a canvas sized to its box at the screen's resolution; returns the 2D context in CSS pixels */
export function fit(cv, h) {
  const w = Math.max(50, cv.clientWidth || cv.parentElement.clientWidth);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (h) cv.style.height = `${h}px`;
  const hh = cv.clientHeight || h || 100;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(hh * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(hh * dpr); }
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, hh);
  g.font = '10px ui-monospace, Consolas, monospace';
  return { g, w, h: hh };
}

/** per-cell series from a flight (cells from the pack when known) + the resting estimate when R is known */
export function cellSeries(d) {
  const cells = d.summary?.cells || d.cells || 1, R = (d.summary?.ir_pack_mohm || 0) / 1000;
  const cv = d.v.map((v) => v / cells);
  const rest = R ? d.v.map((v, k) => (v + d.i[k] * R) / cells) : null;
  return { cells, cv, rest, R };
}

/** discharge chart. opts: { cursor (s), tStart, tEnd, compact, low (V/cell) } -> { tAt(x), xAt(t) } for clicks */
export function drawDischarge(cv, d, opts = {}) {
  const { g, w, h } = fit(cv, opts.height);
  const { cv: cell, rest } = cellSeries(d);
  const t = d.t, n = t.length;
  const t0 = opts.tStart ?? t[0], t1 = opts.tEnd ?? t[n - 1];
  const m = { l: 32, r: d.summary?.has_current === false ? 8 : 30, t: opts.compact ? 4 : 8, b: 14 };
  const W = w - m.l - m.r, H = h - m.t - m.b;
  let lo = Math.min(...cell), hi = Math.max(...(rest || cell));
  lo = Math.floor((lo - 0.05) * 10) / 10; hi = Math.ceil((hi + 0.03) * 10) / 10;
  if (hi - lo < 0.3) hi = lo + 0.3;
  const imax = Math.max(10, Math.ceil(Math.max(...d.i) / 10) * 10);
  const x = (s) => m.l + (s - t0) / Math.max(t1 - t0, 1e-3) * W;
  const yv = (v) => m.t + H - (v - lo) / (hi - lo) * H;
  const yi = (a) => m.t + H - a / imax * H;
  // grid and axes
  g.strokeStyle = COL.grid; g.lineWidth = 1; g.fillStyle = COL.text;
  const rows = opts.compact ? 2 : 4;
  for (let k = 0; k <= rows; k++) {
    const yy = Math.round(m.t + H * k / rows) + 0.5;
    g.beginPath(); g.moveTo(m.l, yy); g.lineTo(m.l + W, yy); g.stroke();
    g.textAlign = 'right'; g.fillText((hi - (hi - lo) * k / rows).toFixed(2), m.l - 3, yy + 3);
    if (m.r > 10) { g.textAlign = 'left'; g.fillText(`${Math.round(imax - imax * k / rows)}`, m.l + W + 3, yy + 3); }
  }
  const span = t1 - t0, stepT = span > 600 ? 120 : span > 240 ? 60 : span > 60 ? 30 : span > 20 ? 5 : 1;
  g.textAlign = 'center';
  for (let s = Math.ceil(t0 / stepT) * stepT; s <= t1; s += stepT) g.fillText(fmtT(s), x(s), h - 2);
  // the low-voltage band
  const low = opts.low ?? d.summary?.low ?? 3.5;
  if (low > lo) { g.fillStyle = 'rgba(255,45,85,0.08)'; g.fillRect(m.l, yv(low), W, m.t + H - yv(low)); }
  const line = (ys, color, width = 1.3, dash = null, alpha = 1) => {
    g.save(); g.beginPath(); g.strokeStyle = color; g.lineWidth = width; g.globalAlpha = alpha;
    if (dash) g.setLineDash(dash);
    const step = Math.max(1, Math.floor(n / (W * 1.5)));
    let first = true;
    for (let k = 0; k < n; k += step) {
      if (t[k] < t0 || t[k] > t1 || ys[k] == null) { first = true; continue; }
      const xx = x(t[k]), yy = ys[k];
      first ? g.moveTo(xx, yy) : g.lineTo(xx, yy); first = false;
    }
    g.stroke(); g.restore();
  };
  g.save(); g.beginPath(); g.rect(m.l, m.t, W, H); g.clip();
  if (d.thr) line(d.thr.map((v) => m.t + H - v * H), COL.thr, 1, null, 0.45);
  if (d.summary?.has_current !== false) line(d.i.map(yi), COL.cur, 1, null, 0.85);
  if (rest) line(rest.map(yv), COL.volt, 1.2, [4, 3], 0.7);
  line(cell.map(yv), COL.volt, 1.7);
  // lowest point
  let kmin = 0; for (let k = 1; k < n; k++) if (cell[k] < cell[kmin]) kmin = k;
  if (!opts.compact) {
    g.strokeStyle = COL.bad; g.lineWidth = 1.5; g.beginPath(); g.arc(x(t[kmin]), yv(cell[kmin]), 4, 0, 7); g.stroke();
    g.fillStyle = COL.bad; g.textAlign = x(t[kmin]) > m.l + W - 90 ? 'right' : 'left';
    g.fillText(`min ${cell[kmin].toFixed(2)} V`, x(t[kmin]) + (g.textAlign === 'left' ? 7 : -7), Math.min(yv(cell[kmin]) + 12, m.t + H - 2));
  }
  g.restore();
  if (opts.cursor != null && opts.cursor >= t0 && opts.cursor <= t1) {
    g.strokeStyle = COL.fg; g.globalAlpha = 0.85; g.lineWidth = 1;
    g.beginPath(); g.moveTo(Math.round(x(opts.cursor)) + 0.5, m.t); g.lineTo(Math.round(x(opts.cursor)) + 0.5, m.t + H); g.stroke(); g.globalAlpha = 1;
  }
  return { tAt: (px) => t0 + (px - m.l) / W * (t1 - t0), xAt: x, valueAt: (s) => valueAt(d, cell, s) };
}

/** cell voltage, current, mAh at a time (s) */
export function valueAt(d, cell, s) {
  const t = d.t; let lo = 0, hi = t.length - 1;
  if (s < t[0] || s > t[hi]) return null;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (t[mid] <= s) lo = mid; else hi = mid; }
  let mah = 0; for (let k = 1; k <= lo; k++) mah += d.i[k] * Math.min(1, t[k] - t[k - 1]) / 3.6;
  return { cell: cell[lo], amps: d.i[lo], mah };
}

/** sag vs current: each dot is how far the cell voltage dropped at that current; the line is the resistance */
export function drawSag(cv, d, opts = {}) {
  const { g, w, h } = fit(cv, opts.height || 130);
  const { cells, rest, R } = cellSeries(d);
  const m = { l: 34, r: 8, t: 6, b: 14 }, W = w - m.l - m.r, H = h - m.t - m.b;
  const imax = Math.max(20, Math.ceil(Math.max(...d.i) / 20) * 20);
  const dmax = R ? Math.max(0.1, Math.ceil((imax * R / cells) * 1.3 * 20) / 20) : 0.5;
  const x = (a) => m.l + a / imax * W, y = (s) => m.t + s / dmax * H;
  g.strokeStyle = COL.grid; g.fillStyle = COL.text; g.lineWidth = 1;
  for (let k = 0; k <= 4; k++) {
    const yy = Math.round(m.t + H * k / 4) + 0.5;
    g.beginPath(); g.moveTo(m.l, yy); g.lineTo(m.l + W, yy); g.stroke();
    g.textAlign = 'right'; g.fillText((dmax * k / 4).toFixed(2), m.l - 3, yy + 3);
  }
  g.textAlign = 'center';
  for (let a = 0; a <= imax; a += imax / 4) g.fillText(`${Math.round(a)} A`, x(a), h - 2);
  if (!R || !rest) {
    g.fillStyle = COL.text; g.textAlign = 'center';
    g.fillText(d.summary?.has_current === false ? 'no current sensor in this log' : 'not enough punch-outs to measure the resistance', m.l + W / 2, m.t + H / 2);
    return;
  }
  const cell = d.v.map((v) => v / cells), n = d.t.length, used = d.summary?.mah || 0;
  let mah = 0;
  for (let k = 0; k < n; k += 2) {
    if (k) mah += d.i[k] * Math.min(1, d.t[k] - d.t[k - 2]) / 3.6;
    g.fillStyle = used && mah > used - 300 ? COL.warn : COL.cur; g.globalAlpha = 0.5;
    g.fillRect(x(d.i[k]) - 1, y(rest[k] - cell[k]) - 1, 2.2, 2.2);
  }
  g.globalAlpha = 1; g.strokeStyle = COL.volt; g.lineWidth = 1.6;
  g.beginPath(); g.moveTo(x(0), y(0)); g.lineTo(x(imax), y(imax * R / cells)); g.stroke();
  g.fillStyle = COL.volt; g.textAlign = 'right';
  g.fillText(`slope = ${(R * 1000 / cells).toFixed(1)} mΩ per cell`, m.l + W - 4, m.t + 12);
}

/** a pack's resistance per cell over its flights (dates) */
export function drawTrend(cv, trend, opts = {}) {
  const { g, w, h } = fit(cv, opts.height || 120);
  const m = { l: 34, r: 8, t: 8, b: 14 }, W = w - m.l - m.r, H = h - m.t - m.b;
  g.fillStyle = COL.text;
  if (!trend.length) { g.textAlign = 'center'; g.fillText('no resistance measured yet (needs flights with punch-outs)', w / 2, h / 2); return; }
  const vals = trend.map((p) => p.ir), lo = Math.max(0, Math.floor(Math.min(...vals) - 1)), hi = Math.ceil(Math.max(...vals) + 1);
  const x = (k) => m.l + (trend.length === 1 ? W / 2 : k / (trend.length - 1) * W), y = (v) => m.t + H - (v - lo) / (hi - lo) * H;
  g.strokeStyle = COL.grid; g.lineWidth = 1;
  for (let k = 0; k <= 3; k++) {
    const yy = Math.round(m.t + H * k / 3) + 0.5;
    g.beginPath(); g.moveTo(m.l, yy); g.lineTo(m.l + W, yy); g.stroke();
    g.textAlign = 'right'; g.fillText((hi - (hi - lo) * k / 3).toFixed(1), m.l - 3, yy + 3);
  }
  const lab = [0, trend.length - 1].filter((k, i, a) => a.indexOf(k) === i);
  for (const k of lab) {
    g.textAlign = lab.length === 1 ? 'center' : k === 0 ? 'left' : 'right';
    g.fillText((trend[k].when || '').slice(0, 10), x(k), h - 2);
  }
  const rising = vals.length >= 4 && vals.at(-1) > 1.4 * vals[0];
  g.strokeStyle = rising ? COL.warn : COL.good; g.lineWidth = 1.6; g.beginPath();
  trend.forEach((p, k) => (k ? g.lineTo(x(k), y(p.ir)) : g.moveTo(x(k), y(p.ir)))); g.stroke();
  g.fillStyle = g.strokeStyle;
  trend.forEach((p, k) => { g.beginPath(); g.arc(x(k), y(p.ir), 2.5, 0, 7); g.fill(); });
}

/** a small inline sparkline (svg text) of resistance values */
export function sparkline(vals, w = 90, h = 20) {
  if (!vals.length) return '<span class="muted">–</span>';
  const lo = Math.min(...vals) - 0.5, hi = Math.max(...vals) + 0.5;
  const pts = vals.map((v, k) => `${(vals.length === 1 ? w / 2 : k / (vals.length - 1) * (w - 4) + 2).toFixed(1)},${(h - 2 - (v - lo) / (hi - lo) * (h - 4)).toFixed(1)}`);
  const c = vals.length >= 4 && vals.at(-1) > 1.4 * vals[0] ? COL.warn : COL.good;
  const [lx, ly] = pts.at(-1).split(',');
  return `<svg width="${w}" height="${h}" class="spark"><polyline points="${pts.join(' ')}" fill="none" stroke="${c}" stroke-width="1.5"/><circle cx="${lx}" cy="${ly}" r="2.2" fill="${c}"/></svg>`;
}
