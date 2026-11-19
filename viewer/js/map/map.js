// fpv3d map page: basemap (swisstopo in Switzerland, OpenStreetMap / satellite elsewhere), cached terrain tiles,
// existing locations, and click-to-create new locations (pilot + area) with optional one-click build.
// A location lives on a metric grid: Swiss LV95 in and around Switzerland, its UTM zone elsewhere (core/geo.js).
/* global L */
import { initTabs } from '../core/tabs.js';
import { createBuildProgress } from './buildprog.js';
import { stripTiles, contextTiles, stripShapes, routeLength, stripArea, boxCells } from './corridor.js';
import { LITE } from '../core/env.js';
import { mountDrone } from '../core/drone.js';
import { esc } from '../core/esc.js';
import { toGrid, toWGS, crsFor, gridName, isSwiss } from '../core/geo.js';
const $ = (id) => document.getElementById(id);
const TILE = 1000;
const LV95 = 'EPSG:2056';

// a rectangle of the grid `crs` (metres) as map corners
const gridRect = (crs, e0, n0, e1, n1) => [toWGS(e0, n0, crs), toWGS(e1, n0, crs), toWGS(e1, n1, crs), toWGS(e0, n1, crs)];
const fmtLV = (e, n) => `${Math.round(e).toLocaleString('de-CH')} / ${Math.round(n).toLocaleString('de-CH')}`;
// 46.7614, 6.9845 -> "46.76140 N · 6.98450 E" (as the viewer's top bar writes a position)
const fmtDeg = (lat, lon) => `${Math.abs(lat).toFixed(5)} ${lat >= 0 ? 'N' : 'S'} · ${Math.abs(lon).toFixed(5)} ${lon >= 0 ? 'E' : 'W'}`;

// ---------------------------------------------------------------- map + basemaps
const map = L.map('map', { preferCanvas: true, zoomControl: false }).setView([46.8, 8.2], 8);
L.control.zoom({ position: 'bottomright' }).addTo(map);
L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);
const attr = '© <a href="https://www.swisstopo.admin.ch/">swisstopo</a>';
const wmts = (layer, ext) => L.tileLayer(
  `https://wmts.geo.admin.ch/1.0.0/${layer}/default/current/3857/{z}/{x}/{y}.${ext}`,
  { attribution: attr, maxZoom: 19, maxNativeZoom: layer.includes('swissimage') ? 19 : 18, minZoom: 6 });
const base = {
  'swisstopo map': wmts('ch.swisstopo.pixelkarte-farbe', 'jpeg'),
  'swisstopo aerial': wmts('ch.swisstopo.swissimage', 'jpeg'),
  'swisstopo grey': wmts('ch.swisstopo.pixelkarte-grau', 'jpeg'),
  // OpenStreetMap's servers refuse browser requests that don't say which page they come from ("Access blocked"
  // tiles). Our server asks browsers to send no referrer at all (the PIN link must never leak), so this layer alone
  // sends the page's origin (http://localhost:8000/, never the path or the PIN).
  OpenStreetMap: L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    { attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 19, referrerPolicy: 'origin' }),
  'Satellite (world, 10 m)': L.tileLayer('https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg',
    { attribution: 'Sentinel-2 cloudless 2016 by <a href="https://cloudless.eox.at">EOX</a> (CC BY 4.0)', maxZoom: 19, maxNativeZoom: 14 }),
};
base['swisstopo map'].addTo(map);
// The swisstopo maps end at the Swiss border regions: when the view leaves them (or zooms out past them), the map
// switches to OpenStreetMap by itself, and back when it returns. A layer picked by hand is left alone.
let baseNow = 'swisstopo map', baseAuto = null, baseSwitching = false;
map.on('baselayerchange', (e) => { baseNow = e.name; if (!baseSwitching) baseAuto = null; });
function setBase(name) {
  if (name === baseNow) return;
  baseSwitching = true;
  map.removeLayer(base[baseNow]); base[name].addTo(map); baseNow = name;
  baseSwitching = false;
}
function autoBase() {
  const c = map.getCenter(), swiss = isSwiss(crsFor(c.lat, c.lng)) && map.getZoom() >= 7;
  if (!swiss && baseNow.startsWith('swisstopo')) { baseAuto = baseNow; setBase('OpenStreetMap'); }
  else if (swiss && baseAuto && !baseNow.startsWith('swisstopo')) { const b = baseAuto; baseAuto = null; setBase(b); }
}
map.on('moveend', autoBase);
const overlays = {
  'Drone restrictions (FOCA, official)': L.tileLayer(
    'https://wmts.geo.admin.ch/1.0.0/ch.bazl.einschraenkungen-drohnen/default/current/3857/{z}/{x}/{y}.png',
    { attribution: '© BAZL/FOCA', opacity: 0.6, maxZoom: 19, maxNativeZoom: 18, minZoom: 6 }),
};
overlays['Drone restrictions (FOCA, official)'].addTo(map);
L.control.layers(base, overlays, { position: 'topright' }).addTo(map);
let tileErrors = 0;
base['swisstopo map'].on('tileerror', () => {
  if (++tileErrors === 6) msg('Basemap not loading (offline?) - cached tiles and locations are still shown.', 'err');
});
// OpenStreetMap not answering while it is the automatic map abroad: show the satellite layer instead
let osmErrors = 0;
base.OpenStreetMap.on('tileerror', () => {
  if (++osmErrors === 6 && baseNow === 'OpenStreetMap' && baseAuto) {
    setBase('Satellite (world, 10 m)');
    msg('OpenStreetMap is not loading: showing the satellite layer instead (layers menu, top right, to change).', 'err');
  }
});

// ---------------------------------------------------------------- layers: cache + locations
const groups = { lod_dtm: L.layerGroup(), lod_dsm: L.layerGroup(), lod_ortho: L.layerGroup(), raw: L.layerGroup(), locs: L.layerGroup() };
for (const [k, g] of Object.entries(groups)) if (document.querySelector(`.lyr[data-l="${k}"]`).checked) g.addTo(map);
document.querySelectorAll('.lyr').forEach((cb) => cb.onchange = () => {
  const g = groups[cb.dataset.l]; if (cb.checked) g.addTo(map); else g.remove();
});

const KIND_COL = { dtm: '#2ecc71', dsm: '#16a085', ortho: '#f1c40f' };
let STATE = null;
const cachedSet = {};   // `${kind}|${res}` -> Set(keys), plus `raw|${kind}`

// The cached 1 km tiles of one source on one grid. Sets are kept per grid (`${crs}|${kind}|${res}`): tiles of
// several sources on the same grid (swisstopo and the worldwide model at the Swiss border) add up.
function drawLod(lod, crs, label, lodKeys) {
  for (const [kind, byRes] of Object.entries(lod || {})) {
    const finest = {};     // key -> finest res
    for (const [res, keys] of Object.entries(byRes)) {
      const id = `${crs}|${kind}|${+res}`;
      cachedSet[id] = new Set([...(cachedSet[id] || []), ...keys]);
      for (const k of keys) { finest[k] = Math.min(finest[k] ?? 1e9, +res); lodKeys?.add(k); }
    }
    for (const [k, r] of Object.entries(finest)) {
      const [e, n] = k.split('-').map((v) => +v * TILE);
      const all = Object.entries(byRes).filter(([, ks]) => ks.includes(k)).map(([rr]) => `${rr} m`).join(', ');
      // finer = more opaque
      const op = kind === 'ortho' ? 0.18 : Math.max(0.18, Math.min(0.6, 0.65 - Math.log2(r) * 0.12));
      L.polygon(gridRect(crs, e, n, e + TILE, n + TILE), {
        color: KIND_COL[kind], weight: kind === 'ortho' ? 1 : 0.6, fillOpacity: kind === 'ortho' ? 0 : op,
        dashArray: kind === 'ortho' ? '3 3' : null, interactive: true,
      }).bindTooltip(`${kind.toUpperCase()} tile ${k}${label}<br>cached at ${all}`, { className: 'tip', sticky: true })
        .addTo(groups[`lod_${kind}`] || groups.lod_dtm);
    }
  }
}

function drawCache(inv, world = []) {
  Object.values(groups).forEach((g, i) => i < 4 && g.clearLayers());
  for (const k of Object.keys(cachedSet)) delete cachedSet[k];
  const lodKeys = new Set();
  drawLod(inv.lod, LV95, '', lodKeys);
  for (const w of world) drawLod(w.lod, w.crs, ` · ${esc(w.label)}${isSwiss(w.crs) ? '' : `, ${gridName(w.crs)}`}`);
  for (const [kind, keys] of Object.entries(inv.raw || {})) {
    cachedSet[`raw|${kind}`] = new Set(keys);
    for (const k of keys) {
      if (lodKeys.has(k)) continue;
      const [e, n] = k.split('-').map((v) => +v * TILE);
      L.polygon(gridRect(LV95, e, n, e + TILE, n + TILE), { color: '#95a5a6', weight: 0.6, fillOpacity: 0.25 })
        .bindTooltip(`downloaded ${kind} tile ${k} (not resampled yet - next build does it offline)`, { className: 'tip', sticky: true })
        .addTo(groups.raw);
    }
  }
  const nDtm = new Set(Object.values(inv.lod?.dtm || {}).flat()).size, nDsm = new Set(Object.values(inv.lod?.dsm || {}).flat()).size;
  const nRaw = new Set(Object.values(inv.raw || {}).flat()).size;
  const nWorld = world.filter((w) => !isSwiss(w.crs) && w.lod.dtm).reduce((a, w) => a + new Set(Object.values(w.lod.dtm).flat()).size, 0);
  const rows = [['Bare ground', nDtm], ['Trees + buildings', nDsm], ['Raw downloads', nRaw]];
  if (nWorld) rows.push(['Outside Switzerland', nWorld]);
  $('cacheSummary').innerHTML = rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v.toLocaleString('de-CH')} km²</dd></div>`).join('');
}

function drawLocations(locs) {
  groups.locs.clearLayers();
  const ul = $('locList'); ul.innerHTML = '';
  $('fRadio').innerHTML = '<option value="">defaults</option>' + locs.filter((l) => !l.error).map((l) => `<option value="${esc(l.name)}">${esc(l.title)}</option>`).join('');
  if (!locs.length) {                      // empty: a hovering drone and how to make the first location
    ul.innerHTML = '<li class="droneEmpty"><span id="noLocDrone"></span><span class="small">No locations yet. Click the map where you fly, then <b>Save &amp; build</b> in New.</span></li>';
    mountDrone($('noLocDrone'), { size: 44 }).loop('hover');
  }
  for (const l of locs) {
    const li = document.createElement('li');
    if (l.error) { li.innerHTML = `<span class="t">${esc(l.file)}</span><span class="badge">error</span>`; li.title = l.error; ul.appendChild(li); continue; }
    const crs = l.crs || LV95, [ce, cn] = toGrid(...l.center, crs), h = l.half_size_m;
    let poly;
    if (l.corridor) {
      const pts = l.corridor.points.map((q) => toGrid(...q, crs));
      poly = L.featureGroup([L.polyline(l.corridor.points, { color: '#4fc3f7', weight: 2.5, dashArray: l.built ? null : '6 4' }),
        ...stripShapes(pts, l.corridor.width_m, 16).map((s) => L.polygon(s.map((q) => toWGS(...q, crs)), { stroke: false, fillColor: '#4fc3f7', fillOpacity: 0.07 }))]);
      poly.bindTooltip(`<b>${esc(l.title)}</b><br>route ${(l.corridor.length_m / 1000).toFixed(1)} km · ${2 * l.corridor.width_m} m wide · ${l.resolution_m} m · ${l.surface}${l.built ? '' : '<br>not built yet'}`, { className: 'tip', sticky: true });
    } else {
      poly = L.polygon(gridRect(crs, ce - h, cn - h, ce + h, cn + h), { color: '#4fc3f7', weight: 2, fill: false, dashArray: l.built ? null : '6 4' })
        .bindTooltip(`<b>${esc(l.title)}</b><br>${(2 * h / 1000).toFixed(1)} km · ${l.resolution_m} m · ${l.surface}${l.built ? '' : '<br>not built yet'}`, { className: 'tip', sticky: true });
    }
    poly.addTo(groups.locs);
    const pin = L.marker(l.pilot, { icon: L.divIcon({ className: 'locpin', html: '', iconSize: [10, 10], iconAnchor: [5, 5] }) })
      .bindTooltip(`${esc(l.title)} - pilot${l.pilot_from_log ? ' (from first log)' : ''}`, { className: 'tip' }).addTo(groups.locs);
    const pick = (fromMap) => { map.fitBounds(poly.getBounds(), { padding: [40, 40] }); loadIntoForm(l); if (fromMap === true) tabs.show('new', { keepOpen: true }); };
    // while drawing a route, a click on an existing location adds a point instead of opening it
    poly.on('click', (e) => { L.DomEvent.stop(e); if (drawingRoute()) onMapClick(e); else pick(true); });
    pin.on('click', (e) => { if (drawingRoute()) onMapClick(e); else pick(true); });
    li.innerHTML = `<span class="t">${esc(l.title)}</span>
      <span class="badge ${l.built ? 'ok' : ''}">${l.built ? 'built' : 'not built'}</span>
      ${l.built ? `<a href="index.html?scene=${encodeURIComponent(l.name)}" title="Open in the 3D viewer">3D</a>` : ''}`;
    li.querySelector('.t').onclick = pick;
    const ren = document.createElement('button'); ren.className = 'iconbtn'; ren.textContent = 'Rename'; ren.title = 'Rename';
    ren.onclick = () => openRename(li, l);
    li.appendChild(ren);
    const del = document.createElement('button'); del.className = 'iconbtn'; del.textContent = 'Delete'; del.title = 'Delete';
    del.onclick = () => openDelete(li, l);
    li.appendChild(del);
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------- rename a location (clean ASCII file name + title)
const slugify = (s) => s.normalize('NFKD').replace(/[^\x00-\x7f]/g, '').toLowerCase().replace(/[^a-z0-9-]+/g, '_').replace(/_+/g, '_').replace(/^[_-]+|[_-]+$/g, '').slice(0, 60);
const noEmoji = (s) => s.replace(/[\p{Extended_Pictographic}\u{FE0F}\u{200D}]/gu, '').replace(/\s{2,}/g, ' ').trim();
function openRename(li, l) {
  document.querySelectorAll('.loclist .renbox').forEach((b) => b.remove());
  const box = document.createElement('div'); box.className = 'renbox';
  box.innerHTML = `<label class="row small">Title <input class="rt"></label>
    <label class="row small">File name <input class="rn" spellcheck="false"></label>
    <div class="row"><button class="primary go">Rename</button><button class="no">Cancel</button><span class="small m"></span></div>`;
  li.after(box);
  box.scrollIntoView({ block: 'nearest' });
  const rt = box.querySelector('.rt'), rn = box.querySelector('.rn'), m = box.querySelector('.m');
  rt.value = l.title; rn.value = l.name; rt.focus();
  rt.oninput = () => { if (!rn.dataset.touched) rn.value = slugify(rt.value); };
  rn.oninput = () => { rn.dataset.touched = '1'; };
  box.querySelector('.no').onclick = () => box.remove();
  box.querySelector('.go').onclick = async () => {
    const nn = slugify(rn.value);
    if (!nn) { m.textContent = 'file name is empty'; m.className = 'small err'; return; }
    m.textContent = 'renaming…'; m.className = 'small muted';
    try {
      const r = await fetch('/api/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'location', old: l.name, new: nn, title: noEmoji(rt.value) }) });
      const j = await r.json();
      if (!r.ok || j.error) throw new Error(j.error || r.status);
      try {
        const lk = `fpv3d:links:${l.name}`;
        if (localStorage.getItem(lk) != null) { localStorage.setItem(`fpv3d:links:${j.name}`, localStorage.getItem(lk)); localStorage.removeItem(lk); }
      } catch { /* private mode */ }
      box.remove(); refresh();
    } catch (e) { m.textContent = e.message; m.className = 'small err'; }
  };
}

// ---------------------------------------------------------------- delete / restore (kept in deleted/, undoable)
function locMsg(html, cls = '') { $('locMsg').innerHTML = html; $('locMsg').className = `small ${cls}`; }
function openDelete(li, l) {
  document.querySelectorAll('.loclist .renbox').forEach((b) => b.remove());
  const box = document.createElement('div'); box.className = 'renbox delbox';
  box.innerHTML = `<div class="small">Delete <b>${esc(l.title)}</b>? Its location file${l.built ? ', 3D scene' : ''} and training flights
    move to the <code>deleted/</code> folder; you can restore them. Cached terrain and your own logs are kept.</div>
    <div class="row"><button class="danger go">Delete</button><button class="no">Cancel</button><span class="small m"></span></div>`;
  li.after(box);
  box.scrollIntoView({ block: 'nearest' });
  box.querySelector('.no').onclick = () => box.remove();
  box.querySelector('.go').onclick = async () => {
    const m = box.querySelector('.m'); m.textContent = 'deleting…';
    try {
      const r = await fetch('/api/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: l.name }) });
      const j = await r.json();
      if (!r.ok || j.error) throw new Error(j.error || r.status);
      box.remove();
      locMsg(`Deleted “${esc(l.title)}”. <a href="#" id="undoDel">Undo</a>`, 'ok');
      $('undoDel').onclick = (e) => { e.preventDefault(); restore(j.folder); };
      refresh();
    } catch (e) { m.textContent = e.message; m.className = 'small err'; }
  };
}
async function restore(folder) {
  try {
    const r = await fetch('/api/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ folder }) });
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || r.status);
    locMsg(`Restored “${esc(j.title)}”.`, 'ok');
    refresh();
  } catch (e) { locMsg(e.message, 'err'); }
}
function drawBin(rows) {
  $('binBox').classList.toggle('hidden', !rows.length);
  $('binList').innerHTML = '';
  for (const d of rows) {
    const li = document.createElement('li');
    li.innerHTML = `<span class="t">${esc(d.title || d.name)}</span><span class="badge">${(d.deleted || '').slice(5)}</span>`;
    const b = document.createElement('button'); b.className = 'iconbtn'; b.textContent = 'Restore'; b.title = 'Restore';
    b.onclick = () => restore(d.folder);
    li.appendChild(b); $('binList').appendChild(li);
  }
}

async function refresh() {
  try {
    STATE = await (await fetch('/api/state', { cache: 'no-store' })).json();
    drawCache(STATE.cache, STATE.cache_world || []); drawLocations(STATE.locations); drawBin(STATE.deleted || []); updatePreview();
  } catch (e) {
    msg('Cannot reach the fpv3d server. Start it with: python -m fpv3d map', 'err');
  }
}

// ---------------------------------------------------------------- draft location (pilot + area)
const draft = { center: null, pilot: null, shape: 'square', route: [], pilotAuto: true };
const routeL = L.layerGroup(), routeMarks = L.layerGroup();
const pilotM = L.marker([0, 0], { draggable: true, icon: L.divIcon({ className: 'tag tagpilot', html: 'pilot', iconSize: [48, 18], iconAnchor: [24, 25] }) });
const centerM = L.marker([0, 0], { draggable: true, icon: L.divIcon({ className: 'tag tagcenter', html: '+', iconSize: [18, 18], iconAnchor: [9, 9] }) });
const areaR = L.polygon([], { color: '#ff9f1a', weight: 2, fillOpacity: 0.06 });
const tilesL = L.layerGroup();
pilotM.on('drag', () => { const p = pilotM.getLatLng(); draft.pilot = [p.lat, p.lng]; updatePreview(false); });
pilotM.on('dragend', () => updatePreview());
centerM.on('drag', () => { const p = centerM.getLatLng(); draft.center = [p.lat, p.lng]; updatePreview(false); });
centerM.on('dragend', () => updatePreview());

pilotM.on('dragstart', () => { draft.pilotAuto = false; });
// the grid of the location being drawn: from the start of its route, else from its centre (as fpv3d/config.py does)
function draftCrs() {
  const p = draft.shape === 'route' && draft.route.length ? draft.route[0] : draft.center;
  return p ? crsFor(p[0], p[1]) : LV95;
}
// what is different about a place outside Switzerland, said once under the area
const abroadNote = (crs) => (isSwiss(crs) ? '' : '<span class="muted">Outside Switzerland: terrain from the worldwide 30 m model '
  + '(coarse; a finer detail only smooths it), satellite photo of about 10 m, no drone zones.</span>');
function routeCenter() {
  const crs = draftCrs(), pts = draft.route.map((q) => toGrid(...q, crs)), es = pts.map((q) => q[0]), ns = pts.map((q) => q[1]);
  return toWGS((Math.min(...es) + Math.max(...es)) / 2, (Math.min(...ns) + Math.max(...ns)) / 2, crs);
}
function setShape(s) {
  draft.shape = s;
  document.querySelectorAll('#shapePick button').forEach((b) => b.classList.toggle('on', b.dataset.shape === s));
  document.querySelectorAll('#panel .sq').forEach((el) => el.classList.toggle('hidden', s !== 'square'));
  document.querySelectorAll('#panel .rt').forEach((el) => el.classList.toggle('hidden', s !== 'route'));
  document.querySelector(`input[name=cm][value=${s === 'route' ? 'route' : 'both'}]`).checked = true;
  if (s === 'square') { routeL.remove(); routeMarks.remove(); } else { areaR.remove(); centerM.remove(); }
  drawRouteMarks();
  updatePreview();
}
document.querySelectorAll('#shapePick button').forEach((b) => { b.onclick = () => setShape(b.dataset.shape); });
function drawRouteMarks() {
  routeMarks.clearLayers();
  if (draft.shape !== 'route') return;
  routeMarks.addTo(map);
  draft.route.forEach((ll, i) => {
    const m = L.marker(ll, { draggable: true, icon: L.divIcon({ className: '', html: `<div class="rtpt ${i ? '' : 'first'}"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] }) })
      .bindTooltip(i ? `point ${i + 1}` : 'start of the route', { className: 'tip' }).addTo(routeMarks);
    m.on('drag', () => {
      const q = m.getLatLng(); draft.route[i] = [q.lat, q.lng];
      if (i === 0 && draft.pilotAuto) draft.pilot = draft.route[0];
      draft.center = routeCenter(); updatePreview(false);
    });
    m.on('dragend', () => updatePreview());
  });
}
$('bUndoPt').onclick = () => { draft.route.pop(); if (!draft.route.length) { draft.pilotAuto = true; } else if (draft.pilotAuto) draft.pilot = draft.route[0]; draft.center = draft.route.length ? routeCenter() : null; drawRouteMarks(); updatePreview(); };
$('bClearRt').onclick = () => { draft.route = []; draft.pilotAuto = true; draft.center = null; routeL.clearLayers(); tilesL.clearLayers(); pilotM.remove(); drawRouteMarks(); updatePreview(); };
$('fWidth').addEventListener('input', () => updatePreview(false));

function drawingRoute() {
  return draft.shape === 'route' && tabs.current === 'new';
}
map.on('click', onMapClick);
function onMapClick(e) {
  const w = e.latlng.wrap();                 // the map repeats east and west: bring the longitude back to -180..180
  const mode = document.querySelector('input[name=cm]:checked').value, ll = [w.lat, w.lng];
  if (draft.shape === 'route') {
    if (mode === 'pilot') { draft.pilot = ll; draft.pilotAuto = false; } else {
      draft.route.push(ll);
      if (draft.pilotAuto || !draft.pilot) draft.pilot = draft.route[0];
      drawRouteMarks();
    }
    draft.center = draft.route.length ? routeCenter() : ll;
    tabs.show('new', { keepOpen: true });
    updatePreview();
    return;
  }
  if (mode !== 'center') draft.pilot = ll;
  if (mode !== 'pilot' || !draft.center) draft.center = ll;
  if (!draft.pilot) draft.pilot = ll;
  tabs.show('new', { keepOpen: true });
  updatePreview();
}

let heightReq = 0;
async function updatePreview(full = true) {
  $('fHalfOut').textContent = `${(2 * +$('fHalf').value / 1000).toFixed(1)} × ${(2 * +$('fHalf').value / 1000).toFixed(1)} km`;
  $('fWidthOut').textContent = `${+$('fWidth').value} m · strip ${(2 * +$('fWidth').value / 1000).toFixed(1)} km`;
  if (draft.shape === 'route') { updateRoutePreview(); if (full && draft.pilot) pilotHeight(); return; }
  if (!draft.center) return;
  const crs = draftCrs(), gn = gridName(crs);
  const h = +$('fHalf').value, [ce, cn] = toGrid(...draft.center, crs), [pe, pn] = toGrid(...draft.pilot, crs);
  pilotM.setLatLng(draft.pilot).addTo(map); centerM.setLatLng(draft.center).addTo(map);
  areaR.setLatLngs(gridRect(crs, ce - h, cn - h, ce + h, cn + h)).addTo(map);
  const inside = Math.abs(pe - ce) <= h && Math.abs(pn - cn) <= h;
  $('oPilot').innerHTML = `${fmtDeg(...draft.pilot)}<span class="sub">${gn} ${fmtLV(pe, pn)}</span>`
    + (inside ? '' : '<span class="bad">outside the map area</span>');
  const km = (2 * h / 1000).toFixed(1);
  $('oArea').innerHTML = `${km} × ${km} km<span class="sub">centre ${gn} ${fmtLV(ce, cn)}</span>${abroadNote(crs)}`;

  // which 1 km tiles are needed, and how many are already cached at this detail
  const res = +$('fRes').value, kind = $('fSurface').value;
  const keys = [];
  for (let e = Math.floor((ce - h) / TILE); e < Math.ceil((ce + h) / TILE); e++)
    for (let n = Math.floor((cn - h) / TILE); n < Math.ceil((cn + h) / TILE); n++) keys.push(`${e}-${n}`);
  const { lod, raw } = cachedFor(crs, kind, res);
  const nLod = keys.filter((k) => lod.has(k)).length, nRaw = keys.filter((k) => !lod.has(k) && raw.has(k)).length;
  const toDl = keys.length - nLod - nRaw;
  $('oTiles').innerHTML = `${keys.length} km² · <b>${nLod}</b> ready${nRaw ? ` · ${nRaw} downloaded earlier` : ''}`
    + `<span class="sub">${downloadText(crs, toDl, kind, res)}</span>`;
  showSize(Math.pow(Math.round(2 * h / res) + 1, 2), kind);
  tilesL.clearLayers().addTo(map);
  for (const k of keys) {
    const [e, n] = k.split('-').map((v) => +v * TILE);
    const c = lod.has(k) ? '#2ecc71' : raw.has(k) ? '#95a5a6' : '#ff9f1a';
    L.polygon(gridRect(crs, e, n, e + TILE, n + TILE), { color: c, weight: 0.5, fill: false, interactive: false }).addTo(tilesL);
  }
  if (!full) return;
  pilotHeight();
}

// which of a grid's tiles are ready (resampled) or only downloaded; raw downloads per tile exist for swisstopo only
function cachedFor(crs, kind, res) {
  return { lod: cachedSet[`${crs}|${kind}|${res}`] || new Set(), raw: (isSwiss(crs) && cachedSet[`raw|${kind}`]) || new Set() };
}
function downloadText(crs, toDl, kind, res) {
  if (!toDl) return 'nothing to download';
  if (!isSwiss(crs)) return `<b>${toDl}</b> to prepare (the worldwide model comes as one 20–50 MB file per degree square, downloaded once)`;
  const mb = kind === 'dsm' ? 30 : res < 2 ? 25 : 1.5;   // rough MB per raw tile
  return `<b>${toDl}</b> to download (~${Math.round(toDl * mb)} MB)`;
}

// size of the scene and memory needed to build it (same rule as fpv3d/buildlock.py: 4 bytes a cell per terrain
// layer, a second layer for the surface model, about 6 layers of memory at the peak of the build)
function showSize(cells, kind) {
  const layer = cells * 4 / 1e6, scene = layer * (kind === 'dsm' ? 2 : 1) + 5, ram = layer * 6 / 1000;
  draft.est = { scene, ram };
  const mbs = (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)} GB` : `${Math.round(v)} MB`);
  $('oSize').innerHTML = `scene ≈ <b>${mbs(scene)}</b><span class="sub">building needs ≈ ${ram.toFixed(1)} GB of memory</span>`
    + (ram > 8 ? '<span class="warnline">Very large: most PCs will run out of memory. Use a coarser detail or a smaller area.</span>'
      : ram > 4 ? '<span class="warnline">Large: the build will take long and may fail on a PC with 8 GB or less.</span>' : '');
}

function updateRoutePreview() {
  const w = +$('fWidth').value, res = +$('fRes').value, kind = $('fSurface').value;
  routeL.clearLayers().addTo(map); tilesL.clearLayers();
  if (draft.pilot) pilotM.setLatLng(draft.pilot).addTo(map);
  if (draft.route.length < 2) {
    $('oArea').textContent = draft.route.length ? 'add at least one more point' : 'click the map to add route points';
    $('oTiles').textContent = '–';
    if (draft.pilot) $('oPilot').textContent = fmtDeg(...draft.pilot);
    return;
  }
  const crs = draftCrs();
  const pts = draft.route.map((q) => toGrid(...q, crs)), pil = draft.pilot ? toGrid(...draft.pilot, crs) : null;
  L.polyline(draft.route, { color: '#ff9f1a', weight: 3, interactive: false }).addTo(routeL);
  for (const s of stripShapes(pts, w)) L.polygon(s.map((q) => toWGS(...q, crs)), { stroke: false, fillColor: '#ff9f1a', fillOpacity: 0.1, interactive: false }).addTo(routeL);
  const keys = stripTiles(pts, w), ks = new Set(keys);
  const ctx = contextTiles(pts, w, pil).filter((k) => !ks.has(k));
  const { lod, raw } = cachedFor(crs, kind, res);
  const nLod = keys.filter((k) => lod.has(k)).length, nRaw = keys.filter((k) => !lod.has(k) && raw.has(k)).length;
  const toDl = keys.length - nLod - nRaw;
  for (const k of keys) {
    const [e, n] = k.split('-').map((v) => +v * TILE);
    const c = lod.has(k) ? '#2ecc71' : raw.has(k) ? '#95a5a6' : '#ff9f1a';
    L.polygon(gridRect(crs, e, n, e + TILE, n + TILE), { color: c, weight: 0.6, fill: false, interactive: false }).addTo(tilesL);
  }
  for (const k of ctx) {
    const [e, n] = k.split('-').map((v) => +v * TILE);
    L.polygon(gridRect(crs, e, n, e + TILE, n + TILE), { color: '#9aa7b8', weight: 0.5, dashArray: '2 4', fill: false, interactive: false }).addTo(tilesL);
  }
  tilesL.addTo(map);
  const len = routeLength(pts), area = stripArea(pts, w);
  const es = pts.map((q) => q[0]), ns = pts.map((q) => q[1]);
  const sq = Math.pow(Math.max(Math.max(...es) - Math.min(...es), Math.max(...ns) - Math.min(...ns)) + 2 * w, 2) / 1e6;
  $('oArea').innerHTML = `route ${(len / 1000).toFixed(2)} km · strip ≈ ${area.toFixed(1)} km²`
    + `<span class="sub">a square around it: ${sq.toFixed(0)} km²</span>${abroadNote(crs)}`;
  const cells = boxCells(pts, w, pil, res);
  $('oTiles').innerHTML = `${keys.length} km² on the strip · <b>${nLod}</b> ready${nRaw ? ` · ${nRaw} downloaded earlier` : ''}`
    + `<span class="sub">${downloadText(crs, toDl, kind, res)}</span>`
    + (ctx.length ? `<span class="sub">+ ${ctx.length} km² coarse context between pilot and route (10 m, small)</span>` : '')
    + (cells > 150e6 ? `<span class="warnline">Large box (${Math.round(cells / 1e6)} M cells at ${res} m): choose a coarser detail or split the route.</span>` : '');
  showSize(cells, kind);
  const [pe, pn] = pil || pts[0];
  $('oPilot').innerHTML = `${fmtDeg(...draft.pilot)}`
    + `<span class="sub">${gridName(crs)} ${fmtLV(pe, pn)}${draft.pilotAuto ? ' · start of the route' : ''}</span>`;
}

async function pilotHeight() {
  const id = ++heightReq;
  $('oHeight').textContent = '…';
  try {
    const r = await (await fetch(`/api/height?lat=${draft.pilot[0]}&lon=${draft.pilot[1]}`)).json();
    if (id === heightReq) $('oHeight').innerHTML = r.height == null ? `<span class="muted">${r.source}</span>` : `${r.height.toFixed(0)} m <span class="muted">${r.source}</span>`;
  } catch { if (id === heightReq) $('oHeight').textContent = '–'; }
}
// default terrain detail of a new location: Full mode 2 m, Lite mode 5 m
$('fRes').value = LITE ? '5' : '2';
['fHalf', 'fRes', 'fSurface'].forEach((id) => $(id).addEventListener('input', () => updatePreview(false)));

function loadIntoForm(l) {
  $('fName').value = l.name; $('fTitle').value = l.title; $('fHalf').value = Math.min(6000, l.half_size_m);
  if (l.corridor) {
    draft.route = l.corridor.points.map((q) => [...q]); $('fWidth').value = l.corridor.width_m; draft.pilotAuto = false;
  }
  $('fRes').value = String(l.resolution_m); $('fSurface').value = l.surface; $('fAnt').value = l.antenna_height_m;
  $('fRadio').value = l.name; $('fOverwrite').checked = false;
  draft.center = l.center; draft.pilot = l.pilot;
  setShape(l.corridor ? 'route' : 'square');
  msg(`Loaded "${l.title}". Change it and save under a new name, or tick "overwrite" (the file is rewritten; your radio settings are kept).`);
}

// ---------------------------------------------------------------- save / build
function msg(text, cls = '') { const m = $('msg'); m.textContent = text; m.className = `small ${cls}`; }
const slug = (s) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40);
$('fTitle').addEventListener('input', () => { if (!$('fName').dataset.touched) $('fName').value = slug($('fTitle').value); });
$('fName').addEventListener('input', () => { $('fName').dataset.touched = $('fName').value ? '1' : ''; });

async function save() {
  if (draft.shape === 'route' && draft.route.length < 2) { msg('Click at least 2 points for the route.', 'err'); return null; }
  if (!draft.center) { msg('Click on the map first to place the pilot / area.', 'err'); return null; }
  const name = $('fName').value.trim() || slug($('fTitle').value);
  if (!name) { msg('Give the location a name.', 'err'); return null; }
  const body = {
    name, title: $('fTitle').value.trim() || name, center: draft.center, pilot: draft.pilot,
    half_size_m: +$('fHalf').value, resolution_m: +$('fRes').value, surface: $('fSurface').value,
    antenna_height_m: +$('fAnt').value, radio_from: $('fRadio').value || null, overwrite: $('fOverwrite').checked,
    corridor: draft.shape === 'route' ? { points: draft.route, width_m: +$('fWidth').value } : null,
  };
  const r = await fetch('/api/locations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json();
  if (!r.ok) { msg(d.exists ? `${d.error} - tick "overwrite" or choose another name.` : d.error, 'err'); return null; }
  msg(`Saved ${d.file}`, 'ok'); await refresh(); return d.name || name;   // the server adds the number (015_name)
}

let PROG = null, BUILD_DRONE = null, buildCrs = LV95;      // the grid of the location being built (its tiles are drawn live)
async function build(name) {
  if (draft.est?.ram > 4 && !confirm(`This location needs about ${draft.est.ram.toFixed(1)} GB of memory to build and makes a ${Math.round(draft.est.scene)} MB scene. Build anyway?`)) return;
  const r = await fetch('/api/build', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
  const d = await r.json();
  if (!r.ok) { msg(d.error, 'err'); return; }
  buildCrs = (STATE?.locations || []).find((l) => l.name === name)?.crs || draftCrs();
  PROG ||= createBuildProgress({ map, toWGS: (e, n) => toWGS(e, n, buildCrs), el: { card: $('prog'), title: $('progTitle'), pct: $('progPct'), steps: $('progSteps'),
    bar: $('progBar'), now: $('progNow'), stats: $('progStats'), log: $('jobLog') } });
  PROG.start(`Building “${$('fTitle').value.trim() || name}”`);
  BUILD_DRONE ||= mountDrone($('progDrone'), { size: 34 });      // props spinning while it builds
  BUILD_DRONE.off(false); BUILD_DRONE.loop('props');
  tilesL.remove();                          // the live tiles replace the draft tile preview
  msg('');
  $('bBuild').disabled = true;
  $('progCancel').classList.remove('hidden'); $('progCancel').disabled = false;
  $('progCancel').onclick = async () => {
    $('progCancel').disabled = true;
    try { await fetch(`/api/jobs/${d.job}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch { /* finished meanwhile */ }
  };
  let since = 0;
  window.alpBusy?.(true);
  try { for (;;) {
    await new Promise((ok) => setTimeout(ok, 400));
    let j;
    try { j = await (await fetch(`/api/jobs/${d.job}?since=${since}`)).json(); } catch { continue; }
    since = j.events_total ?? since;
    PROG.update(j);
    if (j.status !== 'running') {
      $('bBuild').disabled = false; $('progCancel').classList.add('hidden');
      BUILD_DRONE.loop(null); BUILD_DRONE.off(j.status !== 'done');
      if (j.status === 'cancelled') { msg('Build cancelled. The location file is kept; build it again any time.', 'err'); refresh(); break; }
      if (j.status === 'done') {
        msg('', 'ok');
        $('msg').innerHTML = `Built. <a href="index.html?scene=${encodeURIComponent(name)}" style="color:var(--accent)">Open “${esc(name)}” in 3D</a>`;
      } else msg('Build failed - open “Technical details” above.', 'err');
      refresh(); break;
    }
  } } finally { window.alpBusy?.(false); }
}
function refreshAll(mode) {             // the logo spins until the job ends, however it ends
  window.alpBusy?.(true);
  return refreshAllJob(mode).finally(() => window.alpBusy?.(false));
}
async function refreshAllJob(mode) {
  const r = await fetch('/api/refresh-all', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, missing: $('fMissing').checked }) });
  const d = await r.json(), m = $('allMsg');
  if (!r.ok) { m.textContent = d.error; m.className = 'small err'; return; }
  const log = $('allLog'); log.classList.remove('hidden'); log.textContent = 'starting…';
  $('bRefreshAll').disabled = $('bZonesAll').disabled = $('bBldAll').disabled = true;
  m.textContent = mode === 'zones' ? 'Refreshing the drone zones of every scene…' : mode === 'buildings' ? 'Adding 3D buildings where they are missing…' : 'Updating every scene (terrain reused, your tracks kept)…'; m.className = 'small';
  for (;;) {
    await new Promise((ok) => setTimeout(ok, 800));
    const j = await (await fetch(`/api/jobs/${d.job}`)).json();
    log.textContent = j.lines.slice(-300).join('\n'); log.scrollTop = log.scrollHeight;
    if (j.status !== 'running') {
      $('bRefreshAll').disabled = $('bZonesAll').disabled = $('bBldAll').disabled = false;
      const failed = j.lines.filter((l) => /^(FAILED|\S+\s+FAILED)/.test(l.trim())).length;
      m.textContent = j.status === 'done' ? 'All scenes up to date.' : `Finished with ${failed || 'some'} error(s) - see the log.`;
      m.className = `small ${j.status === 'done' ? 'ok' : 'err'}`;
      refresh(); break;
    }
  }
}
$('bRefreshAll').onclick = () => refreshAll('all');
$('bZonesAll').onclick = () => refreshAll('zones');
$('bBldAll').onclick = () => refreshAll('buildings');
$('bSave').onclick = save;
$('bBuild').onclick = async () => { const n = await save(); if (n) build(n); };

// ---------------------------------------------------------------- search
// The worldwide search is off until switched on: it sends what is typed to a second outside service (Photon).
const WORLD_KEY = 'fpv3d:worldsearch';
try { $('fWorldSearch').checked = localStorage.getItem(WORLD_KEY) === '1'; } catch { /* private mode */ }
$('fWorldSearch').onchange = () => {
  try { localStorage.setItem(WORLD_KEY, $('fWorldSearch').checked ? '1' : '0'); } catch { /* private mode */ }
  $('search').dispatchEvent(new Event('input'));          // search again with the new choice
};
let searchT = null;
$('search').addEventListener('input', () => {
  clearTimeout(searchT);
  const q = $('search').value.trim();
  if (q.length < 2) { $('results').innerHTML = ''; return; }
  searchT = setTimeout(async () => {
    try {
      const world = $('fWorldSearch').checked;
      const res = await (await fetch(`/api/search?q=${encodeURIComponent(q)}${world ? '&world=1' : ''}`)).json();
      $('results').innerHTML = res.length ? '' : `<li class="muted">No match (or offline)${world ? '' : '. For places outside Switzerland, tick the box below or type a position (47.26 11.39).'}</li>`;
      for (const r of res) {
        const li = document.createElement('li'); li.textContent = r.label;
        li.onclick = () => {
          map.setView([r.lat, r.lon], 14);
          draft.center = [r.lat, r.lon]; draft.pilot = [r.lat, r.lon];
          if (!$('fTitle').value) { $('fTitle').value = r.label.split(/[,(]/)[0].trim(); $('fTitle').dispatchEvent(new Event('input')); }
          updatePreview(); $('results').innerHTML = ''; document.activeElement?.blur?.();   // the drop-down closes
        };
        $('results').appendChild(li);
      }
    } catch { $('results').innerHTML = '<li class="muted">search unavailable</li>'; }
  }, 300);
});

const tabs = initTabs($('panel'), { storageKey: 'fpv3d:maptab', fallback: 'new' });
$('topbar').querySelector('h1').onclick = () => tabs.toggle();

// ---------------------------------------------------------------- top bar: the position under the mouse, the ··· menu
const showPos = (lat, lon) => {
  const crs = crsFor(lat, lon), [e, n] = toGrid(lat, lon, crs);
  $('topCoords').textContent = `${fmtDeg(lat, lon)} · ${gridName(crs)} ${fmtLV(e, n)}`;
};
const showCentre = () => { const c = map.getCenter().wrap(); showPos(c.lat, c.lng); };
map.on('mousemove', (e) => { const w = e.latlng.wrap(); showPos(w.lat, w.lng); });
map.on('mouseout', showCentre);
map.on('moveend', () => { if (!$('map').matches(':hover')) showCentre(); });
showCentre();
// theme.js puts the dark / light switch next to the name once the page is there: it belongs in the menu, as in the viewer
addEventListener('DOMContentLoaded', () => {
  const sw = document.querySelector('#topbar .themeSw'), mode = document.querySelector('#topbar small.lite');
  if (sw) $('themeSlot').appendChild(sw);
  if (mode) $('modeSlot').appendChild(mode);
});
document.addEventListener('click', (ev) => { if (!$('topMenu').contains(ev.target)) $('topMenu').open = false; });
// the map's box changes when the panel folds or the window turns: Leaflet has to measure it again
new ResizeObserver(() => map.invalidateSize({ pan: false })).observe($('map'));
addEventListener('keydown', (e) => {
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
  const b = $('panel').querySelectorAll('.rail button[data-tab]')[+e.key - 1];
  if (b && /^[1-9]$/.test(e.key)) b.click();
});
updatePreview();
refresh();
