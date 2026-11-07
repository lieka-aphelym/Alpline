// Flight model checks (viewer/simphysics.js):   node tests/test_sim.mjs    (run by tests/test_sim.py)
import * as THREE from '../viewer/vendor/three.module.js';
import { createFlightModel, collide, throttleCurve, cellVolts, powerFactor, groundEffect, G } from '../viewer/simphysics.js';

const M = createFlightModel(THREE);
let fails = 0;
const check = (name, ok, info = '') => { console.log(`  ${ok ? 'ok  ' : 'FAIL'}  ${name}${ok ? '' : '  ' + info}`); if (!ok) fails++; };
const cfg = (over = {}) => ({ mode: 'angle', rates: { center: 200, max: 670, expo: 0.5 }, maxAngle: 55, twr: 7, topSpeed: 150,
  response: 25, physics: { battery: true, packMin: 6, sag: 0.35, propwash: 0.5, thrMid: 0.5, thrExpo: 0 }, ...over });
const quad = () => ({ pos: new THREE.Vector3(0, 50, 0), vel: new THREE.Vector3(), q: new THREE.Quaternion(), w: new THREE.Vector3(),
  armed: true, failsafe: 0, charge: 1, pw: { x: 0, z: 0 } });
const fly = (st, c, inp, secs, env = { agl: 50 }) => { for (let t = 0; t < secs; t += 0.004) M.step(st, c, { roll: 0, pitch: 0, yaw: 0, ...inp }, 0.004, env); };

// throttle curve
check('throttle curve: no expo = straight line', [0, 0.2, 0.5, 0.9, 1].every((t) => Math.abs(throttleCurve(t, 0.5, 0) - t) < 1e-9));
check('throttle curve: mid stays mid, expo flattens around it', Math.abs(throttleCurve(0.5, 0.5, 0.6) - 0.5) < 1e-9 &&
  Math.abs(throttleCurve(0.6, 0.5, 0.6) - 0.5) < Math.abs(0.6 - 0.5) && throttleCurve(1, 0.5, 0.6) === 1);

// hover
{
  const c = cfg(), st = quad();
  const h = M.hoverThrottle(c);
  fly(st, c, { throttle: h }, 2);
  check('hover throttle keeps it level (full pack)', Math.abs(st.vel.y) < 0.4, `vy ${st.vel.y.toFixed(2)} at ${h.toFixed(2)}`);
}

// battery
{
  check('volts: full 4.2, empty 3.5, sag under load', Math.abs(cellVolts(1, 0) - 4.2) < 1e-9 && cellVolts(0, 0) < 3.3 && cellVolts(1, 1) < 3.9);
  const c = cfg({ physics: { battery: true, packMin: 1, sag: 0.35, propwash: 0 } }), st = quad();
  const h = M.hoverThrottle(c);
  fly(st, c, { throttle: h }, 30); const half = st.charge;
  fly(st, c, { throttle: h }, 35);
  check('hovering empties the pack in about its time', half > 0.35 && half < 0.65 && st.charge < 0.05, `half ${half.toFixed(2)}, end ${st.charge.toFixed(2)}`);
  check('an empty pack can no longer hold a hover', st.vel.y < -0.5, `vy ${st.vel.y.toFixed(2)}`);
  check('less power from an empty pack', powerFactor(cellVolts(0.05, 0.5)) < powerFactor(cellVolts(1, 0.5)) * 0.85);
}

// top speed (no battery, so full power)
{
  const c = cfg({ physics: { battery: false, propwash: 0 } });
  const a = Math.acos(1 / c.twr) * 180 / Math.PI;      // tilt where thrust balances weight at full throttle
  c.maxAngle = a;
  const st = quad(); fly(st, c, { throttle: 1, pitch: 1 }, 30);
  const v = Math.hypot(st.vel.x, st.vel.z) * 3.6;
  check('top speed in level flight close to the setting', v > 0.75 * c.topSpeed && v < 1.15 * c.topSpeed, `${v.toFixed(0)} km/h for ${c.topSpeed}`);
}

// drag: falling flat is slower than falling edge-on
{
  const c = cfg({ physics: { battery: false, propwash: 0 } });
  const a = quad(); a.armed = false; fly(a, c, { throttle: 0 }, 15);
  const b = quad(); b.armed = false; b.q.setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2); c.mode = 'acro'; fly(b, c, { throttle: 0 }, 15);
  check('falls flat slower than edge-on (prop disk drag)', Math.abs(a.vel.y) < Math.abs(b.vel.y) * 0.9, `${a.vel.y.toFixed(1)} vs ${b.vel.y.toFixed(1)}`);
}

// ground effect
check('ground effect: extra lift at 5 cm, none at 2 m', groundEffect(0.05) > 1.08 && groundEffect(2) < 1.001);

// propwash
{
  const c = cfg({ physics: { battery: false, propwash: 1 } });
  const calm = quad(); fly(calm, c, { throttle: M.hoverThrottle(c) }, 1);
  const wash = quad(); wash.vel.set(0, -12, 0);
  let maxAmp = 0, maxRate = 0;
  for (let t = 0; t < 0.4; t += 0.004) { M.step(wash, c, { roll: 0, pitch: 0, yaw: 0, throttle: 0.5 }, 0.004, { agl: 50 }); maxAmp = Math.max(maxAmp, wash.propwash || 0); maxRate = Math.max(maxRate, wash.w.length()); }
  check('propwash shakes it when falling into the wake', maxAmp > 0.1 && maxRate > 0.05 && calm.w.length() < 0.01, `amp ${maxAmp}, rate ${maxRate}, calm ${calm.w.length()}`);
}

// collisions
{
  const prev = new THREE.Vector3(0, 10, 0);
  const st = quad(); st.pos.set(1, 10, 0); st.vel.set(15, 0, 0);
  const r = collide(st, prev, () => ({ h: 0, wall: true }));
  check('flying into a wall at speed: crash, back outside', /building/.test(r) && st.pos.x === 0, String(r));
  const s2 = quad(); s2.pos.set(0, -0.5, 0); s2.vel.set(0, -2, 0);
  check('a soft landing is a bump, not a crash', collide(s2, prev, () => ({ h: 0, wall: false })) === 'bump' && s2.pos.y > 0);
  const s3 = quad(); s3.pos.set(0, -0.5, 0); s3.vel.set(0, -12, 0);
  check('hitting the ground fast is a crash', /crashed/.test(collide(s3, prev, () => ({ h: 0, wall: false })) || ''));
  const s4 = quad(); s4.pos.set(0, 30, 0);
  check('above the ground and walls: nothing', collide(s4, prev, () => ({ h: 0, wall: false })) === null);
}
console.log(fails ? `${fails} failed` : 'all ok');
process.exit(fails ? 1 : 0);
