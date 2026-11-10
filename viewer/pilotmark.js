// fpv3d — the pilot on the 3D map (option C of the pilot marker review):
//   close: a small tripod with a patch antenna at the real antenna height, turned toward the drone
//   far:   a round radio badge on a thin mast, a fixed size on screen (crisp at any distance)
//   both:  a ground disc with a north tick; close up the antenna height is written next to it
//   faded: the location's own point while a live flight uses the real takeoff point (hollow, grey)
// Distance rings (500 m / 1 km / 2 km, dashed, lying on the terrain) are a separate object: createRangeRings().
// World frame as in app.js: X east, Z south, Y = height × exaggeration.

import { pxPerUnit as ppuOf } from './screen.js';

const SWITCH_M = 250;          // camera distance where the station gives way to the badge
const BADGE_PX = 46, STATION_PX = 90, DISC_PX = 22, LABEL_PX = 15;

function badgeTexture(THREE, faded) {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  g.globalAlpha = faded ? 0.6 : 1;
  g.fillStyle = 'rgba(7,9,12,0.85)'; g.beginPath(); g.arc(64, 64, 58, 0, 7); g.fill();
  g.lineWidth = 7; g.strokeStyle = faded ? '#a9b4c2' : '#ffd60a'; g.beginPath(); g.arc(64, 64, 55, 0, 7); g.stroke();
  // the radio you hold: body, two sticks, antenna with waves
  g.strokeStyle = '#f2f5f8'; g.fillStyle = '#f2f5f8'; g.lineWidth = 6; g.lineJoin = 'round'; g.lineCap = 'round';
  g.beginPath(); g.roundRect(26, 58, 76, 36, 10); g.stroke();
  for (const x of [46, 82]) { g.beginPath(); g.arc(x, 76, 6, 0, 7); g.fill(); }
  g.strokeStyle = faded ? '#a9b4c2' : '#ffd60a'; g.lineWidth = 7;
  g.beginPath(); g.moveTo(64, 58); g.lineTo(64, 30); g.stroke();
  g.lineWidth = 5; g.beginPath(); g.arc(64, 30, 11, -2.6, -0.55); g.stroke(); g.beginPath(); g.arc(64, 30, 20, -2.5, -0.65); g.stroke();
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

export function textSprite(THREE, text, { color = '#ffffff', w = 512 } = {}) {
  const c = document.createElement('canvas'); c.width = w; c.height = 64;
  const g = c.getContext('2d');
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  s.renderOrder = 12;
  s.userData.set = (txt) => {
    g.clearRect(0, 0, c.width, c.height);
    g.font = 'bold 30px ui-monospace, Consolas, monospace'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.lineWidth = 6; g.strokeStyle = 'rgba(0,0,0,0.75)'; g.strokeText(txt, w / 2, 34);
    g.fillStyle = color; g.fillText(txt, w / 2, 34);
    tex.needsUpdate = true;
  };
  s.userData.aspect = w / 64;
  s.userData.set(text);
  return s;
}

function stationModel(THREE) {
  const g = new THREE.Group();
  const dark = new THREE.MeshLambertMaterial({ color: 0x1b1f26 }), light = new THREE.MeshLambertMaterial({ color: 0xe8ecf0 });
  for (let k = 0; k < 3; k++) {                               // tripod legs, 1.8 m tall model
    const a = k * Math.PI * 2 / 3, leg = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.04, 1.75, 6), dark);
    leg.position.set(Math.cos(a) * 0.32, 0.8, Math.sin(a) * 0.32); leg.lookAt(0, 1.6, 0); leg.rotateX(Math.PI / 2); g.add(leg);
  }
  const head = new THREE.Group(); head.position.y = 1.8; g.add(head);
  const patch = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.36, 0.06), light); patch.position.z = -0.08; head.add(patch);
  const face = new THREE.Mesh(new THREE.PlaneGeometry(0.28, 0.28), new THREE.MeshBasicMaterial({ color: 0xffd60a, side: THREE.DoubleSide }));
  face.position.z = -0.115; head.add(face);
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.1, 0.12), dark); box.position.set(0, -0.12, 0.02); head.add(box);
  g.userData.head = head;
  return g;
}

function groundDisc(THREE, faded) {
  const g = new THREE.Group();
  // drawn over the terrain (a flat disc on a slope would be half buried), like the badge
  const m = new THREE.MeshBasicMaterial({ color: faded ? 0xa9b4c2 : 0xffd60a, transparent: true, opacity: faded ? 0.7 : 0.95,
    side: THREE.DoubleSide, depthWrite: false, depthTest: false });
  const r = new THREE.Mesh(new THREE.RingGeometry(1, 1.14, 64), m); r.rotation.x = -Math.PI / 2; g.add(r);
  if (!faded) {
    const fill = new THREE.Mesh(new THREE.CircleGeometry(1, 48), new THREE.MeshBasicMaterial({ color: 0x07090c, transparent: true, opacity: 0.35, depthWrite: false, depthTest: false }));
    fill.rotation.x = -Math.PI / 2; fill.position.y = -0.01; fill.renderOrder = 4; g.add(fill);
    r.renderOrder = 5;
    const n = new THREE.Mesh(new THREE.ConeGeometry(0.18, 0.4, 3), m);       // north = -Z
    n.rotation.x = -Math.PI / 2; n.position.set(0, 0, -1.35); n.renderOrder = 5; g.add(n);
  }
  g.renderOrder = 2;
  return g;
}

/** opts: THREE, scene3, camera, viewEl (for the on-screen size), faded */
export function createPilotMarker({ THREE, scene3, camera, viewEl, faded = false }) {
  const group = new THREE.Group();
  const badge = new THREE.Sprite(new THREE.SpriteMaterial({ map: badgeTexture(THREE, faded), depthTest: false, transparent: true }));
  badge.renderOrder = 10; group.add(badge);
  const mast = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 1, 0)]),
    new THREE.LineBasicMaterial({ color: faded ? 0xa9b4c2 : 0xffffff, transparent: true, opacity: 0.85 }));
  group.add(mast);
  const disc = groundDisc(THREE, faded); group.add(disc);
  const station = faded ? null : stationModel(THREE);
  if (station) group.add(station);
  const label = faded ? null : textSprite(THREE, 'antenna 1.8 m');
  if (label) group.add(label);
  scene3.add(group);
  const st = { antWorld: 1.8, antM: 1.8, target: null };
  const _v = new THREE.Vector3();
  const pxPerUnit = (d) => ppuOf(camera, viewEl, d);

  return {
    group,
    /** base: the ground under the pilot (world); antennaM: antenna height in metres; exag: vertical exaggeration */
    place(base, antennaM, exag = 1) {
      group.position.copy(base);
      st.antM = antennaM; st.antWorld = Math.max(0.3, antennaM * exag);
      if (label) label.userData.set(`antenna ${antennaM.toFixed(1)} m`);
    },
    /** every frame: target = where the antenna should point (the drone, world) or null */
    update(target) {
      if (!group.visible) return;
      const d = camera.position.distanceTo(group.position), ppu = pxPerUnit(d);
      const near = d < SWITCH_M && !!station;
      if (station) {
        station.visible = near;
        const sc = Math.max(st.antWorld / 1.8, STATION_PX / (1.8 * ppu));
        station.scale.setScalar(sc);
        if (near) {
          const head = station.userData.head;
          if (target) { head.lookAt(_v.copy(target)); head.rotateY(Math.PI); }
          else head.rotation.set(0, 0, 0);
        }
      }
      const top = near ? 1.8 * station.scale.x : Math.max(st.antWorld, 24 / ppu);
      const s = (BADGE_PX * (faded ? 0.8 : 1)) / ppu;
      badge.visible = !near; mast.visible = !near;
      badge.scale.setScalar(s); badge.position.y = top + s * 0.55;
      mast.scale.y = top;
      disc.scale.setScalar(Math.max(1.2, DISC_PX / ppu)); disc.position.y = 0.15;
      if (label) {
        label.visible = near;
        const hs = (LABEL_PX * 2.1) / ppu, w = hs * label.userData.aspect;     // canvas 64 px high, text ~half of it
        label.scale.set(w, hs, 1);
        label.position.set(w * 0.42, top * 0.5, 0);                            // to the right of the station
      }
    },
    setVisible(on) { group.visible = on; },
    get visible() { return group.visible; },
    dispose() { scene3.remove(group); },
  };
}

/** dashed distance rings on the terrain around a point. heightAt(x, y) local -> world Y; toWorld(x, y, z) */
export function createRangeRings({ THREE, scene3, camera, viewEl, toWorld, groundWorldY, radii = [500, 1000, 2000] }) {
  const group = new THREE.Group();
  const lines = [], labels = [];
  for (const r of radii) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(161 * 3), 3));
    const l = new THREE.Line(g, new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: r / 25, gapSize: r / 40, transparent: true, opacity: 0.55, depthWrite: false }));
    l.renderOrder = 3; group.add(l); lines.push(l);
    const t = textSprite(THREE, r >= 1000 ? `${r / 1000} km` : `${r} m`, { w: 256 });
    group.add(t); labels.push(t);
  }
  scene3.add(group);
  const _w = new THREE.Vector3();
  const pxPerUnit = (d) => ppuOf(camera, viewEl, d);
  return {
    group,
    /** centre (local x, y metres); the rings follow the ground (a little above it so they stay visible) */
    setCenter(cx, cy) {
      radii.forEach((r, k) => {
        const a = lines[k].geometry.attributes.position;
        for (let i = 0; i <= 160; i++) {
          const ang = (i / 160) * Math.PI * 2, x = cx + r * Math.cos(ang), y = cy + r * Math.sin(ang);
          toWorld(x, y, 0, _w); _w.y = groundWorldY(x, y) + 2;
          a.setXYZ(i, _w.x, _w.y, _w.z);
        }
        a.needsUpdate = true; lines[k].geometry.computeBoundingSphere(); lines[k].computeLineDistances();
        toWorld(cx, cy + r, 0, _w); _w.y = groundWorldY(cx, cy + r) + 6;     // label on the north side
        labels[k].position.copy(_w);
      });
    },
    update() {
      if (!group.visible) return;
      for (const t of labels) {
        const ppu = pxPerUnit(camera.position.distanceTo(t.position)), hs = (LABEL_PX * 2.1) / ppu;
        t.scale.set(hs * t.userData.aspect, hs, 1);
      }
    },
    setVisible(on) { group.visible = on; },
  };
}
