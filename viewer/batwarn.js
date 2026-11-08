// fpv3d — battery warnings during a live flight, from the radio's telemetry (voltage, current, mAh used).
// Pure logic (no sound, no page): warn.js speaks / plays what it returns, tests/test_warn.mjs checks it.
//
//   half      half the pack used (mAh)                              "Half pack"                      once
//   land      the planned share used (default 80 % of the capacity)  "Land now, 1040 milliamp hours"  then every 30 s
//   low       cells under the low level under load for 2 s          "Battery low, land"              every 20 s while it lasts
//   critical  resting voltage under 3.4 V/cell, or 0.3 V under low  "Battery critical, land now"     every 10 s
// Cells: from the chosen pack, else Betaflight's rule on the first voltage (plugged in, no load).
// The resting voltage is the voltage plus the sag (current x resistance): the pack's resistance from its flights,
// else a typical 5 mΩ per cell.

export const BAT_DEFAULTS = { on: true, cells: 0, capacity: 0, landPct: 80, low: 3.3, half: true, irCell: 0 };

export function createBatteryWatch(cfg = {}) {
  const c = { ...BAT_DEFAULTS, ...cfg };
  const st = { cells: c.cells || 0, lowSince: null, critSince: null, said: {}, last: null };
  function cellsFrom(v) { return Math.min(8, Math.floor(v / 4.3) + 1); }
  return {
    cfg: c,
    get cells() { return st.cells; },
    get status() { return st.last; },
    reset() { st.cells = c.cells || 0; st.lowSince = st.critSince = null; st.said = {}; st.last = null; },
    set(o) { Object.assign(c, o); if (o.cells) st.cells = o.cells; },
    /** b = { voltage (V), current (A) | null, mah | null }, now in ms -> { kind, text, short, level } or null */
    update(b, now) {
      if (!c.on || b?.voltage == null || !(b.voltage > 1)) return null;
      if (!st.cells) st.cells = c.cells || cellsFrom(b.voltage);
      const n = st.cells, cell = b.voltage / n, amps = Math.max(0, b.current || 0);
      const r = (c.irCell || 5) / 1000;
      const rest = cell + amps * r;
      const used = b.mah != null && c.capacity ? b.mah / c.capacity : null;
      st.last = { cell, rest, amps, mah: b.mah, used, cells: n };
      const again = (k, every) => !st.said[k] || now - st.said[k] >= every;
      const fire = (k, ev) => { st.said[k] = now; return { kind: k, ...ev }; };
      // critical first
      const crit = rest < 3.4 || cell < c.low - 0.3;
      st.critSince = crit ? (st.critSince ?? now) : null;
      if (crit && now - st.critSince >= 1000 && again('critical', 10000)) {
        return fire('critical', { level: 'critical', text: 'Battery critical, land now', short: 'Land now' });
      }
      const low = cell < c.low;
      st.lowSince = low ? (st.lowSince ?? now) : null;
      if (low && now - st.lowSince >= 2000 && again('low', 20000)) {
        return fire('low', { level: 'low', text: 'Battery low, land', short: 'Battery low' });
      }
      if (used != null && used >= c.landPct / 100 && again('land', 30000)) {
        const first = !st.said.land;
        return fire('land', { level: 'land', text: first ? `Land now, ${Math.round(b.mah)} milliamp hours` : 'Land now', short: 'Land now' });
      }
      if (c.half && used != null && used >= 0.5 && !st.said.half) {
        return fire('half', { level: 'info', text: 'Half pack', short: 'Half pack' });
      }
      return null;
    },
  };
}
