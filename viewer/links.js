import { esc } from './esc.js';
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
// ready-made setups: transmit power + antenna gains [label, mW, tx antenna dBi, rx antenna dBi]
// (video: tx = drone, rx = goggles · control: tx = radio, rx = drone). Receiver sensitivity,
// losses and safety margin keep the location's values (they are under Advanced).
export const PRESETS = {
  video: [
    ['25 mW · stock antennas (CH / EU limit)', 25, 2, 2],
    ['25 mW · patch on the goggles', 25, 2, 8],
    ['200 mW · stock antennas', 200, 2, 2],
    ['500 mW · stock antennas', 500, 2, 2],
    ['500 mW · patch on the goggles', 500, 2, 8],
    ['1 W · helical on the goggles', 1000, 3, 12],
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
export function presetIndex(l) {
  const mw = 10 ** (l.tx_power_dbm / 10);
  return PRESETS[presetKind(l.freq_mhz)].findIndex(([, w, tg, rg]) => Math.abs(w - mw) / w < 0.03 && Math.abs(tg - l.tx_gain_dbi) < 0.26 && Math.abs(rg - l.rx_gain_dbi) < 0.26);
}
/** link budget in dB above free-space loss at 1 km... (tx + gains - losses - sensitivity - margin) */
export const linkBudget = (l) => l.tx_power_dbm + l.tx_gain_dbi + l.rx_gain_dbi - l.misc_losses_db - l.rx_sensitivity_dbm - l.fade_margin_db;
export const hasParams = (l) => LINK_KEYS.every((k) => typeof l[k] === 'number');
/** range in metres where the free-space loss uses up the budget */
export const rangeFor = (budgetDb, freqMhz) => Math.pow(10, (budgetDb - 20 * Math.log10(freqMhz) - 32.44) / 20) * 1000;

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
      return `<label class="row setup"><span><span class="sw" style="background:${l0.color}"></span> ${esc(l0.name.replace(/ \d.*$/, ''))}</span>
        <select data-preset="${esc(l0.name)}">${PRESETS[k].map(([lab], j) => `<option value="${j}" ${j === cur ? 'selected' : ''}>${lab}</option>`).join('')}
        <option value="custom" ${cur < 0 ? 'selected' : ''}>Custom (see Advanced)</option></select></label>`;
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
    box.innerHTML = `<p class="muted small">Pick your setup: the range, the colours on the map and the warnings follow right away.</p>${setups}
      <div id="lnkDirty" class="small hidden"><span style="color:var(--warn)">Changed, not saved yet.</span> <span id="lnkShadowNote"></span></div>
      <div class="row btns"><button id="lnkReset">Undo changes</button><button id="lnkSave" class="primary">Save for this location</button></div>
      <div id="lnkMsg" class="small muted"></div>
      <details class="adv" id="lnkAdv"><summary>Advanced: exact radio values</summary>${exact}
        <p class="muted small">Legal limits in Switzerland / EU (EIRP): 25 mW at 5.8 GHz, 100 mW at 2.4 GHz.</p></details>`;
    box.querySelectorAll('select[data-preset]').forEach((sel) => sel.onchange = () => {
      if (sel.value === 'custom') { $('lnkAdv').open = true; return; }
      const name = sel.dataset.preset, l0 = S.links0.find((x) => x.name === name);
      const [, mw, tg, rg] = PRESETS[presetKind(l0.freq_mhz)][+sel.value];
      const d = box.querySelector(`details.lnk[data-name="${CSS.escape(name)}"]`), q = (k) => d.querySelector(`[data-k="${k}"]`);
      if (![...q('mw').options].some((o) => +o.value === mw)) q('mw').insertAdjacentHTML('beforeend', `<option value="${mw}">${mw} mW</option>`);
      q('mw').value = String(mw); q('tx_gain_dbi').value = tg; q('rx_gain_dbi').value = rg;
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
