// Flight maths shared by the viewer's parts: time and distance text, speed and acceleration from the GPS track,
// the red-to-green colour ramp. No three.js scene here: plain numbers in, numbers out.
import * as THREE from 'three';

export function fmtTime(s) {
  s = Math.max(0, s); const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}
export const fmtDist = (m) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);
export const lerp = (a, b, t) => a + (b - a) * t;

export const G = 9.80665;

// position at time t, linearly interpolated between log samples
export function sampleAt(tr, keyX, keyY, keyZ, t) {
  const a = tr.t, n = a.length;
  if (t <= a[0]) return [tr[keyX][0], tr[keyY][0], tr[keyZ][0]];
  if (t >= a[n - 1]) return [tr[keyX][n - 1], tr[keyY][n - 1], tr[keyZ][n - 1]];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (a[m] <= t) lo = m; else hi = m; }
  const f = (t - a[lo]) / Math.max(a[hi] - a[lo], 1e-9);
  return [lerp(tr[keyX][lo], tr[keyX][hi], f), lerp(tr[keyY][lo], tr[keyY][hi], f), lerp(tr[keyZ][lo], tr[keyZ][hi], f)];
}

// Central differences over a time window: GPS updates at ~5-10 Hz and has
// metre-level noise, so differentiating sample-to-sample would be pure noise.
// v(t) = [p(t+h) - p(t-h)] / 2h,  a(t) = [v(t+h) - v(t-h)] / 2h,  h = window / 2
export function computeKinematics(tr, windowS) {
  const n = tr.n, h = windowS / 2, t0 = tr.t[0], t1 = tr.t[n - 1];
  const deriv = (kx, ky, kz, outX, outY, outZ) => {
    tr[outX] = new Float32Array(n); tr[outY] = new Float32Array(n); tr[outZ] = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const ta = Math.max(t0, tr.t[i] - h), tb = Math.min(t1, tr.t[i] + h), dt = tb - ta;
      if (dt < 1e-3) continue;
      const pa = sampleAt(tr, kx, ky, kz, ta), pb = sampleAt(tr, kx, ky, kz, tb);
      tr[outX][i] = (pb[0] - pa[0]) / dt; tr[outY][i] = (pb[1] - pa[1]) / dt; tr[outZ][i] = (pb[2] - pa[2]) / dt;
    }
  };
  deriv('x', 'y', 'z', 'vx', 'vy', 'vz');
  deriv('vx', 'vy', 'vz', 'ax', 'ay', 'az');
  tr.speed = Array.from(tr.vx, (_, i) => Math.hypot(tr.vx[i], tr.vy[i], tr.vz[i]) * 3.6);   // km/h
  tr.accG = Array.from(tr.ax, (_, i) => Math.hypot(tr.ax[i], tr.ay[i], tr.az[i]) / G);      // g
}

export const RAMP = [[0, '#d7263d'], [0.35, '#f49d37'], [0.6, '#f6e05e'], [1, '#3ddc84']];
export const rampColor = (t, out = new THREE.Color()) => {
  t = Math.min(Math.max(t, 0), 1);
  for (let i = 1; i < RAMP.length; i++) if (t <= RAMP[i][0]) {
    const [a, ca] = RAMP[i - 1], [b, cb] = RAMP[i];
    return out.set(ca).lerp(new THREE.Color(cb), (t - a) / (b - a));
  }
  return out.set(RAMP[RAMP.length - 1][1]);
};

// the numbers of the compare table: one flight, against the location's main radio link
export function trackStats(tr, meta) {
  const n = tr.n, prim = meta.links[meta.primary_link]?.name, m = tr.margin?.[prim] || [];
  const fin = (a) => a.filter((v) => v != null && isFinite(v));
  const pick = (re) => { const k = Object.keys(tr.telemetry || {}).find((x) => re.test(x)); return k ? fin(tr.telemetry[k]) : null; };
  const rssi = pick(/^1RSS|RSSI/i), lq = pick(/RQly|(^|_)LQ/i);
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  return {
    'Duration': fmtTime(tr.t[n - 1] - tr.t[0]),
    'Max distance': fmtDist(Math.max(...fin(tr.dist))),
    'Max height AGL': `${Math.max(...fin(tr.agl)).toFixed(0)} m`,
    'Max speed': tr.speed ? `${Math.max(...tr.speed).toFixed(0)} km/h` : '–',
    'Time without LOS': `${(100 * tr.clearance.filter((c) => c < 0).length / n).toFixed(0)} %`,
    'Time in restricted zones': tr.zoneSev ? `${(100 * tr.zoneSev.filter((v) => v >= 2).length / n).toFixed(0)} %` : '–',
    'Time predicted loss': m.length ? `${(100 * fin(m).filter((v) => v < 0).length / n).toFixed(0)} %` : '–',
    'Worst predicted margin': m.length ? `${Math.min(...fin(m)).toFixed(1)} dB` : '–',
    'Logged RSSI min / avg': rssi?.length ? `${Math.min(...rssi).toFixed(0)} / ${mean(rssi).toFixed(0)}` : '–',
    'Logged LQ min': lq?.length ? `${Math.min(...lq).toFixed(0)} %` : '–',
  };
}
