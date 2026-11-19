// The surroundings: a coarse ring of terrain around the location (worldwide 30 m heights, the 2016 satellite
// photo), built with the scene (scene.py build_surround). It only shows what lies around, so the 3D map does not end
// like a cut slab: no signal shadows, no range colours, a little paler than the area itself, and its outer rim
// melts into the sky. The area itself is drawn over it, untouched.

const VS = /* glsl */`
  #include <common>
  #include <logdepthbuf_pars_vertex>
  varying vec2 vUv; varying vec3 vNormal; varying vec2 vXZ; varying float vDist; varying float vH;
  attribute float aH;
  void main() {
    vUv = uv; vNormal = normalize(normal); vXZ = position.xz; vH = aH;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vDist = -mv.z;
    gl_Position = projectionMatrix * mv;
    #include <logdepthbuf_vertex>
  }`;

const FS = /* glsl */`
  #include <logdepthbuf_pars_fragment>
  uniform sampler2D uPhoto; uniform float uHasPhoto, uHMax;
  uniform vec2 uInner; uniform vec2 uOuter; uniform float uRim;    // half sizes (m): the area, the whole ring
  uniform vec3 uSky; uniform vec3 uHaze;
  varying vec2 vUv; varying vec3 vNormal; varying vec2 vXZ; varying float vDist; varying float vH;
  void main() {
    #include <logdepthbuf_fragment>
    if (abs(vXZ.x) < uInner.x && abs(vXZ.y) < uInner.y) discard;      // the area itself is drawn there
    vec3 sun = normalize(vec3(-0.5, 0.8, 0.35));
    float ndl = max(dot(normalize(vNormal), sun), 0.0);
    float t = clamp(vH / max(uHMax, 1.0), 0.0, 1.0);
    vec3 relief = mix(vec3(0.42, 0.50, 0.38), vec3(0.80, 0.80, 0.82), t);
    vec3 col = uHasPhoto > 0.5 ? texture2D(uPhoto, vUv).rgb * (0.75 + 0.45 * ndl) : relief * (0.45 + 0.75 * ndl);
    float g = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(g), 0.25);                                     // a little greyer: context, not data
    float e = min(uOuter.x - abs(vXZ.x), uOuter.y - abs(vXZ.y));       // metres to the outer rim
    col = mix(uSky, col, smoothstep(0.0, uRim, e));
    col = mix(col, uSky, uHaze.z * smoothstep(uHaze.x, uHaze.y, vDist));
    gl_FragColor = vec4(col, 1.0);
  }`;

/** Build the ring from scene.json's `surround` entry. Returns { mesh, setExag, setVisible } or null. */
export async function createSurround({ THREE, S, scene3, loadTex, maxSide = 500 }) {
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
  let k = 0;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++, k++) {
    const e = g.min_e + (c * step + 0.5) * g.res, n = g.max_n - (r * step + 0.5) * g.res;
    const h = full[r * step * g.cols + c * step] - S.hBase;
    pos[k * 3] = e - main.min_e - S.W / 2; pos[k * 3 + 1] = h * S.exag; pos[k * 3 + 2] = -(n - main.min_n - S.H / 2);
    uv[k * 2] = (e - g.min_e) / W; uv[k * 2 + 1] = (n - g.min_n) / H; aH[k] = h;
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
  const tu = S.terrainMat.uniforms;
  // centre of the ring relative to the area's centre (the ring is not always exactly centred: it snaps to its cells)
  const cx = (g.min_e + g.max_e) / 2 - (main.min_e + main.max_e) / 2, cz = -((g.min_n + g.max_n) / 2 - (main.min_n + main.max_n) / 2);
  const blank = new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1); blank.needsUpdate = true;
  const mat = new THREE.ShaderMaterial({
    vertexShader: VS, fragmentShader: FS,
    uniforms: {
      uPhoto: { value: blank }, uHasPhoto: { value: 0 }, uHMax: { value: S.meta.elevation.max - S.hBase },
      uInner: { value: new THREE.Vector2(S.W / 2 - S.view.res, S.H / 2 - S.view.res) },
      uOuter: { value: new THREE.Vector2(W / 2 - Math.abs(cx), H / 2 - Math.abs(cz)) },
      uRim: { value: Math.min(W, H) * 0.12 },
      uSky: tu.uSky, uHaze: tu.uHaze,                  // the same sky and haze as the area
    },
    polygonOffset: true, polygonOffsetFactor: 2, polygonOffsetUnits: 2,   // the area wins where they overlap
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.renderOrder = -1;
  scene3.add(mesh);
  if (m.photo) {
    try { const t = await loadTex(S.base + m.photo); mat.uniforms.uPhoto.value = t; mat.uniforms.uHasPhoto.value = 1; } catch { /* relief colours */ }
  }
  return {
    mesh,
    setExag(x) {
      const p = geo.attributes.position, a = geo.attributes.aH;
      for (let i = 0; i < p.count; i++) p.setY(i, a.getX(i) * x);
      p.needsUpdate = true; geo.computeVertexNormals();
    },
    setVisible(on) { mesh.visible = on; },
  };
}
