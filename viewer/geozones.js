// fpv3d — Swiss drone geozones (FOCA / BAZL "Geographical UAS zones").
// Drawn as a hatched overlay on the terrain plus translucent walls showing each zone's
// vertical extent; also answers "which zones is this point in?" for the HUD, the track
// colouring, the comparison table and the simulator OSD.
// INFORMATIVE ONLY - always check the official map / app before flying.
import * as THREE from 'three';

export const RESTRICTIONS = {
  PROHIBITED: { color: '#ff3b30', label: 'Prohibited', sev: 3 },
  REQ_AUTHORISATION: { color: '#ff9500', label: 'Authorisation required', sev: 2 },
  CONDITIONAL: { color: '#ffd60a', label: 'Conditional', sev: 1 },
  NO_RESTRICTION: { color: '#4fc3f7', label: 'Information', sev: 0 },
};
export const restrictionInfo = (r) => RESTRICTIONS[r] || { color: '#4fc3f7', label: r ? r.toLowerCase().replace(/_/g, ' ') : 'zone', sev: 0 };

const WALL_CAP = 300;   // m: "unlimited" upper limits are drawn this high above the lower limit

export function isActive(z, now = new Date()) {
  if (z.permanent) return true;
  const s = z.start ? new Date(z.start) : null, e = z.end ? new Date(z.end) : null;
  if (s && !isNaN(s) && now < s) return false;
  if (e && !isNaN(e) && now > e) return false;
  return true;
}

export function fmtLimits(z) {
  const f = (v, ref) => (v == null ? '?' : v >= 9000 ? 'unlimited' : `${Math.round(v)} m ${ref === 'AMSL' ? 'AMSL' : 'above ground'}`);
  if ((z.lower ?? 0) <= 0 && z.lower_ref !== 'AMSL') return `ground → ${f(z.upper, z.upper_ref)}`;
  return `${f(z.lower, z.lower_ref)} → ${f(z.upper, z.upper_ref)}`;
}

function inRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export async function loadZones({ S, scene3, toWorld, demHeight }) {
  const m = S.meta.geozones;
  if (!m) return null;
  const data = await (await fetch(S.base + m.file, { cache: 'no-store' })).json();
  const zones = data.zones.map((z, i) => {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9, cx = 0, cy = 0, n = 0;
    for (const poly of z.polygons) for (const [x, y] of poly[0]) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); cx += x; cy += y; n++; }
    return { ...z, idx: i, bbox: [x0, y0, x1, y1], centroid: [cx / n, cy / n], info: restrictionInfo(z.restriction) };
  });
  const st = { showInactive: false, overlay: true, walls: true };
  const visibleZone = (z) => st.showInactive || isActive(z);

  // ------------------------------------------------------------ hatched overlay texture
  const scale = Math.min(2048 / Math.max(S.W, S.H), 2);          // px per metre
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(S.W * scale); canvas.height = Math.ceil(S.H * scale);
  const tex = new THREE.CanvasTexture(canvas);
  function drawOverlay() {
    const g = canvas.getContext('2d');
    g.clearRect(0, 0, canvas.width, canvas.height);
    const sorted = zones.filter(visibleZone).sort((a, b) => a.info.sev - b.info.sev);   // worst on top
    for (const z of sorted) {
      const active = isActive(z);
      g.beginPath();
      for (const poly of z.polygons) for (const ring of poly) {
        ring.forEach(([x, y], k) => (k ? g.lineTo : g.moveTo).call(g, x * scale, (S.H - y) * scale));
        g.closePath();
      }
      g.globalAlpha = active ? 0.55 : 0.25; g.fillStyle = z.info.color; g.fill('evenodd');
      g.globalAlpha = 1; g.lineWidth = Math.max(2, 3 * scale); g.strokeStyle = z.info.color;
      g.setLineDash(active ? [] : [10, 8]); g.stroke(); g.setLineDash([]);
    }
    tex.needsUpdate = true;
  }

  // ------------------------------------------------------------ vertical extent: walls along the borders
  const group = new THREE.Group(); scene3.add(group);
  function limits(z, x, y) {
    const gnd = demHeight(x, y);
    const lo = z.lower_ref === 'AMSL' ? Math.max(z.lower ?? 0, gnd) : gnd + (z.lower ?? 0);
    let hi = z.upper == null || z.upper >= 9000 ? lo + WALL_CAP : (z.upper_ref === 'AMSL' ? z.upper : gnd + z.upper);
    hi = Math.max(hi, lo + 1);
    return [lo, Math.min(hi, lo + 3000), gnd];
  }
  function buildWalls() {
    group.children.slice().forEach((o) => { group.remove(o); o.geometry.dispose(); });
    const step = Math.max(S.meta.grid.res * 2, 10), v = new THREE.Vector3();
    for (const z of zones) {
      if (!visibleZone(z)) continue;
      const pos = [], idx = [], top = [];
      for (const poly of z.polygons) for (const ring of poly) {
        let prev = -1;
        for (let k = 0; k < ring.length - 1; k++) {
          const [ax, ay] = ring[k], [bx, by] = ring[k + 1], len = Math.hypot(bx - ax, by - ay), n = Math.max(1, Math.ceil(len / step));
          for (let i = 0; i <= n; i++) {
            if (i === n && k < ring.length - 2) continue;              // shared vertex with next edge
            const x = ax + (bx - ax) * (i / n), y = ay + (by - ay) * (i / n);
            if (x < 0 || y < 0 || x > S.W || y > S.H) { prev = -1; continue; }   // outside the map
            const [lo, hi] = limits(z, x, y), b = pos.length / 3;
            toWorld(x, y, lo, v); pos.push(v.x, v.y, v.z);
            toWorld(x, y, hi, v); pos.push(v.x, v.y, v.z);
            if (prev >= 0) { idx.push(prev, prev + 1, b, b, prev + 1, b + 1); top.push(prev + 1, b + 1); }
            prev = b;
          }
        }
      }
      if (!idx.length) continue;
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx);
      const active = isActive(z), col = new THREE.Color(z.info.color);
      const wall = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: active ? 0.22 : 0.1, side: THREE.DoubleSide, depthWrite: false }));
      const lg = new THREE.BufferGeometry(); lg.setAttribute('position', g.getAttribute('position')); lg.setIndex(top);
      const edge = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: active ? 0.9 : 0.4 }));
      wall.renderOrder = edge.renderOrder = 6;
      group.add(wall, edge);
    }
    group.visible = st.walls;
  }

  // ------------------------------------------------------------ queries
  /** zones containing (x, y); with z (AMSL) also tells whether the point is inside the vertical band */
  function zonesAt(x, y, z = null, { includeInactive = st.showInactive } = {}) {
    const hits = [];
    for (const zn of zones) {
      if (!includeInactive && !isActive(zn)) continue;
      const [x0, y0, x1, y1] = zn.bbox;
      if (x < x0 || x > x1 || y < y0 || y > y1) continue;
      const inside = zn.polygons.some((poly) => inRing(x, y, poly[0]) && !poly.slice(1).some((h) => inRing(x, y, h)));
      if (!inside) continue;
      let inBand = true;
      if (z != null) { const [lo, hi] = limits(zn, x, y); inBand = z >= lo - 0.5 && z <= (zn.upper >= 9000 ? Infinity : hi); }
      hits.push({ zone: zn, inBand });
    }
    return hits.sort((a, b) => b.zone.info.sev - a.zone.info.sev);
  }

  drawOverlay(); buildWalls();
  return {
    zones, meta: data, texture: tex, group, zonesAt,
    set(o) {
      Object.assign(st, o);
      if ('showInactive' in o) { drawOverlay(); buildWalls(); }
      group.visible = st.walls;
    },
    rebuild: buildWalls,          // after a vertical-exaggeration change
    state: st,
  };
}
