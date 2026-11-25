// fpv3d — camera modes: orbit (default), free fly, chase, drone view.
//
// Free fly: drag with the left mouse button to look around,
//   W/S forward/back, A/D sideways, E/Q up/down (physical keys: ZQSD/AE on AZERTY),
//   arrow keys to turn, Shift = 4x faster, Alt = 4x slower, mouse wheel = change base speed.
//   The camera never goes below the terrain.
import * as THREE from 'three';

export function initCameraModes({ camera, controls, dom, groundY, sceneSpan, droneView }) {
  const keys = new Set();
  const euler = new THREE.Euler(0, 0, 0, 'YXZ');
  const st = { mode: 'orbit', speed: Math.max(10, sceneSpan() / 60), drag: null };
  const fwd = new THREE.Vector3(), right = new THREE.Vector3(), move = new THREE.Vector3();
  const qTarget = new THREE.Quaternion(), m4 = new THREE.Matrix4();

  const typing = (e) => /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName);
  addEventListener('keydown', (e) => {
    if (st.mode !== 'fly' || typing(e)) return;
    keys.add(e.code);
    if (/^(Arrow|Key[WASDQE])/.test(e.code)) e.preventDefault();
  });
  addEventListener('keyup', (e) => keys.delete(e.code));
  addEventListener('blur', () => keys.clear());

  dom.addEventListener('pointerdown', (e) => {
    if (st.mode !== 'fly' || e.button !== 0) return;
    st.drag = { x: e.clientX, y: e.clientY }; dom.setPointerCapture(e.pointerId);
  });
  dom.addEventListener('pointermove', (e) => {
    if (!st.drag) return;
    const dx = e.clientX - st.drag.x, dy = e.clientY - st.drag.y; st.drag = { x: e.clientX, y: e.clientY };
    euler.setFromQuaternion(camera.quaternion);
    euler.y -= dx * 0.004; euler.x = THREE.MathUtils.clamp(euler.x - dy * 0.004, -1.55, 1.55); euler.z = 0;
    camera.quaternion.setFromEuler(euler);
  });
  dom.addEventListener('pointerup', () => { st.drag = null; });
  dom.addEventListener('wheel', (e) => {
    if (st.mode !== 'fly') return;
    e.preventDefault();
    st.speed = THREE.MathUtils.clamp(st.speed * (e.deltaY < 0 ? 1.25 : 0.8), 1, 2000);
    hint();
  }, { passive: false });

  function hint() {
    const el = document.getElementById('camHint'); if (!el) return;
    el.innerHTML = {
      orbit: 'Drag to turn, right-drag to move, wheel to zoom',
      fly: `Drag to look, <b>W A S D</b> to move, <b>E / Q</b> up and down, Shift faster; wheel sets the speed (<b>${st.speed.toFixed(0)} m/s</b>)`,
      chase: 'The camera follows the drone while a flight plays',
      drone: 'Seen from the drone, looking where it flies',
    }[st.mode];
  }

  function setMode(mode) {
    const prev = st.mode; st.mode = mode; keys.clear();
    controls.enabled = mode === 'orbit' || mode === 'chase';
    if ((mode === 'orbit' || mode === 'chase') && (prev === 'fly' || prev === 'drone')) {
      // put the orbit pivot a bit in front of where we are looking
      camera.getWorldDirection(fwd);
      controls.target.copy(camera.position).addScaledVector(fwd, Math.max(150, sceneSpan() * 0.08));
    }
    if (mode === 'fly' && prev !== 'fly') { euler.setFromQuaternion(camera.quaternion); euler.z = 0; camera.quaternion.setFromEuler(euler); }
    hint();
  }

  function update(dt) {
    if (st.mode === 'fly') {
      const k = (c) => keys.has(c);
      let sp = st.speed * (k('ShiftLeft') || k('ShiftRight') ? 4 : 1) * (k('AltLeft') || k('AltRight') ? 0.25 : 1);
      // turning with arrow keys
      const turn = 1.2 * dt;
      if (k('ArrowLeft') || k('ArrowRight') || k('ArrowUp') || k('ArrowDown')) {
        euler.setFromQuaternion(camera.quaternion);
        euler.y += (k('ArrowLeft') ? turn : 0) - (k('ArrowRight') ? turn : 0);
        euler.x = THREE.MathUtils.clamp(euler.x + (k('ArrowUp') ? turn : 0) - (k('ArrowDown') ? turn : 0), -1.55, 1.55);
        euler.z = 0; camera.quaternion.setFromEuler(euler);
      }
      camera.getWorldDirection(fwd);
      right.crossVectors(fwd, camera.up).normalize();
      move.set(0, 0, 0);
      if (k('KeyW')) move.add(fwd);
      if (k('KeyS')) move.sub(fwd);
      if (k('KeyD')) move.add(right);
      if (k('KeyA')) move.sub(right);
      if (k('KeyE')) move.y += 1;
      if (k('KeyQ')) move.y -= 1;
      if (move.lengthSq() > 0) camera.position.addScaledVector(move.normalize(), sp * dt);
      const gy = groundY(camera.position.x, camera.position.z);
      if (gy != null && camera.position.y < gy + 3) camera.position.y = gy + 3;   // don't fly into the hills
    } else if (st.mode === 'drone') {
      const v = droneView();                      // { pos, dir } in world space, or null
      if (!v) return;
      camera.position.copy(v.pos);
      m4.lookAt(v.pos, v.pos.clone().add(v.dir), camera.up);
      qTarget.setFromRotationMatrix(m4);
      camera.quaternion.slerp(qTarget, Math.min(1, dt * 6));   // smooth GPS-direction jitter
    }
  }

  hint();
  return { setMode, update, groundY, mode: () => st.mode, usesOrbit: () => st.mode === 'orbit' || st.mode === 'chase' };
}
