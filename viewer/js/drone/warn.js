// fpv3d — warnings for the pilot (in goggles) and a spotter (screen).
//
// Every update gets the drone state (local x/y metres, z AMSL, velocity m/s, heading) from the live
// telemetry or the simulator. The path of the next few seconds is checked against the 3D
// line-of-sight ceilings of the scene: below the ceiling there is no line of sight to the pilot.
// Voice = reason + one action, short enough for the goggles ("short + reason"):
//   caution  blind zone within the look-ahead (default 5 s) -> slow beeps   + "Blind zone ahead, climb 30" / "..., turn left"
//   urgent   blind zone within 2 s                          -> fast beeps   + "Blind zone close, climb 30 now" / "..., turn back now"
//   blind    no line of sight right now                     -> double beeps + "No line of sight, climb 40" / "..., turn right"
//   link     real LQ low (live telemetry only)              -> "Signal weak" / "Signal weak, turn back"
//   lost     telemetry stopped                              -> one long tone + "Signal lost"
//   battery  from the radio's battery telemetry (batwarn.js): half pack, land at 80 %, cells low / critical
//   back to ok                                              -> "Clear"
// Repeats only say the action ("Climb 30", "Turn left now"). Directions are relative to the direction of flight:
// bear left/right (up to 45 deg), turn left/right (up to 120 deg), turn back. The spotter's screen also shows a clock dial.
//
// Command sounds (no files, made with Web Audio; left / right are panned, so use stereo earbuds):
//   climb      rising sweep (twice = climb a lot, more than 40 m)
//   left/right double tick in that ear only           back   two falling tones, left then right
//   blind      low harsh double buzz (+ the action)   weak   soft low wobble (+ "back" when very weak)
//   lost       one long low tone                      clear  two bright rising notes
// Repetition = urgency: ahead every 1.6 s, close every 0.7 s, blind every 1.3 s, weak every 2.5 s.
// Climb repeats faster (ahead 0.9 s, close 0.6 s, no sight 0.8 s with the buzz every 3rd time) while you must still climb;
// in mixed mode every 4th one is the spoken word "Climb".
// Modes: 'mixed' (default: voice says the sentence once when the situation changes, then only the sound repeats),
//        'sounds' (never speaks), 'voice' (sentences + the old plain beeps).
import { createBatteryWatch } from '../battery/batwarn.js';

const RANK = { ok: 0, link: 1, outside: 1.5, caution: 2, urgent: 3, blind: 4, lost: 5 };
const COLORS = { ok: '#1f6f4a', link: '#9a6b00', outside: '#3d4654', caution: '#b07800', urgent: '#c0392b', blind: '#7d1d8c', lost: '#555' };

export function createWarner({ S, demHeight, el, ceil: ceilFn = null }) {
  // ceil(x, y): metres above the ground needed there to see the pilot (null = unknown). The live flight passes its
  // own (from the live pilot position); otherwise the scene's precomputed 3D shadows are used.
  const cfg = { mode: 'mixed', lookahead: 5, margin: 5, climbRate: 12 };
  try { Object.assign(cfg, JSON.parse(localStorage.getItem('fpv3d:warn') || '{}')); } catch { /* private mode */ }
  if (!['mixed', 'sounds', 'voice', 'off'].includes(cfg.mode)) cfg.mode = 'mixed';
  delete cfg.voice; delete cfg.beeps;                       // settings of the older version
  if (!Array.isArray(cfg.muted)) cfg.muted = [];
  if (!['full', 'compact', 'off'].includes(cfg.screen)) cfg.screen = 'full';   // warning box on screen            // sound groups switched off (see GROUP)
  const save = () => { try { localStorage.setItem('fpv3d:warn', JSON.stringify({ ...cfg, bat: BW.cfg })); } catch { /* ignore */ } };
  const BW = createBatteryWatch(cfg.bat || {});             // battery warnings (live telemetry): batwarn.js
  delete cfg.bat;
  let last = { level: 'ok' }, lastSpoke = 0, lastText = '', lastKind = '', active = false;

  // ------------------------------------------------------------ model
  const ceil = ceilFn || ((x, y) => (S.vol?.ceilAt ? S.vol.ceilAt('los', x, y) : null));
  const ready = () => !!ceilFn || !!S.vol?.ceilAt;
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
  const turnOf = (rel) => (Math.abs(rel) > 120 ? 'turn back' : `${Math.abs(rel) <= 45 ? 'bear' : 'turn'} ${rel < 0 ? 'left' : 'right'}`);
  /** first heading change (relative, deg; + = right) whose path stays in sight, or null */
  function escape(s, speed, horizon) {
    const v = Math.max(speed, 8), hdg = s.heading * Math.PI / 180;
    for (const rel of [-30, 30, -60, 60, -90, 90, -120, 120, -150, 150, 180]) {
      const a = hdg + rel * Math.PI / 180;
      const r = pathCheck(s, v * Math.sin(a), v * Math.cos(a), 0, Math.min(horizon, 4));
      if (r.first == null) return rel;
    }
    return null;
  }
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  const round5 = (m) => Math.max(5, Math.ceil(m / 5) * 5);

  function evaluate(s) {
    if (!ready()) return { level: 'ok', text: '', detail: 'no 3D shadow data in this scene (refresh it)' };
    const speed = Math.hypot(s.vx, s.vy);
    if (s.z - demHeight(s.x, s.y) < 4 && speed < 4) return { level: 'ok', text: '', detail: 'on the ground' };
    const now = blindAt(s.x, s.y, s.z);
    const L = cfg.lookahead;
    let r = { level: 'ok', text: '', detail: 'line of sight OK' };
    if (now == null) {
      // outside the built area (or no shadow data under the drone): never report that as "in sight"
      r = { level: 'outside', action: 'Turn back to the map', text: 'Outside the map, no line of sight check', short: 'Outside the map',
        detail: 'the drone left the built area: no shadow data here' };
    } else if (now.blind) {
      const climb = round5(now.need + cfg.margin), rel = climb > 60 ? escape(s, speed, L) : null;
      const act = climb <= 60 ? `climb ${climb}` : rel != null ? turnOf(rel) : 'turn back';
      r = { level: 'blind', climb, clock: rel != null ? clockOf(rel) : null, action: cap(act),
        text: `No line of sight, ${act}`, short: cap(act),
        detail: `${Math.round(now.need)} m below the line of sight` + (climb > 60 ? ' · too high to climb' : '') };
    } else if (speed > 1.5 || Math.abs(s.vz) > 1) {
      const p = pathCheck(s, s.vx, s.vy, s.vz, L);
      if (p.first != null) {
        const climb = round5(p.need + cfg.margin), canClimb = climb <= cfg.climbRate * p.first + 5;
        const rel = canClimb ? null : escape(s, speed, L);
        const urgent = p.first <= 2;
        const act = canClimb ? `climb ${climb}` : rel != null ? turnOf(rel) : 'turn back';
        const now_ = urgent ? ' now' : '';
        r = { level: urgent ? 'urgent' : 'caution', tShadow: p.first, climb, clock: rel != null ? clockOf(rel) : null, action: cap(act),
          text: `Blind zone ${urgent ? 'close' : 'ahead'}, ${act}${now_}`, short: cap(act) + now_,
          detail: `in ${p.first.toFixed(1)} s · needs +${Math.round(p.need)} m` };
      }
    }
    if (s.lq != null && s.lq < 70 && RANK[r.level] < RANK.caution) {
      r = { level: s.lq < 50 ? 'urgent' : 'link', text: s.lq < 50 ? 'Signal weak, turn back' : 'Signal weak',
        short: s.lq < 50 ? 'Turn back' : 'Signal weak', action: s.lq < 50 ? 'Turn back' : 'Watch the signal', detail: `link quality ${s.lq}%` };
    }
    return r;
  }

  // ------------------------------------------------------------ sound
  let ac = null, cueT = 0, quietUntil = 0;
  function audio() { if (!ac) { try { ac = new AudioContext(); } catch { ac = null; } } if (ac?.state === 'suspended') ac.resume(); return ac; }
  /** one note: freq (-> freqEnd) Hz, dur s, start in `when` s, pan -1 left .. +1 right */
  function tone(freq, dur, when = 0, vol = 0.25, { type = 'square', freqEnd = null, pan = 0, trem = 0 } = {}) {
    const a = audio(); if (!a) return;
    const o = a.createOscillator(), g = a.createGain(), t0 = a.currentTime + when;
    o.type = type; o.frequency.setValueAtTime(freq, t0);
    if (freqEnd) o.frequency.exponentialRampToValueAtTime(freqEnd, t0 + dur);
    g.gain.setValueAtTime(0, t0); g.gain.linearRampToValueAtTime(vol, t0 + 0.01);
    g.gain.setValueAtTime(vol, t0 + dur - 0.02); g.gain.linearRampToValueAtTime(0, t0 + dur);
    let out = g;
    if (trem) {                                           // tremolo: a second gain wobbled by a slow oscillator
      const tg = a.createGain(), lfo = a.createOscillator(), depth = a.createGain();
      tg.gain.value = 0.5; lfo.frequency.value = trem; depth.gain.value = 0.5;
      lfo.connect(depth).connect(tg.gain); lfo.start(t0); lfo.stop(t0 + dur + 0.05);
      g.connect(tg); out = tg;
    }
    if (pan && a.createStereoPanner) { const p = a.createStereoPanner(); p.pan.value = pan; out.connect(p); out = p; }
    o.connect(g); out.connect(a.destination); o.start(t0); o.stop(t0 + dur + 0.05);
  }
  // each sound returns its length in seconds, so two can be chained (blind + climb)
  const SOUNDS = {
    climb: (t) => { tone(450, 0.24, t, 0.22, { type: 'triangle', freqEnd: 1150 }); return 0.3; },
    climb2: (t) => { tone(450, 0.2, t, 0.22, { type: 'triangle', freqEnd: 1150 }); tone(450, 0.2, t + 0.26, 0.22, { type: 'triangle', freqEnd: 1150 }); return 0.5; },
    left: (t) => { tone(1500, 0.045, t, 0.3, { pan: -1 }); tone(1500, 0.045, t + 0.1, 0.3, { pan: -1 }); return 0.2; },
    right: (t) => { tone(1500, 0.045, t, 0.3, { pan: 1 }); tone(1500, 0.045, t + 0.1, 0.3, { pan: 1 }); return 0.2; },
    back: (t) => { tone(950, 0.18, t, 0.22, { type: 'triangle', freqEnd: 520, pan: -0.8 }); tone(850, 0.18, t + 0.22, 0.22, { type: 'triangle', freqEnd: 430, pan: 0.8 }); return 0.45; },
    blind: (t) => { tone(150, 0.13, t, 0.32, { type: 'sawtooth' }); tone(150, 0.13, t + 0.19, 0.32, { type: 'sawtooth' }); return 0.4; },
    weak: (t) => { tone(330, 0.55, t, 0.28, { type: 'sine', trem: 9 }); return 0.65; },
    lost: (t) => { tone(420, 1.2, t, 0.3); return 1.25; },
    clear: (t) => { tone(880, 0.1, t, 0.2, { type: 'sine' }); tone(1320, 0.16, t + 0.12, 0.2, { type: 'sine' }); return 0.3; },
    battery: (t) => { tone(1046, 0.1, t, 0.22, { type: 'triangle' }); tone(784, 0.1, t + 0.14, 0.22, { type: 'triangle' }); tone(523, 0.2, t + 0.28, 0.22, { type: 'triangle' }); return 0.55; },
  };
  // sounds can be switched off by group in the panel; a warning whose sounds are all off stays silent (no voice either)
  const GROUP = { climb: 'climb', climb2: 'climb', left: 'turns', right: 'turns', back: 'back', blind: 'blind', weak: 'weak', lost: 'lost', clear: 'clear', battery: 'battery' };
  const muted = (n) => cfg.muted.includes(GROUP[n]);
  const audible = (names) => names.filter((n) => !muted(n));
  function play(names, force = false) { audio(); let t = 0; for (const n of force ? names : audible(names)) t += SOUNDS[n]?.(t) ?? 0; }
  /** a warning is silent when it has sounds and they are all switched off */
  const silent = (names) => names.length > 0 && audible(names).length === 0;
  /** which sounds stand for a warning: [reason?, action] */
  function cueOf(r) {
    const a = (r.action || '').toLowerCase();
    const act = a.startsWith('climb') ? (r.climb > 40 ? 'climb2' : 'climb') : a.includes('left') ? 'left' : a.includes('right') ? 'right' : a.includes('back') ? 'back' : null;
    if (r.level === 'blind') return ['blind', act].filter(Boolean);
    if (r.level === 'outside') return ['back'];
    if (r.level === 'link' || r.detail?.startsWith('link')) return ['weak', act === 'back' ? 'back' : null].filter(Boolean);
    return act ? [act] : [];
  }
  const EVERY = { caution: 1600, urgent: 700, blind: 1300, link: 2500, outside: 4000 };
  const CLIMB_EVERY = { caution: 900, urgent: 600, blind: 800 };   // the climb sweep repeats faster than the other sounds
  let cueN = 0, climbN = 0;
  const BEEP = { caution: [900, () => tone(880, 0.09)], urgent: [300, () => tone(1320, 0.08)],
    blind: [650, () => { tone(1100, 0.08); tone(700, 0.1, 0.12); }], link: [1400, () => tone(600, 0.12)] };
  function soundLoop(now) {
    if (cfg.mode === 'off' || now < quietUntil) return;
    if (cfg.mode === 'voice') {                           // old behaviour: plain beeps, faster = closer
      const b = BEEP[last.level];
      if (b && !silent(cueOf(last)) && now - cueT >= b[0]) { cueT = now; b[1](); }
      return;
    }
    let names = cueOf(last);
    const climbing = names.some((n) => n === 'climb' || n === 'climb2');
    // climbing: the sweep repeats fast for as long as you still have to climb; with no line of sight the buzz
    // only comes every 3rd time so the climb stays easy to follow
    const every = last.detail?.startsWith('link') ? 2000 : climbing ? CLIMB_EVERY[last.level] : EVERY[last.level];
    if (!every || now - cueT < every) return;
    cueT = now;
    // mixed mode: after three climb sounds the voice says "Climb", then the sounds go on (sweep, sweep, sweep, "Climb", ...)
    if (climbing && cfg.mode === 'mixed' && climbN >= 3 && 'speechSynthesis' in window) {
      climbN = 0; speechSynthesis.cancel(); say('Climb'); return;
    }
    if (climbing && names.length > 1 && cueN++ % 3 !== 0) names = names.filter((n) => n !== 'blind');
    if (climbing && !muted('climb')) climbN++;
    play(names);
  }
  const speaks = () => cfg.mode === 'mixed' || cfg.mode === 'voice';
  function say(text, interrupt) {
    if (!speaks() || !text || !('speechSynthesis' in window)) return;
    if (interrupt) speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.15; u.lang = 'en-US';
    const v = speechSynthesis.getVoices().find((x) => /^en/i.test(x.lang));
    if (v) u.voice = v;
    speechSynthesis.speak(u);
    quietUntil = performance.now() + Math.min(3000, 600 + text.length * 55);   // let the sentence finish before the sounds go on
  }

  // ------------------------------------------------------------ screen (spotter)
  // the box on screen: full, compact (a small tag in the corner, only while there is a warning) or off.
  // Clicking it switches full <-> compact.
  if (el?.box && !el.box.dataset.bound) {
    el.box.dataset.bound = '1';
    el.box.title = 'Click: smaller / bigger';
    el.box.addEventListener('click', () => { cfg.screen = cfg.screen === 'full' ? 'compact' : 'full'; save(); render(last); });
  }
  function render(r) {
    if (!el) return;
    el.box.dataset.size = cfg.screen;
    el.box.classList.toggle('hidden', !active || cfg.screen === 'off' || (cfg.screen === 'compact' && r.level === 'ok'));
    el.box.style.background = COLORS[r.level] || COLORS.ok;
    el.title.textContent = r.level === 'urgent' && r.detail?.startsWith('link') ? 'SIGNAL VERY WEAK'
      : { ok: 'Line of sight OK', link: 'SIGNAL WEAK', outside: 'OUTSIDE THE MAP', caution: 'BLIND ZONE AHEAD', urgent: 'BLIND ZONE CLOSE', blind: 'NO LINE OF SIGHT', lost: 'SIGNAL LOST' }[r.level];
    el.text.textContent = r.level === 'ok' ? r.detail : r.action || r.text;
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
      if (r.level === 'ok' && RANK[last.level] >= RANK.caution) {
        lastKind = '';
        if (cfg.mode === 'voice') { if (!muted('clear')) say('Clear', true); }
        else if (cfg.mode !== 'off' && !muted('clear')) { if ('speechSynthesis' in window) speechSynthesis.cancel(); quietUntil = 0; play(['clear']); }
      } else if (r.level !== 'ok') {
        const kind = `${r.level}:${(r.action || '').replace(/\d+/g, '#')}`;      // same situation, maybe another number
        const newKind = kind !== lastKind;
        if (cfg.mode === 'voice') {
          // full sentence ("Blind zone ahead, climb 30") when the situation is new, only the action ("Climb 35") when it goes on
          const every = r.level === 'caution' || r.level === 'link' ? 8000 : 4000;
          if (!silent(cueOf(r)) && (rose || now - lastSpoke > every || (r.text !== lastText && now - lastSpoke > 2500))) {
            say(rose || newKind ? r.text : r.short || r.text, rose); lastSpoke = now; lastText = r.text;
          }
        } else if (rose || newKind) {
          // mixed: the sentence once, then the sounds; sounds only: the sound right away
          if (cfg.mode === 'mixed' && !silent(cueOf(r))) say(r.text, true);
          else if (cfg.mode === 'sounds') { cueT = now; play(cueOf(r)); }
          cueT = now;
        }
        if (newKind) { cueN = 1; climbN = cfg.mode === 'sounds' && cueOf(r).some((n) => n.startsWith('climb')) ? 1 : 0; }                            // the first sound (with the buzz) was just played or spoken
        lastKind = kind;
      }
      last = r;
      render(r);
      return r;
    },
    tick(now) { if (active) soundLoop(now); },
    /** battery telemetry b = { voltage, current, mah }: speaks / plays a battery warning when one is due; returns it */
    battery(b, now = performance.now()) {
      const ev = BW.update(b, now);
      if (!ev || cfg.mode === 'off' || muted('battery')) return ev;
      if (cfg.mode === 'sounds') { play(ev.level === 'critical' ? ['battery', 'battery'] : ['battery']); return ev; }
      play(['battery']);
      setTimeout(() => say(ev.text, ev.level === 'critical'), 600);
      return ev;
    },
    bat: BW,
    lost(info) {
      last = { level: 'lost', text: info || 'Telemetry stopped', action: 'Last position marked on the map', detail: info || 'no telemetry for 1.5 s' };
      if (cfg.mode !== 'off' && !muted('lost')) { if ('speechSynthesis' in window) speechSynthesis.cancel(); play(['lost']); }
      if (speaks() && !muted('lost')) setTimeout(() => say('Signal lost', true), 1300);
      render(last);
    },
    stop() { active = false; last = { level: 'ok' }; render(last); if ('speechSynthesis' in window) speechSynthesis.cancel(); },
    unlock() { audio(); },
    /** play one command sound (sound board) */
    play(name) { play(SOUNDS[name] ? [name] : cueOf(name), true); },
    /** switch a sound group on/off: climb, turns, back, blind, weak, lost, clear */
    setMuted(group, off) { cfg.muted = cfg.muted.filter((g) => g !== group); if (off) cfg.muted.push(group); save(); },
    test() {
      if (cfg.mode === 'voice') { audio(); tone(880, 0.09); say('Blind zone ahead, climb 30'); return; }
      if (cfg.mode === 'mixed') say('Blind zone ahead, climb 30');
      setTimeout(() => play(['climb']), cfg.mode === 'mixed' ? 2200 : 0);
    },
    get level() { return last.level; },
    /** a one-off spoken note (page hidden, takeoff far from the pilot point): voice when it speaks, else a tone */
    notice(text) {
      if (cfg.mode === 'off') return;
      if (speaks()) say(text, false); else { audio(); tone(660, 0.18); tone(520, 0.22, 0.24); }
    },
    /** what is switched off, so a live flight never starts silent without saying so */
    silentSummary() {
      const names = { climb: 'climb', turns: 'left / right', back: 'turn back', blind: 'no sight', weak: 'signal weak', lost: 'signal lost', clear: 'clear', battery: 'battery' };
      const out = [];
      if (cfg.mode === 'off') out.push('all warning sounds and voice are off');
      else {
        if (cfg.mode === 'sounds') out.push('no voice (sounds only)');
        if (cfg.muted.length) out.push(`sounds off: ${cfg.muted.map((g) => names[g] || g).join(', ')}`);
      }
      if (cfg.screen === 'off') out.push('no warning box on screen');
      return out;
    },
    setScreen(v) { cfg.screen = v; save(); render(last); },
  };
}
