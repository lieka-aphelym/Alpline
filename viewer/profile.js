// fpv3d — route profile: a side view along a corridor's route.
//   ground          terrain under the route (brown)
//   blind band      below this height above ground there is no line of sight to the pilot (indigo)
//   loss line       below it the predicted link margin is negative (red, dashed)
//   your height     the "shadow at X m above ground" setting (white dashed)
//   flight          the selected log, projected onto the route (dots coloured by link status)
// Hovering shows the numbers and puts a marker on the 3D map.
import * as THREE from 'three';

const CAP = 400;   // m above ground: higher blind columns are drawn as "more than"

export function initProfile({ S, scene3, toWorld, demHeight, el }) {
  const cor = S.meta.corridor;
  if (!cor) return null;
  const pts = cor.points;                     // local metres
  const segLen = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  const total = segLen.reduce((a, b) => a + b, 0);
  const ctx = el.canvas.getContext('2d');
  let samples = null, hoverD = null, open = false;

  // 3D marker for the hovered point
  const marker = new THREE.Group();
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(1.5, 1.5, 1, 8), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  const ball = new THREE.Mesh(new THREE.SphereGeometry(5, 12, 8), new THREE.MeshBasicMaterial({ color: 0xff9f1a }));
  marker.add(pole, ball); marker.visible = false; scene3.add(marker);

  function at(d) {                            // local (x, y) at distance d along the route
    let s = 0;
    for (let i = 0; i < segLen.length; i++) {
      if (d <= s + segLen[i] || i === segLen.length - 1) {
        const t = Math.max(0, Math.min(1, (d - s) / (segLen[i] || 1)));
        return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t];
      }
      s += segLen[i];
    }
    return pts[0];
  }
  function project(x, y) {                    // distance along route + lateral offset of a local point
    let best = { d: 0, off: Infinity }, s = 0;
    for (let i = 0; i < segLen.length; i++) {
      const [ax, ay] = pts[i], [bx, by] = pts[i + 1], L = segLen[i] || 1e-9;
      const t = Math.max(0, Math.min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / (L * L)));
      const off = Math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay)));
      if (off < best.off) best = { d: s + t * L, off };
      s += L;
    }
    return best;
  }

  function sample() {
    const n = Math.min(1500, Math.max(200, Math.round(total / Math.max(S.meta.grid.res * 2, 2))));
    const ceil = (name, x, y) => (S.vol?.ceilAt ? S.vol.ceilAt(name, x, y) : null);
    samples = Array.from({ length: n }, (_, i) => {
      const d = (total * i) / (n - 1), [x, y] = at(d), g = demHeight(x, y);
      return { d, x, y, g, los: ceil('los', x, y), fr: ceil('fresnel', x, y), loss: ceil('loss', x, y) };
    });
  }

  function trackPoints() {
    const tr = S.track;
    if (!tr) return [];
    const out = [], step = Math.max(1, Math.floor(tr.n / 1500));
    for (let i = 0; i < tr.n; i += step) {
      if (tr.x[i] == null) continue;
      const p = project(tr.x[i], tr.y[i]);
      if (p.off > cor.width_m * 1.3) continue;
      const blocked = tr.clearance?.[i] != null && tr.clearance[i] < 0;
      out.push({ d: p.d, z: tr.z[i], c: blocked ? '#ff3b30' : '#2ecc71' });
    }
    return out;
  }

  function draw() {
    if (!open) return;
    const W = el.canvas.clientWidth, H = el.canvas.clientHeight, dpr = devicePixelRatio || 1;
    if (el.canvas.width !== W * dpr) { el.canvas.width = W * dpr; el.canvas.height = H * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (!samples) sample();
    const agl = S.lastAgl ?? 30, p = S.meta.pilot;
    const tp = trackPoints();
    let lo = Infinity, hi = -Infinity;
    for (const s of samples) {
      lo = Math.min(lo, s.g); hi = Math.max(hi, s.g + Math.max(agl, Math.min(s.los ?? 0, CAP)));
    }
    for (const q of tp) { lo = Math.min(lo, q.z); hi = Math.max(hi, q.z); }
    const pp = project(p.x, p.y), pilotOn = pp.off <= cor.width_m * 1.5;
    if (pilotOn) hi = Math.max(hi, p.z);
    lo -= 15; hi += 25;
    const L = 46, R = 10, T = 10, B = 22;
    const X = (d) => L + ((W - L - R) * d) / total, Y = (z) => T + ((H - T - B) * (hi - z)) / (hi - lo);
    // grid
    ctx.font = '10px system-ui, sans-serif'; ctx.fillStyle = '#8b96a8'; ctx.strokeStyle = 'rgba(255,255,255,.07)'; ctx.lineWidth = 1;
    const zStep = niceStep((hi - lo) / 4), dStep = niceStep(total / 6);
    for (let z = Math.ceil(lo / zStep) * zStep; z <= hi; z += zStep) {
      ctx.beginPath(); ctx.moveTo(L, Y(z)); ctx.lineTo(W - R, Y(z)); ctx.stroke(); ctx.fillText(`${Math.round(z)}`, 4, Y(z) + 3);
    }
    for (let d = 0; d <= total; d += dStep) {
      ctx.beginPath(); ctx.moveTo(X(d), T); ctx.lineTo(X(d), H - B); ctx.stroke();
      ctx.fillText(d >= 1000 ? `${(d / 1000).toFixed(dStep < 1000 ? 1 : 0)} km` : `${Math.round(d)} m`, X(d) - 10, H - 7);
    }
    // blind band (no line of sight)
    if (samples[0].los != null) {
      ctx.beginPath();
      samples.forEach((s, i) => { const z = s.g + Math.min(s.los, CAP); i ? ctx.lineTo(X(s.d), Y(z)) : ctx.moveTo(X(s.d), Y(z)); });
      for (let i = samples.length - 1; i >= 0; i--) ctx.lineTo(X(samples[i].d), Y(samples[i].g));
      ctx.closePath(); ctx.fillStyle = 'rgba(91,75,214,.45)'; ctx.fill();
      line((s) => s.g + Math.min(s.loss, CAP), '#ff3b30', [5, 4], 1.5);
    }
    // ground
    ctx.beginPath();
    samples.forEach((s, i) => (i ? ctx.lineTo(X(s.d), Y(s.g)) : ctx.moveTo(X(s.d), Y(s.g))));
    ctx.lineTo(X(total), H - B); ctx.lineTo(X(0), H - B); ctx.closePath();
    ctx.fillStyle = '#5b4a3a'; ctx.fill();
    line((s) => s.g, '#c8a77e', [], 1.5);
    // chosen height above ground
    line((s) => s.g + agl, 'rgba(255,255,255,.7)', [3, 4], 1);
    // flight
    for (const q of tp) { ctx.fillStyle = q.c; ctx.fillRect(X(q.d) - 1.2, Y(q.z) - 1.2, 2.4, 2.4); }
    if (S.drone && S.track) {
      const v = S.drone.position, x = v.x + S.W / 2, y = S.H / 2 - v.z, z = v.y / S.exag + S.hBase, q = project(x, y);
      if (q.off <= cor.width_m * 1.3) { ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(X(q.d), Y(z), 4, 0, 7); ctx.fill(); }
    }
    // pilot
    if (pilotOn) {
      ctx.fillStyle = '#ffd400'; ctx.beginPath(); ctx.arc(X(pp.d), Y(p.z), 4.5, 0, 7); ctx.fill();
      ctx.fillText('pilot', X(pp.d) + 6, Y(p.z) - 5);
    }
    // hover
    if (hoverD != null) {
      const i = Math.round((hoverD / total) * (samples.length - 1)), s = samples[Math.max(0, Math.min(samples.length - 1, i))];
      ctx.strokeStyle = 'rgba(255,255,255,.6)'; ctx.setLineDash([]); ctx.beginPath(); ctx.moveTo(X(s.d), T); ctx.lineTo(X(s.d), H - B); ctx.stroke();
      const fmt = (v) => (v == null ? '–' : v >= 1e4 ? 'at no height' : v < 0.5 ? 'from the ground up' : `from ${Math.round(v)} m above ground`);
      el.info.innerHTML = `<b>${s.d >= 1000 ? `${(s.d / 1000).toFixed(2)} km` : `${Math.round(s.d)} m`}</b> along the route · ground ${Math.round(s.g)} m`
        + (s.los != null ? ` · line of sight ${fmt(s.los)} · signal ${fmt(s.loss)}` : '');
      toWorld(s.x, s.y, s.g, marker.position);
      const hgt = Math.max(20, Math.min(s.los ?? 0, CAP)) * S.exag;
      pole.scale.y = hgt; pole.position.y = hgt / 2; ball.position.y = hgt;
      marker.visible = true;
    } else {
      marker.visible = false;
      el.info.innerHTML = `Route ${(total / 1000).toFixed(2)} km · strip ${2 * cor.width_m} m wide · <span style="color:#8f84ff">■</span> no line of sight below · <span style="color:#ff3b30">- -</span> signal loss · <span style="color:#ddd">- -</span> ${agl} m above ground`;
    }

    function line(f, color, dash, w) {
      ctx.beginPath(); ctx.setLineDash(dash); ctx.strokeStyle = color; ctx.lineWidth = w;
      samples.forEach((s, i) => { const z = f(s); i ? ctx.lineTo(X(s.d), Y(z)) : ctx.moveTo(X(s.d), Y(z)); });
      ctx.stroke(); ctx.setLineDash([]); ctx.lineWidth = 1;
    }
  }

  el.canvas.addEventListener('pointermove', (e) => {
    S.requestRender?.(300);                  // the 3D marker follows the hover
    const r = el.canvas.getBoundingClientRect();
    hoverD = Math.max(0, Math.min(total, ((e.clientX - r.left - 46) / (r.width - 56)) * total));
    draw();
  });
  el.canvas.addEventListener('pointerleave', () => { hoverD = null; draw(); });
  new ResizeObserver(() => draw()).observe(el.canvas);

  let lastTick = 0;
  return {
    show(on) { open = on; el.box.classList.toggle('hidden', !on); if (!on) marker.visible = false; else { samples = null; draw(); } },
    get open() { return open; },
    /** data changed (radio edit, shadow height, track) */
    redraw() { samples = null; draw(); },
    /** playback: redraw the drone dot ~8x per second */
    tick() { const now = performance.now(); if (open && now - lastTick > 120) { lastTick = now; draw(); } },
    setExag() { if (marker.visible) draw(); },
  };
}

function niceStep(x) {
  const p = 10 ** Math.floor(Math.log10(Math.max(x, 1e-9))), f = x / p;
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p;
}
