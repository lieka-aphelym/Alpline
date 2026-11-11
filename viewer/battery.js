// fpv3d — the viewer's [battery] tab: what the pack did during the flight being replayed.
// Summary, tiles, sag vs current, which pack flew it (and a new pack), landing advice for that pack, and a chart
// under the playback bar with the replay cursor (click it to jump there). The data: GET /api/battery/flight
// (series at 0.1 s on the track's clock) and /api/battery/packs; analysis in fpv3d/battery.py.
import { esc } from './esc.js';
import { APP } from './env.js';
import { drawDischargeCursor, drawSag, fmtT } from './batchart.js';

import { postJSON as post, getJSON as get } from './net.js';

export function initBattery({ S, $, seek, onChange }) {
  const st = { d: null, fid: null, packs: null, chart: null, lastCursor: null, tab: false };
  const strip = $('batStrip'), stripOn = $('batStripOn');
  try { stripOn.checked = localStorage.getItem('fpv3d:batStrip') !== '0'; } catch { /* private mode */ }

  async function loadPacks() {
    try { st.packs = await get('/api/battery/packs'); } catch { st.packs = { packs: [], flights: [] }; }
    return st.packs;
  }

  /** a flight was picked (tm: its summary in scene.json, or null) */
  async function trackChanged(tm) {
    st.d = null; st.fid = tm?.battery || null;
    $('batSection').classList.toggle('noBat', !st.fid);
    if (!st.fid) { render(); showStrip(); onChange?.(); return; }
    try {
      const [d] = await Promise.all([get(`/api/battery/flight?id=${encodeURIComponent(st.fid)}`), loadPacks()]);
      if (st.fid !== tm.battery) return;                   // another flight was picked meanwhile
      st.d = d;
    } catch (e) { st.d = null; $('batSummary').textContent = `Battery data could not be loaded (${e.message}).`; }
    render(); showStrip(); onChange?.();
  }

  function tiles(sm) {
    const pk = currentPack();
    const it = [];
    if (sm.has_current) {
      it.push([`${sm.mah}`, 'mAh used', pk ? `${sm.used_pct} % of ${pk.capacity}` : 'pick the pack for %']);
      it.push([`${sm.peak_a} A`, 'peak current', `${sm.peak_c ? `${sm.peak_c} C · ` : ''}avg ${sm.avg_a} A`]);
      it.push([`${sm.wh} Wh`, 'energy', sm.seconds > 5 ? `${Math.round(sm.wh / (sm.seconds / 3600))} W average` : '']);
    }
    it.push([`${sm.min_cell.toFixed(2)} V`, 'lowest cell', sm.below_low_s > 0 ? `under ${sm.low} V for ${sm.below_low_s} s` : `under load, never below ${sm.low} V`]);
    it.push([`${sm.end_rest_cell.toFixed(2)} V`, 'at landing', `resting · took off at ${sm.start_cell.toFixed(2)} V`]);
    if (sm.ir_cell_mohm) it.push([`${sm.ir_cell_mohm} mΩ`, 'mΩ per cell', `${sm.ir_pack_mohm} mΩ pack · ${sm.health}${sm.chem_label ? ` for ${sm.chem_label}` : ''}`]);
    if (sm.worst_sag_cell) it.push([`−${sm.worst_sag_cell.toFixed(2)} V`, 'worst cell sag', `at ${sm.peak_a} A`]);
    it.push([fmtT(sm.seconds), 'logged', sm.landing_t != null ? `${sm.landing_mah} mAh (80 %) at ${fmtT(sm.landing_t)}` : '']);
    return it.map(([v, l, s]) => `<div class="batTile"><b>${esc(v)}</b><span>${esc(l)}</span><div>${esc(s)}</div></div>`).join('');
  }
  const currentPack = () => st.packs?.packs.find((p) => p.id === st.d?.pack) || null;

  function render() {
    const d = st.d, box = $('batBody');
    if (!st.fid) {
      $('batSummary').innerHTML = S.track ? 'This flight has no battery data. It comes from the blackbox (voltage and current are '
        + 'logged by default) or from radio logs with RxBt / Curr. Flights downloaded before this version: download them again.'
        : 'Pick a flight in [flights] to see its battery.';
      box.classList.add('hidden');
      return;
    }
    if (!d) return;
    box.classList.remove('hidden');
    const sm = d.summary, pk = currentPack();
    $('batSummary').innerHTML = (sm.has_current ? `<b>${sm.mah} mAh</b> used in ${fmtT(sm.seconds)}, ` : `${fmtT(sm.seconds)} logged (no current sensor), `)
      + `lowest <b class="${sm.min_cell < 3.5 ? 'bad' : sm.min_cell < 3.6 ? 'warnTxt' : ''}">${sm.min_cell.toFixed(2)} V/cell</b> under load`
      + (sm.ir_cell_mohm ? `, pack resistance <b>${sm.ir_cell_mohm} mΩ/cell</b>.` : '.')
      + ` <span class="muted">${sm.cells}S${sm.chem_label ? ` ${sm.chem_label}` : ''}${d.meta?.craft ? ` · ${esc(d.meta.craft)}` : ''}</span>`
      + (sm.hint ? `<div class="warnTxt small">${esc(sm.hint)}</div>` : '')
      + (sm.cells_unsure ? `<div class="warnTxt small">${esc(sm.cells_unsure)}</div>` : '');
    // which pack
    const sel = $('batPack');
    sel.innerHTML = `<option value="">${d.pack ? '(no pack)' : 'which pack was it? ▾'}</option>`
      + (st.packs?.packs || []).filter((p) => !p.retired || p.id === d.pack)
        .map((p) => `<option value="${esc(p.id)}" ${p.id === d.pack ? 'selected' : ''}>${esc(p.name)} · ${p.cells}S ${p.capacity} mAh ${p.chem_label}</option>`).join('')
      + '<option value="+">+ new pack…</option>';
    sel.classList.toggle('ask', !d.pack);
    $('batTiles').innerHTML = tiles(sm);
    drawSag($('batSag'), d, { height: 120 });
    // landing advice for this pack, from its flights
    const adv = $('batAdvice');
    if (pk && pk.mah_per_min) {
      adv.innerHTML = `<b>${esc(pk.name)}</b> at your flying: about <b>${pk.mah_per_min} mAh a minute</b>. Land at <b>${pk.landing_mah} mAh</b> `
        + `(80 % of ${pk.capacity}): after about <b>${pk.landing_min} min</b>.` + (pk.flags.length ? `<div class="warnTxt">${pk.flags.map(esc).join('<br>')}</div>` : '');
    } else if (pk) adv.innerHTML = `Landing advice for <b>${esc(pk.name)}</b> appears after a flight longer than a minute with it.`;
    else adv.innerHTML = `Say which pack flew this flight: ${APP} then follows each pack's health and how long it lasts at your flying.`;
    // the pack's notes (newest 3) and a quick note tied to this flight
    $('batNoteBox').classList.toggle('hidden', !pk);
    $('batNotes').innerHTML = pk?.notes?.length ? `<b>Notes</b>: ` + pk.notes.slice(0, 3).map((n) =>
      `<div class="${n.level === 'retire' ? 'bad' : n.level === 'check' ? 'warnTxt' : 'muted'}">${esc(n.when)} · ${esc(n.label)}${n.text ? ` – ${esc(n.text)}` : ''}${n.flight === st.fid ? ' (this flight)' : ''}</div>`).join('')
      + (pk.notes.length > 3 ? `<div class="muted">and ${pk.notes.length - 3} more on the packs page</div>` : '') : '';
  }

  $('batPack').onchange = async (e) => {
    const v = e.target.value;
    if (v === '+') { $('batNew').classList.remove('hidden'); $('batNewName').value = `pack ${(st.packs?.packs.length || 0) + 1}`;
      $('batNewCells').value = String(st.d?.summary.cells || 6); $('batNewName').focus(); return; }
    try { await post('/api/battery/assign', { flights: [st.fid], pack: v || null }); await reload(); }
    catch (ex) { $('batMsg').textContent = ex.message; }
  };
  $('batNewCancel').onclick = () => { $('batNew').classList.add('hidden'); render(); };
  $('batNoteAdd').onclick = async () => {
    try {
      const f = st.packs?.flights.find((x) => x.id === st.fid);
      await post('/api/battery/note', { pack: st.d.pack, kind: $('batNoteKind').value, text: $('batNoteText').value,
        when: (f?.when || '').slice(0, 10) || undefined, flight: st.fid });
      $('batNoteText').value = ''; $('batNoteMsg').textContent = 'saved'; $('batNoteBox').open = false;
      await reload();
    } catch (ex) { $('batNoteMsg').textContent = ex.message; }
  };
  $('batNewOk').onclick = async () => {
    try {
      const j = await post('/api/battery/pack', { name: $('batNewName').value, cells: +$('batNewCells').value, capacity: +$('batNewCap').value,
        chemistry: $('batNewChem').value });
      await post('/api/battery/assign', { flights: [st.fid], pack: j.pack.id });
      $('batNew').classList.add('hidden'); $('batMsg').textContent = '';
      await reload();
    } catch (ex) { $('batMsg').textContent = ex.message; }
  };
  async function reload() {
    if (!st.fid) return;
    const [d] = await Promise.all([get(`/api/battery/flight?id=${encodeURIComponent(st.fid)}`), loadPacks()]);
    st.d = d; render(); showStrip(true);
  }

  // ---------------------------------------------------------------- the chart under the playback bar
  function showStrip(force) {
    const on = !!(st.d && st.tab && stripOn.checked && S.track);
    strip.classList.toggle('hidden', !on);
    $('timeline').classList.toggle('withBat', on);
    if (on) tick(force);
  }
  function tick(force) {
    if (strip.classList.contains('hidden') || !st.d) return;
    const tnow = S.time;
    if (!force && st.lastCursor === tnow) return;
    st.lastCursor = tnow;
    st.chart = drawDischargeCursor(strip, st.d, { cursor: tnow, compact: true, height: 74, tStart: Math.min(0, st.d.t[0]),
      tEnd: Math.max(S.track.t[S.track.n - 1], st.d.t.at(-1)) });
    const v = st.chart.valueAt(tnow);
    $('batAt').innerHTML = v ? `at ${fmtT(tnow)}: <b class="volt">${v.cell.toFixed(2)} V/cell</b>`
      + (st.d.summary.has_current ? ` · <b class="cur">${v.amps.toFixed(0)} A</b> · ${Math.round(v.mah)} mAh` : '') : '';
  }
  strip.addEventListener('click', (e) => {
    if (!st.chart) return;
    const r = strip.getBoundingClientRect();
    seek(Math.max(0, Math.min(S.track.t[S.track.n - 1], st.chart.tAt(e.clientX - r.left))));
  });
  stripOn.onchange = () => { try { localStorage.setItem('fpv3d:batStrip', stripOn.checked ? '1' : '0'); } catch { /* */ } showStrip(true); };
  window.addEventListener('resize', () => { if (st.d) { render(); showStrip(true); } });
  window.addEventListener('fpv3d:theme', () => { if (st.d) { render(); showStrip(true); } });

  return {
    trackChanged, tick,
    tabChanged(tab) { st.tab = tab === 'battery'; showStrip(true); if (st.tab && st.d) render(); },
    has: () => !!st.d,
  };
}

/** after a blackbox download: ask which pack flew the new flights (one choice for all, changeable per flight later) */
export async function askPacks(box, fids) {
  if (!fids.length) return;
  let packs;
  try { packs = await get('/api/battery/packs'); } catch { return; }
  const div = document.createElement('div');
  div.className = 'batAsk';
  const opts = packs.packs.filter((p) => !p.retired)
    .map((p) => `<option value="${esc(p.id)}" ${p.id === packs.last_pack ? 'selected' : ''}>${esc(p.name)} · ${p.cells}S ${p.capacity} ${p.chem_label}</option>`).join('');
  div.innerHTML = `<b>Which pack did you fly?</b> <span class="muted">(${fids.length} flight${fids.length > 1 ? 's' : ''} with battery data)</span>
    <div class="row"><select>${opts}<option value="+">+ new pack…</option><option value="">not now</option></select><button class="primary">[save]</button></div>
    <div class="row hidden newp"><input placeholder="name" value="pack ${packs.packs.length + 1}"> <select class="c">${[2, 3, 4, 5, 6, 8].map((c) => `<option ${c === 6 ? 'selected' : ''}>${c}</option>`).join('')}</select>S
      <input class="cap" type="number" value="1300" min="100" step="50" style="width:70px"> mAh <select class="chem"><option value="lipo" selected>LiPo</option><option value="lihv">LiPo HV</option><option value="liion">Li-ion</option></select></div>
    <div class="small msg"></div>`;
  box.appendChild(div);
  const [sel, btn] = [div.querySelector('select'), div.querySelector('button')];
  const syncNew = () => div.querySelector('.newp').classList.toggle('hidden', sel.value !== '+');
  sel.onchange = syncNew; syncNew();
  btn.onclick = async () => {
    try {
      let pid = sel.value;
      if (pid === '') { div.remove(); return; }
      if (pid === '+') {
        const np = div.querySelector('.newp');
        pid = (await post('/api/battery/pack', { name: np.querySelector('input').value, cells: +np.querySelector('.c').value,
          capacity: +np.querySelector('.cap').value, chemistry: np.querySelector('.chem').value })).pack.id;
      }
      const name = sel.value === '+' ? div.querySelector('.newp input').value : sel.options[sel.selectedIndex].text.split(' · ')[0];
      await post('/api/battery/assign', { flights: fids, pack: pid });
      div.innerHTML = `<span class="ok">saved: ${fids.length} flight${fids.length > 1 ? 's' : ''} → ${esc(name)}</span> · <a href="packs.html">[packs]</a>`;
    } catch (e) { div.querySelector('.msg').textContent = e.message; }
  };
}
