// fpv3d: Full / Lite / phone for the modules. Decided once by theme.js (a plain script that runs first on every
// page, from /api/mode.js and ?mode=); this file only hands the result on.
//   LITE  : the light mode chosen in the launcher (or --lite)      PHONE : a touch screen smaller than 900 px
//   LIGHT : either of them (lighter 3D: smaller meshes, render on demand)
const E = window.ALPLINE || { mode: 'full', lite: false, phone: false, light: false };
export const MODE = E.mode, LITE = E.lite, PHONE = E.phone, LIGHT = E.light;
