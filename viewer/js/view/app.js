// Alpline 3D viewer: the scene (terrain, pilot, flight path, signal shadows), loading a location and a flight, playback.
// The parts with their own topic are in the files imported below (path colours: colouring.js, flight maths: trackmath.js).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { initVideo } from './video.js';
import { initCameraModes } from './camera.js';
import { initSim } from '../sim/sim.js';
import { loadVolumes } from './volume.js';
import { initTabs } from '../core/tabs.js';
import { LITE, PHONE, LIGHT } from '../core/env.js';
import { createHud } from './hud.js';
import { createLinks } from './links.js';
import { initRename } from './rename.js';
import { mountDrone } from '../core/drone.js';
import { makeMovable } from '../core/dock.js';
import { initDetail } from './detail.js';
import { loadBuildings } from './buildings.js';
import { initProfile } from './profile.js';
import { initLive } from '../drone/live.js';
import { initBlackbox } from '../drone/blackbox.js';
import { readTerrain, TERRAIN_ENC } from './terrain_codec.js';
import { createDroneMarker } from './marker.js';
import { createPilotMarker, createRangeRings } from './pilotmark.js';
import { esc } from '../core/esc.js';
import { gridName, isSwiss } from '../core/geo.js';
import { initBattery } from '../battery/battery.js';
import { loadZones, restrictionInfo, isActive, fmtLimits } from './geozones.js';
import { terrainVS, terrainFS } from './terrain_shaders.js';
import * as COL from './colouring.js';
import { fmtTime, fmtDist, lerp, computeKinematics, trackStats } from './trackmath.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const SCENES = '../scenes/';
const MAX_LINKS = 4;
const TERRAIN_FS = terrainFS(MAX_LINKS);

// ------------------------------------------------------------------ Full / Lite mode
// decided once in theme.js (see env.js). A phone always gets the light settings, even in Full mode: a 0.5 m
// location in full quality needs more graphics memory than a phone has, and the tab just reloads or stays blank.

// ------------------------------------------------------------------ renderer / camera
const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, PHONE ? 1.5 : LITE ? 1.25 : 2));   // Lite: fewer pixels on high-DPI screens
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
$('view').appendChild(renderer.domElement);

const scene3 = new THREE.Scene();
scene3.background = new THREE.Color(0x9fb8cf);
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 1, 200000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.495;
scene3.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.2));
// the 3D view can be full screen or a small inset (when the video is swapped to full screen)
function fitRenderer() {
  const el = $('view'), w = el.clientWidth || innerWidth, h = el.clientHeight || innerHeight;
  camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h);
  requestRender();
}

// ------------------------------------------------------------------ render on demand
// The scene is only drawn when something changes (camera, playback, simulator, live data, UI), instead of 60 times
// per second: same picture, far less GPU work (cooler laptop, longer battery at the field). ?render=always draws
// continuously (for comparison or a screen recorder that needs steady frames).
const RENDER_PARAM = new URLSearchParams(location.search).get('render');
const RENDER_ALWAYS = RENDER_PARAM === 'always';
let renderUntil = 0;
function requestRender(ms = 250) { renderUntil = Math.max(renderUntil, performance.now() + ms); }
for (const ev of ['input', 'change', 'click', 'keydown', 'keyup', 'wheel', 'pointerup']) addEventListener(ev, () => requestRender(400), true);
{   // anything loaded from the server (scene data, terrain close-up, live telemetry) may change the picture
  const f = window.fetch.bind(window);
  window.fetch = (...a) => f(...a).finally(() => requestRender(800));
}
new ResizeObserver(fitRenderer).observe($('view'));
addEventListener('resize', fitRenderer);

// ------------------------------------------------------------------ state
const S = {
  meta: null, base: '', W: 0, H: 0, hBase: 0, exag: 1,
  dem: null, terrain: null, terrainMat: null, spheres: [], pilot: null,
  losTex: {}, track: null, trackObj: null, curtain: null, drone: null, beam: null,
  time: 0, playing: false, idx: 0, following: false,
};

// world transform: local x (east), y (north), z (AMSL) -> three.js (X east, Y up, Z south)
const toWorld = (x, y, z, out = new THREE.Vector3()) =>
  out.set(x - S.W / 2, (z - S.hBase) * S.exag, -(y - S.H / 2));
const toReal = (x, y, z, out = new THREE.Vector3()) =>  // same but without exaggeration
  out.set(x - S.W / 2, z - S.hBase, -(y - S.H / 2));

// ------------------------------------------------------------------ helpers
async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}
const loadTex = (url) => new Promise((ok, err) => new THREE.TextureLoader().load(url, (t) => {
  requestRender();
  t.anisotropy = renderer.capabilities.getMaxAnisotropy(); ok(t);
}, undefined, err));


function demHeight(x, y) {  // bilinear on the loaded (overview) DEM, local coords
  const v = S.view, d = S.dem;
  let c = (x / v.grid.res - 0.5) / v.step, r = ((S.H - y) / v.grid.res - 0.5) / v.step;
  c = Math.min(Math.max(c, 0), v.cols - 1.0001); r = Math.min(Math.max(r, 0), v.rows - 1.0001);
  const c0 = c | 0, r0 = r | 0, fc = c - c0, fr = r - r0, i = r0 * v.cols + c0;
  const top = lerp(d[i], d[i + 1], fc), bot = lerp(d[i + v.cols], d[i + v.cols + 1], fc);
  return lerp(top, bot, fr);
}

// Overview terrain: from the local server, already decimated (a 0.5 m scene can be > 1 GB);
// without the server (static hosting) the whole file is downloaded and decimated here.
const API = '/api';
async function loadOverview(which) {
  const fileMeta = which === 'dtm' && S.meta.terrain_dtm ? S.meta.terrain_dtm : { file: S.meta.terrain, grid: S.meta.grid };
  const g = fileMeta.grid, maxSide = +(params.get('maxgrid') || (PHONE ? 600 : LITE ? 800 : 1500));   // overview mesh: phone 600, Lite 800, Full 1500
  const step = Math.max(1, Math.ceil(Math.max(g.cols, g.rows) / maxSide));
  let dem = null, cols, rows, api = null;
  try {
    const r = await fetch(`${API}/terrain?scene=${encodeURIComponent(S.meta.name)}&which=${which}&step=${step}&enc=${TERRAIN_ENC}`);
    if (r.ok && r.headers.get('X-Cols')) {
      cols = +r.headers.get('X-Cols'); rows = +r.headers.get('X-Rows'); dem = await readTerrain(r, cols); api = API;
    }
  } catch { /* static hosting */ }
  if (!dem) {
    const full = new Float32Array(await (await fetch(S.base + fileMeta.file)).arrayBuffer());
    cols = Math.floor((g.cols - 1) / step) + 1; rows = Math.floor((g.rows - 1) / step) + 1;
    dem = new Float32Array(cols * rows);
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) dem[r * cols + c] = full[r * step * g.cols + c * step];
  }
  S.dem = dem;
  S.view = { grid: g, step, cols, rows, res: g.res * step, which, api };
}

// ------------------------------------------------------------------ terrain

function buildTerrain() {
  const { grid: g, step, cols, rows } = S.view;
  const pos = new Float32Array(cols * rows * 3), uv = new Float32Array(cols * rows * 2), aH = new Float32Array(cols * rows);
  let k = 0;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++, k++) {
    const gr = r * step, gc = c * step;
    const x = (gc + 0.5) * g.res, y = S.H - (gr + 0.5) * g.res, h = S.dem[r * cols + c];
    pos[k * 3] = x - S.W / 2; pos[k * 3 + 1] = (h - S.hBase) * S.exag; pos[k * 3 + 2] = -(y - S.H / 2);
    uv[k * 2] = x / S.W; uv[k * 2 + 1] = y / S.H; aH[k] = h - S.hBase;
  }
  const idx = new Uint32Array((cols - 1) * (rows - 1) * 6);
  k = 0;
  for (let r = 0; r < rows - 1; r++) for (let c = 0; c < cols - 1; c++) {
    const a = r * cols + c, b = a + 1, d = a + cols, e = d + 1;
    idx[k++] = a; idx[k++] = d; idx[k++] = b; idx[k++] = b; idx[k++] = d; idx[k++] = e;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setAttribute('aH', new THREE.BufferAttribute(aH, 1));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  const blank = new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1); blank.needsUpdate = true;
  S.terrainMat = new THREE.ShaderMaterial({
    vertexShader: terrainVS, fragmentShader: TERRAIN_FS,
    uniforms: {
      uOrtho: { value: blank }, uLos: { value: blank }, uUseOrtho: { value: 0 }, uLosOn: { value: 1 },
      uLosOpacity: { value: 0.85 }, uZones: { value: blank }, uZonesOn: { value: 0 }, uHMin: { value: 0 }, uHMax: { value: S.meta.elevation.max - S.hBase },
      uPilot: { value: new THREE.Vector3() }, uRanges: { value: new THREE.Vector4() },
      uColors: { value: Array.from({ length: MAX_LINKS }, () => new THREE.Color()) },
      uRangeOn: { value: new THREE.Vector4() }, uSize: { value: new THREE.Vector2(S.W, S.H) },
      uOrthoRect: { value: new THREE.Vector4(0, 0, 1, 1) }, uHole: { value: new THREE.Vector4(1, 1, -1, -1) },
      uCor: { value: corridorUniform() }, uCorN: { value: Math.min(64, S.meta.corridor?.points.length || 0) },
      uCorW: { value: S.meta.corridor?.width_m || 0 },
    },
  });
  S.terrain = new THREE.Mesh(geo, S.terrainMat);
  scene3.add(S.terrain);
}

function corridorUniform() {
  const out = Array.from({ length: 64 }, () => new THREE.Vector2());
  (S.meta.corridor?.points || []).slice(0, 64).forEach(([x, y], i) => out[i].set(x - S.W / 2, -(y - S.H / 2)));
  return out;
}

function setExaggeration(e) {
  S.exag = e;
  if (S.terrain) {
    const pos = S.terrain.geometry.attributes.position, aH = S.terrain.geometry.attributes.aH;
    for (let i = 0; i < pos.count; i++) pos.setY(i, aH.getX(i) * e);
    pos.needsUpdate = true; S.terrain.geometry.computeVertexNormals();
  }
  S.detail?.rebuild();
  S.bld?.set({ exag: e });
  S.prof?.setExag();
  S.spheres.forEach((s) => { const k = s.userData.k || 1; s.scale.set(k, k * e, k); });
  placePilot();
  S.live?.setExag?.();
  if (S.track) buildTrackObjects();
  if (S.cmp) buildCompareObjects();
  S.vol?.set({ exag: e });
  S.zones?.rebuild();
  $('exagOut').textContent = `${e.toFixed(1)}×`;
}

// ------------------------------------------------------------------ pilot + spheres
function buildPilot() {
  // the pilot: ground station close / radio badge far (pilotmark.js), distance rings on the terrain around it
  S.pilotMarker = createPilotMarker({ THREE, scene3, camera, viewEl: $('view') });
  S.pilot = S.pilotMarker.group;
  S.rings = createRangeRings({ THREE, scene3, camera, viewEl: $('view'), toWorld, groundWorldY: (x, y) => (demHeight(x, y) - S.hBase) * S.exag });
  let ringsOn = true; try { ringsOn = localStorage.getItem('fpv3d:rings') !== '0'; } catch { /* private mode */ }
  $('ringsOn').checked = ringsOn; S.rings.setVisible(ringsOn);
  $('ringsOn').onchange = () => {
    S.rings.setVisible($('ringsOn').checked);
    try { localStorage.setItem('fpv3d:rings', $('ringsOn').checked ? '1' : '0'); } catch { /* private mode */ }
    S.requestRender?.(200);
  };

  S.meta.links.forEach((l, i) => {
    const color = new THREE.Color(l.color);
    const grpS = new THREE.Group();
    const fill = new THREE.Mesh(new THREE.SphereGeometry(l.range_m, 64, 32),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.06, depthWrite: false, side: THREE.FrontSide }));
    const wire = new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.SphereGeometry(l.range_m, 24, 12)),
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.18, depthWrite: false }));
    grpS.add(fill, wire); grpS.userData = { fill, wire, link: l };
    grpS.visible = i === S.meta.primary_link;
    scene3.add(grpS); S.spheres.push(grpS);
    if (i < MAX_LINKS) {
      S.terrainMat.uniforms.uColors.value[i].set(l.color);
      S.terrainMat.uniforms.uRanges.value.setComponent(i, l.range_m);
    }
  });
  placePilot();
  updateRangeUniforms();
}

function placePilot() {
  if (!S.pilot) return;
  const p = S.meta.pilot;
  const top = toWorld(p.x, p.y, p.z), bottom = toWorld(p.x, p.y, p.ground);
  S.pilotMarker.place(bottom, Math.max(0.3, p.z - p.ground), S.exag);
  S.rings.setCenter(p.x, p.y);
  S.spheres.forEach((s) => s.position.copy(top));
  S.terrainMat.uniforms.uPilot.value.copy(toReal(p.x, p.y, p.z));
}

function updateRangeUniforms() {
  const v = S.terrainMat.uniforms.uRangeOn.value;
  S.spheres.forEach((s, i) => i < MAX_LINKS && v.setComponent(i, s.visible ? 1 : 0));
}

// ------------------------------------------------------------------ track
// colouring of the path: colouring.js (these three keep the short names used below)
const statusOf = (i) => COL.statusOf(S, i);
const colorModes = () => COL.colorModes(S);
const trackColors = () => COL.trackColors(S, $('colorMode').value, $('colorLegend'));

// ------------------------------------------------------------------ kinematics (1st / 2nd derivative)
const C_VEL = 0x22d3ee, C_ACC = 0xc084fc;


const velScale = () => 2 * +$('vecScale').value;   // arrow = where the drone is in 2 s
const accScale = () => 4 * +$('vecScale').value;   // 4 m of arrow per m/s²

// solid arrow (shaft + head) so it stays readable at any zoom; drawn on top of everything
const _Y = new THREE.Vector3(0, 1, 0);
function makeArrow(color) {
  const mat = new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true });
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 10).translate(0, 0.5, 0), mat);
  const head = new THREE.Mesh(new THREE.ConeGeometry(1, 1, 14).translate(0, 0.5, 0), mat);
  const a = new THREE.Group(); a.add(shaft, head); a.userData = { shaft, head };
  shaft.renderOrder = head.renderOrder = 10; a.visible = false; scene3.add(a); return a;
}

const _a = new THREE.Vector3(), _b = new THREE.Vector3(), _d = new THREE.Vector3();
function placeArrow(arrow, i, kx, ky, kz, scale, on) {
  const tr = S.track;
  if (!on || !tr.vx) { arrow.visible = false; return; }
  const x = tr.x[i], y = tr.y[i], z = tr.z[i];
  toWorld(x + tr[kx][i] * scale, y + tr[ky][i] * scale, z + tr[kz][i] * scale, _b);
  toWorld(x, y, z, _d); _b.sub(_d);             // vector in world units (incl. vertical exaggeration)
  const len = _b.length();
  if (len < 0.3) { arrow.visible = false; return; }
  const r = Math.max(0.15, camera.position.distanceTo(S.drone.position) / 320);   // ~constant on-screen thickness
  const headLen = Math.min(len * 0.4, 7 * r);
  const { shaft, head } = arrow.userData;
  shaft.scale.set(r, Math.max(len - headLen, 0.001), r);
  head.scale.set(2.6 * r, headLen, 2.6 * r);
  head.position.set(0, len - headLen, 0);
  arrow.visible = true;
  arrow.position.copy(S.drone.position);
  arrow.quaternion.setFromUnitVectors(_Y, _b.divideScalar(len));
}

function updateArrows() {
  if (!S.track || !S.velArrow) return;
  placeArrow(S.velArrow, S.idx, 'vx', 'vy', 'vz', velScale(), $('velOn').checked);
  placeArrow(S.accArrow, S.idx, 'ax', 'ay', 'az', accScale(), $('accOn').checked);
}

// short vector "combs" along the whole flight, one every `everyS` seconds
function buildCombs() {
  for (const o of [S.velComb, S.accComb]) if (o) { scene3.remove(o); o.geometry.dispose(); }
  S.velComb = S.accComb = null;
  const tr = S.track;
  if (!tr?.vx || !$('combOn').checked) return;
  const everyS = Math.max(0.5, tr.t[tr.n - 1] / 400);
  const make = (kx, ky, kz, scale, color) => {
    const pts = []; let next = tr.t[0];
    for (let i = 0; i < tr.n; i++) {
      if (tr.t[i] < next) continue; next = tr.t[i] + everyS;
      toWorld(tr.x[i], tr.y[i], tr.z[i], _a);
      toWorld(tr.x[i] + tr[kx][i] * scale, tr.y[i] + tr[ky][i] * scale, tr.z[i] + tr[kz][i] * scale, _b);
      pts.push(_a.x, _a.y, _a.z, _b.x, _b.y, _b.z);
    }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    const o = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.75 }));
    scene3.add(o); return o;
  };
  if ($('velOn').checked) S.velComb = make('vx', 'vy', 'vz', velScale(), C_VEL);
  if ($('accOn').checked) S.accComb = make('ax', 'ay', 'az', accScale(), C_ACC);
}


function buildTrackObjects() {
  for (const o of [S.trackObj, S.curtain]) if (o) { scene3.remove(o); o.geometry.dispose(); }
  const tr = S.track, n = tr.n;
  const pos = new Float32Array(n * 3), v = new THREE.Vector3();
  for (let i = 0; i < n; i++) toWorld(tr.x[i], tr.y[i], tr.z[i], v).toArray(pos, i * 3);
  const cols = trackColors();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.BufferAttribute(cols, 3));
  S.trackObj = new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true }));
  scene3.add(S.trackObj);

  // translucent "curtain" from the track down to the ground helps judge height
  const cp = new Float32Array(n * 6), cc = new Float32Array(n * 6), idx = [];
  for (let i = 0; i < n; i++) {
    toWorld(tr.x[i], tr.y[i], tr.z[i], v).toArray(cp, i * 6);
    toWorld(tr.x[i], tr.y[i], tr.z[i] - tr.agl[i], v).toArray(cp, i * 6 + 3);
    cc.set(cols.subarray(i * 3, i * 3 + 3), i * 6); cc.set(cols.subarray(i * 3, i * 3 + 3), i * 6 + 3);
    if (i < n - 1) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 2, a + 1, a + 3); }
  }
  const cg = new THREE.BufferGeometry();
  cg.setAttribute('position', new THREE.BufferAttribute(cp, 3));
  cg.setAttribute('color', new THREE.BufferAttribute(cc, 3));
  cg.setIndex(idx);
  S.curtain = new THREE.Mesh(cg, new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false }));
  S.curtain.visible = $('curtainOn').checked;
  scene3.add(S.curtain);
  buildCombs();
  updateDrone();
}

function buildDrone() {
  S.droneMarker = createDroneMarker({ THREE, scene3, camera, viewEl: $('view') });   // marker.js: quad close, badge far
  S.drone = S.droneMarker.group;
  S.velArrow = makeArrow(C_VEL); S.accArrow = makeArrow(C_ACC);
  const bg = new THREE.BufferGeometry(); bg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
  S.beam = new THREE.Line(bg, new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 12, gapSize: 8 }));
  scene3.add(S.beam);
}

function findIndex(t) {
  const a = S.track.t; let lo = 0, hi = a.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (a[mid] <= t) lo = mid; else hi = mid - 1; }
  return lo;
}

// the replay drone's marker: heading / bank from the track's speed and acceleration, the drop line to the ground,
// and a tail of the last 5 s of the flight
const _mv = new THREE.Vector3(), _ma = new THREE.Vector3(), _mg = new THREE.Vector3(), _tailPts = Array.from({ length: 64 }, () => new THREE.Vector3());
function trackMarkerArgs(tr, i, out = {}) {
  const has = !!tr.vx;
  out.vel = has ? _mv.set(tr.vx[i], tr.vz[i] * S.exag, -tr.vy[i]) : null;
  out.acc = has ? _ma.set(tr.ax[i], tr.az[i] * S.exag, -tr.ay[i]) : null;
  out.groundY = toWorld(tr.x[i], tr.y[i], demHeight(tr.x[i], tr.y[i]), _mg).y;
  out.agl = tr.agl ? tr.agl[i] : null;
  return out;
}
function replayMarker(now) {
  const tr = S.track, i = S.idx ?? 0, st = statusOf(i);
  const a = trackMarkerArgs(tr, i);
  let n = 0;                                               // the last 5 s, at most 64 points
  const t0 = tr.t[i] - 5;
  let k = i; while (k > 0 && tr.t[k - 1] >= t0) k--;
  const step = Math.max(1, Math.ceil((i - k + 1) / 63));
  for (let j = k; j <= i && n < 63; j += step) toWorld(tr.x[j], tr.y[j], tr.z[j], _tailPts[n++]);
  _tailPts[n++].copy(S.drone.position);
  S.droneMarker.update({ ...a, color: st.c, css: st.css, tail: _tailPts.slice(0, n), now });
}

const _v = new THREE.Vector3(), _prev = new THREE.Vector3();
function updateDrone() {
  const tr = S.track; if (!tr || !S.drone) return;
  const i = findIndex(S.time), j = Math.min(i + 1, tr.n - 1);
  const f = j > i ? (S.time - tr.t[i]) / Math.max(tr.t[j] - tr.t[i], 1e-6) : 0;
  S.idx = f > 0.5 ? j : i;
  S.prof?.tick();
  _prev.copy(S.drone.position);
  toWorld(lerp(tr.x[i], tr.x[j], f), lerp(tr.y[i], tr.y[j], f), lerp(tr.z[i], tr.z[j], f), S.drone.position);
  const st = statusOf(S.idx);
  const p = S.meta.pilot, b = S.beam.geometry.attributes.position;
  toWorld(p.x, p.y, p.z, _v); b.setXYZ(0, _v.x, _v.y, _v.z);
  b.setXYZ(1, S.drone.position.x, S.drone.position.y, S.drone.position.z); b.needsUpdate = true;
  S.beam.computeLineDistances(); S.beam.material.color.copy(st.c);
  if (S.following) {
    _v.subVectors(S.drone.position, _prev);
    if (_v.lengthSq() < 1e6) { camera.position.add(_v); controls.target.add(_v); }
    else controls.target.copy(S.drone.position);
  }
  updateArrows();
  if ($('losFollow').checked) pickLosLayer(tr.agl[S.idx]);
  $('scrub').value = Math.round((S.time / tr.t[tr.n - 1]) * 1000);
  $('clock').textContent = `${fmtTime(S.time)} / ${fmtTime(tr.t[tr.n - 1])}`;
  HUD.render(st);
  S.bat?.tick();
  placeGhost();
}

const HUD = createHud({ S, $, fmtDist });   // info box: hud.js

// ------------------------------------------------------------------ LOS layers
async function pickLosLayer(agl) {
  if (S.vol?.overlay) {                    // 2D shadow computed live from the 3D ceilings (any height, follows radio edits)
    const h = agl != null ? agl : +$('losAgl').value;
    if (S.lastAgl != null && Math.abs(h - S.lastAgl) < 2) return;
    S.lastAgl = h;
    if (agl != null) {                     // show the nearest listed height in the dropdown
      const opts = [...$('losAgl').options].map((o) => +o.value);
      $('losAgl').value = String(opts.reduce((a, b) => (Math.abs(b - h) < Math.abs(a - h) ? b : a), opts[0]));
    }
    S.terrainMat.uniforms.uLos.value = S.vol.overlay(h);
    S.prof?.redraw();
    updateSignalSummary(h);
    return;
  }
  const layers = S.meta.los_layers; if (!layers.length) return;
  let best = layers.find((l) => String(l.agl) === $('losAgl').value) || layers[0];
  if (agl != null) {
    best = layers[0];
    for (const l of layers) if (Math.abs(l.agl - agl) < Math.abs(best.agl - agl)) best = l;
  }
  if (agl != null) $('losAgl').value = String(best.agl);
  if (!S.losTex[best.file]) S.losTex[best.file] = loadTex(S.base + best.file).then((t) => {
    t.magFilter = THREE.NearestFilter; return t;
  });
  S.terrainMat.uniforms.uLos.value = await S.losTex[best.file];
  updateSignalSummary(best.agl, best);
}

// one-sentence answers at the top of the tabs
function updateSignalSummary(agl, layer) {
  const m = S.meta, i = m.primary_link, l = m.links[i];
  const range = l.range_m;                // already follows the radio setup
  const rangeTxt = range >= 1000 ? `${(range / 1000).toFixed(1)} km` : `${Math.round(range)} m`;
  let txt = `${l.name.split(' ')[0]} reaches about <b>${rangeTxt}</b> (open sky).`;
  if (S.vol?.ceilAt) {                     // share of the area within range where the drone stays in sight / keeps signal
    const cor = m.corridor, p = m.pilot, N = 90;
    let n = 0, vis = 0, ok = 0;
    for (let a = 0; a < N; a++) for (let b = 0; b < N; b++) {
      const x = ((a + 0.5) / N) * S.W, y = ((b + 0.5) / N) * S.H;
      if (Math.hypot(x - p.x, y - p.y) > range) continue;
      if (cor && corDistLocal(cor.points, x, y) > cor.width_m) continue;
      const c = S.vol.ceilAt('los', x, y), c2 = S.vol.ceilAt('loss', x, y);
      if (c == null) continue;
      n++; if (c <= agl) vis++; if (c <= agl && (c2 == null || c2 <= agl)) ok++;
    }
    if (n) txt += ` Flying at ${agl} m, the drone stays <b>in sight over ${Math.round((100 * vis) / n)}%</b> of that ${cor ? 'route' : 'area'}`
      + `, with a usable signal over ${Math.round((100 * ok) / n)}%.`;
  } else if (layer) {
    txt += ` Flying at ${agl} m, the drone is hidden by terrain over ${Math.round(layer.blocked * 100)}% of the map.`;
  }
  $('sumSignal').innerHTML = txt;
}
function corDistLocal(pts, x, y) {
  let d = Infinity;
  for (let k = 0; k < pts.length - 1; k++) {
    const [ax, ay] = pts[k], [bx, by] = pts[k + 1], dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1e-9;
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / L2));
    d = Math.min(d, Math.hypot(x - (ax + t * dx), y - (ay + t * dy)));
  }
  return d;
}
// how old the zone copy is: zones change (new areas, events, temporary restrictions), so it is shown and refreshable
function showZoneAge() {
  const f = S.meta.geozones?.fetched;
  if (!f) { $('zonesAge').textContent = 'zone data: none yet'; return; }
  const days = Math.floor((Date.now() - Date.parse(f.replace(' ', 'T'))) / 864e5);
  $('zonesAge').innerHTML = `zone data from ${f.slice(0, 10)} · ${days <= 0 ? 'today' : days === 1 ? '1 day old' : `${days} days old`}`
    + (days > 7 ? ' · <b class="warn">refresh before flying</b>' : '');
}
async function refreshZones() {
  const b = $('zonesRefresh'); b.disabled = true; $('zonesAge').textContent = 'downloading the current zones…';
  window.alpBusy?.(true);
  try {
    const r = await fetch('/api/zones', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scene: S.meta.name }) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status);
    for (;;) {
      await new Promise((ok) => setTimeout(ok, 1000));
      const k = await (await fetch(`/api/jobs/${j.job}`)).json();
      if (k.status === 'running') continue;
      if (k.status !== 'done') throw new Error((k.lines || []).at(-1) || k.status);
      break;
    }
    location.reload();                            // simplest way to redraw the zones everywhere
  } catch (e) { $('zonesAge').textContent = `could not refresh: ${e.message}`; b.disabled = false; window.alpBusy?.(false); }
}

function updateZoneSummary() {
  showZoneAge();
  const z = S.zones;
  if (!z) { $('sumZones').textContent = ''; return; }
  const act = z.zones.filter((zn) => isActive(zn));
  const by = (sev) => act.filter((zn) => zn.info.sev === sev).length;
  const parts = [[by(3), 'forbidden', 'forbidden'], [by(2), 'needs permission', 'need permission'], [by(1), 'has conditions', 'have conditions']]
    .filter(([n]) => n).map(([n, one, many]) => `${n} ${n > 1 ? many : one}`);
  $('sumZones').innerHTML = act.length ? `<b>${act.length} no-fly zone${act.length > 1 ? 's' : ''}</b> on this map today: ${parts.join(', ')}. Click one in the list for its rules.`
    : 'No no-fly zone on this map today.';
}

// ------------------------------------------------------------------ 2D shadow on terrain vs 3D volumes
function applyShadowMode() {
  const want3d = $('vol3d').checked && !!S.vol;
  $('volOpts').classList.toggle('hidden', !want3d);
  $('volMissing').classList.toggle('hidden', !($('vol3d').checked && !S.vol));
  const on2d = $('losOn').checked && (!want3d || $('vol2dToo').checked);
  S.terrainMat.uniforms.uLosOn.value = on2d ? 1 : 0;
  if (S.vol) {
    const show = {}; document.querySelectorAll('.volLayer').forEach((cb) => { show[cb.dataset.l] = cb.checked; });
    S.vol.set({ visible: want3d, show, cap: +$('volCap').value, opacity: +$('volOpacity').value, exag: S.exag });
  }
}

// ------------------------------------------------------------------ click-to-inspect
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
function setRay(ev) {
  const rc = renderer.domElement.getBoundingClientRect();
  ndc.set(((ev.clientX - rc.left) / rc.width) * 2 - 1, -((ev.clientY - rc.top) / rc.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
}
function terrainHit(ev) {
  const rc = renderer.domElement.getBoundingClientRect();
  ndc.set(((ev.clientX - rc.left) / rc.width) * 2 - 1, -((ev.clientY - rc.top) / rc.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const o = ray.ray.origin, d = ray.ray.direction, p = new THREE.Vector3();
  for (let s = 0; s < 80000; s += Math.max(2, s * 0.004)) {   // march along the ray
    p.copy(o).addScaledVector(d, s);
    const x = p.x + S.W / 2, y = -p.z + S.H / 2;
    if (x < 0 || y < 0 || x > S.W || y > S.H) continue;
    const h = demHeight(x, y);
    if (p.y <= (h - S.hBase) * S.exag) return { x, y, h };
  }
  return null;
}
let downAt = null;
renderer.domElement.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', (e) => {
  const pk = $('pick');
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4) return;
  setRay(e);
  const bh = S.bld?.pick(ray.ray);
  if (bh) {
    const b = bh.item, p = S.meta.pilot;
    const cx = b.p.reduce((s, q) => s + q[0], 0) / b.p.length, cy = b.p.reduce((s, q) => s + q[1], 0) / b.p.length;
    pk.innerHTML = `<b>${esc(b.name || 'Building')}</b> · ${(b.t - b.b).toFixed(1)} m high<br>roof ${b.t.toFixed(0)} m · ${fmtDist(Math.hypot(cx - p.x, cy - p.y, b.t - p.z))} from pilot`
      + `<br><span class="muted">${b.k !== 'yes' ? `${esc(b.k)} · ` : ''}height ${b.src === 'dsm' ? 'measured (swissSURFACE3D)' : 'estimated (OSM tags)'}</span>`;
    pk.style.left = `${e.clientX + 14}px`; pk.style.top = `${e.clientY + 10}px`;
    pk.classList.remove('hidden');
    return;
  }
  const h = terrainHit(e);
  if (h && S.pickHook) { const f = S.pickHook; S.pickHook = null; f(h); return; }   // live flight: [pick on the map]
  if (!h) { pk.classList.add('hidden'); return; }
  const p = S.meta.pilot, g = S.meta.grid;
  const d = Math.hypot(h.x - p.x, h.y - p.y, h.h - p.z);
  const zh = S.zones ? S.zones.zonesAt(h.x, h.y) : [];
  pk.innerHTML = `<b>${h.h.toFixed(0)} m</b> · ${fmtDist(d)} from pilot<br><span class="muted">${gridName(g.crs)} ${(g.min_e + h.x).toFixed(0)} / ${(g.min_n + h.y).toFixed(0)}</span>` +
    zh.map(({ zone: z }) => `<br><b style="color:${z.info.color}">${z.info.label}</b> · ${esc(z.name)}<br><span class="muted">${fmtLimits(z)}</span>`).join('');
  pk.style.left = `${e.clientX + 14}px`; pk.style.top = `${e.clientY + 10}px`;
  pk.classList.remove('hidden');
});

// ------------------------------------------------------------------ ground model, buildings, close-up
function groundChoice() {
  const can = !!S.meta.terrain_dtm;
  let pref = params.get('ground');
  try { pref ||= localStorage.getItem(`fpv3d:ground:${S.meta.name}`); } catch { /* private mode */ }
  if (pref === 'bare' && can) return 'bare';
  if (pref === 'surface') return 'surface';
  return can && S.meta.buildings?.count ? 'bare' : 'surface';   // default: clean buildings when we have them
}
function initGroundUi() {
  const m = S.meta, v = S.view;
  const sel = $('groundMode');
  const opts = [];
  if (m.surface === 'dsm') opts.push(['surface', 'Surface model (trees + buildings as measured)']);
  if (m.terrain_dtm || m.surface === 'dtm') opts.push(['bare', m.buildings?.count ? 'Bare ground + 3D buildings' : 'Bare ground']);
  sel.innerHTML = opts.map(([k, l]) => `<option value="${k}" ${k === (m.surface === 'dtm' ? 'bare' : S.ground) ? 'selected' : ''}>${l}</option>`).join('');
  sel.disabled = opts.length < 2;
  sel.onchange = () => {
    try { localStorage.setItem(`fpv3d:ground:${m.name}`, sel.value); } catch { /* private mode */ }
    const u = new URL(location.href); u.searchParams.set('ground', sel.value); location.href = u.toString();
  };
  $('bldRow').classList.toggle('hidden', !S.bld);
  const bm = m.buildings;
  const why = S.bld ? '' : bm?.disabled ? '3D buildings are off for this location (set <code>buildings: true</code> under <code>terrain:</code> in its file, then refresh it).'
    : !bm ? 'No 3D buildings in this scene yet (built before buildings existed).'
    : bm.error ? `No 3D buildings: the OpenStreetMap download failed (${esc(bm.when || '')}): ${esc(bm.error)}`
      : bm.count === 0 ? 'No buildings in this area on OpenStreetMap.' : '';
  $('bldMissing').classList.toggle('hidden', !why);
  if (why) $('bldMissing').innerHTML = `${why}${bm && bm.count === 0 && !bm.error ? '' : '<br>Fix: <code>python -m fpv3d buildings</code> or Map → [saved] → Buildings.'}`;
  if (S.bld) {
    $('bldOn').checked = S.ground === 'bare' || m.surface === 'dtm';
    S.bld.set({ visible: $('bldOn').checked });
    $('bldOn').onchange = () => S.bld.set({ visible: $('bldOn').checked });
    $('bldCount').textContent = `${S.bld.count} · ${m.buildings.heights_from_dsm || 0} measured`;
  }
  $('detailRow').classList.toggle('hidden', !S.detail?.enabled);
  $('detailOn').onchange = () => S.detail.set($('detailOn').checked);
  const full = v.grid.res;
  $('meshInfo').textContent = S.detail?.enabled ? `Mesh: ${S.detail.info}${m.detail ? ` · sharp photo ${m.detail.res} m near the pilot` : ''}`
    : `Mesh: ${full} m everywhere${v.step > 1 ? '' : ''}`;
}

// ------------------------------------------------------------------ UI wiring
function initUI() {
  const m = S.meta;
  const pilotFrom = m.pilot.source === 'config' ? 'set in the location file' : m.pilot.source === 'map centre' ? 'map centre' : m.pilot.source.replace('first fix of', 'start of the log');
  // heights from the worldwide model: measured every 30 m only, and trees / roofs are partly in it
  const world = (m.terrain_sources || []).filter((s) => s.name === 'copernicus');
  const onlyWorld = world.length && m.terrain_sources.length === 1;
  const ground = onlyWorld ? 'from the worldwide 30 m model (coarse: trees and roofs partly included)'
    : m.surface === 'dsm' ? 'with trees and buildings' : 'bare ground';
  const credit = world.length ? `<br>${onlyWorld ? '' : 'Outside Switzerland: worldwide 30 m model. '}<span class="muted small">${esc(world[0].credit)}</span>` : '';
  $('sceneInfo').innerHTML = (m.corridor
    ? `Route ${(m.corridor.length_m / 1000).toFixed(1)} km, ${2 * m.corridor.width_m} m wide`
    : `${(S.W / 1000).toFixed(1)} × ${(S.H / 1000).toFixed(1)} km area`) + ` · terrain every ${m.grid.res} m, ${ground}<br>Pilot position: ${pilotFrom}` + credit;
  initGroundUi();
  $('orthoOn').disabled = !m.ortho;
  $('orthoOn').onchange = () => { S.terrainMat.uniforms.uUseOrtho.value = $('orthoOn').checked && m.ortho ? 1 : 0; };
  $('exag').oninput = () => setExaggeration(+$('exag').value);
  $('losLink').textContent = `(${m.links[m.primary_link].name})`;
  $('losAgl').innerHTML = m.los_layers.map((l) => `<option value="${l.agl}">${l.agl} m above the ground</option>`).join('');
  $('losAgl').onchange = () => { $('losFollow').checked = false; S.lastAgl = null; pickLosLayer(); };
  $('losOn').onchange = applyShadowMode;
  $('vol3d').onchange = applyShadowMode;
  $('vol2dToo').onchange = applyShadowMode;
  document.querySelectorAll('.volLayer').forEach((cb) => cb.onchange = applyShadowMode);
  $('volCap').oninput = () => { $('volCapOut').textContent = `${$('volCap').value} m`; applyShadowMode(); };
  $('volOpacity').oninput = applyShadowMode;
  $('losOpacity').oninput = () => { S.terrainMat.uniforms.uLosOpacity.value = +$('losOpacity').value; };
  $('linkList').innerHTML = m.links.map((l, i) => `<label class="link"><input type="checkbox" data-i="${i}" ${i === m.primary_link ? 'checked' : ''}>
      <span class="sw" style="background:${l.color}"></span>${esc(l.name)}<span class="r" id="lnkRange${i}">${fmtDist(l.range_m)}</span></label>`).join('');
  LINKS.init();
  $('linkList').querySelectorAll('input[data-i]').forEach((cb) => cb.onchange = () => {
    S.spheres[+cb.dataset.i].visible = cb.checked; updateRangeUniforms();
  });
  $('sphereOpacity').oninput = () => S.spheres.forEach((s) => {
    s.userData.fill.material.opacity = +$('sphereOpacity').value;
    s.userData.wire.material.opacity = Math.min(1, +$('sphereOpacity').value * 2.5);
  });
  fillTrackPickers();
  initRename({ S, $, refreshTracks });
  $('cmpPick').onchange = () => loadCompare($('cmpPick').value);
  $('trackPick').onchange = () => { rememberFlight($('trackPick').value); loadTrack($('trackPick').value); };
  $('colorMode').onchange = () => S.track && buildTrackObjects();
  const vecRefresh = () => { if (!S.track) return; buildCombs(); updateDrone(); };
  $('velOn').onchange = vecRefresh; $('accOn').onchange = vecRefresh; $('combOn').onchange = vecRefresh;
  $('vecScale').oninput = () => { $('vecScaleOut').textContent = `${(+$('vecScale').value).toFixed(2)}×`; vecRefresh(); };
  $('smooth').oninput = () => {
    $('smoothOut').textContent = `${(+$('smooth').value).toFixed(1)} s`;
    if (!S.track) return; computeKinematics(S.track, +$('smooth').value);
    const m = $('colorMode').value; if (m === 'speed' || m === 'accel') buildTrackObjects(); else vecRefresh();
  };
  $('curtainOn').onchange = () => S.curtain && (S.curtain.visible = $('curtainOn').checked);
  $('camMode').onchange = () => {
    const m = $('camMode').value;
    CAM.setMode(m);
    S.following = m === 'chase';
    if (m === 'chase' && S.drone) { controls.target.copy(S.drone.position); camera.position.copy(S.drone.position).add(new THREE.Vector3(-150, 90, 150)); }
    $('camMode').blur();   // so W/A/S/D go to the camera, not the dropdown
  };
  addEventListener('keydown', (e) => {
    if (e.code !== 'KeyC' || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    const sel = $('camMode'); sel.selectedIndex = (sel.selectedIndex + 1) % sel.options.length; sel.onchange();
  });
  makeMovable($('timeline'), $('tlGrip'), 'fpv3d:timelinePos');
  $('play').onclick = togglePlay;
  $('scrub').oninput = () => { if (!S.track) return; S.time = ($('scrub').value / 1000) * S.track.t[S.track.n - 1]; updateDrone(); V.seekToLog(S.time); };
  $('speed').onchange = () => V.setRate(+$('speed').value);
  S.bat = initBattery({ S, $, seek: (t) => { S.time = t; updateDrone(); V.seekToLog(t); S.requestRender?.(200); },
    onChange: () => { if (S.track) refreshColorModes(); } });
  $('panel').addEventListener('tabchange', (e) => S.bat?.tabChanged(e.detail));
  S.tabs = initTabs($('panel'), { storageKey: 'fpv3d:tab4', fallback: 'map' });
  S.bat.tabChanged(S.tabs.current);
  if (params.get('tab')) S.tabs.show(params.get('tab'), { keepOpen: true });   // e.g. ?tab=fly from the launcher
  $('panel').querySelector('h1').onclick = () => S.tabs.toggle();
  // keys 1..6 jump to a panel tab
  addEventListener('keydown', (e) => {
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey || document.body.classList.contains('sim-on')) return;
    const b = $('panel').querySelectorAll('.rail button[data-tab]')[+e.key - 1];
    if (b && /^[1-9]$/.test(e.key)) b.click();
  });
  setTimeout(() => S.tabs.refreshDim(), 0);
  addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target.tagName !== 'INPUT') { e.preventDefault(); togglePlay(); } });
}

function setPlayingUi(on) { S.playing = on; $('play').textContent = on ? '[pause]' : '[play]'; }
function togglePlay() {
  if (!S.track) return;
  if (S.playing) { V.pause(); setPlayingUi(false); return; }
  if (S.time >= S.track.t[S.track.n - 1]) { S.time = 0; V.seekToLog(0); }
  if (V.active()) V.play();          // the video becomes the master clock
  setPlayingUi(true);
}

const _dv = { pos: new THREE.Vector3(), dir: new THREE.Vector3(0, 0, -1) };
const CAM = initCameraModes({
  camera, controls, dom: renderer.domElement,
  sceneSpan: () => Math.max(S.W, S.H) || 2000,
  groundY: (wx, wz) => {
    const x = wx + S.W / 2, y = -wz + S.H / 2;
    if (!S.dem || x < 0 || y < 0 || x > S.W || y > S.H) return null;
    return (demHeight(x, y) - S.hBase) * S.exag;
  },
  droneView: () => {
    if (!S.drone || !S.track) return null;
    const tr = S.track, i = S.idx;
    _dv.pos.copy(S.drone.position); _dv.pos.y += 2 * S.exag;
    if (tr.vx && Math.hypot(tr.vx[i], tr.vy[i]) > 1) {   // keep the last heading when hovering
      toWorld(tr.x[i] + tr.vx[i], tr.y[i] + tr.vy[i], tr.z[i] + tr.vz[i], _a);
      toWorld(tr.x[i], tr.y[i], tr.z[i], _d);
      _dv.dir.subVectors(_a, _d).normalize();
    }
    return _dv;
  },
});

// what the training flight collides with: the terrain you see (sharp patch where it is loaded, else the overview;
// with trees when the map shows the surface model) and the 3D buildings (roofs; walls when flown into from the side)
function simGround(wx, wz, wy, prevY) {
  const lx = wx + S.W / 2, ly = -wz + S.H / 2;
  const h = (S.detail?.heightAt?.(lx, ly) ?? demHeight(lx, ly)) - S.hBase;
  const roof = S.bld?.group.visible ? S.bld.roofAt?.(lx, ly) : null;
  if (roof == null) return { h, wall: false };
  const top = roof - S.hBase;
  if (top <= h) return { h, wall: false };
  if (wy < top && prevY < top - 0.05) return { h, wall: true };     // came in from the side
  return { h: top, wall: false };                                   // on (or landing on) the roof
}

const SIM = initSim({
  THREE, scene3, camera, renderer, S, toWorld, demHeight, setExaggeration, simGround,
  detailSize: () => S.detail?.sizeM,
  markerUpdate: (o) => S.droneMarker?.update(o),
  ensureDrone: () => { if (!S.drone) buildDrone(); },
  zonesAt: (x, y, z) => (S.zones ? S.zones.zonesAt(x, y, z) : []),
  setClutterVisible: (on) => {   // markers that only get in the way of an FPV view
    for (const o of [S.curtain, S.pilot, S.beam, S.velComb, S.accComb, S.cmpGhost, S.velArrow, S.accArrow]) if (o) o.visible = on && (o !== S.curtain || $('curtainOn').checked) && (!!S.track || o === S.pilot || o === S.cmpGhost);
    S.rings?.setVisible(on && $('ringsOn').checked);
  },
  onStop: () => { if (S.track) updateDrone(); },
  onSaved: (file) => refreshTracks(file),
  onSimTick: (st) => S.live?.simTick(st),
  onSimStop: () => S.live?.simStop(),
});

const V = initVideo({
  getTime: () => S.time,
  duration: () => (S.track ? S.track.t[S.track.n - 1] : 0),
  keyPrefix: () => `${S.meta?.name}:${S.track?.name}`,
  onLayout: () => requestAnimationFrame(fitRenderer),
  setPlayingUi,
});

// ------------------------------------------------------------------ compare two flights (e.g. training vs real)

function renderCompare() {
  const el = $('cmpTable');
  if (!S.track || !S.cmp) { el.innerHTML = ''; return; }
  const a = trackStats(S.track, S.meta), b = trackStats(S.cmp, S.meta);
  el.innerHTML = `<table class="cmp"><tr><th></th><th>${esc(S.track.name)}</th><th style="color:#e6e6e6">${esc(S.cmp.name)}</th></tr>` +
    Object.keys(a).map((k) => `<tr><td>${k}</td><td>${a[k]}</td><td>${b[k]}</td></tr>`).join('') + '</table>' +
    '<p class="muted small">White dashed line + ghost = compared flight (ghost at the same elapsed time).</p>';
}

function buildCompareObjects() {
  if (S.cmpLine) { scene3.remove(S.cmpLine); S.cmpLine.geometry.dispose(); }
  S.cmpMarker?.dispose();
  S.cmpLine = S.cmpGhost = S.cmpMarker = null;
  const tr = S.cmp; if (!tr) return;
  const pos = new Float32Array(tr.n * 3), v = new THREE.Vector3();
  for (let i = 0; i < tr.n; i++) toWorld(tr.x[i], tr.y[i], tr.z[i], v).toArray(pos, i * 3);
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  S.cmpLine = new THREE.Line(g, new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 6, gapSize: 4, transparent: true, opacity: 0.85 }));
  S.cmpLine.computeLineDistances(); scene3.add(S.cmpLine);
  S.cmpMarker = createDroneMarker({ THREE, scene3, camera, viewEl: null, ghost: true });   // see-through, no label
  S.cmpGhost = S.cmpMarker.group;
  placeGhost();
}
function placeGhost() {
  const tr = S.cmp; if (!tr || !S.cmpGhost) return;
  const t = Math.min(S.time + tr.t[0], tr.t[tr.n - 1]);
  let lo = 0, hi = tr.n - 1; while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (tr.t[mid] <= t) lo = mid; else hi = mid - 1; }
  toWorld(tr.x[lo], tr.y[lo], tr.z[lo], S.cmpGhost.position);
  S.cmpMarker?.update({ ...trackMarkerArgs(tr, lo), color: 0xffffff, css: '#f2f5f8' });
}

async function loadCompare(file) {
  S.cmp = file ? await getJSON(S.base + file) : null;
  if (S.cmp) { LINKS.shiftTrackMargins(S.cmp); computeKinematics(S.cmp, +$('smooth').value); computeTrackZones(S.cmp); }
  buildCompareObjects(); renderCompare();
}

function fillTrackPickers(selectFile) {
  const tr = S.meta.tracks;
  const label = (t) => t.name;
  $('trackPick').innerHTML = tr.length ? '<option value="">(none)</option>' + tr.map((t) => `<option value="${esc(t.file)}">${esc(label(t))}</option>`).join('') : '<option value="">(no flight yet)</option>';
  if (!tr.length) {                         // empty: a hovering drone and how to get a first flight
    $('trackInfo').innerHTML = '<span class="droneEmpty"><span id="noFlightDrone"></span><span>No flight yet. Add a log (<code>python -m fpv3d add-log</code>), fly a training flight or record one live (both in <b>[fly]</b>).</span></span>';
    mountDrone($('noFlightDrone'), { size: 44 }).loop('hover');
  }
  $('trackPick').value = selectFile || (S.track ? S.trackFile || '' : '');
  const cur = $('cmpPick').value;
  $('cmpPick').innerHTML = '<option value="">(none)</option>' + tr.map((t) => `<option value="${esc(t.file)}">${esc(label(t))}</option>`).join('');
  if ([...$('cmpPick').options].some((o) => o.value === cur)) $('cmpPick').value = cur;
}

async function refreshTracks(selectFile) {
  S.meta = await getJSON(S.base + 'scene.json');
  if (S.links0) LINKS.apply();
  fillTrackPickers(selectFile);
  if (selectFile) { rememberFlight(selectFile); await loadTrack(selectFile); }
}

// radio link editor: links.js
const LINKS = createLinks({ S, $, fmtDist, maxLinks: MAX_LINKS,
  onShadows: () => { S.lastAgl = null; pickLosLayer(); },
  onTracks: () => { buildTrackObjects(); renderCompare(); } });

// ------------------------------------------------------------------ drone geozones
function computeTrackZones(tr) {
  if (!S.zones || !tr) return;
  tr.zoneSev = new Int8Array(tr.n).fill(-1); tr.zoneIdx = new Int32Array(tr.n).fill(-1);
  for (let i = 0; i < tr.n; i++) {
    const hit = S.zones.zonesAt(tr.x[i], tr.y[i], tr.z[i]).find((h) => h.inBand);
    if (hit) { tr.zoneSev[i] = hit.zone.info.sev; tr.zoneIdx[i] = hit.zone.idx; }
  }
}

function fillZoneUi() {
  const z = S.zones;
  $('zonesMissing').classList.toggle('hidden', !!z);
  const ts = S.meta.terrain_sources || [];
  if (!z && (!isSwiss(S.meta.grid.crs) || (ts.length && !ts.some((s) => s.name === 'swisstopo')))) $('zonesMissing').textContent = 'Drone zones are only known for Switzerland. Check the official drone map of the country you fly in.';
  $('zonesBody').classList.toggle('hidden', !z);
  if (!z) return;
  $('zonesSource').textContent = `FOCA geographical UAS zones, data from ${z.meta.fetched}.`;
  const list = z.zones.filter((zn) => z.state.showInactive || isActive(zn)).sort((a, b) => b.info.sev - a.info.sev);
  $('zoneList').innerHTML = list.length ? list.map((zn) => `<li data-i="${zn.idx}">
      <i style="background:${zn.info.color}"></i><span class="t">${esc(zn.name)}</span>
      <span class="muted">${zn.info.label}${isActive(zn) ? '' : ' · not active now'}</span></li>`).join('')
    : '<li class="muted">No zone in this map area (per FOCA data).</li>';
  $('zoneList').querySelectorAll('li[data-i]').forEach((li) => li.onclick = () => showZone(z.zones[+li.dataset.i]));
}

function showZone(zn) {
  const [cx, cy] = zn.centroid, [x0, y0, x1, y1] = zn.bbox, span = Math.max(x1 - x0, y1 - y0, 300);
  const c = toWorld(cx, cy, demHeight(Math.min(Math.max(cx, 0), S.W), Math.min(Math.max(cy, 0), S.H)));
  if (CAM.usesOrbit()) { controls.target.copy(c); camera.position.copy(c).add(new THREE.Vector3(-span * 0.6, span * 0.8, span * 0.9)); }
  const when = zn.permanent ? 'permanent' : `${zn.start ? zn.start.slice(0, 16).replace('T', ' ') : '…'} → ${zn.end ? zn.end.slice(0, 16).replace('T', ' ') : '…'}`;
  $('zoneDetail').innerHTML = `<b style="color:${zn.info.color}">${zn.info.label}</b> · ${esc(zn.name)}<br>
    <span class="muted">Height:</span> ${fmtLimits(zn)}<br><span class="muted">Valid:</span> ${when}${isActive(zn) ? '' : ' <b>(not active now)</b>'}<br>
    ${zn.conditions ? `<span class="muted">Rule:</span> ${zn.conditions}<br>` : ''}${zn.message ? `${zn.message}<br>` : ''}
    ${zn.authority ? `<span class="muted">Authority:</span> ${zn.authority}<br>` : ''}${zn.url ? `<a href="${zn.url}" target="_blank" rel="noopener">More information / permits</a>` : ''}`;
  $('zoneDetail').classList.remove('hidden');
}

function applyZones() {
  if (!S.zones) { S.terrainMat.uniforms.uZonesOn.value = 0; fillZoneUi(); showZoneAge(); return; }
  S.zones.set({ walls: $('zonesWalls').checked && $('zonesOn').checked, showInactive: $('zonesInactive').checked });
  S.terrainMat.uniforms.uZonesOn.value = $('zonesOn').checked ? 1 : 0;
  computeTrackZones(S.track); computeTrackZones(S.cmp);
  fillZoneUi();
  updateZoneSummary();
  if (S.track) { const sel = $('colorMode'), prev = sel.value; sel.innerHTML = colorModes().map((mm) => `<option value="${mm.id}">${mm.label}</option>`).join(''); sel.value = prev || 'status'; buildTrackObjects(); renderCompare(); }
}

// the flight picked per location is remembered ('' = none), so "no flight" stays chosen next time
const flightKey = () => `fpv3d:flight:${S.meta?.name}`;
function rememberFlight(file) { try { localStorage.setItem(flightKey(), file); } catch { /* private mode */ } }
function rememberedFlight() {
  const asked = params.get('track');                    // ?track=NAME (links from the packs page)
  if (asked) { const t = S.meta.tracks.find((x) => x.name === asked); if (t) return t.file; }
  let f = null; try { f = localStorage.getItem(flightKey()); } catch { /* private mode */ }
  if (f === '') return '';
  return S.meta.tracks.some((t) => t.file === f) ? f : S.meta.tracks[0]?.file || '';
}

/** no flight selected: hide the path, the drone, the flight info box and the playback bar */
function clearTrack() {
  if (S.playing) togglePlay();
  S.track = null; S.trackFile = null;
  if ($('trkRenBtn')) $('trkRenBtn').disabled = true;
  for (const o of [S.trackObj, S.curtain, S.velComb, S.accComb]) if (o) { scene3.remove(o); o.geometry.dispose(); }
  S.trackObj = S.curtain = S.velComb = S.accComb = null;
  for (const o of [S.velArrow, S.accArrow, S.beam]) if (o) o.visible = false;
  $('timeline').classList.add('hidden');
  $('hud').innerHTML = '';
  $('trackInfo').innerHTML = S.meta.tracks.length ? `No flight shown. Pick one above to replay it (${S.meta.tracks.length} saved).` : $('trackInfo').innerHTML;
  S.bat?.trackChanged(null);
  if (S.cmp) { buildCompareObjects(); renderCompare(); }
  S.prof?.redraw();
  S.requestRender?.(300);
}

async function loadTrack(file) {
  if (!file) { clearTrack(); return; }
  S.track = await getJSON(S.base + file);
  S.trackFile = file;
  if ($('trkRenBtn')) $('trkRenBtn').disabled = false;
  if (S.beam) S.beam.visible = true;
  LINKS.shiftTrackMargins(S.track);
  computeKinematics(S.track, +$('smooth').value);
  computeTrackZones(S.track);
  const tm = S.meta.tracks.find((t) => t.file === file);
  $('trackInfo').innerHTML = tm ? `<b>${fmtTime(tm.duration_s)}</b> of flight, up to <b>${fmtDist(tm.max_dist_m)}</b> away and <b>${tm.max_agl_m} m</b> above the ground. `
    + `Hidden by terrain ${tm.no_los_pct}% of the time.` : '';
  refreshColorModes(false);
  if (!S.drone) buildDrone();
  S.time = 0;
  buildTrackObjects();
  $('timeline').classList.remove('hidden');
  V.trackChanged();
  S.prof?.redraw();
  if (S.cmp) { buildCompareObjects(); renderCompare(); }
  S.bat?.trackChanged(tm);
}

function refreshColorModes(rebuild = true) {
  const sel = $('colorMode'), prev = sel.value;
  sel.innerHTML = colorModes().map((mm) => `<option value="${mm.id}">${mm.label}</option>`).join('');
  if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
  if (rebuild && S.track && sel.value !== prev) buildTrackObjects();
}

// ------------------------------------------------------------------ boot
async function loadScene(name) {
  S.base = `${SCENES}${name}/`;
  loadStep('Opening the location…');
  S.meta = await getJSON(S.base + 'scene.json');
  loadStep(`${S.meta.title || name} · terrain…`);
  const g = S.meta.grid;
  S.W = g.max_e - g.min_e; S.H = g.max_n - g.min_n; S.hBase = S.meta.elevation.min;
  S.ground = groundChoice();
  await loadOverview(S.ground === 'bare' ? 'dtm' : 'surface');
  buildTerrain();
  if (S.meta.ortho) {
    loadStep(`${S.meta.title || name} · aerial photo…`);
    const t = await loadTex(S.base + S.meta.ortho);
    S.terrainMat.uniforms.uOrtho.value = t; S.terrainMat.uniforms.uUseOrtho.value = 1;
  }
  try { S.bld = await loadBuildings({ S, scene3 }); } catch (e) { console.warn('buildings', e); S.bld = null; }
  S.detail = initDetail({ S, scene3, camera, controls, terrainVS, terrainFS: TERRAIN_FS, api: S.view.api, which: S.view.which });
  buildPilot();
  initUI();
  await pickLosLayer();
  loadStep(`${S.meta.title || name} · signal shadows…`);
  try { S.vol = await loadVolumes({ scene3, S, demHeight }); } catch (e) { console.warn('3D volumes', e); S.vol = null; }
  if (S.vol?.overlay) {   // any height works now: offer a finer list
    $('losAgl').innerHTML = [5, 10, 20, 30, 45, 60, 90, 120, 150, 200, 300].map((a) => `<option value="${a}" ${a === 30 ? 'selected' : ''}>${a} m above the ground</option>`).join('');
  }
  if (S.links0) LINKS.apply();
  S.lastAgl = null; await pickLosLayer();
  S.prof = initProfile({ S, scene3, toWorld, demHeight, el: { box: $('profile'), canvas: $('profCanvas'), info: $('profInfo') } });
  $('profBtn').classList.toggle('hidden', !S.prof);
  if (S.prof) {
    $('profBtn').onclick = () => S.prof.show(!S.prof.open);
    $('profClose').onclick = () => S.prof.show(false);
    S.prof.show(true);
  }
  try {
    S.live = initLive({ S, scene3, camera, controls, toWorld, demHeight, onSaved: (file) => refreshTracks(file),
      onStart: () => { if (S.playing) togglePlay(); } });
  } catch (e) { console.warn('live', e); }
  try { initBlackbox({ S, $, onAdded: (file) => refreshTracks(file) }); } catch (e) { console.warn('blackbox', e); }
  window.__alpline = { live: S.live };            // for the automated browser checks
  try { S.zones = await loadZones({ S, scene3, toWorld, demHeight }); } catch (e) { console.warn('geozones', e); S.zones = null; }
  if (S.zones) S.terrainMat.uniforms.uZones.value = S.zones.texture;
  ['zonesOn', 'zonesWalls', 'zonesInactive'].forEach((id) => { $(id).onchange = applyZones; });
  $('zonesRefresh').onclick = refreshZones;
  applyZones();
  applyShadowMode();
  const span = Math.max(S.W, S.H);
  const p = toWorld(S.meta.pilot.x, S.meta.pilot.y, S.meta.pilot.z);
  controls.target.set(0, p.y, 0);
  camera.position.set(-span * 0.35, p.y + span * 0.45, span * 0.75);
  scene3.fog = new THREE.Fog(0x9fb8cf, span * 1.5, span * 6);
  if (S.meta.tracks.length) { const f = rememberedFlight(); $('trackPick').value = f; await loadTrack(f); }
  await closeSplash();
}

// ------------------------------------------------------------------ launch screen
const splashT0 = performance.now();
const loadStep = (t) => { const m = $('loadMsg'); if (m) m.textContent = t; };
async function closeSplash() {
  const l = $('loading'); if (!l) return;
  const wait = 1900 - (performance.now() - splashT0);              // let the spin-up finish (signal sent)
  if (wait > 0) await new Promise((ok) => setTimeout(ok, wait));
  l.classList.add('out');
  window.alpBusy?.(false);
  setTimeout(() => l.remove(), 500);
}

async function boot() {
  let list = [];
  try { list = await getJSON(SCENES + 'index.json'); } catch { /* none yet */ }
  if (!list.length) throw new Error('No scenes found.\nBuild one first:  python -m fpv3d build locations/my_spot.yaml');
  const name = params.get('scene') || list[0].name;
  $('scenePick').innerHTML = list.map((s) => `<option value="${esc(s.name)}" ${s.name === name ? 'selected' : ''}>${esc(s.title)}</option>`).join('');
  $('scenePick').onchange = () => { location.search = `?scene=${encodeURIComponent($('scenePick').value)}`; };
  await loadScene(name);
}

let lastT = performance.now();
renderer.setAnimationLoop(() => {
  const now = performance.now(), dt = Math.min((now - lastT) / 1000, 0.1); lastT = now;
  if (SIM.update(dt)) {                 // training-flight simulator owns camera + drone
    S.detail?.update(now);
    S.live?.tick(now);
    if (!SIM.frozen()) renderer.render(scene3, camera);   // frozen = simulated video loss
    return;
  }
  if (S.playing && S.track) {
    const end = S.track.t[S.track.n - 1];
    if (V.drivesClock()) S.time = Math.min(Math.max(V.logTime(), 0), end);   // follow the video
    else {
      S.time += dt * +$('speed').value;
      if (S.time >= end) { S.time = end; setPlayingUi(false); }
    }
    updateDrone();
  }
  V.tick();
  if (S.pilotMarker) {                              // the antenna turns toward the drone being replayed or flown
    const sim = document.body.classList.contains('sim-on');
    S.pilotMarker.update(S.drone?.visible && (S.track || sim) ? S.drone.position : S.live?.dronePos?.() || null);
    S.rings?.update();
  }
  updateArrows();
  CAM.update(dt);
  const liveOn = document.body.classList.contains('live-on');   // a live flight: its own drone, not the replayed one
  if (S.drone) S.drone.visible = !liveOn && CAM.mode() !== 'drone' && (!!S.track || document.body.classList.contains('sim-on'));   // don't sit inside the marker
  if (S.beam && liveOn !== !!S.beamOffForLive) { S.beamOffForLive = liveOn; S.beam.visible = !liveOn && !!S.track; }
  if (S.drone && S.track) replayMarker(now);
  if (S.cmpMarker) placeGhost();
  if (S.curtain) S.curtain.visible = $('curtainOn').checked && CAM.mode() !== 'drone';
  const orbitMoved = CAM.usesOrbit() ? controls.update() : false;
  S.detail?.update(now);
  S.live?.tick(now);
  // draw only when needed: camera moved, playback, recent UI/data change
  const camMoved = _lastCamPos.distanceToSquared(camera.position) > 1e-6 || 1 - Math.abs(_lastCamQuat.dot(camera.quaternion)) > 1e-9;
  if (RENDER_ALWAYS || orbitMoved || camMoved || S.playing || V.drivesClock() || now < renderUntil) {
    renderer.render(scene3, camera);
    _lastCamPos.copy(camera.position); _lastCamQuat.copy(camera.quaternion);
    S.frames = (S.frames || 0) + 1;
  }
});
const _lastCamPos = new THREE.Vector3(), _lastCamQuat = new THREE.Quaternion();

S.requestRender = requestRender;
window.fpv3d = { S, camera, controls, THREE, SIM, requestRender };
boot().catch((e) => {
  console.error(e); window.alpBusy?.(false);
  const l = $('loading'); if (!l) return;
  l.classList.add('err');
  const name = params.get('scene');
  loadStep(/: 404$/.test(e.message) && name ? `Location “${name}” was not found.\nPick another one in the launcher or on the locations map.` : e.message);
  // nothing to show: the drone hovers instead of the logo
  const lg = l.querySelector('svg.logo'); if (lg) lg.style.display = 'none';
  const box = document.createElement('div'); box.className = 'droneSplash'; l.prepend(box);
  mountDrone(box, { size: 112 }).loop('hover');
  const a = document.createElement('a'); a.href = 'map.html'; a.textContent = '[locations map]'; a.className = 'navlink';
  a.style.marginTop = '14px'; l.append(a);
});
