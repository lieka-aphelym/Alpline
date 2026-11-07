// fpv3d — the training flight's flight model (no page, no drawing: tested on its own in tests/test_sim.mjs).
//
// World frame: three.js axes in real metres (X east, Y up, Z south). Body frame: forward = -Z, up = +Y, right = +X.
// What it models, per step:
//   sticks -> body rates (Betaflight "actual" rates, acro or angle mode) -> first-order motor/PID response
//   thrust = TWR · g · curve(throttle)^1.6 · battery power · ground effect
//      curve: Betaflight throttle mid / expo        battery: voltage drops as the pack empties and sags under load
//      ground effect: a little extra lift within a few prop diameters of the ground
//   drag on the airspeed (wind + gusts), stronger through the prop disk (falling) than sideways
//   propwash: descending into your own wake with throttle on shakes the quad
// Collisions (with the ground you see and with buildings) are in collide().

export const G = 9.81;
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);

/** Betaflight throttle curve (thr_mid, thr_expo): same stick, same feel as on the real quad. t, mid in 0..1. */
export function throttleCurve(t, mid = 0.5, expo = 0) {
  const tmp = t - mid, y = tmp >= 0 ? 1 - mid : mid;
  if (y <= 0) return t;
  return clamp(mid + tmp * (1 - expo + expo * (tmp * tmp) / (y * y)), 0, 1);
}

/** Volts per cell: 4.2 full -> 3.5 empty at rest, minus the sag under load (load 0..1 = share of full power). */
export function cellVolts(charge, load, sag = 0.35) {
  const rest = 3.5 + 0.7 * clamp(charge, 0, 1) - 0.25 * Math.max(0, 0.15 - charge) / 0.15;   // knee near empty
  return rest - sag * clamp(load, 0, 1);
}

/** Share of full thrust the pack can give at that voltage (motor power ~ voltage²). */
export const powerFactor = (v) => clamp((v / 4.2) ** 2, 0, 1);

/** Ground effect: extra lift below about two prop diameters (5" props: ~0.25 m). */
export const groundEffect = (agl, propM = 0.127) => 1 + 0.15 * Math.exp(-Math.max(agl, 0) / (1.6 * propM));

export function createFlightModel(THREE) {
  const _u = new THREE.Vector3(), _dq = new THREE.Quaternion(), _ax = new THREE.Vector3(), _e = new THREE.Euler();
  const _rel = new THREE.Vector3(), _relB = new THREE.Vector3(), _qi = new THREE.Quaternion(), _acc = new THREE.Vector3();

  const rateOf = (x, r) => {                    // Betaflight "actual rates", deg/s
    const a = Math.abs(x), e = a * (x ** 4 * r.expo + (1 - r.expo));
    return Math.sign(x) * (a * r.center + Math.max(0, r.max - r.center) * e);
  };

  /** One physics step. st: pos, vel, q, w, armed, failsafe, charge, pw (propwash noise). env: wind (Vector3), agl. */
  function step(st, cfg, inp, dt, env) {
    const mode = inp.mode || cfg.mode;
    let wx, wy, wz;
    wy = -rateOf(inp.yaw, cfg.rates) * Math.PI / 180;
    if (mode === 'acro') {
      wx = -rateOf(inp.pitch, cfg.rates) * Math.PI / 180;
      wz = -rateOf(inp.roll, cfg.rates) * Math.PI / 180;
    } else {                                     // angle mode: P-controller on the tilt angles
      _e.setFromQuaternion(st.q, 'YXZ');
      const maxA = cfg.maxAngle * Math.PI / 180;
      wx = clamp((-inp.pitch * maxA - _e.x) * 8, -8, 8);
      wz = clamp((-inp.roll * maxA - _e.z) * 8, -8, 8);
    }
    if (st.failsafe > 0) { wx = wy = wz = 0; }
    const k = 1 - Math.exp(-dt / Math.max(0.005, cfg.response / 1000));
    st.w.x += (wx - st.w.x) * k; st.w.y += (wy - st.w.y) * k; st.w.z += (wz - st.w.z) * k;

    // --- thrust
    const ph = cfg.physics || {};
    const thrIn = st.armed && st.failsafe < 2 ? throttleCurve(inp.throttle, ph.thrMid ?? 0.5, ph.thrExpo ?? 0) : 0;
    const load = Math.pow(thrIn, 1.6);                              // share of full thrust asked for
    let power = 1;
    if (ph.battery !== false) {
      st.volts = cellVolts(st.charge ?? 1, load, ph.sag ?? 0.35);
      power = powerFactor(st.volts);
      // energy: hovering empties the pack in packMin minutes; power ~ thrust^1.1 above that
      const hoverLoad = 1 / cfg.twr, rel = Math.max(load, 0.02) / hoverLoad;
      st.charge = Math.max(0, (st.charge ?? 1) - dt * rel ** 1.1 / (60 * Math.max(0.5, ph.packMin ?? 6)));
    }
    const thrust = cfg.twr * G * load * power * groundEffect(env.agl ?? 99);

    // --- propwash: falling through your own wake with throttle on
    const pwStrength = ph.propwash ?? 0.5;
    if (pwStrength > 0 && st.pw) {
      _u.set(0, 1, 0).applyQuaternion(st.q);
      const sink = -st.vel.dot(_u);                                 // speed into the prop disk (m/s)
      const amp = sink > 2 && load > 0.6 / cfg.twr ? pwStrength * Math.min(1, (sink - 2) / 6) * Math.min(1, load * cfg.twr) : 0;
      const rnd = () => (Math.random() + Math.random() + Math.random() - 1.5) * 2;
      for (const c of ['x', 'z']) st.pw[c] += (-st.pw[c] * 25 + amp * 60 * rnd()) * dt;   // fast, filtered shake
      st.w.x += st.pw.x * dt * 10; st.w.z += st.pw.z * dt * 10;
      st.propwash = amp;
    }

    const ang = st.w.length() * dt;
    if (ang > 0) { _dq.setFromAxisAngle(_ax.copy(st.w).normalize(), ang); st.q.multiply(_dq).normalize(); }

    _u.set(0, 1, 0).applyQuaternion(st.q);
    const acc = _acc.copy(_u).multiplyScalar(thrust);
    acc.y -= G;
    // drag on the airspeed: quadratic term sized so level flight at full throttle tops out at cfg.topSpeed;
    // 1.6x stronger along the prop axis (a quad falls flat slower than it slides)
    const c1 = 0.15, vmax = Math.max(cfg.topSpeed, 10) / 3.6;
    const c2 = Math.max(0.002, (Math.sqrt(Math.max(cfg.twr ** 2 - 1, 0.1)) * G - c1 * vmax) / (vmax * vmax));
    const rel = _rel.copy(st.vel);
    if (env.wind) rel.sub(env.wind);
    const sp = rel.length();
    _relB.copy(rel).applyQuaternion(_qi.copy(st.q).invert());     // airspeed in the body frame
    const d = c1 + c2 * sp;
    _relB.set(_relB.x * d, _relB.y * d * 1.6, _relB.z * d).applyQuaternion(st.q);
    acc.sub(_relB);
    st.vel.addScaledVector(acc, dt);
    st.pos.addScaledVector(st.vel, dt);
    st.load = load; st.power = power;
  }

  /** Hover throttle stick position (for the settings hint), with a full pack. */
  function hoverThrottle(cfg) {
    const need = Math.pow(1 / (cfg.twr * powerFactor(cellVolts(1, 1 / cfg.twr, cfg.physics?.sag ?? 0.35))), 1 / 1.6);
    // invert the throttle curve numerically
    let lo = 0, hi = 1;
    for (let i = 0; i < 30; i++) { const m = (lo + hi) / 2; if (throttleCurve(m, cfg.physics?.thrMid ?? 0.5, cfg.physics?.thrExpo ?? 0) < need) lo = m; else hi = m; }
    return (lo + hi) / 2;
  }
  return { step, hoverThrottle };
}

/** Ground and walls. ground(x, z) -> { h, wall } in world metres: h = surface height (terrain you see, roofs),
 *  wall = true when (x, z) is inside a building whose roof is above `y` and the quad came from the side (prevY).
 *  Returns null, "bump" or a crash text. */
export function collide(st, prev, ground, crashSpeed = 4) {
  const g = ground(st.pos.x, st.pos.z, st.pos.y, prev.y);
  if (g.wall) {                                   // flew into a building's wall
    const v = st.vel.length();
    st.pos.copy(prev); st.vel.multiplyScalar(-0.15); st.w.multiplyScalar(0.3);
    return v > crashSpeed ? `hit a building at ${(v * 3.6).toFixed(0)} km/h` : 'bump';
  }
  if (st.pos.y < g.h + 0.12) {
    const v = st.vel.length();
    st.pos.y = g.h + 0.12;
    st.vel.multiplyScalar(0.2); if (st.vel.y < 0) st.vel.y = 0;
    st.w.multiplyScalar(0.5);
    return v > crashSpeed ? `crashed at ${(v * 3.6).toFixed(0)} km/h` : 'bump';
  }
  return null;
}
