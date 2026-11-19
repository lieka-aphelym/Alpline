// fpv3d: automated checks for the pilot warnings (warn.js) and the small pure helpers (radio range, file names).
// No browser, no 3D, no sound card: the scene, the clock, the speech and the audio are fakes, so every case is the
// same each time. Runs two ways:
//   python tests/run_all.py            (uses Node when it is installed)
//   http://localhost:8000/viewer/test/  (any browser, while the server runs)
import { createWarner } from '../js/drone/warn.js';
import { linkBudget, rangeFor, presetIndex, presetKind, presetValues, PRESETS, fsplDb } from '../js/view/links.js';
import { slugify, noEmoji } from '../js/view/rename.js';
import { telName } from '../js/view/hud.js';
import { createBatteryWatch } from '../js/battery/batwarn.js';

// ------------------------------------------------------------ fakes
// Terrain flat at 1000 m. The scene is 2000 x 2000 m. East of x = 1000 a hill blocks the view: no line of sight
// below 30 m above ground (from x = 1500: below 200 m, too high to climb, so the warning must say turn).
const GROUND = 1000;
const ceilAt = (_k, x) => (x >= 1500 ? 200 : x >= 1000 ? 30 : 0);
function fakeScene({ vol = true } = {}) {
  return { S: { W: 2000, H: 2000, vol: vol ? { ceilAt } : null }, demHeight: () => GROUND };
}
function installFakes() {
  const g = globalThis, saved = {}, rec = { tones: [], spoken: [], clock: 10000 };
  const put = (k, v) => { saved[k] = Object.getOwnPropertyDescriptor(g, k); Object.defineProperty(g, k, { value: v, configurable: true, writable: true }); };
  const store = new Map();
  put('localStorage', { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) });
  put('performance', { now: () => rec.clock });
  class Param { constructor() { this.value = 0; } setValueAtTime(v) { this.first ??= v; this.value = v; } linearRampToValueAtTime() {} exponentialRampToValueAtTime() {} }
  class Node_ { connect(x) { return x; } }
  put('AudioContext', class {
    constructor() { this.currentTime = 0; this.state = 'running'; this.destination = new Node_(); }
    createOscillator() { const o = new Node_(); o.type = 'sine'; o.frequency = new Param(); o.start = () => rec.tones.push({ f: o.frequency.first, type: o.type }); o.stop = () => {}; return o; }
    createGain() { const n = new Node_(); n.gain = new Param(); return n; }
    createStereoPanner() { const n = new Node_(); n.pan = new Param(); return n; }
  });
  put('SpeechSynthesisUtterance', class { constructor(t) { this.text = t; } });
  put('speechSynthesis', { speak: (u) => rec.spoken.push(u.text), cancel: () => {}, getVoices: () => [] });
  if (typeof g.window === 'undefined') put('window', g);
  rec.restore = () => { for (const [k, d] of Object.entries(saved)) { if (d) Object.defineProperty(g, k, d); else delete g[k]; } };
  return rec;
}
// which command sound a tone belongs to (first note of each sound in warn.js)
const SOUND_OF = (t) => (t.f === 450 ? 'climb' : t.f === 1500 ? 'turn' : t.f === 950 ? 'back' : t.f === 150 ? 'blind'
  : t.f === 330 ? 'weak' : t.f === 420 ? 'lost' : t.f === 880 && t.type === 'sine' ? 'clear' : t.f === 1046 ? 'battery'
  : t.f === 1320 || t.f === 784 || t.f === 523 ? null : `?${t.f}`);
const sounds = (rec) => rec.tones.map(SOUND_OF).filter(Boolean);

// drone states (x east, y north, z AMSL, velocity m/s, heading deg)
const st = (o) => ({ x: 500, y: 1000, z: GROUND + 50, vx: 0, vy: 0, vz: 0, heading: 90, ...o });
const east = (x, speed, agl = 20) => st({ x, z: GROUND + agl, vx: speed, heading: 90 });

// ------------------------------------------------------------ cases
const CASES = [];
const test = (name, fn) => CASES.push({ name, fn });
function eq(a, b, what = '') { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${what} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); }
function ok(c, what) { if (!c) throw new Error(what); }

function warner(mode = 'mixed', opts = {}) {
  const { S, demHeight } = fakeScene(opts);
  const w = createWarner({ S, demHeight, el: null });
  w.cfg.mode = mode;
  return w;
}

// --- what the warning says (evaluate)
test('no 3D shadow data: never warns, says why', () => {
  const r = warner('mixed', { vol: false }).evaluate(st({}));
  eq(r.level, 'ok'); ok(/no 3D shadow/.test(r.detail), 'detail should explain');
});
test('on the ground: quiet', () => eq(warner().evaluate(st({ z: GROUND + 1 })).level, 'ok'));
test('hovering in sight: ok', () => eq(warner().evaluate(st({})).level, 'ok'));
test('outside the map is never "in sight"', () => {
  const r = warner().evaluate(st({ x: -50 }));
  eq(r.level, 'outside'); eq(r.action, 'Turn back to the map');
});
test('no line of sight now, small climb: "climb N" rounded up to 5 with the margin', () => {
  const r = warner().evaluate(st({ x: 1200, z: GROUND + 20 }));      // 10 m below the 30 m ceiling, +5 margin
  eq(r.level, 'blind'); eq(r.climb, 15); eq(r.action, 'Climb 15'); eq(r.text, 'No line of sight, climb 15');
});
test('no line of sight, too high to climb: a turn with a clock direction', () => {
  const r = warner().evaluate(st({ x: 1600, z: GROUND + 20, vx: 10, heading: 90 }));
  eq(r.level, 'blind'); ok(r.climb > 60, 'climb > 60');
  ok(/^(Turn|Bear) (left|right)$|^Turn back$/.test(r.action), `turn action, got ${r.action}`);
  ok(r.clock == null || (r.clock >= 1 && r.clock <= 12), 'clock 1..12');
});
test('blind zone in ~3 s: caution, climb ahead of time', () => {
  const r = warner().evaluate(east(940, 20));                          // reaches x = 1000 after 3 s
  eq(r.level, 'caution'); eq(r.action, 'Climb 15'); ok(Math.abs(r.tShadow - 3) < 0.3, `tShadow ${r.tShadow}`);
});
test('blind zone in ~1.5 s: urgent, "now"', () => {
  const r = warner().evaluate(east(970, 20));
  eq(r.level, 'urgent'); eq(r.short, 'Climb 15 now'); ok(/close/.test(r.text), 'says close');
});
test('blind zone beyond the look-ahead: no warning yet', () => eq(warner().evaluate(east(800, 20)).level, 'ok'));
test('flying away from the hill: ok', () => eq(warner().evaluate(st({ x: 950, z: GROUND + 20, vx: -20, heading: 270 })).level, 'ok'));
test('weak link (LQ 60): "Signal weak"; very weak (LQ 40): turn back', () => {
  const w = warner();
  eq(w.evaluate(st({ lq: 60 })).level, 'link');
  const r = w.evaluate(st({ lq: 40 }));
  eq(r.level, 'urgent'); eq(r.action, 'Turn back');
});
test('no line of sight wins over a weak link', () => eq(warner().evaluate(st({ x: 1200, z: GROUND + 20, lq: 40 })).level, 'blind'));
test('the look-ahead setting is used', () => {
  const w = warner(); w.cfg.lookahead = 2;
  eq(w.evaluate(east(940, 20)).level, 'ok');
});

// --- what the pilot hears (update + tick)
function fly(rec, w, states, ms = 100) {           // feed states every `ms`, tick the sound loop like live.js does
  for (const s of states) { rec.clock += ms; w.update(s); w.tick(rec.clock); }
}
const repeat = (s, n) => Array.from({ length: n }, () => s);
test('mixed: the sentence once, then the climb sound repeats, "Climb" after three sounds', (rec) => {
  const w = warner('mixed');
  fly(rec, w, repeat(east(940, 20), 1));
  eq(rec.spoken, ['Blind zone ahead, climb 15'], 'first');
  fly(rec, w, repeat(st({ x: 1200, z: GROUND + 20 }), 60));   // stay below the line of sight for 6 s
  ok(rec.spoken.filter((t) => t.startsWith('No line of sight')).length === 1, `sentence once: ${rec.spoken}`);
  ok(sounds(rec).filter((n) => n === 'climb').length >= 3, `climb sounds: ${sounds(rec)}`);
  ok(rec.spoken.includes('Climb'), `spoken "Climb" after 3 sounds: ${rec.spoken}`);
});
test('sounds only: never speaks, plays the climb sound right away', (rec) => {
  const w = warner('sounds');
  fly(rec, w, repeat(east(940, 20), 30));
  eq(rec.spoken, []); ok(sounds(rec)[0] === 'climb', `first sound ${sounds(rec)[0]}`);
});
test('back in sight after a warning: the "clear" sound', (rec) => {
  const w = warner('sounds');
  fly(rec, w, [east(940, 20)]);
  fly(rec, w, [st({})]);
  eq(sounds(rec).at(-1), 'clear');
});
test('a muted group stays silent: no sound and no voice for it', (rec) => {
  const w = warner('mixed'); w.setMuted('climb', true);
  fly(rec, w, repeat(east(940, 20), 30));
  eq(rec.spoken, []); ok(!sounds(rec).includes('climb'), 'no climb sound');
});
test('mode off: nothing at all', (rec) => {
  const w = warner('off');
  fly(rec, w, repeat(st({ x: 1200, z: GROUND + 20 }), 30));
  eq(rec.spoken, []); eq(sounds(rec), []);
});
test('telemetry lost: the long tone (even with everything else muted)', (rec) => {
  const w = warner('sounds'); ['climb', 'turns', 'back', 'blind', 'weak', 'clear'].forEach((g) => w.setMuted(g, true));
  w.lost('no telemetry');
  eq(sounds(rec), ['lost']); eq(w.level, 'lost');
});
test('settings are saved and come back', () => {
  const w = warner('sounds'); w.setMuted('turns', true); w.setScreen('compact');
  const { S, demHeight } = fakeScene();
  const w2 = createWarner({ S, demHeight, el: null });
  eq(w2.cfg.muted, ['turns']); eq(w2.cfg.screen, 'compact');
});
test('a flight never starts silent without saying so', () => {
  const w = warner('sounds'); w.setMuted('climb', true); w.setScreen('off');
  const out = w.silentSummary();
  ok(out.some((t) => /no voice/.test(t)) && out.some((t) => /climb/.test(t)) && out.some((t) => /no warning box/.test(t)), out.join(' | '));
  w.cfg.mode = 'off';
  ok(w.silentSummary()[0].includes('all warning sounds'), 'off is reported');
});
test('broken saved settings fall back to safe defaults', () => {
  localStorage.setItem('fpv3d:warn', JSON.stringify({ mode: 'loud', muted: 'x', screen: 'huge' }));
  const { S, demHeight } = fakeScene();
  const w = createWarner({ S, demHeight, el: null });
  eq([w.cfg.mode, w.cfg.muted, w.cfg.screen], ['mixed', [], 'full']);
});

// --- battery (live telemetry)
const pack6 = (o = {}) => createBatteryWatch({ cells: 6, capacity: 1300, landPct: 80, low: 3.3, ...o });
test('battery: cells from the first voltage (Betaflight rule) when no pack is chosen', () => {
  for (const [v, n] of [[25.2, 6], [22.0, 6], [16.8, 4], [12.6, 3], [18.0, 5]]) {
    const w = createBatteryWatch(); w.update({ voltage: v, current: 0.5, mah: 0 }, 0); eq(w.cells, n);
  }
});
test('battery: half pack once, then land at 80 % with the mAh, repeated every 30 s', () => {
  const w = pack6(), said = [];
  for (let t = 0, mah = 0; t <= 400000; t += 1000, mah += 3) {
    const ev = w.update({ voltage: 6 * 3.8, current: 20, mah }, t);
    if (ev) said.push([Math.round(t / 1000), ev.text]);
  }
  eq(said[0], [217, 'Half pack']);
  eq(said[1], [347, 'Land now, 1041 milliamp hours']);
  eq(said[2], [377, 'Land now']);
  eq(said.filter(([, x]) => x === 'Half pack').length, 1);
});
test('battery: a short sag is not low; 2 s under the level is, repeated every 20 s', () => {
  const w = pack6();
  ok(w.update({ voltage: 6 * 3.25, current: 60, mah: 100 }, 0) === null, 'first moment');
  ok(w.update({ voltage: 6 * 3.6, current: 10, mah: 100 }, 1500) === null, 'recovered');
  ok(w.update({ voltage: 6 * 3.25, current: 60, mah: 110 }, 3000) === null, 'new dip');
  eq(w.update({ voltage: 6 * 3.25, current: 60, mah: 120 }, 5100)?.text, 'Battery low, land');
  ok(w.update({ voltage: 6 * 3.25, current: 60, mah: 130 }, 10000) === null, 'not again so soon');
  eq(w.update({ voltage: 6 * 3.25, current: 60, mah: 140 }, 25200)?.kind, 'low');
});
test('battery: critical when the resting voltage is under 3.4 V/cell', () => {
  const w = pack6({ irCell: 5 });
  ok(w.update({ voltage: 6 * 3.35, current: 2, mah: null }, 0) === null, 'needs 1 s');
  const ev = w.update({ voltage: 6 * 3.35, current: 2, mah: 900 }, 1200);
  eq([ev?.kind, ev?.text], ['critical', 'Battery critical, land now']);
});
test('battery: Li-ion levels: 3.1 V/cell is fine, under 2.9 V under load is low', () => {
  const li = pack6({ low: 2.9, critRest: 3.1, chemistry: 'liion' }), po = pack6();
  let liSaid = null, poSaid = null;
  for (let t = 0; t <= 3000; t += 500) { liSaid ||= li.update({ voltage: 6 * 3.1, current: 10, mah: null }, t); poSaid ||= po.update({ voltage: 6 * 3.1, current: 10, mah: null }, t); }
  ok(liSaid === null, 'Li-ion at 3.1 V: nothing'); eq(poSaid?.kind, 'critical');
  let low = null; for (let t = 10000; t <= 13000; t += 500) low ||= li.update({ voltage: 6 * 2.85, current: 30, mah: null }, t);
  eq(low?.kind, 'low');
});
test('battery: no capacity -> no mAh warnings; off -> nothing; no voltage -> nothing', () => {
  const w = createBatteryWatch({ cells: 6 });
  ok(w.update({ voltage: 22, current: 10, mah: 5000 }, 0) === null, 'no capacity');
  ok(pack6({ on: false }).update({ voltage: 18, current: 10, mah: 1200 }, 0) === null, 'off');
  ok(pack6().update({ voltage: null, current: 10, mah: 1200 }, 0) === null, 'no voltage');
});
test('battery: the warner speaks it after its sound; muted group stays silent', (rec) => {
  const { S, demHeight } = fakeScene();
  const w = createWarner({ S, demHeight, el: null });
  w.bat.set({ cells: 6, capacity: 1300 });
  w.battery({ voltage: 22.8, current: 15, mah: 700 }, 0);
  eq(sounds(rec), ['battery']);
  rec.tones.length = 0; w.setMuted('battery', true);
  ok(w.battery({ voltage: 22.8, current: 15, mah: 1100 }, 50000)?.kind === 'land', 'still reported');
  eq(sounds(rec), []);
});

// --- radio range, file names, info box
test('radio: range grows 2x for +6 dB, and matches free-space loss', () => {
  const l = { tx_power_dbm: 14, tx_gain_dbi: 2, rx_gain_dbi: 2, misc_losses_db: 1, rx_sensitivity_dbm: -90, fade_margin_db: 10 };
  const b = linkBudget(l), r = rangeFor(b, 5800);
  ok(Math.abs(fsplDb(r, 5800) - b) < 1e-6, 'fspl(range) = budget');
  const r2 = rangeFor(linkBudget({ ...l, tx_gain_dbi: 8 }), 5800);
  ok(Math.abs(r2 / r - 2) < 0.01, `ratio ${r2 / r}`);
});
test('radio: presets are recognised by band', () => {
  eq([presetKind(5800), presetKind(2400), presetKind(868), presetKind(1300)], ['video', 'ctl24', 'ctl900', 'other']);
  eq(presetIndex({ freq_mhz: 5800, tx_power_dbm: 10 * Math.log10(500), tx_gain_dbi: 2, rx_gain_dbi: 8 }), 4);
  eq(presetIndex({ freq_mhz: 5800, tx_power_dbm: 20, tx_gain_dbi: 7, rx_gain_dbi: 7 }), -1);
});
test('radio: a digital system reaches the range its maker gives, and is recognised again', () => {
  for (const pr of PRESETS.video.filter((x) => x.km)) {
    const v = presetValues(pr, 5800, 'video').values, km = rangeFor(linkBudget(v), 5800) / 1000;
    ok(Math.abs(km - pr.km) / pr.km < 0.05, `${pr.label}: ${km.toFixed(2)} km, rated ${pr.km} km`);
    eq(presetIndex({ freq_mhz: 5800, ...v }), PRESETS.video.indexOf(pr), pr.label);
  }
  const o4 = PRESETS.video.find((x) => x.label?.startsWith('DJI O4 Air Unit · CE'));
  ok(rangeFor(linkBudget(presetValues(o4, 5800, 'video').values), 5800) > 5 * rangeFor(linkBudget(presetValues(PRESETS.video[0], 5800, 'video').values), 5800),
    'the O4 reaches far beyond 25 mW analog');
});
test('file names: clean ASCII, no emoji', () => {
  eq(slugify('Vol à Gruyères #2 🚁'), 'vol_a_gruyeres_2');
  eq(noEmoji('Col 🏔️  du Pillon'), 'Col du Pillon');
});
test('info box: simulator columns hidden, known columns named', () => {
  eq(telName('RQly_%'), 'Control LQ|%'); eq(telName('LQ_sim_Video_5_8'), null); eq(telName('my_col'), 'my col');
});

// ------------------------------------------------------------ runner
export async function runAll(log = console.log) {
  let passed = 0; const failed = [];
  for (const c of CASES) {
    const rec = installFakes();
    try { await c.fn(rec); passed++; log(`  ok    ${c.name}`); }
    catch (e) { failed.push(c.name); log(`  FAIL  ${c.name}\n        ${e.message}`); }
    finally { rec.restore(); }
  }
  log(`${passed} passed, ${failed.length} failed`);
  return { passed, failed };
}
