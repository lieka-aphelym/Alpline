// fpv3d — 3D blind-spot volumes.
//
// The build stores, for every map column, the height above ground below which the drone is
//   los     : out of direct line of sight
//   fresnel : Fresnel zone obstructed
//   loss    : predicted link margin < 0 (incl. diffraction)
// Each layer is drawn as a translucent "lid" at ground + ceiling. Where the ceiling drops to 0
// the lid meets the terrain, so the lid plus the ground enclose the blind volume.
import * as THREE from 'three';

const LAYERS = {
  los: { color: 0x5b4bd6, label: 'No line of sight' },
  fresnel: { color: 0xffb000, label: 'Fresnel zone obstructed' },
  loss: { color: 0xff2d55, label: 'Predicted signal loss' },
};

const VS = /* glsl */`
  #include <common>
  #include <logdepthbuf_pars_vertex>
  attribute float aGround; attribute float aCeil;
  uniform float uExag, uCap;
  varying float vCeil; varying float vCapped; varying vec3 vPos;
  void main() {
    float c = min(aCeil, uCap);
    vCeil = aCeil; vCapped = aCeil >= uCap ? 1.0 : 0.0;
    vec3 p = vec3(position.x, (aGround + c) * uExag, position.z);
    vPos = p;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
    #include <logdepthbuf_vertex>
  }`;
const FS = /* glsl */`
  #include <logdepthbuf_pars_fragment>
  uniform vec3 uColor; uniform float uOpacity;
  varying float vCeil; varying float vCapped; varying vec3 vPos;
  void main() {
    #include <logdepthbuf_fragment>
    if (vCeil < 1.0) discard;                      // no blind volume in this column
    vec3 n = normalize(cross(dFdx(vPos), dFdy(vPos)));
    float shade = 0.55 + 0.45 * abs(n.y);          // walls darker than the lid -> reads as a volume
    float a = uOpacity * (vCapped > 0.5 ? 0.55 : 1.0);
    // thin contour lines every 20 m of ceiling height help judge depth
    float h = mod(min(vCeil, 1e4), 25.0);
    float line = 1.0 - smoothstep(0.0, 1.0, min(h, 25.0 - h));
    gl_FragColor = vec4(uColor * shade + line * 0.12, a);
  }`;

export async function loadVolumes({ scene3, S, demHeight }) {
  const m = S.meta.shadow3d;
  if (!m) return null;
  const buf = await (await fetch(S.base + m.file)).arrayBuffer();
  const raw = new Uint16Array(buf), N = m.rows * m.cols;
  // shared grid: cell centres, ground height at each cell
  const pos = new Float32Array(N * 3), ground = new Float32Array(N);
  for (let r = 0, k = 0; r < m.rows; r++) for (let c = 0; c < m.cols; c++, k++) {
    const x = (c + 0.5) * m.res, y = S.H - (r + 0.5) * m.res;
    pos[k * 3] = x - S.W / 2; pos[k * 3 + 2] = -(y - S.H / 2);
    ground[k] = demHeight(x, y) - S.hBase;
  }
  const idx = new Uint32Array((m.rows - 1) * (m.cols - 1) * 6);
  for (let r = 0, k = 0; r < m.rows - 1; r++) for (let c = 0; c < m.cols - 1; c++) {
    const a = r * m.cols + c, b = a + 1, d = a + m.cols, e = d + 1;
    idx[k++] = a; idx[k++] = d; idx[k++] = b; idx[k++] = b; idx[k++] = d; idx[k++] = e;
  }
  const posAttr = new THREE.BufferAttribute(pos, 3), gAttr = new THREE.BufferAttribute(ground, 1), iAttr = new THREE.BufferAttribute(idx, 1);
  const group = new THREE.Group(); group.visible = false; scene3.add(group);
  const meshes = {}, ceils = {}, lossByOffset = [];
  m.layers.forEach((name, li) => {
    const ceil = new Float32Array(N);
    for (let k = 0; k < N; k++) { const v = raw[li * N + k]; ceil[k] = v === m.inf ? 1e5 : v * m.scale; }
    ceils[name] = ceil;
    const mo = /^loss([+-][\d.]+)?$/.exec(name);
    if (mo) lossByOffset.push({ d: mo[1] ? +mo[1] : 0, ceil });
  });
  lossByOffset.sort((a, b) => a.d - b.d);
  // the displayed "loss" layer is interpolated between the precomputed budget offsets
  const lossNow = new Float32Array(ceils.loss || N);
  function interpLoss(delta) {
    if (lossByOffset.length < 2) return { delta: 0, exact: !delta };
    const lo0 = lossByOffset[0].d, hi0 = lossByOffset.at(-1).d, d = Math.min(Math.max(delta, lo0), hi0);
    let j = 0; while (j < lossByOffset.length - 2 && lossByOffset[j + 1].d < d) j++;
    const a = lossByOffset[j], b = lossByOffset[j + 1], t = (d - a.d) / (b.d - a.d);
    for (let k = 0; k < N; k++) {
      const va = a.ceil[k], vb = b.ceil[k];
      lossNow[k] = va >= 1e5 || vb >= 1e5 ? (t < 0.5 ? va : vb) : va + (vb - va) * t;
    }
    return { delta: d, exact: d === delta };
  }

  for (const name of ['los', 'fresnel', 'loss']) {
    if (!ceils[name]) continue;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', posAttr); g.setAttribute('aGround', gAttr);
    g.setAttribute('aCeil', new THREE.BufferAttribute(name === 'loss' ? lossNow : ceils[name], 1)); g.setIndex(iAttr);
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), Math.hypot(S.W, S.H));
    const mat = new THREE.ShaderMaterial({
      vertexShader: VS, fragmentShader: FS, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      uniforms: { uExag: { value: S.exag }, uCap: { value: 150 }, uColor: { value: new THREE.Color(LAYERS[name]?.color ?? 0xffffff) }, uOpacity: { value: 0.45 } },
    });
    const mesh = new THREE.Mesh(g, mat);
    mesh.renderOrder = { loss: 3, los: 4, fresnel: 5 }[name] ?? 5;   // inner volumes first
    group.add(mesh); meshes[name] = mesh;
  }

  // 2D shadow for any height above ground, built from the same ceilings (matches the volumes)
  const tex2d = new THREE.DataTexture(new Uint8Array(N * 4), m.cols, m.rows, THREE.RGBAFormat);
  tex2d.magFilter = THREE.NearestFilter;
  function overlay(agl) {
    const px = tex2d.image.data, L = ceils.los, F = ceils.fresnel;
    for (let r = 0; r < m.rows; r++) {
      const dst = (m.rows - 1 - r) * m.cols;                // texture row 0 = south
      for (let c = 0; c < m.cols; c++) {
        const k = r * m.cols + c, o = (dst + c) * 4;
        const blocked = L[k] > agl, fres = !blocked && F[k] > agl, lost = lossNow[k] > agl;
        let rgba = [0, 0, 0, 0];
        if (fres) rgba = lost ? [255, 120, 0, 150] : [255, 176, 0, 110];
        if (blocked) rgba = lost ? [5, 5, 12, 225] : [40, 30, 90, 175];
        px[o] = rgba[0]; px[o + 1] = rgba[1]; px[o + 2] = rgba[2]; px[o + 3] = rgba[3];
      }
    }
    tex2d.needsUpdate = true;
    return tex2d;
  }

  return {
    group, meshes, layers: LAYERS, live: lossByOffset.length > 1, offsets: lossByOffset.map((o) => o.d), link: m.link,
    /** follow a change of the link budget (dB) - returns the delta actually applied (clamped to the precomputed range) */
    setLossDelta(delta) {
      const r = interpLoss(delta);
      if (meshes.loss) meshes.loss.geometry.attributes.aCeil.needsUpdate = true;
      return r;
    },
    overlay,
    /** blind height above ground (m) at a local point: 'los' | 'fresnel' | 'loss' (follows radio edits); 1e5 = whole column */
    ceilAt(name, x, y) {
      const c = Math.floor(x / m.res), r = Math.floor((S.H - y) / m.res);
      if (c < 0 || r < 0 || c >= m.cols || r >= m.rows) return null;
      const arr = name === 'loss' ? lossNow : ceils[name];
      return arr ? arr[r * m.cols + c] : null;
    },
    set({ visible, show = {}, cap, opacity, exag }) {
      if (visible != null) group.visible = visible;
      for (const [n, mesh] of Object.entries(meshes)) {
        if (show[n] != null) mesh.visible = show[n];
        const u = mesh.material.uniforms;
        if (cap != null) u.uCap.value = cap;
        if (opacity != null) u.uOpacity.value = opacity;
        if (exag != null) u.uExag.value = exag;
      }
    },
  };
}
