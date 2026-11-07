// fpv3d — [live] tab: telemetry from the radio (EdgeTX USB "Telemetry mirror", CRSF) on the 3D map,
// warnings for the pilot, and the last known position + likely impact zone when the link is lost.
import * as THREE from 'three';
import { createWarner } from './warn.js';
import { mountDrone } from './drone.js';

const $ = (id) => document.getElementById(id);
function toLV95(lat, lon) {
  const p = (lat * 3600 - 169028.66) / 10000, l = (lon * 3600 - 26782.5) / 10000;
  return [2600072.37 + 211455.93 * l - 10938.51 * l * p - 0.36 * l * p * p - 44.54 * l ** 3,
    1200147.07 + 308807.95 * p + 3745.25 * l * l + 76.63 * p * p - 194.56 * l * l * p + 119.79 * p ** 3];
}
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
const fmtDist = (m) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);

export function initLive({ S, scene3, camera, controls, toWorld, demHeight, onSaved, onStart }) {
  const W = createWarner({ S, demHeight, el: { box: $('warnBox'), title: $('warnTitle'), text: $('warnText'), detail: $('warnDetail'), dial: $('warnDial'), hand: $('warnHand') } });
  const st = { on: false, seq: 0, poll: null, calib: null, calibN: 0, calibSum: 0, last: null, prev: null, lost: false, trail: [], fps: 0 };

  // ------------------------------------------------------------ 3D objects
  const drone = new THREE.Group();
  const body = new THREE.Mesh(new THREE.ConeGeometry(6, 16, 4), new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true }));
  body.rotation.x = Math.PI / 2;
  const halo = new THREE.Mesh(new THREE.SphereGeometry(13, 16, 12), new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.25, depthWrite: false }));
  drone.add(body, halo); drone.visible = false; scene3.add(drone);
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

  // ------------------------------------------------------------ UI
  const srcSel = $('liveSrc');
  async function fillPorts() {
    try {
      const r = await (await fetch('/api/live/ports')).json();
      $('livePort').innerHTML = r.ports.length ? r.ports.map((p) => `<option value="${p.device}">${p.device} · ${p.description}${p.likely ? ' (radio?)' : ''}</option>`).join('')
        : '<option value="">no serial port found</option>';
      $('livePortMsg').textContent = r.error || (r.ports.length ? '' : 'Plug the radio in USB and choose "USB Serial (VCP)" on the radio, then [refresh].');
    } catch { $('livePortMsg').textContent = 'needs the fpv3d server (python -m fpv3d serve)'; }
  }
  function fillTracks() {
    $('liveTrack').innerHTML = (S.meta.tracks || []).map((t) => `<option value="${t.file}">${t.name}</option>`).join('') || '<option value="">(no flight logs in this scene)</option>';
  }
  srcSel.onchange = () => {
    $('liveSerialRow').classList.toggle('hidden', srcSel.value !== 'serial');
    $('liveReplayRow').classList.toggle('hidden', srcSel.value !== 'replay');
    if (srcSel.value === 'serial') fillPorts(); else fillTracks();
  };
  $('livePortRefresh').onclick = fillPorts;
  $('liveConnect').onclick = () => (st.on ? disconnect() : connect());
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
  $('liveCalib').onchange = () => { st.manual = $('liveCalib').value === '' ? null : +$('liveCalib').value; };
  srcSel.onchange();

  // ------------------------------------------------------------ connect / poll
  async function connect() {
    $('liveMsg').textContent = 'connecting…'; $('liveMsg').className = 'small muted';
    D.off(false); D.flying(false); D.loop('scan'); linkTxt('connecting…');
    W.unlock();                                 // a click is needed before the browser plays sound
    const body = { scene: S.meta.name, source: srcSel.value };
    if (srcSel.value === 'serial') body.port = $('livePort').value;
    else { body.track = $('liveTrack').value; body.speed = +$('liveSpeed').value; }
    try {
      const r = await fetch('/api/live/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!r.ok || j.error) throw new Error(j.error || r.status);
    } catch (e) { $('liveMsg').textContent = e.message; $('liveMsg').className = 'small err'; D.loop(null); D.off(true); linkTxt('not connected'); return; }
    Object.assign(st, { armedShown: false, flying: false, seenGround: false, lastAt: 0, estAt: 0, gpsEvery: null, frameEvery: null });
    Object.assign(st, { on: true, busy: false, endedShown: false, seq: 0, calib: null, calibN: 0, calibSum: 0, last: null, prev: null, lost: false, trail: [] });
    tGeo.setDrawRange(0, 0); lostPin.visible = false; if (zoneMesh) zoneMesh.visible = false; $('liveLost').classList.add('hidden');
    $('liveConnect').textContent = '[disconnect]'; $('liveConnect').classList.add('danger');
    document.body.classList.add('live-on');
    onStart?.();
    st.poll = setInterval(poll, 200);
    // warning sounds on their own timer: the 3D drawing loop stops when the page is hidden
    st.tickTimer = setInterval(() => { const now = performance.now(); estimate(now); W.tick(now); }, 100);
    keepAwake(true);
    st.pilotChecked = false; $('livePilot').classList.add('hidden');
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
      W.notice('Alpline is in the background. Warnings may be late.');
    } else {
      keepAwake(true);
      if (st.hiddenAt && performance.now() - st.hiddenAt > 1500) W.notice('Warnings back.');
      $('liveMsg').textContent = st.hiddenAt ? 'The page was in the background: warnings may have been late or missing meanwhile. Keep Alpline in front during the flight.' : $('liveMsg').textContent;
      $('liveMsg').className = 'small err';
      st.hiddenAt = null;
    }
  });
  async function disconnect() {
    clearInterval(st.poll); clearInterval(st.tickTimer); st.on = false;
    keepAwake(false); $('liveSilent').classList.add('hidden');
    $('liveConnect').textContent = '[connect]'; $('liveConnect').classList.remove('danger');
    document.body.classList.remove('live-on');
    W.stop(); pred.visible = false;
    D.loop(null); D.flying(false); D.off(true); linkTxt('not connected'); $('liveHint').classList.add('hidden');
    try {
      const r = await fetch('/api/live/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ save: $('liveSave').checked }) });
      const j = await r.json();
      $('liveMsg').textContent = j.file ? `Saved as a flight log: ${j.track}` : j.warning || `Stopped (${j.gps_count} GPS points${j.gps_count < 10 ? ', too few to save' : ''}).`;
      $('liveMsg').className = `small ${j.warning ? 'err' : 'ok'}`;
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
      st.armedShown = true; D.play('arm', () => D.loop('ping')); D.loop('ping'); linkTxt('link');
    }
    j.samples.forEach((s, i) => ingest(s, i === j.samples.length - 1));   // warnings only for the newest point
    if (j.samples.length) st.seq = j.samples.at(-1).seq;
    st.gpsEvery = j.gps_every; st.frameEvery = j.frame_every;
    status(j);
    // Signal lost = nothing at all from the drone for a while (link values included), measured against how often this
    // radio usually sends (some send GPS only every 3 s). A late GPS alone is not a loss: the position is estimated.
    const lostAfter = Math.max(2.5, 2 * (j.frame_every || 0) + 0.5);
    if (st.last && j.frame_age != null && j.frame_age > lostAfter && !st.lost) markLost(j);
    if (st.lost && j.frame_age != null && j.frame_age < 1) { st.lost = false; $('liveLost').classList.add('hidden'); D.off(false); }
    if (j.status === 'ended' && !st.endedShown) { st.endedShown = true; $('liveMsg').textContent = 'Replay finished.'; }
  }

  function ingest(s, newest = true) {
    if (s.lat == null || Math.abs(s.lat) < 1e-6) return;
    const g = S.meta.grid, [e, n] = toLV95(s.lat, s.lon), x = e - g.min_e, y = n - g.min_n;
    const ground = demHeight(x, y), spd = (s.speed_kmh || 0) / 3.6;
    // altitude: GPS, corrected by an offset measured while the drone sits on the ground
    if (st.manual == null && st.calibN < 5 && spd < 0.8 && Math.abs(s.vspeed || 0) < 0.5 && s.alt != null) {
      st.calibSum += ground + 0.2 - s.alt; st.calibN++; st.calib = st.calibSum / st.calibN;
    }
    if (!st.pilotChecked && st.calibN >= 3) checkPilot(x, y, s);     // drone on the ground = the takeoff point
    const off = st.manual ?? st.calib ?? 0;
    const z = (s.alt ?? ground) + off;
    const h = (s.heading || 0) * Math.PI / 180;
    let vz = s.vspeed;
    if (vz == null && st.last) vz = (z - st.last.z) / Math.max(s.t - st.last.t, 0.05);
    const cur = { t: s.t, x, y, z, agl: z - ground, vx: spd * Math.sin(h), vy: spd * Math.cos(h), vz: vz || 0, heading: s.heading || 0, lq: s.lq, raw: s };
    st.prev = st.last; st.last = cur;
    if (newest) { st.lastAt = performance.now(); st.estAt = 0; body.material.opacity = 1; halo.material.opacity = 0.25; }
    if (cur.agl < 3 && spd < 1) st.seenGround = true;      // every sample: a batch may hold the takeoff
    if (newest) {
      D.link(s.lq);
      linkTxt(s.lq != null ? `LQ ${Math.round(s.lq)} %` : 'link');
      if (!st.flying && cur.agl > 5 && spd > 2) {          // take-off, only if we saw it on the ground (else: connected mid-air)
        st.flying = true;
        if (st.seenGround) D.play('takeoff', () => D.loop('ping')); else D.flying(true);
      }
      else if (st.flying && cur.agl < 2 && spd < 1) { st.flying = false; D.flying(false); }
    }
    // drone + trail
    drone.visible = true;
    toWorld(x, y, z, drone.position);
    drone.rotation.y = -h;
    const col = new THREE.Color(s.lq == null ? 0x22d3ee : s.lq >= 80 ? 0x2ecc71 : s.lq >= 60 ? 0xffb000 : 0xff3b30);
    body.material.color.copy(col); halo.material.color.copy(col);
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
    toWorld(x, y, z, drone.position);
    body.material.opacity = 0.55; halo.material.opacity = 0.12;
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
  function checkPilot(x, y, s) {
    st.pilotChecked = true;
    const p = S.meta.pilot, d = Math.hypot(x - p.x, y - p.y);
    if (d < 75) return;
    const dx = x - p.x, dy = y - p.y, brg = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
    $('livePilot').classList.remove('hidden');
    $('livePilotText').innerHTML = `You took off <b>${fmtDist(d)}</b> ${COMPASS[Math.round(brg / 45) % 8]} of this location's pilot point. `
      + 'The signal shadows and warnings are computed from that point, so they may be wrong here.';
    $('livePilotSet').disabled = false;
    $('livePilotSet').onclick = () => setPilot(s.lat, s.lon);
    W.notice(`Takeoff is ${Math.round(d / 10) * 10} meters from the pilot point. Warnings may be wrong.`);
  }
  async function setPilot(lat, lon) {
    $('livePilotSet').disabled = true;
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
    } catch (e) { $('livePilotText').textContent = `Could not move the pilot point: ${e.message}`; $('livePilotSet').disabled = false; }
    finally { window.alpBusy?.(false); }
  }

  function values(c, s) {
    const p = S.meta.pilot, d = Math.hypot(c.x - p.x, c.y - p.y, c.z - p.z);
    const cell = (k, v) => `<div><span class="muted">${k}</span><b>${v ?? '–'}</b></div>`;
    $('liveVals').innerHTML = [
      cell('LQ', s.lq != null ? `${s.lq}%` : null), cell('RSSI', s.rssi1 != null ? `${s.rssi1} dBm` : null), cell('SNR', s.snr),
      cell('TX power', s.tx_power != null ? `${s.tx_power} mW` : null), cell('battery', s.voltage != null ? `${s.voltage.toFixed(1)} V` : null),
      cell('mode', s.mode), cell('height', `${Math.round(c.agl)} m AGL`), cell('speed', `${Math.round(s.speed_kmh || 0)} km/h`),
      cell('distance', fmtDist(d)), cell('sats', s.sats),
    ].join('');
    $('liveCalibInfo').textContent = st.manual != null ? `manual correction ${st.manual} m`
      : st.calib != null ? `GPS altitude corrected by ${st.calib >= 0 ? '+' : ''}${st.calib.toFixed(1)} m (measured on the ground)`
        : 'GPS altitude uncorrected (connect while the drone is on the ground to calibrate)';
  }
  function status(j) {
    const every = j.gps_every || 0, fresh = j.gps_age != null && j.gps_age < Math.max(1.5, 1.5 * every);
    const late = st.last && !st.lost && j.gps_age != null && j.gps_age > Math.max(4, 2.5 * every);
    const s = j.status === 'live' ? (late ? 'GPS late' : fresh ? 'receiving' : j.frame_age != null && j.frame_age < 2.5 ? (st.last ? 'estimating' : 'link, waiting for GPS') : 'no data')
      : j.status;
    const gps = every ? ` · GPS every ${every.toFixed(1)} s` : '';
    const age = st.last && j.gps_age != null ? ` · last ${j.gps_age.toFixed(1)} s ago` : '';
    $('liveStatus').innerHTML = `<b${late ? ' style="color:var(--warn)"' : ''}>${s}</b>${gps}${age} · ${j.gps_count} points${j.bad ? ` · ${j.bad} bad frames` : ''}`;
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
      D.link(L.lq); linkTxt(`LQ ${Math.round(L.lq)} %${st.last ? '' : ' · no GPS'}`);
    } else if (j.status === 'live' && serial && waited && !j.frames) linkTxt('no data from the radio');
  }

  // ------------------------------------------------------------ lost: last known position + likely impact zone
  function markLost(j) {
    st.lost = true;
    D.off(true); linkTxt('signal lost');
    const c = st.last, p = S.meta.pilot;
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
    $('liveGeoAdmin').href = `https://map.geo.admin.ch/?swisssearch=${lat},${lon}&zoom=10`;
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
    tick(now) { W.tick(now); },
    setExag() { if (st.last) { toWorld(st.last.x, st.last.y, st.last.z, drone.position); } },
    /** for the automated checks: where the drone is drawn and whether that is an estimate */
    debug: () => ({ x: drone.position.x, z: drone.position.z, opacity: body.material.opacity, lost: st.lost }),
  };
}
