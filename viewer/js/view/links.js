import { esc } from '../core/esc.js';
// fpv3d viewer: the radio link editor (transmit power, antennas -> range). Changes apply right away to the range
// spheres, the rings on the terrain, the signal-loss shadows, the track colours and the warnings; [save] writes
// them into the location file and rebuilds the shadows. Unsaved edits stay in this browser (localStorage).
export const fsplDb = (d, f) => 20 * Math.log10(Math.max(d, 1) / 1000) + 20 * Math.log10(f) + 32.44;
export const LINK_KEYS = ['tx_power_dbm', 'tx_gain_dbi', 'rx_gain_dbi', 'rx_sensitivity_dbm', 'misc_losses_db', 'fade_margin_db'];
export const MW = [25, 50, 100, 200, 250, 350, 400, 500, 600, 700, 800, 1000, 1200, 1600, 2000];
export const ANT = [
  ['', 'custom'], [2, 'dipole / pagoda / lollipop (2 dBi)'], [3, 'stubby or omni+ (3 dBi)'], [5, 'small patch (5 dBi)'],
  [8, 'patch (8 dBi)'], [10, 'helical / moxon (10 dBi)'], [12, 'big helical (12 dBi)'], [14, 'yagi / tracker (14 dBi)'],
];
// ready-made setups. Analog video and the control links: [label, mW, tx antenna dBi, rx antenna dBi, group].
// Analog video sets a typical analog receiver (ANALOG_SENS: also to come back from a digital system); the control
// links keep the location's own sensitivity, losses and margin (under Advanced), as before.
// Digital video systems: { label, mw, tg, rg, km, by, group } with the range the maker gives for an open field
// without interference (km): the receiver sensitivity is then set so that the free-space range with the usual
// losses and safety margin comes out at that figure. Digital systems decode far weaker signals than analog
// (narrow channels, error correction), which a plain sensitivity in dBm would not capture.
// (video: tx = drone, rx = goggles · control: tx = radio, rx = drone)
const ANALOG_SENS = -90, MISC = 3, FADE = 10;
const digital = (label, mw, km, by) => ({ label, mw, tg: 2, rg: 2, km, by, group: label.split(' ')[0] });
export const PRESETS = {
  video: [
    ['25 mW · stock antennas (CH / EU limit)', 25, 2, 2, 'Analog'],
    ['25 mW · patch on the goggles', 25, 2, 8, 'Analog'],
    ['200 mW · stock antennas', 200, 2, 2, 'Analog'],
    ['500 mW · stock antennas', 500, 2, 2, 'Analog'],
    ['500 mW · patch on the goggles', 500, 2, 8, 'Analog'],
    ['1 W · helical on the goggles', 1000, 3, 12, 'Analog'],
    digital('DJI O4 Air Unit · CE (CH / EU)', 25, 6, 'DJI, CE'),
    digital('DJI O4 Air Unit Pro · CE (CH / EU)', 25, 8, 'DJI, CE'),
    digital('DJI O3 Air Unit · CE (CH / EU)', 25, 2, 'DJI, CE'),
    digital('DJI O3 / O4 Air Unit · FCC', 1000, 10, 'DJI, FCC'),            // the same rated range: one choice
    digital('DJI O4 Air Unit Pro · FCC', 1000, 15, 'DJI, FCC'),
    digital('Walksnail Avatar HD Pro', 500, 4, 'Caddx / Walksnail'),
  ],
  ctl24: [
    ['100 mW · stock antennas (CH / EU limit)', 100, 2, 2],
    ['250 mW · stock antennas', 250, 2, 2],
    ['500 mW · stock antennas', 500, 2, 2],
    ['1 W · stock antennas', 1000, 2, 2],
    ['1 W · directional on the radio', 1000, 8, 2],
  ],
  ctl900: [
    ['25 mW · stock antennas (common EU limit)', 25, 2, 2],
    ['100 mW · stock antennas', 100, 2, 2],
    ['250 mW · stock antennas', 250, 2, 2],
    ['1 W · stock antennas', 1000, 2, 2],
  ],
  other: [['25 mW · stock antennas', 25, 2, 2], ['100 mW · stock antennas', 100, 2, 2], ['500 mW · stock antennas', 500, 2, 2], ['1 W · stock antennas', 1000, 2, 2]],
};
export const presetKind = (f) => (f >= 5000 ? 'video' : f >= 2300 && f <= 2500 ? 'ctl24' : f >= 800 && f <= 1000 ? 'ctl900' : 'other');
/** A preset as the full set of radio values for a link on `freqMhz`. */
export function presetValues(pr, freqMhz, kind) {
  const o = Array.isArray(pr) ? { label: pr[0], mw: pr[1], tg: pr[2], rg: pr[3], group: pr[4] } : pr;
  const tx = 10 * Math.log10(o.mw);
  let sens = kind === 'video' ? ANALOG_SENS : null;
  if (o.km) sens = Math.round((tx + o.tg + o.rg - MISC - FADE - (20 * Math.log10(o.km) + 20 * Math.log10(freqMhz) + 32.44)) * 2) / 2;
  const rest = sens == null ? {} : { rx_sensitivity_dbm: sens, misc_losses_db: MISC, fade_margin_db: FADE };
  return { ...o, values: { tx_power_dbm: +tx.toFixed(2), tx_gain_dbi: o.tg, rx_gain_dbi: o.rg, ...rest } };
}
export function presetIndex(l) {
  const k = presetKind(l.freq_mhz);
  return PRESETS[k].findIndex((pr) => {
    const v = presetValues(pr, l.freq_mhz, k).values;
    const same = (a, b, t) => Math.abs(a - b) <= t;
    return same(v.tx_power_dbm, l.tx_power_dbm, 0.15) && same(v.tx_gain_dbi, l.tx_gain_dbi, 0.26) && same(v.rx_gain_dbi, l.rx_gain_dbi, 0.26)
      // video: the sensitivity tells a digital system from analog with the same power (none given: analog)
      && (v.rx_sensitivity_dbm == null || (l.rx_sensitivity_dbm == null ? !pr.km : same(v.rx_sensitivity_dbm, l.rx_sensitivity_dbm, pr.km ? 0.6 : 3)));
  });
}
/** link budget in dB above free-space loss at 1 km... (tx + gains - losses - sensitivity - margin) */
export const linkBudget = (l) => l.tx_power_dbm + l.tx_gain_dbi + l.rx_gain_dbi - l.misc_losses_db - l.rx_sensitivity_dbm - l.fade_margin_db;
export const hasParams = (l) => LINK_KEYS.every((k) => typeof l[k] === 'number');
/** range in metres where the free-space loss uses up the budget */
export const rangeFor = (budgetDb, freqMhz) => Math.pow(10, (budgetDb - 20 * Math.log10(freqMhz) - 32.44) / 20) * 1000;

/** The line under a setup: where its range comes from. */
export function noteFor(p) {
  if (!p) return 'Your own values (Advanced).';
  if (p.km) return `Open-field range as rated by ${esc(p.by)}: ${p.km} km. Real flights: less behind terrain, trees and with interference.`;
  return p.group === 'Analog' ? 'Analog video: a typical receiver; the picture gets noisy before it is lost.' : 'A typical receiver.';
}

export function createLinks({ S, $, fmtDist, maxLinks, onShadows, onTracks }) {
  const linkKey = () => `fpv3d:links:${S.meta.name}`;

  function loadLinkOverrides() { try { return JSON.parse(localStorage.getItem(linkKey()) || '{}'); } catch { return {}; } }
  function saveLinkOverrides(ov) { try { localStorage.setItem(linkKey(), JSON.stringify(ov)); } catch { /* ignore */ } }

  /** Apply edited radio values: sphere sizes, terrain rings, simulator, and track margins (shifted by the budget change). */
  function applyLinks() {
    const ov = loadLinkOverrides();
    S.linkDelta = {};
    S.links0.forEach((l0, i) => {
      const l = { ...l0, ...(ov[l0.name] || {}) };
      const b0 = hasParams(l0) ? linkBudget(l0) : fsplDb(l0.range_m, l0.freq_mhz);
      const b = hasParams(l) ? linkBudget(l) : b0;
      l.range_m = rangeFor(b, l.freq_mhz);
      S.meta.links[i] = l;
      S.linkDelta[l.name] = b - b0;
      const sp = S.spheres[i]; if (sp) { sp.userData.k = l.range_m / l0.range_m; sp.scale.set(sp.userData.k, sp.userData.k * S.exag, sp.userData.k); }
      if (i < maxLinks) S.terrainMat.uniforms.uRanges.value.setComponent(i, l.range_m);
      const r = $(`lnkRange${i}`);
      if (r) r.innerHTML = Math.abs(b - b0) > 0.05 ? `<b style="color:var(--warn)">${fmtDist(l.range_m)}</b> <span class="muted">(${b > b0 ? '+' : ''}${(b - b0).toFixed(1)} dB)</span>` : fmtDist(l.range_m);
    });
    const dirty = Object.values(S.linkDelta).some((d) => Math.abs(d) > 0.05);
    $('lnkDirty')?.classList.toggle('hidden', !dirty);
    if (S.vol) {                            // predicted-loss shadows (2D + 3D) follow the edited budget
      const name = S.vol.link || S.meta.links[S.meta.primary_link].name, want = S.linkDelta[name] || 0;
      const r = S.vol.setLossDelta(want);
      onShadows();
      const note = $('lnkShadowNote');
      if (note) note.innerHTML = !S.vol.live ? 'The red "signal lost" colours update after a refresh of this scene (<code>python -m fpv3d refresh-all</code>).'
        : r.exact ? 'Save to keep it.'
          : 'The red "signal lost" colours are approximate for this big change; saving makes them exact.';
    }
    for (const tr of [S.track, S.cmp]) shiftTrackMargins(tr);
    if (S.track) onTracks();
  }
  function shiftTrackMargins(tr) {
    if (!tr || !tr.margin || !S.linkDelta) return;
    if (!tr.margin0) tr.margin0 = structuredClone(tr.margin);
    for (const [name, arr] of Object.entries(tr.margin0)) {
      const d = S.linkDelta[name] || 0;
      tr.margin[name] = arr.map((v) => (v == null ? null : v + d));
    }
  }

  function initLinkEditor() {
    S.links0 ||= structuredClone(S.meta.links);   // the saved values (S.meta.links follows the edits)
    const box = $('linkEdit');
    if (!S.links0.every(hasParams)) {
      box.innerHTML = '<p class="muted small">To edit antennas and power here, refresh this scene once (<code>python -m fpv3d refresh-all</code>).</p>';
      return;
    }
    const ov = loadLinkOverrides();
    const opt = (arr, v) => arr.map(([val, lab]) => `<option value="${val}" ${String(val) === String(v) ? 'selected' : ''}>${lab}</option>`).join('');
    // simple view: one "setup" choice per radio link
    const setups = S.links0.map((l0, i) => {
      const l = { ...l0, ...(ov[l0.name] || {}) }, k = presetKind(l0.freq_mhz), cur = presetIndex(l);
      const all = PRESETS[k].map((pr, j) => [presetValues(pr, l0.freq_mhz, k), j]);
      const groups = [...new Set(all.map(([p]) => p.group || ''))];
      const options = groups.map((g) => {
        const os = all.filter(([p]) => (p.group || '') === g).map(([p, j]) => `<option value="${j}" ${j === cur ? 'selected' : ''}>${esc(p.label)}</option>`).join('');
        return g && groups.length > 1 ? `<optgroup label="${esc(g === 'DJI' ? 'DJI digital' : g === 'Walksnail' ? 'Walksnail digital' : g)}">${os}</optgroup>` : os;
      }).join('');
      return `<label class="row setup"><span><span class="sw" style="background:${l0.color}"></span> ${esc(l0.name.replace(/ \d.*$/, ''))}</span>
        <select data-preset="${esc(l0.name)}">${options}
        <option value="custom" ${cur < 0 ? 'selected' : ''}>Custom (see Advanced)</option></select></label>
        <p class="muted small presetNote" data-note="${esc(l0.name)}">${noteFor(cur >= 0 ? all[cur][0] : null)}</p>`;
    }).join('');
    const exact = S.links0.map((l0, i) => {
      const l = { ...l0, ...(ov[l0.name] || {}) }, mw = Math.round(10 ** (l.tx_power_dbm / 10));
      const ant = (v) => (ANT.some(([a]) => a === v) ? v : '');
      return `<details class="lnk" data-name="${esc(l0.name)}"><summary><span class="sw" style="background:${l0.color}"></span> ${esc(l0.name)}</summary>
        <label class="row">TX power <select data-k="mw">${MW.map((w) => `<option value="${w}" ${w === mw ? 'selected' : ''}>${w} mW (${(10 * Math.log10(w)).toFixed(1)} dBm)</option>`).join('')}${MW.includes(mw) ? '' : `<option selected value="${mw}">${mw} mW</option>`}</select></label>
        <label class="row">Drone antenna <select data-k="tx_ant">${opt(ANT, ant(l.tx_gain_dbi))}</select><input type="number" step="0.5" data-k="tx_gain_dbi" value="${l.tx_gain_dbi}"> dBi</label>
        <label class="row">Ground antenna <select data-k="rx_ant">${opt(ANT, ant(l.rx_gain_dbi))}</select><input type="number" step="0.5" data-k="rx_gain_dbi" value="${l.rx_gain_dbi}"> dBi</label>
        <label class="row">Receiver sensitivity <input type="number" step="1" data-k="rx_sensitivity_dbm" value="${l.rx_sensitivity_dbm}"> dBm</label>
        <label class="row">Cable / misc losses <input type="number" step="0.5" data-k="misc_losses_db" value="${l.misc_losses_db}"> dB</label>
        <label class="row">Safety (fade) margin <input type="number" step="1" data-k="fade_margin_db" value="${l.fade_margin_db}"> dB</label>
      </details>`;
    }).join('');
    box.innerHTML = `<p class="muted small">Pick your video system and radio: the range, the colours on the map and the warnings follow right away.</p>${setups}
      <div id="lnkDirty" class="small hidden"><span style="color:var(--warn)">Changed, not saved yet.</span> <span id="lnkShadowNote"></span></div>
      <div class="row btns"><button id="lnkReset">[undo changes]</button><button id="lnkSave" class="primary">[save for this location]</button></div>
      <div id="lnkMsg" class="small muted"></div>
      <details class="adv" id="lnkAdv"><summary>Advanced: exact radio values</summary>${exact}
        <p class="muted small">Legal limits in Switzerland / EU (EIRP): 25 mW at 5.8 GHz, 100 mW at 2.4 GHz: the CE versions of the
        digital systems. Digital systems: the sensitivity is set from the maker's range, see the note under the choice.</p></details>`;
    box.querySelectorAll('select[data-preset]').forEach((sel) => sel.onchange = () => {
      if (sel.value === 'custom') { $('lnkAdv').open = true; return; }
      const name = sel.dataset.preset, l0 = S.links0.find((x) => x.name === name);
      const k = presetKind(l0.freq_mhz), pv = presetValues(PRESETS[k][+sel.value], l0.freq_mhz, k);
      const { mw, tg, rg } = pv;
      const d = box.querySelector(`details.lnk[data-name="${CSS.escape(name)}"]`), q = (key) => d.querySelector(`[data-k="${key}"]`);
      if (![...q('mw').options].some((o) => +o.value === mw)) q('mw').insertAdjacentHTML('beforeend', `<option value="${mw}">${mw} mW</option>`);
      q('mw').value = String(mw); q('tx_gain_dbi').value = tg; q('rx_gain_dbi').value = rg;
      if (pv.values.rx_sensitivity_dbm != null) {
        q('rx_sensitivity_dbm').value = pv.values.rx_sensitivity_dbm; q('misc_losses_db').value = MISC; q('fade_margin_db').value = FADE;
      }
      const note = box.querySelector(`[data-note="${CSS.escape(name)}"]`); if (note) note.innerHTML = noteFor(pv);
      q('tx_ant').value = ANT.some(([a]) => a === tg) ? tg : ''; q('rx_ant').value = ANT.some(([a]) => a === rg) ? rg : '';
      q('mw').dispatchEvent(new Event('input'));
    });
    box.querySelectorAll('details.lnk').forEach((d) => {
      const name = d.dataset.name, q = (k) => d.querySelector(`[data-k="${k}"]`);
      const write = () => {
        const o = loadLinkOverrides();
        o[name] = { tx_power_dbm: +(10 * Math.log10(+q('mw').value)).toFixed(2), tx_gain_dbi: +q('tx_gain_dbi').value, rx_gain_dbi: +q('rx_gain_dbi').value,
          rx_sensitivity_dbm: +q('rx_sensitivity_dbm').value, misc_losses_db: +q('misc_losses_db').value, fade_margin_db: +q('fade_margin_db').value };
        saveLinkOverrides(o); applyLinks();
        const sel = box.querySelector(`select[data-preset="${CSS.escape(name)}"]`);   // keep the simple choice in sync
        const i = presetIndex({ ...S.links0.find((x) => x.name === name), ...o[name] });
        if (sel) sel.value = i < 0 ? 'custom' : String(i);
        const note = box.querySelector(`[data-note="${CSS.escape(name)}"]`), l0 = S.links0.find((x) => x.name === name);
        if (note) note.innerHTML = noteFor(i < 0 ? null : presetValues(PRESETS[presetKind(l0.freq_mhz)][i], l0.freq_mhz, presetKind(l0.freq_mhz)));
      };
      q('tx_ant').onchange = () => { if (q('tx_ant').value !== '') q('tx_gain_dbi').value = q('tx_ant').value; write(); };
      q('rx_ant').onchange = () => { if (q('rx_ant').value !== '') q('rx_gain_dbi').value = q('rx_ant').value; write(); };
      d.querySelectorAll('input, select[data-k="mw"]').forEach((el) => el.addEventListener('input', () => {
        if (el.dataset.k === 'tx_gain_dbi') q('tx_ant').value = ANT.some(([a]) => String(a) === el.value) ? el.value : '';
        if (el.dataset.k === 'rx_gain_dbi') q('rx_ant').value = ANT.some(([a]) => String(a) === el.value) ? el.value : '';
        write();
      }));
    });
    $('lnkReset').onclick = () => { saveLinkOverrides({}); initLinkEditor(); applyLinks(); };
    $('lnkSave').onclick = saveLinksToLocation;
    applyLinks();
  }

  async function saveLinksToLocation() {
    const msg = $('lnkMsg');
    const links = S.meta.links.map((l) => Object.fromEntries([['name', l.name], ...LINK_KEYS.map((k) => [k, l[k]])]));
    window.alpBusy?.(true);
    try {
      const r = await fetch('/api/links', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scene: S.meta.name, links }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || r.statusText);
      msg.textContent = `Saved to locations/${d.file} - recomputing the signal shadows…`;
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 1000));
        const j = await (await fetch(`/api/jobs/${d.job}`)).json();
        msg.textContent = j.lines.at(-1) || '…';
        if (j.status !== 'running') {
          if (j.status === 'done') { saveLinkOverrides({}); msg.textContent = 'Done - reloading…'; setTimeout(() => location.reload(), 600); }
          else msg.textContent = 'Rebuild failed: ' + j.lines.slice(-3).join(' ');
          break;
        }
      }
    } catch (e) { msg.textContent = `Could not save (${e.message}). Is the fpv3d server running?`; }
    finally { window.alpBusy?.(false); }
  }

  return { apply: applyLinks, init: initLinkEditor, shiftTrackMargins };
}
