// The surroundings: a coarse ring of terrain around the location (worldwide 30 m heights, the 2016 satellite
// photo), built with the scene (scene.py build_surround, which sews it to the area's border). It only shows what
// lies around, so the 3D map does not end like a cut slab: no signal shadows, no range colours. Three looks, no fog:
//   photo    the satellite picture, lit like the area
//   relief   a pale shaded relief, so the sharp area stands out in colour
//   contours dark ground with a line every 50 m of height (a thicker one every 250 m)
// Its outer edge is a clean wall down to a base, like a model on a table. The area itself is drawn over it.

export const LOOKS = ['photo', 'relief', 'contours'];

const VS = /* glsl */`
  #include <common>
  #include <logdepthbuf_pars_vertex>
  varying vec2 vUv; varying vec3 vNormal; varying vec2 vXZ; varying float vH;
  attribute float aH;
  void main() {
    vUv = uv; vNormal = normalize(normal); vXZ = position.xz; vH = aH;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    #include <logdepthbuf_vertex>
  }`;

const FS = /* glsl */`
  #include <logdepthbuf_pars_fragment>
  uniform sampler2D uPhoto; uniform float uHasPhoto, uHMax, uHBase, uStyle;
  uniform vec2 uInner;
  varying vec2 vUv; varying vec3 vNormal; varying vec2 vXZ; varying float vH;
  float contour(float h, float every) {             // 1 on a contour line, about one pixel wide at any distance
    float f = h / every;
    return 1.0 - clamp(abs(fract(f - 0.5) - 0.5) / max(fwidth(f), 1e-4), 0.0, 1.0);
  }
  void main() {
    #include <logdepthbuf_fragment>
    if (abs(vXZ.x) < uInner.x && abs(vXZ.y) < uInner.y) discard;      // the area itself is drawn there
    vec3 sun = normalize(vec3(-0.5, 0.8, 0.35));
    float ndl = max(dot(normalize(vNormal), sun), 0.0);
    float t = clamp(vH / max(uHMax, 1.0), 0.0, 1.0);
    vec3 col;
    if (uStyle < 0.5 && uHasPhoto > 0.5) {
      col = texture2D(uPhoto, vUv).rgb * (0.78 + 0.40 * ndl);
    } else if (uStyle < 1.5) {
      col = mix(vec3(0.46, 0.49, 0.53), vec3(0.66, 0.68, 0.71), t) * (0.35 + 0.80 * ndl);
    } else {
      float h = vH + uHBase;
      col = vec3(0.13, 0.15, 0.18) * (0.65 + 0.55 * ndl);
      col = mix(col, vec3(0.42, 0.47, 0.54), 0.55 * contour(h, 50.0));
      col = mix(col, vec3(0.70, 0.75, 0.81), 0.75 * contour(h, 250.0));
    }
    gl_FragColor = vec4(col, 1.0);
  }`;

/** A vertical wall hanging under a closed line of points: [x, y-height (unscaled, from aH), z, u, v] each.
 *  Its bottom is `depth` metres lower. Height scale (exaggeration) is applied like the terrain: y = aH × exag. */
export function makeSkirt(THREE, pts, depth, material, exag) {
  const n = pts.length, pos = new Float32Array(n * 2 * 3), uv = new Float32Array(n * 2 * 2), aH = new Float32Array(n * 2);
  pts.forEach(([x, h, z, u, v], i) => {
    for (const [j, hh] of [[2 * i, h], [2 * i + 1, h - depth]]) {
      pos[j * 3] = x; pos[j * 3 + 1] = hh * exag; pos[j * 3 + 2] = z; uv[j * 2] = u; uv[j * 2 + 1] = v; aH[j] = hh;
    }
  });
  const idx = [];
  for (let i = 0; i < n; i++) {
    const a = 2 * i, b = 2 * ((i + 1) % n);
    idx.push(a, a + 1, b, b, a + 1, b + 1);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setAttribute('aH', new THREE.BufferAttribute(aH, 1));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, material);
  mesh.userData.setExag = (e) => {
    const p = geo.attributes.position, a = geo.attributes.aH;
    for (let i = 0; i < p.count; i++) p.setY(i, a.getX(i) * e);
    p.needsUpdate = true; geo.computeVertexNormals();
  };
  return mesh;
}

/** The points around the edge of a grid of vertices (row-major, `cols` × `rows`), in order, as makeSkirt wants them. */
export function gridEdge(cols, rows, at) {
  const out = [];
  for (let c = 0; c < cols; c++) out.push(at(0, c));
  for (let r = 1; r < rows; r++) out.push(at(r, cols - 1));
  for (let c = cols - 2; c >= 0; c--) out.push(at(rows - 1, c));
  for (let r = rows - 2; r > 0; r--) out.push(at(r, 0));
  return out;
}

/** Build the ring from scene.json's `surround` entry. Returns { mesh, setExag, setVisible, setLook } or null. */
export async function createSurround({ THREE, S, scene3, loadTex, maxSide = 500, look = 'contours' }) {
  const m = S.meta.surround;
  if (!m) return null;
  const g = m.grid, main = S.meta.grid;
  let full;
  try {
    const r = await fetch(S.base + m.file);
    if (!r.ok) return null;
    full = new Float32Array(await r.arrayBuffer());
  } catch { return null; }
  if (full.length < g.cols * g.rows) return null;
  const step = Math.max(1, Math.ceil(Math.max(g.cols, g.rows) / maxSide));
  const cols = Math.floor((g.cols - 1) / step) + 1, rows = Math.floor((g.rows - 1) / step) + 1;
  const pos = new Float32Array(cols * rows * 3), uv = new Float32Array(cols * rows * 2), aH = new Float32Array(cols * rows);
  const W = g.max_e - g.min_e, H = g.max_n - g.min_n;
  let k = 0, hMin = Infinity;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++, k++) {
    const e = g.min_e + (c * step + 0.5) * g.res, n = g.max_n - (r * step + 0.5) * g.res;
    const h = full[r * step * g.cols + c * step] - S.hBase;
    pos[k * 3] = e - main.min_e - S.W / 2; pos[k * 3 + 1] = h * S.exag; pos[k * 3 + 2] = -(n - main.min_n - S.H / 2);
    uv[k * 2] = (e - g.min_e) / W; uv[k * 2 + 1] = (n - g.min_n) / H; aH[k] = h; hMin = Math.min(hMin, h);
  }
  const idx = new Uint32Array((cols - 1) * (rows - 1) * 6);
  k = 0;
  for (let r = 0; r < rows - 1; r++) for (let c = 0; c < cols - 1; c++) {
    const a = r * cols + c, b = a + 1, d = a + cols, e2 = d + 1;
    idx[k++] = a; idx[k++] = d; idx[k++] = b; idx[k++] = b; idx[k++] = d; idx[k++] = e2;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setAttribute('aH', new THREE.BufferAttribute(aH, 1));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  const blank = new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1); blank.needsUpdate = true;
  const mat = new THREE.ShaderMaterial({
    vertexShader: VS, fragmentShader: FS,
    uniforms: {
      uPhoto: { value: blank }, uHasPhoto: { value: 0 }, uHMax: { value: S.meta.elevation.max - S.hBase },
      uHBase: { value: S.hBase }, uStyle: { value: Math.max(0, LOOKS.indexOf(look)) },
      uInner: { value: new THREE.Vector2(S.W / 2 - S.view.res, S.H / 2 - S.view.res) },
    },
    polygonOffset: true, polygonOffsetFactor: 2, polygonOffsetUnits: 2,   // the area wins where they overlap
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.renderOrder = -1;
  // the clean outer edge: a wall from the ring's rim down to a base under its lowest point
  const span = Math.max(W, H);
  const rim = gridEdge(cols, rows, (r, c) => { const i = r * cols + c; return [pos[i * 3], aH[i], pos[i * 3 + 2], 0, 0]; })
    .map((p) => [p[0], p[1], p[2], p[1] - (hMin - span * 0.03), 0]);
  const wallMat = new THREE.MeshBasicMaterial({ color: 0x161a20, side: THREE.DoubleSide, fog: false });
  const wall = makeSkirt(THREE, rim.map(([x, h, z]) => [x, h, z, 0, 0]), 0, wallMat, S.exag);
  // makeSkirt drops each point by one depth; here every point goes down to the same base, so set the bottoms by hand
  const wp = wall.geometry.attributes.position, wa = wall.geometry.attributes.aH;
  rim.forEach(([, h, , d], i) => { wa.setX(2 * i + 1, h - d); wp.setY(2 * i + 1, (h - d) * S.exag); });
  wp.needsUpdate = true;
  const group = new THREE.Group();
  group.add(mesh, wall);
  scene3.add(group);
  if (m.photo) {
    try { const t = await loadTex(S.base + m.photo); mat.uniforms.uPhoto.value = t; mat.uniforms.uHasPhoto.value = 1; } catch { /* relief */ }
  }
  return {
    mesh,
    setExag(x) {
      const p = geo.attributes.position, a = geo.attributes.aH;
      for (let i = 0; i < p.count; i++) p.setY(i, a.getX(i) * x);
      p.needsUpdate = true; geo.computeVertexNormals();
      wall.userData.setExag(x);
    },
    setVisible(on) { group.visible = on; },
    setLook(l) { mat.uniforms.uStyle.value = Math.max(0, LOOKS.indexOf(l)); },
  };
}
