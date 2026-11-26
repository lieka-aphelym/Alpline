// fpv3d — [live] tab: telemetry from the radio (EdgeTX USB "Telemetry mirror", CRSF) on the 3D map,
// warnings for the pilot, and the last known position + likely impact zone when the link is lost.
import * as THREE from 'three';
import { createWarner } from './warn.js';
import { mountDrone } from '../core/drone.js';
import { createDroneMarker } from '../view/marker.js';
import { createPilotMarker, textSprite } from '../view/pilotmark.js';
import { pxPerUnit } from '../core/screen.js';
import { esc } from '../core/esc.js';
import { APP } from '../core/env.js';
import { toGrid, toWGS, isSwiss } from '../core/geo.js';

const $ = (id) => document.getElementById(id);
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
const fmtDist = (m) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);

export function initLive({ S, scene3, camera, controls, toWorld, demHeight, signalHeight = demHeight, onSaved, onStart }) {
  const W = createWarner({ S, demHeight, ceil: (x, y) => liveCeil(x, y),
    el: { box: $('warnBox'), title: $('warnTitle'), text: $('warnText'), detail: $('warnDetail'), dial: $('warnDial'), hand: $('warnHand') } });
  const st = { fixes: [], pilot: null, pilotManual: false, pilotLocked: false, rel: false, on: false, seq: 0, poll: null, calib: null, calibN: 0, calibSum: 0, last: null, prev: null, lost: false, trail: [], fps: 0 };

  // ------------------------------------------------------------ the live pilot: where you really are
  // The location file has a planned pilot point; at the field you may stand elsewhere. The live pilot is, in order:
  //   1. what you chose: your phone's GPS ([my position]) or a point picked on the map,
  //   2. the take-off point: the median of the drone's GPS positions while it sits on the ground (a single drifting
  //      fix can't move it), locked when it takes off so it never jumps during the flight,
  //   3. the location's pilot point.
  // The warnings compute the line of sight from it live (below), so nothing has to be rebuilt at the field.
  const P0 = S.meta.pilot, ANT = Math.max(0.5, (P0.z ?? 0) - (P0.ground ?? (P0.z ?? 0) - 1.8)) || 1.8;
  const PILOT_SRC = { location: "the location's pilot point", takeoff: 'the take-off point', phone: 'your phone\'s position', map: 'the point picked on the map' };
  function pilot() { return st.pilot || { x: P0.x, y: P0.y, z: P0.z, source: 'location' }; }
  function setLivePilot(x, y, source, n = 0) {
    st.pilot = { x, y, z: signalHeight(x, y) + ANT, source, n };   // on the roof when the point is inside a building
    showPilot();
  }
  const median = (a) => { const b = [...a].sort((p, q) => p - q); return b[b.length >> 1]; };
  function groundFix(x, y, sats) {                 // drone on the ground before take-off: collect positions
    if (st.pilotLocked || (st.pilot && st.pilot.source !== 'takeoff')) return;
    if (sats != null && sats < 5 && st.fixes.length) return;       // poor fixes only if there is nothing better
    st.fixes.push([x, y]); st.fixes.splice(0, st.fixes.length - 8);
    if (st.fixes.length >= 2) setLivePilot(median(st.fixes.map((f) => f[0])), median(st.fixes.map((f) => f[1])), 'takeoff', st.fixes.length);
  }
  // line of sight from the live pilot: the height above the ground needed at (x, y) to see the pilot, over the
  // terrain, with the earth's curvature (radio k = 4/3). At the location's own point the precomputed shadows serve.
  const kR2 = 2 * (4 / 3) * 6371000;
  function liveCeil(x, y) {
    if (x < 0 || y < 0 || x > S.W || y > S.H) return null;
    const p = pilot();
    if (p.source === 'location' && S.vol?.ceilAt) return S.vol.ceilAt('los', x, y);
    return ceilFrom(p, x, y);
  }
  function ceilFrom(p, x, y) {
    const D = Math.hypot(x - p.x, y - p.y), g = demHeight(x, y);
    if (D < 20) return 0;
    const n = Math.max(8, Math.min(300, Math.round(D / Math.max(2, S.meta.grid.res || 5))));
    let need = -Infinity;
    for (let i = 1; i < n; i++) {
      const t = i / n, d = t * D;
      if (d < 10) continue;                       // the ground right under the pilot's antenna
      const h = signalHeight(p.x + (x - p.x) * t, p.y + (y - p.y) * t) + d * (D - d) / kR2 + 3;   // +3 m: the browser's blended heights shave ridges a little
      need = Math.max(need, p.z + (h - p.z) / t);
    }
    return Math.max(0, need - g);
  }
  // the pilot when it is not the location's point (takeoff, phone GPS, picked on the map): the full marker moves
  // there, the location's own point stays as a faded ring, with a dashed link and the distance between the two
  const ghostMark = createPilotMarker({ THREE, scene3, camera, viewEl: document.getElementById('view'), faded: true });
  ghostMark.setVisible(false);
  const pLink = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
    new THREE.LineDashedMaterial({ color: 0xa9b4c2, dashSize: 4, gapSize: 3, transparent: true, opacity: 0.9, depthWrite: false }));
  pLink.visible = false; scene3.add(pLink);
  const pLinkTxt = textSprite(THREE, '', { w: 896, color: '#d6dde6' }); pLinkTxt.visible = false; scene3.add(pLinkTxt);
  const _p0 = new THREE.Vector3(), _p1 = new THREE.Vector3();
  function showPilot() {
    const p = pilot(), d0 = Math.hypot(p.x - P0.x, p.y - P0.y), moved = p.source !== 'location';
    const gnd = (x, y) => demHeight(x, y);
    if (S.pilotMarker) {
      const at = moved ? p : P0;
      S.pilotMarker.place(toWorld(at.x, at.y, gnd(at.x, at.y)), ANT, S.exag);
      S.rings?.setCenter(at.x, at.y);
    }
    ghostMark.setVisible(moved);
    pLink.visible = pLinkTxt.visible = moved && d0 > 5;
    if (moved) {
      ghostMark.place(toWorld(P0.x, P0.y, gnd(P0.x, P0.y)), ANT, S.exag);
      toWorld(P0.x, P0.y, gnd(P0.x, P0.y) + 1, _p0); toWorld(p.x, p.y, gnd(p.x, p.y) + 1, _p1);
      pLink.geometry.setFromPoints([_p0, _p1]); pLink.computeLineDistances();
      pLinkTxt.userData.set(`${fmtDist(d0)} from the location's point`);
      pLinkTxt.position.copy(_p0).lerp(_p1, 0.5);
    }
    const src = PILOT_SRC[p.source] + (p.source === 'takeoff' ? ` (${p.n} GPS${st.pilotLocked ? ', locked' : ''})` : '');
    $('lvPilotTxt').innerHTML = `Pilot: <b>${src}</b>` + (p.source !== 'location' && d0 > 15
      ? ` · ${fmtDist(d0)} from the location's point. Warnings use this position; the coloured maps are from the location's point.` : '');
    $('lvPilotSave').classList.toggle('hidden', p.source === 'location' || d0 < 15);
    S.requestRender?.(200);
  }

  // the drone: the same marker as the replay (marker.js), faded while its position is estimated between GPS fixes
  const MK = createDroneMarker({ THREE, scene3, camera, viewEl: document.getElementById('view') });
  const drone = MK.group;
  MK.setVisible(false);
  const mk = { vel: new THREE.Vector3(), color: 0x22d3ee, css: '#22d3ee', agl: null, groundY: null, estimated: false };
  const _gw = new THREE.Vector3();
  function placeMarker(x, y, z, vx, vy, vz) {
    toWorld(x, y, z, drone.position);
    mk.vel.set(vx, vz * S.exag, -vy);
    mk.agl = z - demHeight(x, y);
    mk.groundY = toWorld(x, y, demHeight(x, y), _gw).y;
  }
  const MAXP = 6000;
  const tGeo = new THREE.BufferGeometry();
  tGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(MAXP * 3), 3));
  tGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(MAXP * 3), 3));
  tGeo.setDrawRange(0, 0);
  const trail = new THREE.Line(tGeo, new THREE.LineBasicMaterial({ vertexColors: true }));
  trail.frustumCulled = false; scene3.add(trail);
  const pred = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
    new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 6, gapSize: 4 }));
  pred.visible = false; scene3.add(pred);
  const lostPin = new THREE.Group();
  const pinPole = new THREE.Mesh(new THREE.CylinderGeometry(1.5, 1.5, 1, 8), new THREE.MeshBasicMaterial({ color: 0xff3b30 }));
  const pinHead = new THREE.Mesh(new THREE.SphereGeometry(7, 14, 10), new THREE.MeshBasicMaterial({ color: 0xff3b30 }));
  lostPin.add(pinPole, pinHead); lostPin.visible = false; scene3.add(lostPin);
  let zoneMesh = null;

  // ------------------------------------------------------------ the drone icon: the link at a glance
  // grey = not connected · scanning corners = connecting · arming = first data · pings = link, slower and amber /
  // red as the link quality drops · take-off when it leaves the ground · grey again when the signal is lost
  const D = mountDrone($('liveDrone'), { size: 56 });
  D.off(true);
  const linkTxt = (t) => { $('liveLinkTxt').textContent = t; };
  // the coloured bar on the left of the status: off (grey) · ok (green) · warn (amber: weak link, GPS late) · lost (red)
  const hero = (state) => { $('lvHero').dataset.state = state; };
  const lqState = (lq) => (lq == null || lq >= 80 ? 'ok' : lq >= 60 ? 'warn' : 'lost');
  // one line on each folded section, so the settings can stay closed during a flight
  function summaries() {
    const modes = { mixed: 'sounds + voice', sounds: 'sounds only', voice: 'voice + beeps', off: 'off' };
    const on = 7 - W.cfg.muted.length;
    $('warnSum').textContent = `${modes[W.cfg.mode] || W.cfg.mode} · ${on} of 7 sounds · ${W.cfg.lookahead} s ahead`;
    $('recSum').textContent = [$('liveSave').checked ? 'saves the flight' : 'not saved', $('liveFollow').checked ? 'follows the drone' : 'free camera'].join(' · ');
    $('calSum').textContent = st.rel ? 'armed: height above the take-off point' : st.manual != null ? `manual ${st.manual} m` : st.calib != null ? `automatic (${st.calib >= 0 ? '+' : ''}${st.calib.toFixed(0)} m)` : 'automatic';
  }

  // ------------------------------------------------------------ UI
  const srcSel = $('liveSrc');
  async function fillPorts() {
    try {
      const r = await (await fetch('/api/live/ports')).json();
      $('livePort').innerHTML = r.ports.length ? r.ports.map((p) => `<option value="${esc(p.device)}">${esc(p.device)} · ${esc(p.description)}${p.likely ? ' (radio?)' : ''}</option>`).join('')
        : '<option value="">no serial port found</option>';
      $('livePortMsg').textContent = r.error || (r.ports.length ? '' : 'Plug the radio in USB and choose "USB Serial (VCP)" on the radio, then [refresh].');
    } catch { $('livePortMsg').textContent = 'needs the fpv3d server (python -m fpv3d serve)'; }
  }
  function fillTracks() {
    $('liveTrack').innerHTML = (S.meta.tracks || []).map((t) => `<option value="${esc(t.file)}">${esc(t.name)}</option>`).join('') || '<option value="">(no flight logs in this scene)</option>';
  }
  srcSel.onchange = () => {
    $('liveSerialRow').classList.toggle('hidden', srcSel.value !== 'serial');
    $('liveReplayRow').classList.toggle('hidden', srcSel.value !== 'replay');
    if (srcSel.value === 'serial') fillPorts(); else fillTracks();
  };
  $('livePortRefresh').onclick = fillPorts;
  $('liveConnect').onclick = () => (st.on ? disconnect() : connect());
  $('liveDisconnect').onclick = () => disconnect();
  $('lvPilotMe').onclick = () => {
    if (!navigator.geolocation) { $('livePilotText').textContent = 'This browser has no location (the phone needs the secure https page).'; return; }
    $('livePilotText').textContent = 'getting your position…';
    navigator.geolocation.getCurrentPosition((pos) => {
      const g = S.meta.grid, [e, n] = toGrid(pos.coords.latitude, pos.coords.longitude, g.crs), x = e - g.min_e, y = n - g.min_n;
      if (x < 0 || y < 0 || x > S.W || y > S.H) { $('livePilotText').textContent = 'You are outside this location\'s map.'; return; }
      st.pilotManual = true; setLivePilot(x, y, 'phone');
      $('livePilotText').textContent = `±${Math.round(pos.coords.accuracy)} m`;
    }, (err) => { $('livePilotText').textContent = `No position: ${err.message}`; }, { enableHighAccuracy: true, timeout: 15000 });
  };
  $('lvPilotPick').onclick = () => {
    $('livePilotText').textContent = 'Click the ground where you stand…';
    S.pickHook = (h) => { st.pilotManual = true; setLivePilot(h.x, h.y, 'map'); $('livePilotText').textContent = ''; };
  };
  $('lvPilotLoc').onclick = () => { st.pilotManual = true; st.pilot = null; showPilot(); $('livePilotText').textContent = ''; };
  $('lvPilotSave').onclick = () => { const p = pilot(), [lat, lon] = toWGS(S.meta.grid.min_e + p.x, S.meta.grid.min_n + p.y, S.meta.grid.crs); setPilot(lat, lon); };
  ['warnMode', 'warnLook', 'liveSave', 'liveFollow', 'liveCalib'].forEach((id) => $(id).addEventListener('change', () => summaries()));
  $('warnBoard').addEventListener('change', () => summaries());
  $('warnMode').value = W.cfg.mode;
  $('warnMode').onchange = () => { W.cfg.mode = $('warnMode').value; W.save(); };
  $('warnScreen').value = W.cfg.screen;
  $('warnScreen').onchange = () => W.setScreen($('warnScreen').value);
  $('warnBoard').onclick = (e) => { const s = e.target.closest('button')?.dataset.s; if (s) W.play(s); };
  for (const cb of $('warnBoard').querySelectorAll('input[data-g]')) {
    cb.checked = !W.cfg.muted.includes(cb.dataset.g);
    cb.onchange = () => W.setMuted(cb.dataset.g, !cb.checked);
  }
  $('warnLook').value = W.cfg.lookahead; $('warnLookOut').textContent = `${W.cfg.lookahead} s`;
  $('warnLook').oninput = () => { W.cfg.lookahead = +$('warnLook').value; $('warnLookOut').textContent = `${W.cfg.lookahead} s`; W.save(); };
  $('warnTest').onclick = () => W.test();
  // battery warnings: the pack (cells, capacity, its measured resistance), the share to land at, the low level
  const BC = W.bat.cfg;
  $('batWarnOn').checked = BC.on; $('batWarnPct').value = BC.landPct; $('batWarnLow').value = BC.low; $('batWarnHalf').checked = BC.half;
  async function loadPacks() {
    try {
      const o = await (await fetch('/api/battery/packs')).json();
      st.packs = o.packs.filter((p) => !p.retired);
      $('batWarnPack').innerHTML = '<option value="">cells from the voltage, no capacity</option>'
        + st.packs.map((p) => `<option value="${esc(p.id)}">${esc(p.name)} · ${p.cells}S ${p.capacity} mAh ${p.chem_label}</option>`).join('');
      if (st.packs.some((p) => p.id === BC.pack)) $('batWarnPack').value = BC.pack;
    } catch { /* no server data: the warnings still work from the voltage */ }
  }
  $('batWarnPack').addEventListener('change', () => {          // another pack: its chemistry's low level
    const p = st.packs?.find((x) => x.id === $('batWarnPack').value);
    $('batWarnLow').value = p ? p.warn_load : 3.3;
  });
  const batApply = () => {
    const p = st.packs?.find((x) => x.id === $('batWarnPack').value);
    W.bat.set({ on: $('batWarnOn').checked, landPct: +$('batWarnPct').value || 80, low: +$('batWarnLow').value || 3.3, half: $('batWarnHalf').checked,
      pack: p?.id || null, cells: p?.cells || 0, capacity: p?.capacity || 0, irCell: p?.ir_now || 0,
      critRest: p?.crit_rest || 3.4, chemistry: p?.chemistry || 'lipo' });
    W.save(); summaries();
  };
  ['batWarnOn', 'batWarnPack', 'batWarnPct', 'batWarnLow', 'batWarnHalf'].forEach((id) => $(id).addEventListener('change', batApply));
  loadPacks();
  $('liveCalib').onchange = () => { st.manual = $('liveCalib').value === '' ? null : +$('liveCalib').value; };
  summaries();
  showPilot();
  srcSel.onchange();

  // ------------------------------------------------------------ connect / poll
  async function connect() {
    $('liveMsg').textContent = 'connecting…'; $('liveMsg').className = 'small muted';
    D.off(false); D.flying(false); D.loop('scan'); linkTxt('connecting…'); hero('warn');
    $('liveStatus').textContent = srcSel.value === 'serial' ? `opening ${$('livePort').value || 'the port'}…` : 'starting the replay…';
    W.unlock();                                 // a click is needed before the browser plays sound
    const body = { scene: S.meta.name, source: srcSel.value };
    if (srcSel.value === 'serial') body.port = $('livePort').value;
    else { body.track = $('liveTrack').value; body.speed = +$('liveSpeed').value; }
    try {
      const r = await fetch('/api/live/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!r.ok || j.error) throw new Error(j.error || r.status);
    } catch (e) {
      $('liveMsg').textContent = e.message; $('liveMsg').className = 'small err';
      D.loop(null); D.off(true); linkTxt('not connected'); hero('off'); $('liveStatus').textContent = 'pick the radio and connect'; return;
    }
    W.bat.reset(); batApply();
    st.reconn = false;
    Object.assign(st, { armedShown: false, flying: false, seenGround: false, lastAt: 0, estAt: 0, gpsEvery: null, frameEvery: null,
      fixes: [], pilotLocked: false, rel: false, relBase: null, calibs: [] });
    if (!st.pilotManual) st.pilot = null;
    showPilot();
    Object.assign(st, { on: true, busy: false, endedShown: false, seq: 0, calib: null, calibN: 0, calibSum: 0, last: null, prev: null, lost: false, trail: [] });
    tGeo.setDrawRange(0, 0); lostPin.visible = false; if (zoneMesh) zoneMesh.visible = false; $('liveLost').classList.add('hidden');
    MK.setVisible(false);
    st.t0 = performance.now(); st.flyT0 = null;
    $('liveConnectBox').classList.add('hidden'); $('liveTiles').classList.remove('hidden', 'dim'); $('liveConnBar').classList.remove('hidden');
    $('liveConnTxt').textContent = (srcSel.value === 'serial' ? `${$('livePort').value} · radio` : 'replay')
      + ($('liveSave').checked ? ' · recording' : '');
    ['lvHeight', 'lvDist', 'lvSpeed', 'lvBatt', 'lvClimb', 'lvTime'].forEach((id) => { $(id).textContent = '–'; });
    document.body.classList.add('live-on');
    onStart?.();
    st.poll = setInterval(poll, 200);
    // warning sounds on their own timer: the 3D drawing loop stops when the page is hidden
    st.tickTimer = setInterval(() => { const now = performance.now(); estimate(now); W.tick(now); }, 100);
    keepAwake(true);
    $('livePilotText').textContent = '';
    const silent = W.silentSummary();             // never start a flight silent without saying so
    $('liveSilent').classList.toggle('hidden', !silent.length);
    $('liveSilent').innerHTML = silent.length ? `<b>Check your warnings:</b> ${silent.join(' · ')}. Change it in Warnings below.` : '';
  }

  // ------------------------------------------------------------ the page must stay in front during a live flight
  // Browsers slow down hidden pages (Chrome: timers at most once a second; Android: paused) and the screen may
  // turn off. Ask the screen to stay on (works on the PC; a phone needs https), and say so when the page hides.
  async function keepAwake(on) {
    try {
      if (on && 'wakeLock' in navigator && !st.wake) { st.wake = await navigator.wakeLock.request('screen'); st.wake.addEventListener?.('release', () => { st.wake = null; }); }
      if (!on && st.wake) { await st.wake.release(); st.wake = null; }
    } catch { st.wake = null; }          /* not allowed here (phone over http, battery saver) */
  }
  document.addEventListener('visibilitychange', () => {
    if (!st.on) return;
    if (document.hidden) {
      st.hiddenAt = performance.now();
      W.notice(`${APP} is in the background. Warnings may be late.`);
    } else {
      keepAwake(true);
      if (st.hiddenAt && performance.now() - st.hiddenAt > 1500) W.notice('Warnings back.');
      $('liveMsg').textContent = st.hiddenAt ? `The page was in the background: warnings may have been late or missing meanwhile. Keep ${APP} in front during the flight.` : $('liveMsg').textContent;
      $('liveMsg').className = 'small err';
      st.hiddenAt = null;
    }
  });
  async function disconnect() {
    clearInterval(st.poll); clearInterval(st.tickTimer); st.on = false;
    keepAwake(false); $('liveSilent').classList.add('hidden');
    $('liveConnectBox').classList.remove('hidden'); $('liveTiles').classList.add('hidden'); $('liveConnBar').classList.add('hidden');
    hero('off'); $('liveStatus').textContent = 'pick the radio and connect';
    document.body.classList.remove('live-on');
    W.stop(); pred.visible = false; MK.setVisible(false);
    D.loop(null); D.flying(false); D.off(true); linkTxt('not connected'); $('liveHint').classList.add('hidden');
    try {
      const r = await fetch('/api/live/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ save: $('liveSave').checked }) });
      const j = await r.json();
      $('liveMsg').textContent = j.file ? `Saved as a flight log: ${j.track}` : j.warning || `Stopped (${j.gps_count} GPS points${j.gps_count < 10 ? ', too few to save' : ''}).`;
      $('liveMsg').className = `small ${j.warning ? 'err' : 'ok'}`;
      if (j.file && W.bat.cfg.pack && j.track) {           // the saved flight flew this pack
        setTimeout(() => fetch('/api/battery/assign', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ flights: [j.track], pack: W.bat.cfg.pack }) }).catch(() => {}), 1500);
      }
      if (j.file) onSaved?.(j.file);
    } catch { /* server gone */ }
  }
  async function poll() {
    if (st.busy) return;                         // one request at a time
    st.busy = true;
    try { await pollOnce(); } finally { st.busy = false; }
  }
  async function pollOnce() {
    let j;
    try { j = await (await fetch(`/api/live/state?since=${st.seq}`)).json(); } catch { return; }
    if (!st.on) return;
    j.samples = j.samples.filter((s) => s.seq > st.seq);
    if (j.status === 'error') { $('liveMsg').textContent = j.error; $('liveMsg').className = 'small err'; disconnect(); return; }
    if (j.samples.length && $('liveMsg').textContent === 'connecting…') $('liveMsg').textContent = '';
    if (!st.armedShown && (j.samples.length || (j.frame_age != null && j.frame_age < 2.5))) {   // first data: the quad arms
      st.armedShown = true; D.play('arm', () => D.loop('ping')); D.loop('ping'); linkTxt('link'); hero('ok');
    }
    j.samples.forEach((s, i) => ingest(s, i === j.samples.length - 1));   // warnings only for the newest point
    const bs = [...j.samples].reverse().find((s) => s.voltage != null);
    if (bs) battery(bs);
    if (j.samples.length) st.seq = j.samples.at(-1).seq;
    st.gpsEvery = j.gps_every; st.frameEvery = j.frame_every;
    status(j);
    // the radio's USB link dropped: the server keeps trying to reopen the port; say so (once, with a sound)
    if (j.reconnecting && !st.reconn) {
      st.reconn = true; W.notice('Radio unplugged, reconnecting');
      $('liveMsg').textContent = 'Radio unplugged: check the USB cable. Reconnecting…'; $('liveMsg').className = 'small err';
    } else if (!j.reconnecting && st.reconn) {
      st.reconn = false; W.notice('Radio back');
      $('liveMsg').textContent = 'Radio reconnected.'; $('liveMsg').className = 'small ok';
    }
    // Signal lost = nothing at all from the drone for a while (link values included), measured against how often this
    // radio usually sends (some send GPS only every 3 s). A late GPS alone is not a loss: the position is estimated.
    const lostAfter = j.frame_every ? Math.max(2.5, 2 * j.frame_every + 0.5) : 5;   // 5 s until the rate is known
    if (st.last && j.frame_age != null && j.frame_age > lostAfter && !st.lost) markLost(j);
    if (st.lost && j.frame_age != null && j.frame_age < 1) { st.lost = false; $('liveLost').classList.add('hidden'); $('liveTiles').classList.remove('dim'); D.off(false); hero('ok'); }
    if (st.lost) $('liveLostAge').textContent = j.frame_age != null ? `· ${Math.round(j.frame_age)} s` : '';
    if (j.status === 'ended' && !st.endedShown) { st.endedShown = true; $('liveMsg').textContent = 'Replay finished.'; }
  }

  function battery(s) {
    const ev = W.battery({ voltage: s.voltage, current: s.current, mah: s.mah });
    const b = W.bat.status;
    if (b) {
      $('lvBatt').innerHTML = `${b.cell.toFixed(2)}<small> V</small>`;
      $('lvBattSub').textContent = s.mah != null ? `per cell · ${b.used != null ? `${Math.round(b.used * 100)} %` : `${Math.round(s.mah)} mAh`}` : 'per cell';
      $('lvBattSub').title = `${s.voltage.toFixed(1)} V pack, ${b.cells}S` + (s.mah != null ? ` · ${Math.round(s.mah)} mAh used` : '');
      $('lvBatt').parentElement.classList.toggle('batLow', b.cell < W.bat.cfg.low || (b.used ?? 0) >= W.bat.cfg.landPct / 100);
    }
    if (ev && ev.level !== 'info') $('liveMsg').textContent = ev.text;
  }

  function ingest(s, newest = true) {
    if (s.lat == null || Math.abs(s.lat) < 1e-6) return;
    const g = S.meta.grid, [e, n] = toGrid(s.lat, s.lon, g.crs), x = e - g.min_e, y = n - g.min_n;
    const ground = demHeight(x, y), spd = (s.speed_kmh || 0) / 3.6;
    // altitude: GPS, corrected by an offset measured while the drone sits on the ground
    if (st.manual == null && st.calibN < 5 && spd < 0.8 && Math.abs(s.vspeed || 0) < 0.5 && s.alt != null) {
      (st.calibs ||= []).push(ground + 0.2 - s.alt); st.calibN++;
      st.calib = median(st.calibs);                // median: one drifting GPS fix doesn't shift the heights
    }
    // Altitude. Disarmed, Betaflight sends the GPS altitude above sea level (corrected by the offset measured on
    // the ground). Armed, it sends the height above the arming point instead (760 m becomes 0). Switzerland is never
    // below ~190 m, so an altitude far below the ground under the drone can only be that height above take-off:
    // it is added to the ground height where the drone armed.
    let z;
    if (s.alt != null && s.alt < ground - 100) {
      if (!st.rel) { st.rel = true; st.relBase = st.fixes.length ? demHeight(median(st.fixes.map((f) => f[0])), median(st.fixes.map((f) => f[1]))) : ground; }
      z = st.relBase + 0.2 + s.alt;
    } else {
      if (st.rel) st.rel = false;                 // disarmed again: back to the GPS altitude
      z = (s.alt ?? ground) + (st.manual ?? st.calib ?? 0);
    }
    if (!st.flying && spd < 1) groundFix(x, y, s.sats);              // on the ground: the take-off point = the pilot
    const h = (s.heading || 0) * Math.PI / 180;
    let vz = s.vspeed;
    if (vz == null && st.last) vz = (z - st.last.z) / Math.max(s.t - st.last.t, 0.05);
    const cur = { t: s.t, x, y, z, agl: z - ground, vx: spd * Math.sin(h), vy: spd * Math.cos(h), vz: vz || 0, heading: s.heading || 0, lq: s.lq, raw: s };
    st.prev = st.last; st.last = cur;
    if (newest) { st.lastAt = performance.now(); st.estAt = 0; mk.estimated = false; }
    if (cur.agl < 3 && spd < 1) st.seenGround = true;      // every sample: a batch may hold the takeoff
    if (newest) {
      D.link(s.lq);
      linkTxt(s.lq != null ? `link · LQ ${Math.round(s.lq)} %` : 'link');
      if (!st.flying && cur.agl > 5 && spd > 2) {          // take-off, only if we saw it on the ground (else: connected mid-air)
        st.flying = true; st.flyT0 ??= performance.now();
        if (!st.pilotManual && st.pilot) { st.pilotLocked = true; showPilot(); }   // the take-off point stays put now
        if (st.seenGround) D.play('takeoff', () => D.loop('ping')); else D.flying(true);
      }
      else if (st.flying && cur.agl < 2 && spd < 1) { st.flying = false; D.flying(false); }
    }
    // drone + trail
    MK.setVisible(true);
    placeMarker(x, y, z, cur.vx, cur.vy, cur.vz);
    const col = new THREE.Color(s.lq == null ? 0x22d3ee : s.lq >= 80 ? 0x2ecc71 : s.lq >= 60 ? 0xffb000 : 0xff3b30);
    mk.color = col; mk.css = '#' + col.getHexString();
    const i = st.trail.length % MAXP;
    st.trail.push(1);
    tGeo.attributes.position.setXYZ(i, drone.position.x, drone.position.y, drone.position.z);
    tGeo.attributes.color.setXYZ(i, col.r, col.g, col.b);
    tGeo.attributes.position.needsUpdate = tGeo.attributes.color.needsUpdate = true;
    tGeo.setDrawRange(0, Math.min(st.trail.length, MAXP));
    // predicted path
    const L = W.cfg.lookahead, a = toWorld(x, y, z), b = toWorld(x + cur.vx * L, y + cur.vy * L, z + cur.vz * L);
    pred.geometry.setFromPoints([a, b]); pred.computeLineDistances(); pred.visible = spd > 1.5;
    if (!newest) return;
    if ($('liveFollow').checked) controls.target.lerp(drone.position, 0.5);
    S.requestRender?.(400);
    const r = W.update(cur);
    pred.material.color.set(r.level === 'ok' ? 0xffffff : r.level === 'caution' ? 0xffb000 : 0xff3b30);
    values(cur, s);
  }

  // ------------------------------------------------------------ between two GPS positions: estimate the path
  // Radios send GPS from several times a second down to once every ~3 s. Between two positions the drone keeps
  // moving on its last speed, heading and climb, drawn faded ("estimated"), and the warnings look ahead from there.
  // It stops estimating after twice the usual GPS interval (at least 3 s) and holds; at the next fix it snaps back.
  function estimate(now) {
    const c = st.last;
    if (!st.on || !c || st.lost || !st.lastAt) return;
    const dt = (now - st.lastAt) / 1000;
    if (dt < 0.25) return;                                  // the real position is fresh
    const t = Math.min(dt, Math.max(3, 2 * (st.gpsEvery || 1)));
    const x = c.x + c.vx * t, y = c.y + c.vy * t, g = demHeight(x, y), z = Math.max(g + 0.5, c.z + c.vz * t);
    placeMarker(x, y, z, c.vx, c.vy, c.vz);
    mk.estimated = true;
    const L = W.cfg.lookahead;
    pred.geometry.setFromPoints([toWorld(x, y, z), toWorld(x + c.vx * L, y + c.vy * L, z + c.vz * L)]); pred.computeLineDistances();
    S.requestRender?.(200);
    if (now - (st.estAt || 0) < 250) return;                // warnings 4 times a second from the estimate
    st.estAt = now;
    const r = W.update({ ...c, x, y, z, agl: z - g });
    pred.material.color.set(r.level === 'ok' ? 0xffffff : r.level === 'caution' ? 0xffb000 : 0xff3b30);
  }

  // ------------------------------------------------------------ is the pilot where the location says?
  // Signal shadows are computed from the location's pilot point. Taking off far from it means every warning is
  // computed from the wrong place: say so, and offer to move the pilot point there (rebuilds the shadows).
  async function setPilot(lat, lon) {
    $('lvPilotSave').disabled = true;
    $('livePilotText').textContent = 'Saving the new pilot point and rebuilding the shadows…';
    window.alpBusy?.(true);
    try {
      const r = await fetch('/api/pilot', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scene: S.meta.name, lat, lon }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 1500));
        const k = await (await fetch(`/api/jobs/${j.job}`)).json();
        if (k.status === 'running') { $('livePilotText').textContent = `Rebuilding the shadows… ${(k.lines || []).at(-1) || ''}`; continue; }
        $('livePilotText').innerHTML = k.status === 'done'
          ? 'Done: the pilot point is now your takeoff point. <b>Disconnect and reload the page</b> to use the new shadows.'
          : `The rebuild failed: ${(k.lines || []).at(-1) || k.status}`;
        break;
      }
    } catch (e) { $('livePilotText').textContent = `Could not move the pilot point: ${e.message}`; $('lvPilotSave').disabled = false; }
    finally { window.alpBusy?.(false); }
  }

  function values(c, s) {
    const p = pilot(), d = Math.hypot(c.x - p.x, c.y - p.y, c.z - p.z);
    const cell = (k, v) => `<div><span class="muted">${k}</span><b>${v ?? '–'}</b></div>`;
    $('liveVals').innerHTML = [
      cell('LQ', s.lq != null ? `${s.lq}%` : null), cell('RSSI', s.rssi1 != null ? `${s.rssi1} dBm` : null), cell('SNR', s.snr),
      cell('TX power', s.tx_power != null ? `${s.tx_power} mW` : null), cell('battery', s.voltage != null ? `${s.voltage.toFixed(1)} V` : null),
      cell('mode', s.mode), cell('height', `${Math.round(c.agl)} m AGL`), cell('speed', `${Math.round(s.speed_kmh || 0)} km/h`),
      cell('distance', fmtDist(d)), cell('sats', s.sats),
    ].join('');
    const u = (v, unit) => `${v}<small> ${unit}</small>`;
    $('lvHeight').innerHTML = u(Math.round(c.agl), 'm');
    $('lvDist').innerHTML = d >= 1000 ? u((d / 1000).toFixed(2), 'km') : u(Math.round(d), 'm');
    $('lvSpeed').innerHTML = u(Math.round(s.speed_kmh || 0), 'km/h');
    $('lvClimb').innerHTML = u(`${c.vz >= 0 ? '+' : ''}${c.vz.toFixed(1)}`, 'm/s');
    $('liveCalibInfo').textContent = st.manual != null ? `manual correction ${st.manual} m`
      : st.calib != null ? `GPS altitude corrected by ${st.calib >= 0 ? '+' : ''}${st.calib.toFixed(1)} m (measured on the ground)`
        : 'GPS altitude uncorrected (connect while the drone is on the ground to calibrate)';
    summaries();
  }
  function status(j) {
    const every = j.gps_every || 0, fresh = j.gps_age != null && j.gps_age < Math.max(1.5, 1.5 * every);
    const late = st.last && !st.lost && j.gps_age != null && j.gps_age > Math.max(4, 2.5 * every);
    const L0 = j.latest || {};
    // the line under the status: RSSI · how old the GPS position is (and that it is estimated in between) · satellites
    if (!st.lost && j.status === 'live') {
      const parts = [];
      if (L0.rssi1 != null) parts.push(`RSSI ${L0.rssi1} dBm`);
      if (st.last && j.gps_age != null) parts.push(late ? `<b style="color:var(--warn)">GPS late · ${j.gps_age.toFixed(0)} s</b>`
        : `GPS ${j.gps_age.toFixed(1)} s ago${!fresh || j.gps_age > 0.6 ? ' · estimated' : ''}`);
      else if (j.frames) parts.push('waiting for a GPS fix');
      if (L0.sats != null) parts.push(`${L0.sats} sats`);
      $('liveStatus').innerHTML = parts.join(' · ') || (j.frames ? 'link' : 'waiting for the radio…');
      $('liveStatus').title = `GPS every ${every ? every.toFixed(1) + ' s' : '?'} · ${j.gps_count} positions · ${j.frames} frames${j.bad ? ` (${j.bad} bad)` : ''}`;
      if (j.frames) hero(late ? 'warn' : lqState(L0.lq));
    } else if (j.status === 'ended' && !st.lost) $('liveStatus').textContent = 'replay finished';
    if (st.t0) {                                   // flight time: from take-off (or from connecting when already flying)
      const t = (performance.now() - (st.flyT0 ?? st.t0)) / 1000;
      $('lvTime').textContent = `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
    }
    // why nothing shows: tell the three cases apart (radio silent / not telemetry / telemetry without a GPS fix)
    const L = j.latest || {}, serial = j.source === 'serial', waited = (j.open_for ?? 0) > 3;
    let hint = '';
    if (j.status === 'live' && serial && waited && !j.bytes) {
      hint = `<b>Nothing comes from the radio</b> on ${j.port || 'this port'}. On the radio: <b>SYS → Hardware → Serial ports</b>, set
        <b>USB-VCP</b> to <b>Telemetry Mirror</b> (not CLI or debug). Plug the cable and choose <b>USB Serial (VCP)</b>, not USB Storage
        or Joystick. Then the drone must be <b>on and bound</b>: the radio only passes on the drone's telemetry. Wrong port? Pick the
        other one under Source and [connect] again.`;
    } else if (j.status === 'live' && serial && waited && j.bytes && !j.frames) {
      hint = `<b>Data arrives (${j.bytes} bytes) but it isn't telemetry.</b> On the radio, <b>SYS → Hardware → Serial ports →
        USB-VCP</b> is set to another mode: set it to <b>Telemetry Mirror</b>.`;
    } else if (j.status === 'live' && j.frames && !st.last) {
      hint = `<b>Telemetry is coming in</b>${L.lq != null ? ` (LQ ${Math.round(L.lq)} %)` : ''}, but no GPS position yet${L.sats != null
        ? ` (${L.sats} satellites)` : ''}. The drone appears on the map once its GPS has a fix: outdoors, usually within a minute or two.
        A drone without GPS shows the link values only.`;
    }
    $('liveHint').innerHTML = hint;
    $('liveHint').classList.toggle('hidden', !hint);
    if (j.status === 'live' && j.frames && L.lq != null && !st.lost) {   // link values come more often than GPS
      D.link(L.lq); linkTxt(`link · LQ ${Math.round(L.lq)} %${st.last ? '' : ' · no GPS'}`);
    } else if (j.status === 'live' && serial && waited && !j.frames) linkTxt('no data from the radio');
  }

  // ------------------------------------------------------------ lost: last known position + likely impact zone
  function markLost(j) {
    st.lost = true;
    D.off(true); linkTxt('signal lost'); hero('lost'); $('liveTiles').classList.add('dim');
    $('liveStatus').textContent = 'no telemetry from the drone';
    const c = st.last, p = pilot();
    toWorld(c.x, c.y, demHeight(c.x, c.y), lostPin.position);
    const hgt = 40 * S.exag; pinPole.scale.y = hgt; pinPole.position.y = hgt / 2; pinHead.position.y = hgt;
    lostPin.visible = true;
    // free fall from the last fix, still moving forward and slowed by drag: min..max reach along the course
    const v = Math.hypot(c.vx, c.vy), hAgl = Math.max(c.agl, 0);
    const tf = (c.vz + Math.sqrt(c.vz * c.vz + 19.6 * hAgl)) / 9.81;
    const dMin = 0.3 * v * tf, dMax = Math.max(v * tf, 10), half = Math.max(15, 0.3 * dMax) + 5;
    drawZone(c, dMin, dMax, half);
    const dx = c.x - p.x, dy = c.y - p.y, dist = Math.hypot(dx, dy), brg = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
    const lat = c.raw.lat.toFixed(6), lon = c.raw.lon.toFixed(6);
    $('liveLost').classList.remove('hidden');
    $('liveLostText').innerHTML = `Last fix <b>${fmtDist(dist)}</b> ${COMPASS[Math.round(brg / 45) % 8]} of the pilot (${Math.round(brg)}°), ${Math.round(hAgl)} m above ground, ${Math.round(v * 3.6)} km/h.<br>`
      + `Likely impact: ${Math.round(dMin)}–${Math.round(dMax)} m further along its course (red area).<br><span class="muted">GPS ${lat}, ${lon}</span>`;
    $('liveCopy').onclick = () => navigator.clipboard?.writeText(`${lat}, ${lon}`);
    $('liveGeoAdmin').href = isSwiss(S.meta.grid.crs) ? `https://map.geo.admin.ch/?swisssearch=${lat},${lon}&zoom=10`
      : `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=16/${lat}/${lon}`;
    $('liveGeoAdmin').textContent = isSwiss(S.meta.grid.crs) ? '[map.geo.admin]' : '[OpenStreetMap]';
    $('liveZoom').onclick = () => { controls.target.copy(lostPin.position); camera.position.copy(lostPin.position).add(new THREE.Vector3(-120, 150, 160)); };
    W.lost(`Last fix ${fmtDist(dist)} ${COMPASS[Math.round(brg / 45) % 8]} of the pilot`);
  }
  function drawZone(c, dMin, dMax, half) {
    if (zoneMesh) { scene3.remove(zoneMesh); zoneMesh.geometry.dispose(); }
    const h = c.heading * Math.PI / 180, fx = Math.sin(h), fy = Math.cos(h), rx = Math.cos(h), ry = -Math.sin(h);
    const N = 24, M = 8, pos = [], idx = [];
    const L0 = Math.max(0, dMin - 10), L1 = dMax + 10;
    for (let i = 0; i <= N; i++) {              // ellipse along the course, draped on the terrain
      const u = i / N, along = L0 + (L1 - L0) * u, w = half * Math.sqrt(Math.max(0, 1 - (2 * u - 1) ** 2));
      for (let j = 0; j <= M; j++) {
        const across = w * (2 * j / M - 1), x = c.x + fx * along + rx * across, y = c.y + fy * along + ry * across;
        const v = toWorld(x, y, demHeight(x, y) + 1.5); pos.push(v.x, v.y, v.z);
      }
    }
    for (let i = 0; i < N; i++) for (let j = 0; j < M; j++) {
      const a = i * (M + 1) + j, b = a + 1, d = a + M + 1, e2 = d + 1; idx.push(a, d, b, b, d, e2);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx);
    zoneMesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: 0xff3b30, transparent: true, opacity: 0.4, depthWrite: false, side: THREE.DoubleSide }));
    zoneMesh.renderOrder = 6;
    scene3.add(zoneMesh);
  }

  // ------------------------------------------------------------ simulator hook (warnings while training)
  function simTick(sim) {
    if (!$('warnSim').checked || st.on) return;
    const x = sim.pos.x + S.W / 2, y = -sim.pos.z + S.H / 2, z = sim.pos.y + S.hBase;
    const hd = (Math.atan2(sim.vel.x, -sim.vel.z) * 180 / Math.PI + 360) % 360;
    W.update({ x, y, z, vx: sim.vel.x, vy: -sim.vel.z, vz: sim.vel.y, heading: hd, lq: null });
  }

  return {
    simTick, simStop: () => { if (!st.on) W.stop(); },
    tick(now) {
      W.tick(now);
      if (ghostMark.visible) {
        ghostMark.update(null);
        const ppu = pxPerUnit(camera, document.getElementById('view'), camera.position.distanceTo(pLinkTxt.position));
        const hs = 30 / ppu; pLinkTxt.scale.set(hs * pLinkTxt.userData.aspect, hs, 1);
        pLinkTxt.center.set(0.5, -0.6);                       // just above the dashed link
        pLink.material.dashSize = Math.max(2, camera.position.distanceTo(pLinkTxt.position) / 60); pLink.material.gapSize = pLink.material.dashSize * 0.7;
      }
      if (MK.visible) { MK.style({ faded: mk.estimated }); MK.update({ vel: mk.vel, acc: null, color: mk.color, css: mk.css, groundY: mk.groundY, agl: mk.agl, now }); }
    },
    /** where the live drone is drawn (the pilot's antenna turns toward it), or null */
    dronePos: () => (MK.visible ? drone.position : null),
    setExag() { showPilot(); if (st.last) placeMarker(st.last.x, st.last.y, st.last.z, st.last.vx, st.last.vy, st.last.vz); },
    /** for the automated checks: where the drone is drawn and whether that is an estimate */
    ceilCheck: (pts) => pts.map(([x, y]) => [S.vol?.ceilAt ? S.vol.ceilAt('los', x, y) : null, ceilFrom({ x: P0.x, y: P0.y, z: P0.z }, x, y)]),
    debug: () => ({ x: drone.position.x, z: drone.position.z, opacity: mk.estimated ? 0.55 : 1, lost: st.lost, pilot: pilot(), rel: st.rel, last: st.last && { agl: st.last.agl, z: st.last.z } }),
  };
}
