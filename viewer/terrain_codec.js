// Terrain heights from /api/terrain. Asked for in the compact form (&enc=d16): 16-bit decimetres above the lowest
// point, each stored as the difference to its left neighbour. Half the size of float32 and it compresses well for
// the phone; 0.1 m steps are far finer than the terrain cells. Plain float32 still works (older servers).
export const TERRAIN_ENC = 'd16';

/** fetch Response -> Float32Array of heights in metres (row by row) */
export async function readTerrain(r, cols) {
  const buf = await r.arrayBuffer();
  if (r.headers.get('X-Enc') !== 'd16') return new Float32Array(buf);
  const d = new Uint16Array(buf), base = +r.headers.get('X-Base'), scale = +r.headers.get('X-Scale') || 0.1;
  const nc = +r.headers.get('X-Cols') || cols, out = new Float32Array(d.length);
  for (let i = 0; i < d.length; i += nc) {
    let v = 0;
    for (let j = i, e = Math.min(i + nc, d.length); j < e; j++) { v = (v + d[j]) & 0xffff; out[j] = base + v * scale; }
  }
  return out;
}
