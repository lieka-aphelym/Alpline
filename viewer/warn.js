// fpv3d — warnings for the pilot (in goggles) and a spotter (screen).
//
// Every update gets the drone state (local x/y metres, z AMSL, velocity m/s, heading) from the live
// telemetry or the simulator. The path of the next few seconds is checked against the 3D
// line-of-sight ceilings of the scene: below the ceiling there is no line of sight to the pilot.
//   caution  shadow within the look-ahead (default 5 s)  -> slow beeps + "Shadow in 4 seconds, climb 30"
//   urgent   shadow within 2 s                           -> fast beeps + "Climb now" / "Turn back, clear at 10 o'clock"
//   blind    no line of sight right now                  -> double beeps + "No line of sight, climb 40"
//   link     real LQ low (live telemetry only)           -> "Link low"
//   lost     telemetry stopped                           -> one long tone + "Signal lost"
// Directions use the clock, from the drone's direction of flight: 12 ahead, 3 right, 6 behind, 9 left.
const RANK = { ok: 0, link: 1, caution: 2, urgent: 3, blind: 4, lost: 5 };
const COLORS = { ok: '#1f6f4a', link: '#9a6b00', caution: '#b07800', urgent: '#c0392b', blind: '#7d1d8c', lost: '#555' };

export function createWarner({ S, demHeight, el }) {
  const cfg = { voice: true, beeps: true, lookahead: 5, margin: 5, climbRate: 12 };
  try { Object.assign(cfg, JSON.parse(localStorage.getItem('fpv3d:warn') || '{}')); } catch { /* private mode */ }
  const save = () => { try { localStorage.setItem('fpv3d:warn', JSON.stringify(cfg)); } catch { /* ignore */ } };
  let last = { level: 'ok' }, lastSpoke = 0, lastText = '', active = false;

  // ------------------------------------------------------------ model
  const ceil = (x, y) => (S.vol?.ceilAt ? S.vol.ceilAt('los', x, y) : null);
  function blindAt(x, y, z) {
    if (x < 0 || y < 0 || x > S.W || y > S.H) return null;
    const c = ceil(x, y);
    if (c == null) return null;
    const g = demHeight(x, y);
    const need = g + Math.min(c, 1e4) - z;          // metres to climb to see the pilot again
    return { blind: c > 0.5 && z - g < c, need, g, c };
  }
  function pathCheck(s, vx, vy, vz, horizon) {
    let first = null, need = 0;
    for (let t = 0.25; t <= horizon + 1e-6; t += 0.25) {
      const b = blindAt(s.x + vx * t, s.y + vy * t, s.z + vz * t);
      if (b?.blind) { if (first == null) first = t; need = Math.max(need, b.need); }
    }
    return { first, need };
  }
  const clockOf = (rel) => { const h = ((Math.round(rel / 30) % 12) + 12) % 12; return h === 0 ? 12 : h; };
  function escape(s, speed, horizon) {
    const v = Math.max(speed, 8), hdg = s.heading * Math.PI / 180;
    for (const rel of [-30, 30, -60, 60, -90, 90, -120, 120, -150, 150, 180]) {
      const a = hdg + rel * Math.PI / 180;
      const r = pathCheck(s, v * Math.sin(a), v * Math.cos(a), 0, Math.min(horizon, 4));
      if (r.first == null) return clockOf(rel);
    }
    return null;
  }
  const round5 = (m) => Math.max(5, Math.ceil(m / 5) * 5);

  function evaluate(s) {
    if (!S.vol?.ceilAt) return { level: 'ok', text: '', detail: 'no 3D shadow data in this scene (refresh it)' };
    const speed = Math.hypot(s.vx, s.vy);
    if (s.z - demHeight(s.x, s.y) < 4 && speed < 4) return { level: 'ok', text: '', detail: 'on the ground' };
    const now = blindAt(s.x, s.y, s.z);
    const L = cfg.lookahead;
    let r = { level: 'ok', text: '', detail: 'line of sight OK' };
    if (now?.blind) {
      const clock = escape(s, speed, L);
      const climb = round5(now.need + cfg.margin);
      r = { level: 'blind', climb, clock, text: `No line of sight. Climb ${climb}` + (clock ? `, or clear at ${clock} o'clock` : ''),
        short: climb <= 60 ? `Climb ${climb}` : clock ? `Clear at ${clock} o'clock` : 'Turn back', detail: `blind now · ${Math.round(now.need)} m below the shadow ceiling` };
    } else if (speed > 1.5 || Math.abs(s.vz) > 1) {
      const p = pathCheck(s, s.vx, s.vy, s.vz, L);
      if (p.first != null) {
        const climb = round5(p.need + cfg.margin), canClimb = climb <= cfg.climbRate * p.first + 5;
        const clock = canClimb ? null : escape(s, speed, L);
        const urgent = p.first <= 2;
        const act = canClimb ? `climb ${climb}` : `turn back${clock ? `, clear at ${clock} o'clock` : ''}`;
        r = { level: urgent ? 'urgent' : 'caution', tShadow: p.first, climb, clock,
          text: urgent ? (canClimb ? `Climb now, ${climb}` : `Turn back${clock ? `. Clear at ${clock} o'clock` : ''}`) : `Shadow in ${Math.round(p.first)} seconds, ${act}`,
          detail: `shadow in ${p.first.toFixed(1)} s · needs +${Math.round(p.need)} m` };
      }
    }
    if (s.lq != null && s.lq < 70 && RANK[r.level] < RANK.caution) {
      r = { level: s.lq < 50 ? 'urgent' : 'link', text: s.lq < 50 ? 'Link low. Turn back' : 'Link low', detail: `LQ ${s.lq}%` };
    }
    return r;
  }

  // ------------------------------------------------------------ sound
  let ac = null, beepT = 0;
  function audio() { if (!ac) { try { ac = new AudioContext(); } catch { ac = null; } } if (ac?.state === 'suspended') ac.resume(); return ac; }
  function tone(freq, dur, when = 0, vol = 0.25) {
    const a = audio(); if (!a) return;
    const o = a.createOscillator(), g = a.createGain(), t0 = a.currentTime + when;
    o.frequency.value = freq; o.type = 'square';
    g.gain.setValueAtTime(0, t0); g.gain.linearRampToValueAtTime(vol, t0 + 0.01); g.gain.setValueAtTime(vol, t0 + dur - 0.02); g.gain.linearRampToValueAtTime(0, t0 + dur);
    o.connect(g).connect(a.destination); o.start(t0); o.stop(t0 + dur + 0.02);
  }
  const BEEP = { caution: [900, () => tone(880, 0.09)], urgent: [300, () => tone(1320, 0.08)],
    blind: [650, () => { tone(1100, 0.08); tone(700, 0.1, 0.12); }], link: [1400, () => tone(600, 0.12)] };
  function beepLoop(now) {
    const b = BEEP[last.level];
    if (!cfg.beeps || !b || now - beepT < b[0]) return;
    beepT = now; b[1]();
  }
  function say(text, interrupt) {
    if (!cfg.voice || !text || !('speechSynthesis' in window)) return;
    if (interrupt) speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.15; u.lang = 'en-US';
    const v = speechSynthesis.getVoices().find((x) => /^en/i.test(x.lang));
    if (v) u.voice = v;
    speechSynthesis.speak(u);
  }

  // ------------------------------------------------------------ screen (spotter)
  function render(r) {
    if (!el) return;
    el.box.classList.toggle('hidden', !active);
    el.box.style.background = COLORS[r.level] || COLORS.ok;
    el.title.textContent = { ok: 'Line of sight OK', link: 'LINK LOW', caution: 'SHADOW AHEAD', urgent: 'SHADOW NOW', blind: 'NO LINE OF SIGHT', lost: 'SIGNAL LOST' }[r.level];
    el.text.textContent = r.level === 'ok' ? r.detail : r.text;
    el.detail.textContent = r.level === 'ok' ? '' : r.detail || '';
    el.dial.classList.toggle('hidden', !r.clock);
    if (r.clock) el.hand.style.transform = `rotate(${(r.clock % 12) * 30}deg)`;
  }

  return {
    cfg, save, evaluate,
    /** s = { x, y, z (AMSL), vx, vy, vz, heading (deg from north), lq? } */
    update(s) {
      active = true;
      const r = evaluate(s), now = performance.now();
      const rose = RANK[r.level] > RANK[last.level];
      if (r.level === 'ok' && RANK[last.level] >= RANK.caution) say('Clear', true);
      else if (r.level !== 'ok') {
        const every = r.level === 'caution' || r.level === 'link' ? 8000 : 4000;
        if (rose || now - lastSpoke > every || (r.text !== lastText && now - lastSpoke > 2500)) {
          say(r.level === 'urgent' && r.short ? r.short : r.text, rose); lastSpoke = now; lastText = r.text;
        }
      }
      last = r;
      render(r);
      return r;
    },
    tick(now) { if (active) beepLoop(now); },
    lost(info) {
      last = { level: 'lost', text: info || 'Telemetry stopped', detail: 'last known position marked on the map' };
      if (cfg.beeps) tone(420, 1.2, 0, 0.3);
      say('Signal lost', true);
      render(last);
    },
    stop() { active = false; last = { level: 'ok' }; render(last); if ('speechSynthesis' in window) speechSynthesis.cancel(); },
    unlock() { audio(); },
    test() { audio(); tone(880, 0.09); tone(1320, 0.08, 0.3); say("Shadow in 4 seconds, climb 30. Clear at 10 o'clock"); },
    get level() { return last.level; },
  };
}
