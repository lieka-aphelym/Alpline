// fpv3d — route corridors (same rules as fpv3d/corridor.py): a strip of `w` metres each side of a
// polyline. Coordinates are LV95 [e, n] metres.
export const TILE = 1000;

export function segDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1e-9;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}
export function routeDist(pts, x, y) {
  let d = Infinity;
  for (let i = 0; i < pts.length - 1; i++) d = Math.min(d, segDist(x, y, ...pts[i], ...pts[i + 1]));
  return d;
}
export const routeLength = (pts) => pts.slice(1).reduce((s, p, i) => s + Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]), 0);
export const stripArea = (pts, w) => (routeLength(pts) * 2 * w + Math.PI * w * w) / 1e6;   // km², bends ignored

function rectDist(pts, x0, y0, x1, y1) {
  let best = Infinity;
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1], n = Math.max(2, Math.floor(Math.hypot(bx - ax, by - ay) / 25) + 1);
    for (let k = 0; k < n; k++) {
      const t = k / (n - 1), px = ax + (bx - ax) * t, py = ay + (by - ay) * t;
      const dx = Math.max(x0 - px, 0, px - x1), dy = Math.max(y0 - py, 0, py - y1);
      best = Math.min(best, Math.hypot(dx, dy));
    }
  }
  return best;
}
function bbox(pts, w) {
  const es = pts.map((p) => p[0]), ns = pts.map((p) => p[1]);
  return [Math.min(...es) - w, Math.min(...ns) - w, Math.max(...es) + w, Math.max(...ns) + w];
}
/** 1 km tiles the strip touches: ["E-N", ...] */
export function stripTiles(pts, w) {
  if (pts.length < 2) return [];
  const [e0, n0, e1, n1] = bbox(pts, w), out = [];
  for (let ke = Math.floor(e0 / TILE); ke < Math.ceil(e1 / TILE); ke++)
    for (let kn = Math.floor(n0 / TILE); kn < Math.ceil(n1 / TILE); kn++)
      if (rectDist(pts, ke * TILE, kn * TILE, (ke + 1) * TILE, (kn + 1) * TILE) <= w) out.push(`${ke}-${kn}`);
  return out;
}
function hull(points) {
  const p = [...new Map(points.map((q) => [`${q[0]},${q[1]}`, q])).values()].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p;
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const q of p) { while (lo.length >= 2 && cross(lo.at(-2), lo.at(-1), q) <= 0) lo.pop(); lo.push(q); }
  for (const q of [...p].reverse()) { while (up.length >= 2 && cross(up.at(-2), up.at(-1), q) <= 0) up.pop(); up.push(q); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}
function inside(poly, x, y) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi) c = !c;
  }
  return c;
}
/** coarse 'context' tiles between the pilot and the route (bare ground at 10 m, for signal paths) */
export function contextTiles(pts, w, pilot) {
  if (pts.length < 2) return [];
  const h = hull(pilot ? [...pts, pilot] : pts), ring = h.length >= 3 ? [...h, h[0]] : h;
  const [e0, n0, e1, n1] = bbox(ring, w), out = [];
  for (let ke = Math.floor(e0 / TILE); ke < Math.ceil(e1 / TILE); ke++)
    for (let kn = Math.floor(n0 / TILE); kn < Math.ceil(n1 / TILE); kn++) {
      const cx = (ke + 0.5) * TILE, cy = (kn + 0.5) * TILE;
      if ((h.length >= 3 && inside(h, cx, cy)) || rectDist(ring, ke * TILE, kn * TILE, (ke + 1) * TILE, (kn + 1) * TILE) <= w) out.push(`${ke}-${kn}`);
    }
  return out;
}
/** outline of the strip for drawing: one quad per segment + a circle polygon per vertex */
export function stripShapes(pts, w, nCircle = 20) {
  const shapes = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1], L = Math.hypot(bx - ax, by - ay) || 1;
    const nx = (-(by - ay) / L) * w, ny = ((bx - ax) / L) * w;
    shapes.push([[ax + nx, ay + ny], [bx + nx, by + ny], [bx - nx, by - ny], [ax - nx, ay - ny]]);
  }
  for (const [x, y] of pts) shapes.push(Array.from({ length: nCircle }, (_, k) => [x + w * Math.cos((k / nCircle) * 2 * Math.PI), y + w * Math.sin((k / nCircle) * 2 * Math.PI)]));
  return shapes;
}
/** cells of the box around route + pilot at `res` (memory warning) */
export function boxCells(pts, w, pilot, res) {
  const [e0, n0, e1, n1] = bbox(pilot ? [...pts, pilot] : pts, w);
  return ((e1 - e0) / res) * ((n1 - n0) / res);
}
