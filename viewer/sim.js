import { esc } from './esc.js';
// fpv3d — training-flight simulator.
//
// Fly over the real swisstopo terrain with your radio (USB joystick mode, read through the
// browser Gamepad API) or the keyboard. The radio link to the pilot is evaluated live with
// the same model as the build (free-space loss + knife-edge diffraction over the DEM), shown
// in an OSD, and degrades the picture / triggers failsafe like a real link would. Flights are
// recorded and saved as tracks so they can be compared with the real flight later.
//
// Coordinates: the simulation runs in metres in a local ENU frame
//   x = east, y = north, z = altitude AMSL   (same as the track files)
// and is converted to three.js world space only for rendering.

const G = 9.81;
const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
const LS_KEY = 'fpv3d:sim:settings';

// ---------------------------------------------------------------- LV95 -> WGS84 (swisstopo approx.)
function toWGS(e, n) {
  const y = (e - 2600000) / 1e6, x = (n - 1200000) / 1e6;
  const l = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3;
  const p = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.014 * x ** 3;
  return [p * 100 / 36, l * 100 / 36];
}

// ---------------------------------------------------------------- radio model (mirrors fpv3d/radio.py)
const fspl = (d, f) => 20 * Math.log10(Math.max(d, 1) / 1000) + 20 * Math.log10(f) + 32.44;
function knifeEdge(F) {           // F = clearance / first Fresnel radius
  const v = -Math.SQRT2 * F;
  return v > -0.78 ? 6.9 + 20 * Math.log10(Math.sqrt((v - 0.1) ** 2 + 1) + v - 0.1) : 0;
}

const DEFAULTS = {
  mode: 'angle',                     // 'acro' | 'angle'
  rates: { center: 200, max: 670, expo: 0.5 },   // deg/s, Betaflight "actual" style
  maxAngle: 55,                      // angle mode, deg
  twr: 6,                            // thrust-to-weight (5" freestyle ~ 6-8)
  uptilt: 25,                        // camera uptilt, deg
  fov: 100,                          // vertical-ish FOV used by three.js, deg
  linkFx: true,                      // degrade video / failsafe from the link model
  preset: 'freestyle5',
  topSpeed: 150,                     // km/h, level flight at full throttle (sets the drag)
  response: 25,                      // ms, how fast the quad follows the sticks (motors + PID)
  wind: { speed: 0, dir: 270, gust: 30 },   // km/h, direction it comes FROM (deg, 0 = north), gust %
  physics: { battery: true, packMin: 6, sag: 0.35, propwash: 0.5, thrMid: 0.5, thrExpo: 0 },   // see simphysics.js
  sound: { on: true, volume: 0.5 },
  autoRes: true,                     // lower / raise the drawing resolution to keep the frame rate smooth
  map: {                             // gamepad axis mapping (EdgeTX default: AETR on axes 0..3)
    roll: { axis: 0, inv: false }, pitch: { axis: 1, inv: false },
    throttle: { axis: 2, inv: false }, yaw: { axis: 3, inv: false },
    arm: { axis: 4, inv: false, button: -1 }, mode: { axis: -1, inv: false },
  },
};

// quad presets (rough, typical values)
export const PRESETS = {
  // packMin: minutes a full pack lasts hovering (a mixed flight is about 60-70 % of that)
  freestyle5: { label: '5" freestyle', twr: 7, topSpeed: 150, response: 25, uptilt: 30, packMin: 6, rates: { center: 200, max: 670, expo: 0.5 } },
  racer5: { label: '5" racer', twr: 10, topSpeed: 180, response: 15, uptilt: 40, packMin: 4, rates: { center: 250, max: 800, expo: 0.4 } },
  longrange7: { label: '7" long range', twr: 4, topSpeed: 130, response: 45, uptilt: 20, packMin: 16, rates: { center: 150, max: 500, expo: 0.4 } },
  cinewhoop35: { label: '3.5" cinewhoop', twr: 4, topSpeed: 80, response: 40, uptilt: 10, packMin: 7, rates: { center: 120, max: 400, expo: 0.3 } },
  tinywhoop: { label: 'Tiny whoop', twr: 3, topSpeed: 45, response: 35, uptilt: 15, packMin: 4, rates: { center: 150, max: 600, expo: 0.3 } },
};

import { mountDrone } from './drone.js';
import { createFlightModel, collide } from './simphysics.js';
import { createMotorSound } from './simsound.js';

export function initSim(app) {
  // app: { THREE, scene3, camera, renderer, S, toWorld, demHeight, setExaggeration, onSaved(file), panelEl }
  const { THREE, camera, renderer, S } = app;
  let cfg = loadSettings();
  const st = {
    active: false, armed: false, crashed: false, frozen: false, failsafe: 0,
    pos: new THREE.Vector3(), vel: new THREE.Vector3(), q: new THREE.Quaternion(), w: new THREE.Vector3(),
    throttleKb: 0, t: 0, rec: [], recT: 0, sigT: 0, sig: null, ctrlBadFor: 0, videoBad: false,
    view: 'fpv', saved: null, gamepad: null, keys: new Set(), trail: null, trailPts: [],
    charge: 1, volts: 4.2, load: 0, power: 1, pw: { x: 0, z: 0 }, propwash: 0,
    scale: 1, frameMs: 16.7, resT: 0,       // adaptive drawing resolution
  };
  const FM = createFlightModel(THREE);
  const SOUND = createMotorSound();

  // ---------------------------------------------------------------- settings
  function loadSettings() {
    try { return deepMerge(structuredClone(DEFAULTS), JSON.parse(localStorage.getItem(LS_KEY) || '{}')); } catch { return structuredClone(DEFAULTS); }
  }
  function saveSettings() { try { localStorage.setItem(LS_KEY, JSON.stringify(cfg)); } catch { /* ignore */ } }
  function deepMerge(a, b) { for (const k in b) a[k] = b[k] && typeof b[k] === 'object' && !Array.isArray(b[k]) ? deepMerge(a[k] || {}, b[k]) : b[k]; return a; }

  // ---------------------------------------------------------------- input
  addEventListener('gamepadconnected', (e) => { st.gamepad = e.gamepad.index; status(); });
  addEventListener('gamepaddisconnected', () => { st.gamepad = null; status(); });
  const pad = () => {
    const pads = navigator.getGamepads ? [...navigator.getGamepads()].filter(Boolean) : [];
    return pads.find((p) => p.index === st.gamepad) || pads[0] || null;
  };
  addEventListener('keydown', (e) => {
    if (!st.active || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    st.keys.add(e.code);
    if (e.code === 'Escape') stop();
    if (e.code === 'KeyR') reset();
    if (e.code === 'KeyV') { st.view = st.view === 'fpv' ? 'chase' : 'fpv'; }
    if (e.code === 'KeyH') toggleBox();
    if (e.code === 'Enter') st.kbArm = true;      // used when no arm switch is mapped
    if (e.code !== 'F5' && e.code !== 'F12') { e.preventDefault(); e.stopPropagation(); }
  }, true);
  addEventListener('keyup', (e) => st.keys.delete(e.code), true);

  function axisVal(p, m) {
    if (!p || m.axis < 0 || m.axis >= p.axes.length) return null;
    const v = p.axes[m.axis];
    return m.inv ? -v : v;
  }
  /** sticks in [-1,1] (throttle in [0,1]) + arm / mode switches */
  function readInput(dt) {
    const p = pad();
    if (p) {
      const m = cfg.map, dz = (v) => (Math.abs(v) < 0.02 ? 0 : v);
      const thr = axisVal(p, m.throttle);
      const armAx = axisVal(p, m.arm);
      const armBtn = m.arm.button >= 0 && p.buttons[m.arm.button]?.pressed;
      const modeAx = axisVal(p, m.mode);
      return {
        src: p.id, roll: dz(axisVal(p, m.roll) ?? 0), pitch: dz(axisVal(p, m.pitch) ?? 0), yaw: dz(axisVal(p, m.yaw) ?? 0),
        throttle: thr == null ? 0 : clamp((thr + 1) / 2, 0, 1),
        arm: armBtn || (armAx != null && armAx > 0.5), mode: modeAx == null ? null : (modeAx > 0.3 ? 'acro' : 'angle'),
      };
    }
    // keyboard: W/S throttle up/down, A/D yaw, arrows pitch/roll, Enter = arm
    const k = (c) => st.keys.has(c);
    st.throttleKb = clamp(st.throttleKb + ((k('KeyW') ? 0.6 : 0) - (k('KeyS') ? 0.6 : 0)) * dt, 0, 1);
    return {
      src: 'keyboard', throttle: st.throttleKb,
      roll: (k('ArrowRight') ? 1 : 0) - (k('ArrowLeft') ? 1 : 0), pitch: (k('ArrowUp') ? 1 : 0) - (k('ArrowDown') ? 1 : 0),
      yaw: (k('KeyD') ? 1 : 0) - (k('KeyA') ? 1 : 0), arm: null, mode: null,
    };
  }

  // ---------------------------------------------------------------- physics (viewer/simphysics.js)
  const _prev = new THREE.Vector3();
  function step(inp, dt) {
    windStep(dt);
    const lx = st.pos.x + S.W / 2, ly = -st.pos.z + S.H / 2;
    const here = app.simGround ? app.simGround(st.pos.x, st.pos.z, st.pos.y, st.pos.y) : { h: app.demHeight(lx, ly) - S.hBase };
    _prev.copy(st.pos);
    FM.step(st, cfg, inp, dt, { wind: st.windV, agl: st.pos.y - here.h });
    const nx = st.pos.x + S.W / 2, ny = -st.pos.z + S.H / 2;
    if (nx < 0 || ny < 0 || nx > S.W || ny > S.H) { st.crashed = 'left the map'; setArmed(false); return; }
    const ground = app.simGround || ((x, z) => ({ h: app.demHeight(x + S.W / 2, -z + S.H / 2) - S.hBase, wall: false }));
    const hit = collide(st, _prev, ground);
    if (hit && hit !== 'bump') { st.crashed = hit; setArmed(false); }
  }

  // wind: steady part from the settings + Ornstein-Uhlenbeck gusts
  const _rel = new THREE.Vector3();
  st.windV = new THREE.Vector3(); st.gust = new THREE.Vector3();
  function windStep(dt) {
    const w = cfg.wind, sp = (w.speed || 0) / 3.6, to = ((w.dir || 0) + 180) * Math.PI / 180;
    const sigma = sp * (w.gust || 0) / 100;
    const rnd = () => (Math.random() + Math.random() + Math.random() - 1.5) * 2;   // ~N(0,1)
    st.gust.x += -st.gust.x * dt / 2 + sigma * Math.sqrt(dt) * rnd();
    st.gust.z += -st.gust.z * dt / 2 + sigma * Math.sqrt(dt) * rnd();
    st.gust.y += -st.gust.y * dt / 1 + 0.3 * sigma * Math.sqrt(dt) * rnd();
    st.windV.set(Math.sin(to) * sp, 0, -Math.cos(to) * sp).add(st.gust);
  }
  const hoverThrottle = () => FM.hoverThrottle(cfg);

  // ---------------------------------------------------------------- live link evaluation
  const _links = () => (S.meta.links || []).map((l) => ({
    ...l, budget: fspl(l.range_m, l.freq_mhz), lam: 299.792458 / l.freq_mhz,
  }));
  function evaluateLink() {
    const p = S.meta.pilot, res = S.meta.grid.res, k = 4 / 3 * 6371000;
    const dx = st.pos.x + S.W / 2 - p.x, dy = -st.pos.z + S.H / 2 - p.y;
    const zD = st.pos.y + S.hBase, dz = zD - p.z;
    const hd = Math.hypot(dx, dy), d3 = Math.hypot(hd, dz);
    const links = _links();
    const n = Math.min(800, Math.max(16, Math.ceil(hd / (0.8 * res))));
    let minGap = Infinity; const minF = links.map(() => Infinity);
    const skip = Math.min(1.5 * res / Math.max(hd, 1e-3), 0.45);
    for (let i = 1; i < n; i++) {
      const t = i / n; if (t <= skip || t >= 1 - skip) continue;
      const d1 = hd * t, d2 = hd - d1;
      const ground = app.demHeight(p.x + dx * t, p.y + dy * t) + d1 * d2 / (2 * k);
      const gap = p.z + dz * t - ground;
      if (gap < minGap) minGap = gap;
      links.forEach((l, j) => { const r1 = Math.sqrt(Math.max(l.lam * d1 * d2 / Math.max(hd, 1e-3), 1e-6)); const f = gap / r1; if (f < minF[j]) minF[j] = f; });
    }
    const perLink = links.map((l, j) => {
      const F = Number.isFinite(minF[j]) ? minF[j] : 99;
      const margin = l.budget - fspl(d3, l.freq_mhz) - knifeEdge(F);
      const rssi = l.rx_sensitivity_dbm != null ? margin + l.rx_sensitivity_dbm + (l.fade_margin_db ?? 10) : null;
      const lq = clamp(100 - Math.max(0, 3 - margin) * 9, 0, 100);
      return { name: l.name, color: l.color, margin, rssi, lq, F };
    });
    return { dist: d3, hd, clearance: Number.isFinite(minGap) ? minGap : 9999, agl: st.pos.y - (app.demHeight(st.pos.x + S.W / 2, -st.pos.z + S.H / 2) - S.hBase), links: perLink };
  }

  // ---------------------------------------------------------------- start / stop
  // the drone in the training box: hovers while waiting, takes off when armed, props turning in flight
  let D = null;
  const droneTxt = (t) => { const e = document.getElementById('simDroneTxt'); if (e) e.textContent = t; };
  function droneIcon() {
    if (!D && document.getElementById('simDrone')) D = mountDrone(document.getElementById('simDrone'), { size: 48 });
    return D;
  }
  function setArmed(on) {
    if (on && st.crashed) return;
    if (on && !st.armed) { st.rec = []; st.t = 0; st.recT = 0; st.trailPts = []; droneIcon()?.play('takeoff', () => D.loop('props')); droneTxt('flying · recording'); }
    if (!on && st.armed) {
      droneIcon()?.flying(false); D?.loop(st.crashed ? null : 'hover'); D?.off(!!st.crashed);
      droneTxt(st.crashed ? `${st.crashed}: R to reset` : 'disarmed: arm to take off');
    }
    st.armed = on; status();
  }
  function startPose() {
    const p = S.meta.pilot;
    // take off 5 m in front of the pilot (towards the map centre), on the ground
    const toC = new THREE.Vector2(S.W / 2 - p.x, S.H / 2 - p.y); if (toC.length() < 1) toC.set(0, 1); toC.normalize();
    const lx = p.x + toC.x * 5, ly = p.y + toC.y * 5;
    st.pos.set(lx - S.W / 2, app.demHeight(lx, ly) - S.hBase + 0.12, -(ly - S.H / 2));
    st.vel.set(0, 0, 0); st.w.set(0, 0, 0);
    const yaw = Math.atan2(-toC.x, toC.y);   // face away from the pilot
    st.q.setFromEuler(new THREE.Euler(0, yaw, 0, 'YXZ'));
  }
  function reset() {
    if (st.crashed) { D?.off(false); D?.loop('hover'); droneTxt('waiting: arm to take off'); }
    st.crashed = false; st.failsafe = 0; st.ctrlBadFor = 0; setFrozen(false); setArmed(false); startPose();
    st.charge = 1; st.volts = 4.2; st.pw.x = st.pw.z = 0;     // fresh pack
  }

  function start() {
    if (st.active) return;
    st.active = true;
    app.ensureDrone?.();
    st.saved = { fov: camera.fov, near: camera.near, exag: S.exag, pos: camera.position.clone(), quat: camera.quaternion.clone() };
    if (S.exag !== 1) app.setExaggeration(1);
    camera.fov = cfg.fov; camera.near = 0.1; camera.updateProjectionMatrix();
    document.body.classList.add('sim-on');
    app.setClutterVisible?.(false);
    reset();
    buildTrail();
    status();
    droneIcon()?.flying(false); D?.loop('hover'); droneTxt('waiting: arm to take off');
  }
  function stop() {
    if (!st.active) return;
    st.active = false; setFrozen(false); st.armed = false;
    S.simFocus = null; SOUND.stop();
    app.onSimStop?.();
    camera.fov = st.saved.fov; camera.near = st.saved.near; camera.updateProjectionMatrix();
    camera.position.copy(st.saved.pos); camera.quaternion.copy(st.saved.quat);
    if (st.saved.exag !== 1) app.setExaggeration(st.saved.exag);
    document.body.classList.remove('sim-on');
    app.setClutterVisible?.(true);
    if (st.trail) st.trail.visible = false;
    $('simVideoFx').style.opacity = 0;
    app.onStop?.();
    status();
  }
  function setFrozen(on) { st.frozen = on; applyRes(1); }
  // drawing resolution = the adaptive scale (keeps the frame rate) x the link effect (blocky video when weak)
  const maxRatio = () => Math.min(devicePixelRatio, 2);
  let linkFactor = 1;
  function applyRes(f) {
    linkFactor = f;
    const r = Math.max(0.2, maxRatio() * (cfg.autoRes ? st.scale : 1) * f);
    if (Math.abs(renderer.getPixelRatio() - r) > 0.01) renderer.setPixelRatio(r);
  }
  /** every frame: average frame time; every 0.7 s step the resolution down (slow frames) or back up (room left) */
  function adaptRes(dt) {
    if (!cfg.autoRes || dt <= 0 || dt > 0.25) return;
    st.frameMs += (dt * 1000 - st.frameMs) * 0.1;
    st.resT += dt;
    if (st.resT < 0.7) return;
    st.resT = 0;
    if (st.frameMs > 21 && st.scale > 0.5) st.scale = Math.max(0.5, st.scale * 0.85);          // under ~48 fps
    else if (st.frameMs < 17.8 && st.scale < 1) st.scale = Math.min(1, st.scale * 1.08);      // ~56+ fps: sharper again
    applyRes(linkFactor);
  }

  // ---------------------------------------------------------------- trail (live track)
  function buildTrail() {
    if (st.trail) { app.scene3.remove(st.trail); st.trail.geometry.dispose(); }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3 * 20000), 3));
    g.setDrawRange(0, 0);
    st.trail = new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xffe14d }));
    st.trail.frustumCulled = false;
    app.scene3.add(st.trail);
  }
  function pushTrail() {
    if (!st.trail || st.trailPts.length >= 20000) return;
    const a = st.trail.geometry.attributes.position, i = st.trailPts.length;
    a.setXYZ(i, st.pos.x, st.pos.y, st.pos.z); st.trailPts.push(1);
    a.needsUpdate = true; st.trail.geometry.setDrawRange(0, st.trailPts.length);
  }

  // ---------------------------------------------------------------- per frame
  const _cq = new THREE.Quaternion(), _tilt = new THREE.Quaternion(), _back = new THREE.Vector3();
  const _u = new THREE.Vector3(), _ax = new THREE.Vector3();
  function update(dt) {
    if (!st.active) return false;
    const inp = readInput(dt);
    let wantArm = inp.arm;
    if (wantArm == null) { if (st.kbArm) wantArm = !st.armed; else wantArm = st.armed; }
    st.kbArm = false;
    st.armBlocked = false;
    if (wantArm !== st.armed) {
      if (wantArm && inp.throttle > 0.08) st.armBlocked = true;   // like Betaflight: no arming with throttle up
      else setArmed(wantArm);
    }
    if (!st.crashed) {
      const sub = Math.max(1, Math.ceil(dt / 0.004));
      for (let i = 0; i < sub; i++) step(inp, dt / sub);
    }
    if (st.armed) st.t += dt;
    // the sharp terrain follows the drone, a little ahead in the direction of flight
    {
      const ahead = Math.min(2, (app.detailSize?.() || 600) / 4 / Math.max(st.vel.length(), 1));
      S.simFocus = { x: st.pos.x + st.vel.x * ahead + S.W / 2, y: -(st.pos.z + st.vel.z * ahead) + S.H / 2 };
    }
    SOUND.set(cfg.sound);
    SOUND.update(st.armed && !st.crashed, st.load * st.power, st.vel.length(), st.propwash);
    adaptRes(dt);

    // link model at 10 Hz
    st.sigT += dt;
    if (st.sigT >= 0.1 || !st.sig) { st.sigT = 0; st.sig = evaluateLink(); applyLinkEffects(dt); app.onSimTick?.(st); }

    // record at 10 Hz while armed
    st.recT += dt;
    if (st.armed && st.recT >= 0.1) { st.recT = 0; record(inp); pushTrail(); }

    // camera
    if (st.view === 'fpv') {
      camera.position.copy(st.pos);
      _tilt.setFromAxisAngle(_ax.set(1, 0, 0), cfg.uptilt * Math.PI / 180);
      camera.quaternion.copy(_cq.copy(st.q).multiply(_tilt));
    } else {
      _back.set(0, 0, 1).applyQuaternion(st.q); _back.y = 0;
      if (_back.lengthSq() < 1e-4) _back.set(0, 0, 1);
      _back.normalize();
      camera.position.copy(st.pos).addScaledVector(_back, 12).add(_u.set(0, 4, 0));
      camera.lookAt(st.pos);
    }
    if (S.drone) {                                           // chase view: the same marker as the replay, real attitude
      S.drone.visible = st.view === 'chase'; S.drone.position.copy(st.pos);
      const s = st.sig, g = app.simGround ? app.simGround(st.pos.x, st.pos.z, st.pos.y, st.pos.y).h : null;
      const m = s?.links?.[0]?.margin, css = m == null ? '#3ddc84' : m < 0 ? '#ff2d55' : s.clearance < 0 ? '#ff7a1a' : '#3ddc84';
      app.markerUpdate?.({ vel: st.vel, attitude: st.q, groundY: g, agl: s?.agl, color: css, css });
    }
    osd(inp);
    return true;
  }

  function applyLinkEffects(dt) {
    const fx = $('simVideoFx');
    if (!cfg.linkFx || !st.sig) { fx.style.opacity = 0; if (st.frozen || linkFactor !== 1) setFrozen(false); return; }
    const L = st.sig.links, vid = L[0], ctl = L[1] || L[0];
    // video (link 0): digital-style degradation -> blocky -> frozen + "no signal"
    if (vid.margin < 0) { if (!st.frozen) setFrozen(true); st.frozen = true; }
    else if (vid.margin > 1.5) { if (st.frozen) setFrozen(false); }
    if (!st.frozen) applyRes(vid.margin < 4 ? clamp(0.2 + vid.margin / 5, 0.2, 1) / maxRatio() : 1);
    fx.style.opacity = st.frozen ? 1 : vid.margin < 4 ? clamp((4 - vid.margin) / 8, 0, 0.5) : 0;
    fx.classList.toggle('lost', st.frozen);
    // control link (link 1): lost for > 0.5 s -> failsafe stage 1 (level, hold 1 s) -> stage 2 (drop)
    if (st.armed && ctl.margin < 0) st.ctrlBadFor += 0.1; else st.ctrlBadFor = 0;
    if (st.ctrlBadFor > 0.5) st.failsafe = st.ctrlBadFor > 1.5 ? 2 : 1; else st.failsafe = 0;
  }

  // ---------------------------------------------------------------- OSD
  function bar(v, lo, hi) { const n = Math.round(clamp((v - lo) / (hi - lo), 0, 1) * 5); return '▮'.repeat(n) + '▯'.repeat(5 - n); }
  function osd(inp) {
    const s = st.sig; if (!s) return;
    const spd = st.vel.length() * 3.6;
    const links = s.links.map((l) => `<div class="ol" style="color:${l.margin < 0 ? '#ff4d4d' : l.margin < 4 ? '#ffb000' : l.color}">
        ${esc(l.name.replace(/\s*\(.*\)/, ''))}: ${bar(l.margin, -3, 15)} ${l.margin >= 0 ? '+' : ''}${l.margin.toFixed(0)} dB
        ${l.rssi != null ? `· ${l.rssi.toFixed(0)} dBm` : ''} · LQ ${l.lq.toFixed(0)}%</div>`).join('');
    const zh = app.zonesAt ? app.zonesAt(st.pos.x + S.W / 2, -st.pos.z + S.H / 2, st.pos.y + S.hBase).filter((h) => h.inBand && h.zone.info.sev >= 1) : [];
    const zoneWarn = zh.length ? `<div class="ozone" style="color:${zh[0].zone.info.color}">ZONE: ${zh[0].zone.info.label.toUpperCase()} ZONE · ${esc(zh[0].zone.name)}</div>` : '';
    const warn = st.armBlocked ? 'THROTTLE UP — lower it to arm' : st.crashed ? `${st.crashed.toUpperCase()} — press R` :
      st.failsafe === 2 ? 'FAILSAFE — CONTROL LINK LOST' : st.failsafe === 1 ? 'FAILSAFE (stage 1)' :
        st.frozen ? 'VIDEO SIGNAL LOST' : cfg.physics.battery && st.armed && st.charge < 0.12 ? 'BATTERY LOW — LAND' :
          s.clearance < 0 ? 'NO LINE OF SIGHT' : '';
    $('simOsd').innerHTML = `
      <div class="otl">${st.armed ? '<b class="arm">ARMED</b>' : 'DISARMED'} · ${(inp.mode || cfg.mode).toUpperCase()} · ${fmtT(st.t)}${st.armed ? ' · <span class="rec">● REC</span>' : ''}</div>
      <div class="otr">HOME ${s.dist.toFixed(0)} m<br>AGL ${s.agl.toFixed(0)} m<br>${spd.toFixed(0)} km/h${cfg.wind.speed > 0 ? `<br>wind ${(st.windV.length() * 3.6).toFixed(0)} km/h ${compass(cfg.wind.dir)}` : ''}</div>
      <div class="obl">${links}</div>
      <div class="obr">${cfg.physics.battery ? `<span style="color:${st.volts < 3.4 ? '#ff4d4d' : st.volts < 3.6 ? '#ffb000' : 'inherit'}">BAT ${st.volts.toFixed(2)} V · ${Math.round(st.charge * 100)}%</span><br>` : ''}THR ${(inp.throttle * 100).toFixed(0)}%<br>${s.clearance < 0 ? `LOS blocked ${(-s.clearance).toFixed(0)} m` : `LOS clear +${Math.min(s.clearance, 999).toFixed(0)} m`}</div>
      <div class="owarn">${warn}</div>
      ${zoneWarn}
      <div class="ocross">${st.view === 'fpv' && !st.frozen ? '+' : ''}</div>`;
  }
  const compass = (d) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(((d % 360) + 360) % 360 / 45) % 8];
  const fmtT = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;

  // ---------------------------------------------------------------- recording / saving
  function record(inp) {
    const lx = st.pos.x + S.W / 2, ly = -st.pos.z + S.H / 2, g = S.meta.grid;
    const [lat, lon] = toWGS(g.min_e + lx, g.min_n + ly);
    const row = { t: st.t, lat, lon, alt: st.pos.y + S.hBase, speed: st.vel.length(), thr: inp.throttle };
    st.sig?.links.forEach((l, j) => { row[`m${j}`] = l.margin; row[`r${j}`] = l.rssi; row[`q${j}`] = l.lq; });
    st.rec.push(row);
  }
  function toCsv() {
    const L = S.meta.links;
    const safe = (s) => s.replace(/[^A-Za-z0-9]+/g, '_').replace(/^_|_$/g, '');
    const head = ['time_s', 'lat', 'lon', 'alt', 'speed_m_s', 'throttle'];
    L.forEach((l) => head.push(`RSSI_sim_${safe(l.name)}_dBm`, `LQ_sim_${safe(l.name)}`, `SNR_margin_sim_${safe(l.name)}_dB`));
    const lines = [head.join(',')];
    for (const r of st.rec) {
      const v = [r.t.toFixed(2), r.lat.toFixed(7), r.lon.toFixed(7), r.alt.toFixed(1), r.speed.toFixed(2), r.thr.toFixed(3)];
      L.forEach((_, j) => v.push(r[`r${j}`] == null ? '' : r[`r${j}`].toFixed(1), r[`q${j}`].toFixed(0), r[`m${j}`].toFixed(1)));
      lines.push(v.join(','));
    }
    return lines.join('\n') + '\n';
  }
  async function save() {
    if (st.rec.length < 20) { msg('Nothing recorded yet - arm and fly first (recording runs while armed).', true); return; }
    const name = ($('simName').value || '').trim();
    msg('Saving and analysing…');
    try {
      const r = await fetch('/api/simtrack', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene: S.meta.name, name, csv: toCsv() }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || r.statusText);
      msg(`Saved as “${d.track}” (${st.rec.length} samples). Pick it under Flight, and use “Compare with” for the real flight.`);
      app.onSaved(d.file);
    } catch (e) {
      // no server API (opened as plain files?) -> offer a download instead
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([toCsv()], { type: 'text/csv' }));
      a.download = `sim_${S.meta.name}_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`;
      a.click();
      msg(`Could not save through the server (${e.message}). Downloaded the CSV instead - add it with: python -m fpv3d add-log locations/${S.meta.name}.yaml <file>`, true);
    }
  }
  function msg(t, err = false) { const m = $('simMsg'); m.textContent = t; m.style.color = err ? 'var(--bad)' : 'var(--muted)'; }

  // ---------------------------------------------------------------- UI: settings + radio mapping
  function status() {
    const p = pad();
    $('simInput').innerHTML = p ? `[radio] <b>${p.id.slice(0, 40)}</b> (${p.axes.length} axes)` :
      'Using the keyboard. No radio found yet: plug it in (<b>Joystick</b> mode) and move a stick.';
    $('simStart').textContent = '[start training flight]';
    $('simLive').classList.toggle('hidden', !st.active);
  }
  // the training-flight box can be folded to one line (button or H): it covers less of the FPV view
  function toggleBox(force) {
    const box = $('simLive'), hide = force ?? !box.classList.contains('folded');
    box.classList.toggle('folded', hide);
    $('simHide').textContent = hide ? '[show]' : '[hide]';
    try { localStorage.setItem('fpv3d:simFolded', hide ? '1' : ''); } catch { /* private mode */ }
  }
  function bindUi() {
    const set = (id, path, conv = Number) => {
      const el = $(id), parts = path.split('.');
      const get = () => parts.reduce((o, k) => o[k], cfg);
      if (el.type === 'checkbox') el.checked = get(); else el.value = get();
      el.addEventListener('input', () => {
        const v = el.type === 'checkbox' ? el.checked : conv(el.value);
        parts.slice(0, -1).reduce((o, k) => o[k], cfg)[parts.at(-1)] = v; saveSettings();
        if (id === 'simFov' && st.active) { camera.fov = cfg.fov; camera.updateProjectionMatrix(); }
        const out = $(id + 'Out'); if (out) out.textContent = el.value;
      });
      const out = $(id + 'Out'); if (out) out.textContent = el.value;
    };
    set('simMode', 'mode', String); set('simCenter', 'rates.center'); set('simMax', 'rates.max'); set('simExpo', 'rates.expo');
    set('simTwr', 'twr'); set('simUptilt', 'uptilt'); set('simFov', 'fov'); set('simAngle', 'maxAngle'); set('simFx', 'linkFx');
    set('simTop', 'topSpeed'); set('simResp', 'response');
    set('simWind', 'wind.speed'); set('simWindDir', 'wind.dir'); set('simGust', 'wind.gust');
    set('simBat', 'physics.battery'); set('simPack', 'physics.packMin'); set('simWash', 'physics.propwash');
    set('simThrMid', 'physics.thrMid'); set('simThrExpo', 'physics.thrExpo');
    set('simSound', 'sound.on'); set('simVol', 'sound.volume'); set('simAutoRes', 'autoRes');
    ['simThrMid', 'simThrExpo', 'simBat'].forEach((id) => $(id).addEventListener('input', hoverInfo));
    $('simAutoRes').addEventListener('input', () => { if (!cfg.autoRes) st.scale = 1; applyRes(linkFactor); });
    const sel = $('simPreset');
    sel.innerHTML = Object.entries(PRESETS).map(([k, p]) => `<option value="${k}">${p.label}</option>`).join('') + '<option value="custom">Custom</option>';
    sel.value = PRESETS[cfg.preset] ? cfg.preset : 'custom';
    sel.onchange = () => {
      cfg.preset = sel.value;
      const pr = PRESETS[sel.value];
      if (pr) {
        Object.assign(cfg, { twr: pr.twr, topSpeed: pr.topSpeed, response: pr.response, uptilt: pr.uptilt }); cfg.rates = { ...pr.rates };
        if (pr.packMin) cfg.physics.packMin = pr.packMin;
      }
      saveSettings(); syncUi();
    };
    // any manual change of a flight-model slider turns the preset into "Custom"
    ['simTwr', 'simTop', 'simResp', 'simCenter', 'simMax', 'simExpo'].forEach((id) => $(id).addEventListener('input', () => {
      if (cfg.preset !== 'custom') { cfg.preset = 'custom'; sel.value = 'custom'; saveSettings(); }
      hoverInfo();
    }));
    $('simWindDir').addEventListener('input', () => { $('simWindDirOut').textContent = `${cfg.wind.dir}° (${compass(cfg.wind.dir)})`; });
    hoverInfo(); $('simWindDirOut').textContent = `${cfg.wind.dir}° (${compass(cfg.wind.dir)})`;
    $('simStart').onclick = () => (st.active ? stop() : start());
    $('simSave').onclick = save;
    $('simReset').onclick = reset;
    $('simHide').onclick = () => toggleBox();
    try { toggleBox(localStorage.getItem('fpv3d:simFolded') === '1'); } catch { /* private mode */ }
    $('simExit').onclick = stop;
    $('simMapBtn').onclick = openMapping;
    status();
  }

  function hoverInfo() { $('simHover').textContent = `hover ≈ ${(hoverThrottle() * 100).toFixed(0)} % throttle`; }
  function syncUi() {    // push cfg values back into the inputs (after a preset change)
    const map = { simTwr: cfg.twr, simTop: cfg.topSpeed, simResp: cfg.response, simUptilt: cfg.uptilt,
      simCenter: cfg.rates.center, simMax: cfg.rates.max, simExpo: cfg.rates.expo, simPack: cfg.physics.packMin };
    for (const [id, v] of Object.entries(map)) { $(id).value = v; const o = $(id + 'Out'); if (o) o.textContent = v; }
    hoverInfo();
  }

  // radio mapping dialog with live bars + auto-detect
  let mapTimer = null;
  function openMapping() {
    const dlg = $('simMapDlg'); dlg.classList.remove('hidden');
    const fns = ['throttle', 'yaw', 'pitch', 'roll', 'arm', 'mode'];
    const p = pad(), nAx = p ? p.axes.length : 8;
    const opts = (sel) => `<option value="-1">–</option>` + Array.from({ length: nAx }, (_, i) => `<option value="${i}" ${i === sel ? 'selected' : ''}>axis ${i}</option>`).join('');
    $('simMapRows').innerHTML = fns.map((f) => `<tr data-f="${f}"><td>${f}${f === 'arm' ? ' switch' : f === 'mode' ? ' switch <span class="muted">(acro/angle)</span>' : ''}</td>
        <td><select>${opts(cfg.map[f].axis)}</select></td>
        <td><label><input type="checkbox" ${cfg.map[f].inv ? 'checked' : ''}> invert</label></td>
        <td><button class="det">[detect]</button></td><td class="barcell"><div class="vbar"><i></i></div></td></tr>`).join('');
    $('simMapRows').querySelectorAll('tr').forEach((tr) => {
      const f = tr.dataset.f, sel = tr.querySelector('select'), inv = tr.querySelector('input');
      sel.onchange = () => { cfg.map[f].axis = +sel.value; saveSettings(); };
      inv.onchange = () => { cfg.map[f].inv = inv.checked; saveSettings(); };
      tr.querySelector('.det').onclick = () => detect(f, sel, tr.querySelector('.det'));
    });
    $('simMapPad').textContent = p ? p.id : 'No radio detected yet - plug it in (USB, Joystick mode) and move a stick.';
    clearInterval(mapTimer);
    mapTimer = setInterval(() => {
      const pp = pad(); if (!pp) return;
      $('simMapPad').textContent = pp.id;
      $('simMapRows').querySelectorAll('tr').forEach((tr) => {
        const m = cfg.map[tr.dataset.f], v = axisVal(pp, m);
        tr.querySelector('.vbar i').style.width = v == null ? '0%' : `${((v + 1) / 2) * 100}%`;
      });
    }, 50);
    $('simMapClose').onclick = () => { clearInterval(mapTimer); dlg.classList.add('hidden'); };
  }
  function detect(f, sel, btn) {
    const p0 = pad(); if (!p0) { btn.textContent = 'no radio'; return; }
    const base = [...p0.axes]; let best = -1, bestD = 0, n = 0;
    btn.textContent = 'move it…';
    const iv = setInterval(() => {
      const p = pad(); n++;
      p.axes.forEach((v, i) => { const d = Math.abs(v - base[i]); if (d > bestD) { bestD = d; best = i; } });
      if (n > 60 || bestD > 0.9) {
        clearInterval(iv);
        if (best >= 0 && bestD > 0.3) { cfg.map[f].axis = best; sel.value = best; saveSettings(); btn.textContent = `axis ${best} ok`; } else btn.textContent = 'retry';
      }
    }, 50);
  }

  bindUi();
  return { update, active: () => st.active, frozen: () => st.frozen, start, stop, _state: st };
}
