// fpv3d map page: live build progress.
// The 1 km terrain tiles of the new location are drawn on the map and fill up as they download;
// a card shows the build steps, an overall bar and counters, with the raw log under "Technical details".
/* global L */

const TILE = 1000;
const KIND = {
  dtm: { label: 'Elevation (bare ground)', color: '#2ecc71' },
  dsm: { label: 'Elevation (trees + buildings)', color: '#16a085' },
  ortho: { label: 'Aerial photo', color: '#f1c40f' },
};
const PHASES = [
  { id: 'terrain', label: 'Terrain', w: 35 },
  { id: 'ortho', label: 'Photo', w: 25 },
  { id: 'buildings', label: 'Buildings', w: 4 },
  { id: 'los', label: 'Shadows', w: 30 },
  { id: 'tracks', label: 'Logs', w: 4 },
  { id: 'zones', label: 'Zones', w: 6 },
];
const fmtMB = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`);

/**
 * @param map      Leaflet map
 * @param toWGS    (e, n) -> [lat, lon]
 * @param el       { card, title, pct, steps, bar, now, stats, log }  DOM elements
 */
export function createBuildProgress({ map, toWGS, el }) {
  const renderer = L.svg({ padding: 0.3 });            // SVG so tiles can be animated with CSS
  const layer = L.layerGroup();
  const rect = (e0, n0, e1, n1) => [toWGS(e0, n0), toWGS(e1, n0), toWGS(e1, n1), toWGS(e0, n1)];
  let st, raf = 0, fadeT = 0;

  function reset(title) {
    clearTimeout(fadeT);
    layer.clearLayers(); layer.addTo(map);
    st = { phase: null, done: new Set(), skipped: new Set(), kind: null, res: null, tiles: new Map(), losPct: 0, losLabel: '',
      bytes: 0, speed: 0, lastBytesT: performance.now(), lastBytes: 0, fitted: false, events: 0 };
    el.card.classList.remove('hidden', 'ok', 'err');
    el.title.textContent = title;
    el.steps.innerHTML = PHASES.map((p) => `<li data-p="${p.id}">${p.label}</li>`).join('');
    el.log.textContent = 'starting…';
    render();
    el.card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ---------------------------------------------------------------- tiles on the map
  function setTiles(kind, res, keys, cached) {
    layer.clearLayers(); st.tiles.clear();
    st.kind = kind; st.res = res;
    const col = KIND[kind]?.color || '#4fc3f7', cachedSet = new Set(cached);
    let bounds = null;
    keys.forEach((key, i) => {
      const [ke, kn] = key.split('-').map(Number), e = ke * TILE, n = kn * TILE;
      const outline = L.polygon(rect(e, n, e + TILE, n + TILE), { renderer, className: 'tp tp-pending', color: '#9aa7b8',
        weight: 1, fill: false, interactive: false }).addTo(layer);
      const fill = L.polygon(rect(e, n, e + TILE, n), { renderer, className: 'tp-fill', stroke: false, fillColor: col,
        fillOpacity: 0.5, interactive: false }).addTo(layer);
      const t = { key, e, n, outline, fill, state: 'pending', target: 0, shown: 0, total: 0 };
      st.tiles.set(key, t);
      bounds = bounds ? bounds.extend(outline.getBounds()) : outline.getBounds();
      if (cachedSet.has(key)) setTimeout(() => setState(t, 'cached', 100), 25 * i);   // quick staggered reveal
    });
    if (bounds && !st.fitted) { map.fitBounds(bounds.pad(0.25)); st.fitted = true; }
  }

  function setState(t, state, target) {
    if (!t) return;
    const was = t.state;
    t.state = state;
    if (target != null) t.target = target;
    const cls = { pending: 'tp-pending', query: 'tp-query', download: 'tp-dl', done: 'tp-done', cached: 'tp-cached', raw: 'tp-raw', empty: 'tp-empty' }[state];
    t.outline.getElement()?.setAttribute('class', `tp ${cls}`);
    t.outline.setStyle({ color: state === 'download' ? '#4fc3f7' : state === 'empty' ? '#e74c3c' : state === 'pending' || state === 'query' ? '#9aa7b8' : KIND[st.kind]?.color,
      weight: state === 'download' ? 2.5 : 1, dashArray: state === 'pending' || state === 'query' ? '4 4' : null });
    if (state === 'empty') { t.fill.setStyle({ fillColor: '#7f8c8d', fillOpacity: 0.25 }); t.target = 100; }
    if (state === 'raw') t.fill.setStyle({ fillColor: '#1abc9c' });
    if ((state === 'done' || state === 'raw') && was !== state) {
      t.target = 100;
      const f = t.fill.getElement(); if (f) { f.classList.remove('tp-pop'); void f.getBBox(); f.classList.add('tp-pop'); }
    }
    if (state === 'cached') t.fill.setStyle({ fillOpacity: 0.32 });
    kick();
  }

  // smooth fill-up between the (throttled) progress events
  function kick() { if (!raf) raf = requestAnimationFrame(step); }
  function step() {
    raf = 0;
    let moving = false;
    for (const t of st.tiles.values()) {
      if (Math.abs(t.target - t.shown) < 0.3) { if (t.shown !== t.target) { t.shown = t.target; draw(t); } continue; }
      t.shown += (t.target - t.shown) * (t.target === 100 ? 0.25 : 0.12);
      draw(t); moving = true;
    }
    if (moving) kick();
  }
  function draw(t) { t.fill.setLatLngs(rect(t.e, t.n, t.e + TILE, t.n + TILE * Math.max(0, Math.min(1, t.shown / 100)))); }

  // ---------------------------------------------------------------- events from the build
  function onEvent(ev) {
    st.events++;
    if (ev.ev === 'phase') {
      if (st.phase && st.phase !== ev.id) st.done.add(st.phase);
      if (ev.id === 'done') { PHASES.forEach((p) => st.done.has(p.id) || st.skipped.add(p.id)); st.phase = 'done'; }
      else {
        // phases that never started before this one were skipped (e.g. no aerial photo, terrain reused)
        for (const p of PHASES) { if (p.id === ev.id) break; if (!st.done.has(p.id) && p.id !== st.phase) st.skipped.add(p.id); }
        st.phase = ev.id; st.phaseLabel = ev.label;
      }
      if (ev.id === 'los') {
        layer.eachLayer((l) => l.getElement?.()?.classList.add('tp-scan'));
      }
    } else if (ev.ev === 'tiles') {
      setTiles(ev.kind, ev.res, ev.keys, ev.cached || []);
    } else if (ev.ev === 'query') {
      for (const t of st.tiles.values()) if (t.state === 'pending') setState(t, 'query');
    } else if (ev.ev === 'tile') {
      const t = st.tiles.get(ev.key);
      if (!t) return;
      if (ev.state === 'download') {
        setState(t, 'download', ev.pct ?? Math.min(90, t.target + 10));
        if (ev.total) {
          t.total = ev.total;
          const now = performance.now(), dt = (now - st.lastBytesT) / 1000;
          st.bytesLive = (st.bytes || 0) + (ev.bytes || 0);
          if (dt > 0.4) { st.speed = Math.max(0, (st.bytesLive - st.lastBytes) / dt); st.lastBytes = st.bytesLive; st.lastBytesT = now; }
        }
      } else {
        if (ev.state === 'done') { st.bytes += t.total || 0; st.bytesLive = st.bytes; }
        setState(t, ev.state);
      }
    } else if (ev.ev === 'pct' && ev.phase === 'los') {
      st.losPct = ev.pct; st.losLabel = ev.label || '';
    }
  }

  // ---------------------------------------------------------------- card
  function tileFrac() {
    if (!st.tiles.size) return 0;
    let s = 0;
    for (const t of st.tiles.values()) s += t.state === 'download' ? t.target / 100 : ['done', 'cached', 'raw', 'empty'].includes(t.state) ? 1 : 0;
    return s / st.tiles.size;
  }
  function overall() {
    let got = 0, tot = 0;
    for (const p of PHASES) {
      if (st.skipped.has(p.id)) continue;
      tot += p.w;
      if (st.done.has(p.id) || st.phase === 'done') got += p.w;
      else if (p.id === st.phase) got += p.w * (p.id === 'los' ? st.losPct / 100 : p.id === 'terrain' || p.id === 'ortho' ? tileFrac() : 0.5);
    }
    return tot ? Math.round(100 * got / tot) : 0;
  }
  function render(status) {
    for (const li of el.steps.children) {
      const id = li.dataset.p;
      li.className = st.skipped.has(id) ? 'skip' : st.done.has(id) || st.phase === 'done' ? 'done' : id === st.phase ? 'now' : '';
    }
    const pct = status === 'done' ? 100 : overall();
    el.bar.style.width = `${pct}%`;
    el.pct.textContent = `${pct}%`;
    let now = st.phaseLabel || 'starting…';
    if (st.phase === 'los' && st.losLabel) now = `Signal shadows: ${st.losLabel}`;
    if (st.phase === 'tracks') now = 'Processing your flight logs';
    if (st.phase === 'buildings') now = 'Downloading building footprints (OpenStreetMap) and measuring their heights';
    if (st.phase === 'zones') now = 'Downloading the FOCA drone zones';
    el.now.textContent = status === 'done' ? 'Finished' : status === 'failed' ? 'Stopped with an error (see technical details)' : now;
    // tile counters for the current download step
    if ((st.phase === 'terrain' || st.phase === 'ortho') && st.tiles.size && status !== 'done') {
      const c = { cached: 0, done: 0, raw: 0, empty: 0, download: 0 };
      let dl = null;
      for (const t of st.tiles.values()) { if (t.state in c) c[t.state]++; if (t.state === 'download') dl = t; }
      const ok = c.cached + c.done + c.raw + c.empty;
      el.stats.innerHTML = `<b>${KIND[st.kind]?.label || st.kind} ${st.res} m</b> · ${ok}/${st.tiles.size} km²<br>`
        + [c.cached && `${c.cached} already cached`, c.raw && `${c.raw} from earlier downloads`, c.done && `${c.done} downloaded`,
          dl && `1 downloading (${Math.round(dl.target)}%)`, c.empty && `${c.empty} without data`].filter(Boolean).join(' · ')
        + (st.bytesLive ? `<br>${fmtMB(st.bytesLive)} received${st.speed > 1e3 && dl ? ` · ${fmtMB(st.speed)}/s` : ''}` : '');
    } else if (status === 'done') {
      el.stats.textContent = st.bytes ? `${fmtMB(st.bytes)} downloaded this time` : 'Everything came from the cache';
    } else if (!['terrain', 'ortho'].includes(st.phase)) el.stats.textContent = '';
    if (status === 'done') el.card.classList.add('ok');
    if (status === 'failed') {
      el.card.classList.add('err');
      for (const t of st.tiles.values()) if (['pending', 'query', 'download'].includes(t.state)) t.outline.setStyle({ color: '#e74c3c', dashArray: '2 4' });
    }
  }

  return {
    start(title) { reset(title); },
    /** feed a /api/jobs/<id> response */
    update(job) {
      for (const ev of job.events || []) onEvent(ev);
      el.log.textContent = (job.lines || []).slice(-300).join('\n');
      el.log.scrollTop = el.log.scrollHeight;
      render(job.status === 'running' ? null : job.status);
      if (job.status === 'done') {
        layer.eachLayer((l) => l.getElement?.()?.classList.remove('tp-scan'));
        fadeT = setTimeout(() => layer.remove(), 8000);    // the cache layer shows the new tiles afterwards
      }
    },
    hide() { layer.remove(); el.card.classList.add('hidden'); },
  };
}
