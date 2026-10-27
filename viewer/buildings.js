// fpv3d — 3D buildings: OpenStreetMap footprints extruded from the bare ground to the roof height
// measured on swissSURFACE3D (see fpv3d/buildings.py). Drawn in real metres; the group is scaled
// vertically with the exaggeration slider.
import * as THREE from 'three';

const WALL = new THREE.Color(0xe4dfd3), ROOF = new THREE.Color(0xa8604c), ROOF_FLAT = new THREE.Color(0x8d8f94);

export async function loadBuildings({ S, scene3 }) {
  const m = S.meta.buildings;
  if (!m?.file) return null;
  const data = await (await fetch(S.base + m.file, { cache: 'no-cache' })).json();
  const items = data.items || [];
  const pos = [], col = [], owner = [];
  const v2 = (x, y) => new THREE.Vector2(x - S.W / 2, -(y - S.H / 2));     // world X, Z
  items.forEach((b, bi) => {
    const pts = b.p.map(([x, y]) => v2(x, y));
    if (pts.length < 3) return;
    const y0 = b.b - S.hBase - 0.5, y1 = b.t - S.hBase;      // base sunk 0.5 m to hide terrain gaps
    const flat = /^(industrial|commercial|retail|warehouse|garage|garages|school|hospital|office|supermarket)$/.test(b.k);
    // walls
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], c = pts[(i + 1) % pts.length];
      pos.push(a.x, y0, a.y, c.x, y0, c.y, c.x, y1, c.y, a.x, y0, a.y, c.x, y1, c.y, a.x, y1, a.y);
      for (let k = 0; k < 6; k++) { col.push(WALL.r, WALL.g, WALL.b); owner.push(bi); }
    }
    // roof
    let tris;
    try { tris = THREE.ShapeUtils.triangulateShape(pts, []); } catch { tris = []; }
    const rc = flat ? ROOF_FLAT : ROOF;
    for (const t of tris) for (const j of t) {
      pos.push(pts[j].x, y1, pts[j].y); col.push(rc.r, rc.g, rc.b); owner.push(bi);
    }
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  geo.computeVertexNormals();
  const mat = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide });
  const mesh = new THREE.Mesh(geo, mat);
  const group = new THREE.Group(); group.add(mesh); group.scale.y = S.exag;
  const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(-0.5, 0.8, 0.35);
  group.add(sun);
  scene3.add(group);
  const own = Int32Array.from(owner);
  return {
    group, items, count: items.length,
    set({ visible, exag }) { if (visible != null) group.visible = visible; if (exag != null) group.scale.y = exag; },
    /** building under a ray, or null */
    pick(ray) {
      if (!group.visible) return null;
      const hit = new THREE.Raycaster(ray.origin, ray.direction).intersectObject(mesh, false)[0];
      if (!hit) return null;
      return { item: items[own[hit.face.a]], point: hit.point };
    },
  };
}
