// fpv3d — how the drone is drawn in the 3D view (replay, live flight, training flight chase view, compare ghost).
//
//   close: a small 3D quad (X frame, spinning prop discs, yellow nose) that turns with the flight, banks in turns
//          and tilts when it speeds up; a ring around it in the signal colour
//   far:   Alpline's drone badge, always facing you at a fixed size on screen, with a yellow chevron for the heading
//   both:  a dashed drop line and a shadow straight down to the ground, labelled with the height above ground,
//          and (replay) a short fading tail of the last seconds
//
//   const m = createDroneMarker({ THREE, scene3, camera, viewEl });
//   m.group.position.copy(worldPos);            (S.drone = m.group: everything else keeps using its position)
//   m.update({ vel, acc, color, groundY, agl, tail, attitude, now })   every frame it is drawn
//   m.style({ ghost, faded, ping })             ghost = see-through compare drone, faded = estimated position
const SWITCH_M = 250;          // camera distance (m) where the quad becomes the badge
const QUAD_PX = 56;            // the quad is drawn at least this wide on screen
const BADGE_PX = 42;           // badge size on screen

export function createDroneMarker({ THREE, scene3, camera, viewEl, ghost = false }) {
  const group = new THREE.Group();
  const op = ghost ? 0.45 : 1;
  const mats = [];
  const mat = (m) => { m.transparent = true; m.opacity = (m.opacity ?? 1) * op; m.userData.base = m.opacity; mats.push(m); return m; };

  // ---- the quad (unit: 1 = about 1 m wide, scaled to its on-screen size)
  const quad = new THREE.Group();
  const dark = mat(new THREE.MeshLambertMaterial({ color: ghost ? 0xe8ecf0 : 0x1b1f26 }));
  const light = mat(new THREE.MeshLambertMaterial({ color: 0xe8ecf0 }));
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.13, 0.6), dark); quad.add(body);
  const nose = new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.11, 0.13), mat(new THREE.MeshBasicMaterial({ color: 0xffd60a })));
  nose.position.set(0, 0.02, -0.36); quad.add(nose);
  const discs = [];
  for (const [sx, sz] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.05, 0.8), dark);
    arm.position.set(sx * 0.23, 0, sz * 0.23); arm.rotation.y = sx * sz > 0 ? Math.PI / 4 : -Math.PI / 4; quad.add(arm);
    const disc = new THREE.Mesh(new THREE.CircleGeometry(0.23, 24), mat(new THREE.MeshBasicMaterial({ color: 0xffffff, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false })));
    disc.rotation.x = -Math.PI / 2; disc.position.set(sx * 0.47, 0.06, sz * 0.47); quad.add(disc); discs.push(disc);
    const mot = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.08, 10), light); mot.position.set(sx * 0.47, 0.02, sz * 0.47); quad.add(mot);
  }
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.95, 1.08, 48), mat(new THREE.MeshBasicMaterial({ color: 0x3ddc84, side: THREE.DoubleSide, depthWrite: false })));
  ring.rotation.x = -Math.PI / 2; quad.add(ring);
  group.add(quad);

  // ---- the badge (drawn once per colour)
  const badges = new Map();
  const badgeTex = (css) => {
    if (badges.has(css)) return badges.get(css);
    const c = document.createElement('canvas'); c.width = c.height = 128;
    const g = c.getContext('2d');
    g.fillStyle = 'rgba(7,9,12,0.85)'; g.beginPath(); g.arc(64, 64, 58, 0, 7); g.fill();
    g.lineWidth = 7; g.strokeStyle = css; g.beginPath(); g.arc(64, 64, 55, 0, 7); g.stroke();
    g.strokeStyle = '#f2f5f8'; g.lineWidth = 4; g.lineCap = 'round';                 // the drone icon from above
    g.beginPath(); g.moveTo(38, 38); g.lineTo(90, 90); g.moveTo(90, 38); g.lineTo(38, 90); g.stroke();
    for (const [x, y] of [[38, 38], [90, 38], [38, 90], [90, 90]]) { g.beginPath(); g.arc(x, y, 11, 0, 7); g.lineWidth = 3; g.stroke(); }
    g.strokeStyle = '#ffd60a'; g.lineWidth = 6;
    g.beginPath(); g.moveTo(53, 62); g.lineTo(64, 51); g.lineTo(75, 62); g.stroke();
    g.beginPath(); g.moveTo(64, 53); g.lineTo(64, 80); g.stroke();
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
    badges.set(css, t); return t;
  };
  const badge = new THREE.Sprite(mat(new THREE.SpriteMaterial({ map: badgeTex('#3ddc84'), depthTest: false })));
  badge.renderOrder = 10; group.add(badge);
  const chev = new THREE.Mesh(new THREE.ConeGeometry(0.5, 1.1, 3), mat(new THREE.MeshBasicMaterial({ color: 0xffd60a, depthTest: false })));
  chev.renderOrder = 11; group.add(chev);

  // ---- drop line, shadow, height label, tail
  const dropGeo = new THREE.BufferGeometry(); dropGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
  const drop = new THREE.Line(dropGeo, mat(new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 2, gapSize: 1.4, opacity: 0.8 })));
  drop.frustumCulled = false; scene3.add(drop);
  const shadow = new THREE.Mesh(new THREE.CircleGeometry(1, 24), mat(new THREE.MeshBasicMaterial({ color: 0x000000, opacity: 0.35, depthWrite: false })));
  shadow.rotation.x = -Math.PI / 2; scene3.add(shadow);
  const TAIL = 64;
  const tailGeo = new THREE.BufferGeometry();
  tailGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(TAIL * 3), 3));
  const tc = new Float32Array(TAIL * 4); for (let i = 0; i < TAIL; i++) tc.set([1, 0.84, 0.04, (i / TAIL) * 0.9], i * 4);
  tailGeo.setAttribute('color', new THREE.BufferAttribute(tc, 4)); tailGeo.setDrawRange(0, 0);
  const tail = new THREE.Line(tailGeo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false }));
  tail.frustumCulled = false; scene3.add(tail);
  let label = null;
  if (viewEl && !ghost) {
    label = document.createElement('div'); label.className = 'droneAgl'; viewEl.appendChild(label);
  }
  scene3.add(group);

  const _q = new THREE.Quaternion(), _e = new THREE.Euler(), _v = new THREE.Vector3(), _c = new THREE.Color();
  let visible = true, faded = false;
  const setOpacity = (k) => mats.forEach((m) => { m.opacity = m.userData.base * k; });

  return {
    group,
    /** vel / acc: world units per s (m/s; Y up). color: THREE.Color or hex of the signal state. groundY: world Y of the
     *  ground under it. agl: metres for the label. tail: [Vector3] oldest first (optional). attitude: Quaternion
     *  (training flight: the real attitude instead of guessing it from the track). */
    update({ vel, acc, color, css, groundY, agl, tail: pts, attitude, now = performance.now() }) {
      const show = visible && group.visible;
      drop.visible = shadow.visible = show && groundY != null;
      if (label) label.style.display = show && groundY != null && agl != null ? '' : 'none';
      tail.visible = show && !!pts?.length;
      if (!show) return;
      const p = group.position, camD = camera.position.distanceTo(p);
      const pxPerUnit = viewEl ? viewEl.clientHeight / (2 * Math.max(camD, 0.01) * Math.tan(camera.fov * Math.PI / 360)) : 1;
      const far = camD > SWITCH_M;
      quad.visible = !far; badge.visible = chev.visible = far;
      if (color != null) { _c.set(color); ring.material.color.copy(_c); }
      // heading from the velocity, bank from turning, nose down when speeding up
      let yaw = quad.userData.yaw ?? 0;
      if (vel && Math.hypot(vel.x, vel.z) > 0.8) yaw = Math.atan2(-vel.x, -vel.z);
      quad.userData.yaw = yaw;
      if (attitude) quad.quaternion.copy(attitude);
      else {
        let bank = 0, pitch = 0;
        if (vel && acc) {
          const h2 = Math.max(vel.x * vel.x + vel.z * vel.z, 1);
          const turn = (vel.x * acc.z - vel.z * acc.x) / h2;                    // rad/s, + = turning right
          bank = Math.max(-0.9, Math.min(0.9, -Math.atan(turn * Math.sqrt(h2) / 9.81)));
          const along = (acc.x * vel.x + acc.z * vel.z) / Math.sqrt(h2);
          pitch = Math.max(-0.7, Math.min(0.3, -0.12 - Math.atan(along / 9.81)));
        }
        quad.quaternion.setFromEuler(_e.set(pitch, yaw, bank, 'YXZ'));
      }
      quad.scale.setScalar(Math.max(0.3, QUAD_PX / pxPerUnit));                 // never smaller than QUAD_PX on screen
      discs.forEach((d, i) => { d.material.opacity = d.material.userData.base * (faded ? 0.5 : 1) * (0.7 + 0.3 * Math.sin(now / 16 + i)); });
      if (far) {
        const s = BADGE_PX / pxPerUnit;
        if (css) badge.material.map = badgeTex(css);
        badge.scale.setScalar(s);
        chev.scale.setScalar(s * 0.26);
        chev.position.set(-Math.sin(yaw) * s * 0.64, 0, -Math.cos(yaw) * s * 0.64);
        chev.quaternion.setFromEuler(_e.set(-Math.PI / 2, yaw, 0, 'YXZ'));
      }
      if (groundY != null) {
        const a = dropGeo.attributes.position;
        a.setXYZ(0, p.x, p.y, p.z); a.setXYZ(1, p.x, groundY, p.z); a.needsUpdate = true;
        const dash = Math.max(1, camD / 60);
        drop.material.dashSize = dash; drop.material.gapSize = dash * 0.7; drop.computeLineDistances();
        shadow.position.set(p.x, groundY + Math.max(0.2, camD / 2000), p.z);
        shadow.scale.setScalar(Math.max(0.6, 10 / pxPerUnit));
        if (label && agl != null) {
          // on the drop line, a little below the drone (half way down when the line is short on screen)
          const W = viewEl.clientWidth, H = viewEl.clientHeight;
          _v.copy(p).project(camera);
          const dx = (_v.x * 0.5 + 0.5) * W, dy = (-_v.y * 0.5 + 0.5) * H, front = _v.z < 1;
          _v.set(p.x, groundY, p.z).project(camera);
          const gx = (_v.x * 0.5 + 0.5) * W, gy = (-_v.y * 0.5 + 0.5) * H;
          const len = Math.hypot(gx - dx, gy - dy), k = len > 0 ? Math.min(0.5, 70 / len) : 0;
          const lx = dx + (gx - dx) * k, ly = dy + (gy - dy) * k;
          const onScreen = front && len > 24 && lx > -20 && lx < W && ly > -20 && ly < H;
          label.style.display = onScreen ? '' : 'none';
          label.textContent = `${Math.round(agl)} m`;
          label.style.transform = `translate(${lx + 6}px, ${ly - 8}px)`;
        }
      }
      if (pts?.length) {
        const a = tailGeo.attributes.position, n = Math.min(pts.length, TAIL), off = TAIL - n;
        for (let i = 0; i < n; i++) { const q = pts[pts.length - n + i]; a.setXYZ(i, q.x, q.y, q.z); }
        a.needsUpdate = true;
        // the colours fade from the oldest point: shift them so the newest is the brightest
        const c = tailGeo.attributes.color;
        for (let i = 0; i < n; i++) c.setW(i, ((i + off) / TAIL) * 0.9);
        c.needsUpdate = true;
        tailGeo.setDrawRange(0, n);
      }
    },
    /** ghost: see-through; faded: an estimated position (live flight between GPS fixes) */
    style({ faded: f } = {}) { if (f != null && f !== faded) { faded = f; setOpacity(f ? 0.55 : 1); } },
    setVisible(on) {
      visible = on; group.visible = on;
      if (!on) { drop.visible = shadow.visible = tail.visible = false; if (label) label.style.display = 'none'; }
    },
    get visible() { return visible && group.visible; },
    dispose() {
      scene3.remove(group, drop, shadow, tail);
      label?.remove();
    },
  };
}
