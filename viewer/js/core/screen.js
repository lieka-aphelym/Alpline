// fpv3d — sizes on screen. Markers (drone, pilot, labels) keep a fixed size in pixels whatever the zoom:
// pxPerUnit says how many screen pixels one world unit (a metre) covers at a distance from the camera.
export function pxPerUnit(camera, viewEl, distance) {
  return (viewEl?.clientHeight || 800) / (2 * Math.max(distance, 1e-3) * Math.tan((camera.fov * Math.PI) / 360));
}
