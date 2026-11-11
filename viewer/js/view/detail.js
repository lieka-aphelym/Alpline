// fpv3d — sharp close-up: a patch of terrain at the scene's full resolution around the point you
// look at (orbit target / chased drone), with the sharp aerial photo when the build fetched one.
// The overview mesh is decimated (the browser can't draw 16 000 x 16 000 cells), so without this
// patch a 0.5 m scene looks like a 2-8 m one.
import * as THREE from 'three';
import { LITE, PHONE } from '../core/env.js';
import { readTerrain, TERRAIN_ENC } from './terrain_codec.js';

const N = PHONE ? 256 : LITE ? 384 : 768;   // cells per side (phone 256, Lite 384, Full 768)

export function initDetail({ S, scene3, camera, controls, terrainVS, terrainFS, api, which }) {
  const g = S.view.grid;                      // full-resolution grid of the displayed ground
  const baseRes = S.view.res;                 // overview cell size (m)
  const st = { mesh: null, rect: null, busy: false, wanted: null, enabled: true, center: null, tex: null };
  if (!api || baseRes <= g.res * 1.01) return { enabled: false, update() {}, rebuild() {}, set() {}, heightAt: () => null, sizeM: 0, info: 'full resolution everywhere' };

  const mat = new THREE.ShaderMaterial({
    vertexShader: terrainVS, fragmentShader: terrainFS,
    uniforms: { ...S.terrainMat.uniforms, uOrtho: { value: S.terrainMat.uniforms.uOrtho.value },
      uOrthoRect: { value: new THREE.Vector4(0, 0, 1, 1) }, uHole: { value: new THREE.Vector4(1, 1, -1, -1) } },
  });
  const sizeM = N * g.res;

  function localFocus() {
    const t = controls.target;
    return { x: t.x + S.W / 2, y: S.H / 2 - t.z };
  }

  async function load(cx, cy) {
    st.busy = true;
    const c0 = Math.max(0, Math.min(g.cols - N, Math.round(cx / g.res - 0.5 - N / 2)));
    const r0 = Math.max(0, Math.min(g.rows - N, Math.round((S.H - cy) / g.res - 0.5 - N / 2)));
    const cols = Math.min(N, g.cols), rows = Math.min(N, g.rows);
    try {
      const r = await fetch(`${api}/terrain?scene=${encodeURIComponent(S.meta.name)}&which=${which}&step=1&c0=${c0}&r0=${r0}&cols=${cols}&rows=${rows}&enc=${TERRAIN_ENC}`);
      if (!r.ok) throw new Error(r.status);
      const nc = +r.headers.get('X-Cols') || cols, nr = +r.headers.get('X-Rows') || rows;
      const h = await readTerrain(r, nc);
      const x0 = (c0 + 0.5) * g.res, x1 = (c0 + nc - 0.5) * g.res;
      const y1 = S.H - (r0 + 0.5) * g.res, y0 = S.H - (r0 + nr - 0.5) * g.res;
      build(h, nc, nr, c0, r0);
      st.rect = { x0, x1, y0, y1 };
      st.center = { x: (x0 + x1) / 2, y: (y0 + y1) / 2 };
      // hole in the overview mesh (world coords: X = x - W/2, Z = -(y - H/2))
      S.terrainMat.uniforms.uHole.value.set(x0 - S.W / 2, -(y1 - S.H / 2), x1 - S.W / 2, -(y0 - S.H / 2));
      loadOrtho(x0 - g.res / 2, y0 - g.res / 2, x1 + g.res / 2, y1 + g.res / 2);
    } catch (e) {
      console.warn('detail patch', e); st.failed = (st.failed || 0) + 1;
    }
    st.busy = false;
  }

  async function loadOrtho(x0, y0, x1, y1) {
    if (!S.meta.detail) return;
    try {
      const r = await fetch(`${api}/ortho?scene=${encodeURIComponent(S.meta.name)}&x0=${x0}&y0=${y0}&x1=${x1}&y1=${y1}&px=2048`);
      if (!r.ok) { mat.uniforms.uOrtho.value = S.terrainMat.uniforms.uOrtho.value; mat.uniforms.uOrthoRect.value.set(0, 0, 1, 1); return; }
      const bmp = await createImageBitmap(await r.blob(), { imageOrientation: 'flipY' });
      const tex = new THREE.Texture(bmp);
      tex.colorSpace = THREE.NoColorSpace; tex.anisotropy = 8; tex.needsUpdate = true;
      st.tex?.dispose(); st.tex = tex;
      mat.uniforms.uOrtho.value = tex;
      mat.uniforms.uOrthoRect.value.set(x0 / S.W, y0 / S.H, x1 / S.W, y1 / S.H);
      S.requestRender?.(400);
    } catch (e) { console.warn('sharp photo', e); }
  }

  function build(h, nc, nr, c0, r0) {
    st.patch = { h, nc, nr, c0, r0 };
    const skirt = 2 * (nc + nr);
    const nv = nc * nr + skirt;
    const pos = new Float32Array(nv * 3), uv = new Float32Array(nv * 2), aH = new Float32Array(nv);
    const put = (k, x, y, hh) => {
      pos[k * 3] = x - S.W / 2; pos[k * 3 + 1] = hh * S.exag; pos[k * 3 + 2] = -(y - S.H / 2);
      uv[k * 2] = x / S.W; uv[k * 2 + 1] = y / S.H; aH[k] = hh;
    };
    let k = 0;
    for (let r = 0; r < nr; r++) for (let c = 0; c < nc; c++, k++) {
      put(k, (c0 + c + 0.5) * g.res, S.H - (r0 + r + 0.5) * g.res, h[r * nc + c] - S.hBase);
    }
    const idx = [];
    for (let r = 0; r < nr - 1; r++) for (let c = 0; c < nc - 1; c++) {
      const a = r * nc + c, b = a + 1, d = a + nc, e = d + 1;
      idx.push(a, d, b, b, d, e);
    }
    // skirts: hang the border 4 m down so no crack shows against the coarser overview
    const edge = [];
    for (let c = 0; c < nc; c++) edge.push(c);
    for (let r = 1; r < nr; r++) edge.push(r * nc + nc - 1);
    for (let c = nc - 2; c >= 0; c--) edge.push((nr - 1) * nc + c);
    for (let r = nr - 2; r > 0; r--) edge.push(r * nc);
    const s0 = k;
    edge.forEach((v, i) => {
      put(s0 + i, 0, 0, 0);
      pos.set(pos.subarray(v * 3, v * 3 + 3), (s0 + i) * 3); uv.set(uv.subarray(v * 2, v * 2 + 2), (s0 + i) * 2);
      aH[s0 + i] = aH[v] - 4; pos[(s0 + i) * 3 + 1] = aH[s0 + i] * S.exag;
    });
    for (let i = 0; i < edge.length; i++) {
      const a = edge[i], b = edge[(i + 1) % edge.length], a2 = s0 + i, b2 = s0 + (i + 1) % edge.length;
      idx.push(a, a2, b, b, a2, b2);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    geo.setAttribute('aH', new THREE.BufferAttribute(aH, 1));
    geo.setIndex(new THREE.BufferAttribute(new Uint32Array(idx), 1));
    geo.computeVertexNormals();
    if (st.mesh) { st.mesh.geometry.dispose(); st.mesh.geometry = geo; } else {
      st.mesh = new THREE.Mesh(geo, mat); st.mesh.renderOrder = -1; scene3.add(st.mesh);
    }
    st.mesh.visible = st.enabled;
    S.requestRender?.(400);
  }

  function hide() {
    if (st.mesh) st.mesh.visible = false;
    S.terrainMat.uniforms.uHole.value.set(1, 1, -1, -1);
  }
  function show() {
    if (!st.mesh || !st.rect || !st.enabled) return;
    st.mesh.visible = true;
    const { x0, x1, y0, y1 } = st.rect;
    S.terrainMat.uniforms.uHole.value.set(x0 - S.W / 2, -(y1 - S.H / 2), x1 - S.W / 2, -(y0 - S.H / 2));
  }

  let lastCheck = 0;
  return {
    enabled: true,
    info: `${baseRes.toFixed(1)} m overview · ${g.res} m within ${Math.round(sizeM / 2)} m of the view centre`,
    /** call every frame; cheap */
    update(now) {
      if (!st.enabled || st.busy || now - lastCheck < 250 || (st.failed || 0) > 3) return;
      lastCheck = now;
      const f = S.simFocus || localFocus();                   // training flight: around (and ahead of) the drone
      if (!S.simFocus) {
        const dist = camera.position.distanceTo(controls.target);
        if (dist > sizeM * 4) { hide(); return; }             // too far away to see the difference
      }
      if (!st.center || Math.hypot(f.x - st.center.x, f.y - st.center.y) > sizeM / 4) load(f.x, f.y);
      else show();
    },
    /** vertical exaggeration changed */
    rebuild() {
      if (!st.mesh) return;
      const pos = st.mesh.geometry.attributes.position, aH = st.mesh.geometry.attributes.aH;
      for (let i = 0; i < pos.count; i++) pos.setY(i, aH.getX(i) * S.exag);
      pos.needsUpdate = true; st.mesh.geometry.computeVertexNormals();
    },
    set(on) { st.enabled = on; if (!on) hide(); else { st.center = null; } },
    /** height (m above sea level) of the sharp patch at local (x, y), or null outside it / when it isn't shown */
    heightAt(x, y) {
      const p = st.patch;
      if (!p || !st.mesh?.visible) return null;
      const c = x / g.res - 0.5 - p.c0, r = (S.H - y) / g.res - 0.5 - p.r0;
      if (c < 0 || r < 0 || c > p.nc - 1 || r > p.nr - 1) return null;
      const c0 = Math.min(c | 0, p.nc - 2), r0 = Math.min(r | 0, p.nr - 2), fc = c - c0, fr = r - r0, i = r0 * p.nc + c0;
      const top = p.h[i] + (p.h[i + 1] - p.h[i]) * fc, bot = p.h[i + p.nc] + (p.h[i + p.nc + 1] - p.h[i + p.nc]) * fc;
      return top + (bot - top) * fr;
    },
    get sizeM() { return sizeM; },
  };
}
