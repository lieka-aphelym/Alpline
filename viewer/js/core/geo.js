// fpv3d — GPS position (WGS84 lat/lon) <-> metres on the scene's grid (scene.json: grid.crs).
// Swiss scenes are on LV95 (EPSG:2056, swisstopo's approximate formulas, about 1 m); scenes anywhere else are on
// their UTM zone (EPSG:326xx north, EPSG:327xx south; Krüger series, well under a millimetre). Mirrors fpv3d/geo.py.

const LV95 = 'EPSG:2056';

function toLV95(lat, lon) {
  const p = (lat * 3600 - 169028.66) / 10000, l = (lon * 3600 - 26782.5) / 10000;
  return [2600072.37 + 211455.93 * l - 10938.51 * l * p - 0.36 * l * p * p - 44.54 * l ** 3,
    1200147.07 + 308807.95 * p + 3745.25 * l * l + 76.63 * p * p - 194.56 * l * l * p + 119.79 * p ** 3];
}
function fromLV95(e, n) {
  const y = (e - 2600000) / 1e6, x = (n - 1200000) / 1e6;
  const lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3;
  const lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3;
  return [lat * 100 / 36, lon * 100 / 36];
}

// ---------------------------------------------------------------- UTM on the WGS84 ellipsoid
const A = 6378137, F = 1 / 298.257223563, K0 = 0.9996, N = F / (2 - F);
const AA = A / (1 + N) * (1 + N ** 2 / 4 + N ** 4 / 64), C = 2 * Math.sqrt(N) / (1 + N);
const AL = [N / 2 - 2 * N ** 2 / 3 + 5 * N ** 3 / 16, 13 * N ** 2 / 48 - 3 * N ** 3 / 5, 61 * N ** 3 / 240];
const BE = [N / 2 - 2 * N ** 2 / 3 + 37 * N ** 3 / 96, N ** 2 / 48 + N ** 3 / 15, 17 * N ** 3 / 480];
const DE = [2 * N - 2 * N ** 2 / 3 - 2 * N ** 3, 7 * N ** 2 / 3 - 8 * N ** 3 / 5, 56 * N ** 3 / 15];
const RAD = Math.PI / 180;

export function utmZone(crs) {                       // "EPSG:32632" -> { zone: 32, south: false }, null when not UTM
  const m = /^EPSG:32([67])(\d\d)$/.exec(crs || '');
  return m && +m[2] >= 1 && +m[2] <= 60 ? { zone: +m[2], south: m[1] === '7' } : null;
}
function toUTM(lat, lon, { zone, south }) {
  const p = lat * RAD, l = (lon - (zone * 6 - 183)) * RAD;
  const t = Math.sinh(Math.atanh(Math.sin(p)) - C * Math.atanh(C * Math.sin(p)));
  const xi = Math.atan2(t, Math.cos(l)), eta = Math.atanh(Math.sin(l) / Math.sqrt(1 + t * t));
  let e = eta, n = xi;
  for (let j = 1; j <= 3; j++) {
    e += AL[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
    n += AL[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
  }
  return [500000 + K0 * AA * e, (south ? 10000000 : 0) + K0 * AA * n];
}
function fromUTM(e, n, { zone, south }) {
  const xi = (n - (south ? 10000000 : 0)) / (K0 * AA), eta = (e - 500000) / (K0 * AA);
  let x = xi, h = eta;
  for (let j = 1; j <= 3; j++) {
    x -= BE[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
    h -= BE[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
  }
  const chi = Math.asin(Math.sin(x) / Math.cosh(h));
  let lat = chi;
  for (let j = 1; j <= 3; j++) lat += DE[j - 1] * Math.sin(2 * j * chi);
  return [lat / RAD, zone * 6 - 183 + Math.atan(Math.sinh(h) / Math.cos(x)) / RAD];
}

// ---------------------------------------------------------------- which grid a place is built on (fpv3d/config.py)
const SWISS_BOX = [45.7, 5.8, 47.9, 10.6];           // lat0, lon0, lat1, lon1: Switzerland and its border regions
export function utmCrs(lat, lon) {
  const zone = ((Math.floor((lon + 180) / 6) % 60) + 60) % 60 + 1;
  return `EPSG:${(lat >= 0 ? 32600 : 32700) + zone}`;
}
/** Swiss LV95 in and right around Switzerland, the place's UTM zone anywhere else. */
export function crsFor(lat, lon) {
  return lat >= SWISS_BOX[0] && lat <= SWISS_BOX[2] && lon >= SWISS_BOX[1] && lon <= SWISS_BOX[3] ? LV95 : utmCrs(lat, lon);
}

// ---------------------------------------------------------------- what the pages use
export const isSwiss = (crs) => !crs || crs === LV95;
/** [e, n] metres on the grid `crs` (scene.json grid.crs; none = LV95, scenes made before it existed). */
export function toGrid(lat, lon, crs) {
  const u = utmZone(crs);
  return u ? toUTM(lat, lon, u) : toLV95(lat, lon);
}
/** [lat, lon] degrees from metres on the grid `crs`. */
export function toWGS(e, n, crs) {
  const u = utmZone(crs);
  return u ? fromUTM(e, n, u) : fromLV95(e, n);
}
/** Short name of the grid for labels: "LV95", "UTM 32N". */
export function gridName(crs) {
  const u = utmZone(crs);
  return u ? `UTM ${u.zone}${u.south ? 'S' : 'N'}` : 'LV95';
}
