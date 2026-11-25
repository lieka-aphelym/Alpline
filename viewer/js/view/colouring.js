// How the flight path is coloured: in sight / hidden / lost, signal strength, height, speed, battery, no-fly zones.
// Each function takes the viewer state S; trackColors also writes the legend under the colour picker.
import * as THREE from 'three';
import { RESTRICTIONS } from './geozones.js';
import { RAMP, rampColor } from './trackmath.js';

// the signal states, the same on the ground, the flight path, the status and the playback bar (pro.css)
export const STATE = { ok: '#3ddc84', hidden: '#8b7cf6', lost: '#ff2d55' };
const C_OK = new THREE.Color(STATE.ok), C_FRES = new THREE.Color(0xffb000),
  C_BLOCK = new THREE.Color(STATE.hidden), C_LOST = new THREE.Color(STATE.lost);

export function statusOf(S, i) {
  const tr = S.track, prim = S.meta.links[S.meta.primary_link].name;
  const m = tr.margin[prim]?.[i];
  if (m != null && m < 0) return { c: C_LOST, label: 'Signal probably lost', css: STATE.lost, k: 'lost' };
  if (tr.clearance[i] < 0) return { c: C_BLOCK, label: 'Hidden by terrain', css: STATE.hidden, k: 'hidden' };
  return { c: C_OK, label: 'In sight', css: STATE.ok, k: 'ok' };
}

export function colorModes(S) {
  const modes = [{ id: 'status', label: 'In sight / hidden / signal lost' }];
  for (const l of S.meta.links) modes.push({ id: 'margin:' + l.name, label: `Signal strength · ${l.name}`, lo: -10, hi: 20, unit: 'dB' });
  modes.push({ id: 'agl', label: 'Height above ground', lo: 0, hi: null, unit: 'm', invert: false });
  modes.push({ id: 'speed', label: 'Speed', lo: 0, hi: null, unit: 'km/h' });
  modes.push({ id: 'accel', label: 'Acceleration', lo: 0, hi: null, unit: 'g', dec: 1 });
  if (S.zones) modes.push({ id: 'zones', label: 'No-fly zones' });
  if (S.track?.cell_v) {
    modes.push({ id: 'cellv', label: 'Battery: cell voltage', lo: 3.3, hi: 4.2, unit: 'V', dec: 2 });
    if (S.track.amps?.some((a) => a > 0.5)) modes.push({ id: 'amps', label: 'Battery: current', lo: 0, hi: null, unit: 'A' });
  }
  for (const k of Object.keys(S.track?.telemetry || {})) modes.push({ id: 'tel:' + k, label: `Log: ${k}`, unit: '' });
  return modes;
}

export function seriesFor(S, mode) {
  const tr = S.track;
  if (mode.startsWith('margin:')) return tr.margin[mode.slice(7)];
  if (mode === 'agl') return tr.agl;
  if (mode === 'speed') return tr.speed;
  if (mode === 'accel') return tr.accG;
  if (mode.startsWith('tel:')) return tr.telemetry[mode.slice(4)];
  if (mode === 'cellv') return tr.cell_v;
  if (mode === 'amps') return tr.amps;
  return null;
}

export function trackColors(S, mode, leg) {
  const tr = S.track, n = tr.n;
  mode = mode || 'status';
  const cols = new Float32Array(n * 3), c = new THREE.Color();
  if (mode === 'zones' && tr.zoneSev) {
    const cz = [new THREE.Color('#3ddc84'), new THREE.Color(RESTRICTIONS.CONDITIONAL.color), new THREE.Color(RESTRICTIONS.REQ_AUTHORISATION.color), new THREE.Color(RESTRICTIONS.PROHIBITED.color)];
    for (let i = 0; i < n; i++) cz[Math.max(0, tr.zoneSev[i])].toArray(cols, i * 3);
    leg.className = 'legend gradient cat';
    leg.innerHTML = [['#3ddc84', 'Outside no-fly zones'], [RESTRICTIONS.CONDITIONAL.color, 'Conditions apply'], [RESTRICTIONS.REQ_AUTHORISATION.color, 'Permission needed'], [RESTRICTIONS.PROHIBITED.color, 'Forbidden']]
      .map(([k, t]) => `<li><i style="background:${k}"></i>${t}</li>`).join('');
    return cols;
  }
  if (mode === 'status') {
    for (let i = 0; i < n; i++) statusOf(S, i).c.toArray(cols, i * 3);
    leg.className = 'legend gradient cat';
    leg.innerHTML = [[STATE.ok, 'In sight'], [STATE.hidden, 'Hidden by terrain'], [STATE.lost, 'Signal probably lost']]
      .map(([k, t]) => `<li><i style="background:${k}"></i>${t}</li>`).join('');
    return cols;
  }
  const s = seriesFor(S, mode), m = colorModes(S).find((x) => x.id === mode) || {};
  const finite = s.filter((v) => v != null && isFinite(v));
  let lo = m.lo ?? Math.min(...finite), hi = m.hi ?? Math.max(...finite);
  if (hi - lo < 1e-6) hi = lo + 1;
  for (let i = 0; i < n; i++) {
    const v = s[i];
    if (v == null) c.set(0x888888);
    else if (mode === 'speed' || mode === 'accel' || mode === 'amps') c.setHSL(0.62 - 0.62 * Math.min(Math.max((v - lo) / (hi - lo), 0), 1), 0.85, 0.55);
    else rampColor((v - lo) / (hi - lo), c);
    c.toArray(cols, i * 3);
  }
  leg.className = 'gradient';
  leg.style.background = (mode === 'speed' || mode === 'accel' || mode === 'amps')
    ? 'linear-gradient(90deg, hsl(223,85%,55%), hsl(112,85%,55%), hsl(0,85%,55%))'
    : `linear-gradient(90deg, ${RAMP.map(([p, k]) => `${k} ${p * 100}%`).join(',')})`;
  const dp = m.dec ?? 0;
  leg.innerHTML = `<span style="left:0">${lo.toFixed(dp)} ${m.unit || ''}</span><span style="right:0">${hi.toFixed(dp)} ${m.unit || ''}</span>`;
  return cols;
}
