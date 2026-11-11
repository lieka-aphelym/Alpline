// fpv3d — training flight motor sound (Web Audio, nothing to download).
// Two detuned saw "motors" through a low-pass filter: pitch and loudness follow the throttle (and the load the
// battery gives), plus a band of air noise that grows with speed. Starts on the first arm (browsers only allow
// sound after a click), silent when disarmed.
export function createMotorSound() {
  let ac = null, nodes = null, vol = 0.5, on = true;

  function build() {
    try { ac = new (window.AudioContext || window.webkitAudioContext)(); } catch { ac = null; return; }
    const master = ac.createGain(); master.gain.value = 0; master.connect(ac.destination);
    const lp = ac.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 1400; lp.Q.value = 0.8; lp.connect(master);
    const motors = [0, 7, -5, 12].map((det) => {                    // four motors, slightly different speeds
      const o = ac.createOscillator(); o.type = 'sawtooth'; o.detune.value = det; o.frequency.value = 120;
      const g = ac.createGain(); g.gain.value = 0.18; o.connect(g); g.connect(lp); o.start();
      return o;
    });
    // air noise
    const buf = ac.createBuffer(1, ac.sampleRate * 2, ac.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const noise = ac.createBufferSource(); noise.buffer = buf; noise.loop = true;
    const bp = ac.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 900; bp.Q.value = 0.6;
    const ng = ac.createGain(); ng.gain.value = 0;
    noise.connect(bp); bp.connect(ng); ng.connect(master); noise.start();
    nodes = { master, lp, motors, ng, bp };
  }

  return {
    set(o) { if (o.volume != null) vol = o.volume; if (o.on != null) on = o.on; },
    /** call every frame: armed, throttle load 0..1 (after the curve and battery), airspeed m/s, propwash 0..1 */
    update(armed, load, speed, wash = 0) {
      if (!on || vol <= 0) { if (nodes) nodes.master.gain.setTargetAtTime(0, ac.currentTime, 0.05); return; }
      if (!ac) { if (!armed) return; build(); if (!ac) return; }
      if (ac.state === 'suspended') ac.resume();
      const t = ac.currentTime, l = Math.max(0, Math.min(1, load));
      const f = armed ? 95 + 520 * Math.pow(l, 0.55) : 0;
      nodes.motors.forEach((o, i) => o.frequency.setTargetAtTime(Math.max(30, f * (1 + i * 0.004) + wash * 25 * Math.sin(t * 40 + i)), t, 0.04));
      nodes.lp.frequency.setTargetAtTime(700 + 2600 * l, t, 0.05);
      nodes.master.gain.setTargetAtTime(armed ? vol * (0.25 + 0.6 * Math.pow(l, 0.7)) : 0, t, armed ? 0.05 : 0.15);
      nodes.ng.gain.setTargetAtTime(armed ? Math.min(0.5, speed / 60) * 0.6 : 0, t, 0.1);
      nodes.bp.frequency.setTargetAtTime(600 + speed * 25, t, 0.1);
    },
    stop() { if (nodes) nodes.master.gain.setTargetAtTime(0, ac.currentTime, 0.05); },
  };
}
