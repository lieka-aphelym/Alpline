// fpv3d — the battery packs page: every pack with its health over time and landing advice, every flight with battery
// data (which pack flew it, charger entry), one flight's discharge, and the current-sensor check.
// Data: GET /api/battery/packs (computed in fpv3d/battery.py), /api/battery/flight?id=; changes: POST /api/battery/*.
import { esc } from '../core/esc.js';
import { APP } from '../core/env.js';
import { drawDischarge, drawSag, drawTrend, sparkline, fmtT } from './batchart.js';

const $ = (id) => document.getElementById(id);
import { postJSON as post } from '../core/net.js';
const st = { o: null, pack: null, flight: null, filter: 'all', fdata: null };

async function load() {
  const r = await fetch('/api/battery/packs');
  st.o = await r.json();
  render();
}

function render() {
  renderPacks(); renderDetail(); renderFlights(); renderCharger();
}

function renderPacks() {
  const o = st.o, box = $('packs');
  if (!o.packs.length) {
    box.innerHTML = '<p class="muted">No pack yet. Add your packs with <b>[+ new pack]</b>, or pick “+ new pack” on a flight below.</p>';
    return;
  }
  const rows = o.packs.map((p) => {
    const ir = p.trend.map((x) => x.ir);
    return `<tr class="click ${p.id === st.pack ? 'sel' : ''}" data-p="${esc(p.id)}">
      <td><b>${esc(p.name)}</b>${p.retired ? '<span class="retired">retired</span>' : ''}${p.state === 'retire' && !p.retired ? ' <span class="flag" title="a note says it is swollen or damaged">⚠ retire</span>' : ''}${p.notes.length ? ` <span class="muted small" title="notes">✎${p.notes.length}</span>` : ''}${p.note ? `<div class="muted small">${esc(p.note)}</div>` : ''}</td>
      <td>${p.cells}S ${p.capacity} <span class="chem chem-${esc(p.chemistry)}">${esc(p.chem_label)}</span></td><td class="num">${p.flights}</td>
      <td class="num">${p.ir_now ? `${p.ir_now.toFixed(1)} mΩ` : '–'}</td><td>${sparkline(ir)}</td>
      <td class="num hideS">${p.sag100 ? `${p.sag100.toFixed(2)} V` : '–'}</td>
      <td class="num hideS">${p.mah_per_min ? `${p.mah_per_min}/min` : '–'}</td>
      <td class="num">${p.landing_min ? `${p.landing_mah} mAh ≈ ${p.landing_min} min` : `${p.landing_mah} mAh`}</td>
      <td class="flag">${p.flags.map(esc).join('<br>')}</td>
      <td><button class="small" data-edit="${esc(p.id)}">[edit]</button></td></tr>`;
  }).join('');
  box.innerHTML = `<div class="wrap"><table class="pk"><tr><th>pack</th><th>type</th><th>flights</th><th>mΩ/cell</th><th>trend</th>
    <th class="hideS">sag @100 A</th><th class="hideS">use</th><th>land at (80 %)</th><th></th><th></th></tr>${rows}</table></div>`;
  box.querySelectorAll('tr[data-p]').forEach((tr) => tr.addEventListener('click', (e) => {
    if (e.target.closest('button')) return;
    st.pack = st.pack === tr.dataset.p ? null : tr.dataset.p; render();
  }));
  box.querySelectorAll('[data-edit]').forEach((b) => b.addEventListener('click', () => editPack(o.packs.find((p) => p.id === b.dataset.edit))));
}

function renderDetail() {
  const p = st.o.packs.find((x) => x.id === st.pack);
  $('detail').classList.toggle('hidden', !p);
  if (!p) return;
  $('dTitle').textContent = `${p.name} · ${p.cells}S ${p.capacity} mAh ${p.chem_label} · since ${p.since}`;
  drawTrend($('dTrend'), p.trend, { height: 140, notes: p.notes });
  renderNotes(p);
  const mine = st.o.flights.filter((f) => f.pack === p.id);
  const totalMah = mine.reduce((s, f) => s + (f.summary.mah || 0), 0);
  $('dText').innerHTML = `<p><b>${p.flights}</b> flight${p.flights === 1 ? '' : 's'}, ${Math.round(totalMah)} mAh logged in total.</p>`
    + (p.ir_now ? `<p>Resistance now <b>${p.ir_now.toFixed(1)} mΩ per cell</b>${p.ir_first && p.trend.length >= 4 ? ` (first flights: ${p.ir_first.toFixed(1)})` : ''}. `
      + (p.chemistry === 'liion' ? 'A good Li-ion pack is usually under 20 mΩ per cell (it sags more than a LiPo by design); '
        : 'A fresh good LiPo is usually 2 to 6 mΩ per cell; ') + 'it rises with age and wear, and on cold days.</p>' : '<p>No resistance measured yet: it needs flights with some punch-outs.</p>')
    + `<p class="muted">${esc(p.chem_label)}: low under load ${p.low} V per cell; the live warnings use ${p.warn_load} V under load and ${p.crit_rest} V resting.</p>`
    + (p.mah_per_min ? `<p>At your flying it gives about <b>${p.mah_per_min} mAh a minute</b>: land at <b>${p.landing_mah} mAh</b>, after about <b>${p.landing_min} min</b>.</p>` : '')
    + (p.flags.length ? `<p class="flag">${p.flags.map(esc).join('<br>')}</p>` : '');
}

function renderNotes(p) {
  const fl = (id) => st.o.flights.find((f) => f.id === id);
  $('dNotes').innerHTML = p.notes.length ? `<table class="pk notes">${p.notes.map((n) => `<tr class="lvl-${esc(n.level)}">
      <td>${esc(n.when)}</td><td><b>${esc(n.label)}</b>${n.level === 'retire' ? ' <span class="flag">retire it</span>' : ''}</td>
      <td class="txt">${esc(n.text || '')}${n.flight && fl(n.flight) ? ` <span class="muted">(flight ${esc(fl(n.flight).when || n.flight)})</span>` : ''}</td>
      <td><button class="small" data-delnote="${esc(n.id)}" title="Delete this note (on this computer)">[x]</button></td></tr>`).join('')}</table>`
    : '<p class="muted small">No note yet. Write down crashes, puffing, a damaged lead or plug: they explain a jump in resistance, and a swollen pack is flagged to retire.</p>';
  $('dNotes').querySelectorAll('[data-delnote]').forEach((b) => b.addEventListener('click', async () => {
    try { await post('/api/battery/delete-note', { id: b.dataset.delnote }); await load(); }
    catch (e) { $('nMsg').textContent = /403|this computer/.test(e.message) ? 'Deleting works on the computer only.' : e.message; }
  }));
  const mine = st.o.flights.filter((f) => f.pack === p.id).slice().reverse();
  $('nFlight').innerHTML = '<option value="">(none)</option>' + mine.map((f) => `<option value="${esc(f.id)}">${esc(f.when || f.id)}</option>`).join('');
  if (!$('nWhen').value) $('nWhen').value = new Date().toISOString().slice(0, 10);
}
$('nFlight').onchange = () => { const f = st.o.flights.find((x) => x.id === $('nFlight').value); if (f?.when) $('nWhen').value = f.when.slice(0, 10); };
$('nAdd').onclick = async () => {
  try {
    await post('/api/battery/note', { pack: st.pack, kind: $('nKind').value, text: $('nText').value, when: $('nWhen').value, flight: $('nFlight').value || null });
    $('nText').value = ''; $('nMsg').textContent = ''; await load();
  } catch (e) { $('nMsg').textContent = e.message; }
};

function packOptions(sel) {
  return `<option value="">${sel ? '(no pack)' : 'which pack? ▾'}</option>` + st.o.packs.filter((p) => !p.retired || p.id === sel)
    .map((p) => `<option value="${esc(p.id)}" ${p.id === sel ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
}

function renderFlights() {
  const all = [...st.o.flights].reverse();                            // newest first
  const none = all.filter((f) => !f.pack);
  document.querySelector('[data-f="none"]').textContent = `[without a pack (${none.length})]`;
  let list = st.filter === 'none' ? none : all;
  if (st.pack) list = list.filter((f) => f.pack === st.pack || (st.filter === 'none' && !f.pack));
  if (!list.length) {
    $('flights').innerHTML = `<p class="muted">${st.o.flights.length ? 'No flight here.' : 'No flight with battery data yet. Download the blackbox (launcher → drone, or the viewer\'s flights tab): voltage and current are in it.'}</p>`;
    return;
  }
  const rows = list.map((f) => {
    const s = f.summary, where = f.scene && f.track ? `<a href="index.html?scene=${encodeURIComponent(f.scene)}&track=${encodeURIComponent(f.track)}&tab=battery">${esc(f.scene)}</a>` : '<span class="muted">no GPS</span>';
    return `<tr class="click ${f.id === st.flight ? 'sel' : ''}" data-f="${esc(f.id)}">
      <td>${f.when_approx ? '<span title="The drone had no clock in this log (no GPS fix): this is the download date. Click the pencil to correct it.">≈ </span>' : ''}${esc(f.when || '')} <button class="small ghost" data-date="${esc(f.id)}" title="Change the date of this flight">✎</button></td><td class="hideS">${esc(f.craft || '')}</td><td>${where}</td>
      <td><select data-assign="${esc(f.id)}" class="${f.pack ? '' : 'ask'}">${packOptions(f.pack)}</select></td>
      <td class="num">${fmtT(s.seconds)}</td><td class="num">${s.mah != null ? s.mah : '–'}</td>
      <td class="num ${s.min_cell < (s.low ?? 3.5) ? 'flag' : ''}" ${s.hint ? `title="${esc(s.hint)}"` : ''}>${s.min_cell.toFixed(2)}${s.hint ? ' ⚠' : ''}</td>
      <td class="num">${s.ir_cell_mohm ? s.ir_cell_mohm.toFixed(1) : '–'}</td>
      <td class="num hideS"><input class="chg" type="number" min="0" step="10" placeholder="mAh" data-chg="${esc(f.id)}" value="${f.charged_mah ?? ''}" title="What your charger put back in after this flight"></td></tr>`;
  }).join('');
  $('flights').innerHTML = `<div class="wrap"><table class="pk"><tr><th>when</th><th class="hideS">quad</th><th>where</th><th>pack</th><th>time</th>
    <th>mAh</th><th>min V/cell</th><th>mΩ/cell</th><th class="hideS">charger mAh</th></tr>${rows}</table></div>`;
  $('flights').querySelectorAll('tr[data-f]').forEach((tr) => tr.addEventListener('click', (e) => {
    if (e.target.closest('select,input,a,button')) return;
    showFlight(tr.dataset.f);
  }));
  $('flights').querySelectorAll('[data-assign]').forEach((sel) => sel.addEventListener('change', async () => {
    try { await post('/api/battery/assign', { flights: [sel.dataset.assign], pack: sel.value || null }); await load(); }
    catch (e) { window.alpOops?.(e.message); }
  }));
  $('flights').querySelectorAll('[data-date]').forEach((btn) => btn.addEventListener('click', () => {
    const f = st.o.flights.find((x) => x.id === btn.dataset.date), td = btn.parentElement;
    td.innerHTML = `<input type="datetime-local" value="${esc((f.when || '').replace(' ', 'T'))}">`;
    const inp = td.firstChild; inp.focus();
    inp.addEventListener('change', async () => {
      try { await post('/api/battery/flight-date', { flight: f.id, when: inp.value }); await load(); }
      catch (e) { window.alpOops?.(e.message); }
    });
    inp.addEventListener('blur', () => setTimeout(() => { if (document.activeElement !== inp) renderFlights(); }, 200));
  }));
  $('flights').querySelectorAll('[data-chg]').forEach((inp) => inp.addEventListener('change', async () => {
    try { await post('/api/battery/charger', { flight: inp.dataset.chg, mah: inp.value === '' ? null : +inp.value }); await load(); }
    catch (e) { window.alpOops?.(e.message); }
  }));
}

async function showFlight(fid) {
  st.flight = st.flight === fid ? null : fid;
  $('flight').classList.toggle('hidden', !st.flight);
  renderFlights();
  if (!st.flight) return;
  const r = await fetch(`/api/battery/flight?id=${encodeURIComponent(fid)}`);
  st.fdata = await r.json();
  const f = st.o.flights.find((x) => x.id === fid), s = st.fdata.summary;
  $('fTitle').textContent = `${f.when} · ${s.cells}S · ${s.mah != null ? `${s.mah} mAh · ` : ''}peak ${s.peak_a ?? '–'} A · lowest ${s.min_cell.toFixed(2)} V/cell`
    + (s.ir_cell_mohm ? ` · ${s.ir_cell_mohm} mΩ/cell` : '');
  drawFlight();
  $('flight').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function drawFlight() {
  if (!st.fdata || $('flight').classList.contains('hidden')) return;
  drawDischarge($('fChart'), st.fdata, { height: 230 });
  drawSag($('fSag'), st.fdata, { height: 230 });
}

function renderCharger() {
  const c = st.o.charger, box = $('charger');
  const how = '<p class="muted">After a flight, type in the flights list what your charger put back in (mAh). ' + APP + ' compares it with the mAh '
    + 'the drone logged: if they differ, the current sensor needs calibrating, and you get the value to set in Betaflight.</p>';
  if (!c) { box.innerHTML = how; return; }
  const pct = Math.round((c.ratio - 1) * 100);
  box.innerHTML = `<p>${c.flights} flight${c.flights > 1 ? 's' : ''}: the drone logged <b>${c.logged} mAh</b>, the charger put back <b>${c.charged} mAh</b> `
    + `(${pct === 0 ? 'the same' : `${Math.abs(pct)} % ${pct < 0 ? 'less' : 'more'} logged`}).</p>`
    + (c.ok ? '<p class="ok">The current sensor is right (within 5 %).</p>'
      : c.scale_new ? `<p>The current sensor reads ${pct < 0 ? 'low' : 'high'}. In Betaflight's CLI: <code>set ibata_scale = ${c.scale_new}</code> then <code>save</code> `
        + `(now ${c.scale_now}). Check again after a few flights.</p>` : '<p>The current sensor needs calibrating (Betaflight → Power &amp; Battery → current scale).</p>')
    + how;
}

// ---------------------------------------------------------------- battery from the saved blackbox files
$('rescan').onclick = async () => {
  const box = $('rescanLog'), btn = $('rescan');
  btn.disabled = true; box.classList.remove('hidden'); box.textContent = 'starting…'; window.alpBusy?.(true);
  try {
    const j = await post('/api/battery/rescan', {});
    for (;;) {
      await new Promise((ok) => setTimeout(ok, 700));
      const k = await (await fetch(`/api/jobs/${j.job}`)).json();
      box.innerHTML = (k.lines || []).filter((l) => !/^(ADDED|BATTERY) /.test(l)).map((l) =>
        `<div class="${/battery now kept|→ added/.test(l) ? 'ok' : ''}">${esc(l)}</div>`).join('');
      box.scrollTop = box.scrollHeight;
      if (k.status !== 'running') break;
    }
    await load();
  } catch (e) { box.textContent = `could not start: ${e.message}`; }
  finally { btn.disabled = false; window.alpBusy?.(false); }
};

// ---------------------------------------------------------------- pack form
function editPack(p) {
  $('packForm').classList.remove('hidden');
  $('pfId').value = p?.id || ''; $('pfName').value = p?.name || `pack ${st.o.packs.length + 1}`;
  $('pfCells').value = String(p?.cells || 6); $('pfCap').value = p?.capacity || 1300; $('pfChem').value = p?.chemistry || 'lipo';
  $('pfNote').value = p?.note || ''; $('pfRetired').checked = !!p?.retired;
  $('pfDelete').classList.toggle('hidden', !p); $('pfMsg').textContent = '';
  $('pfName').focus();
}
$('newPack').onclick = () => editPack(null);
$('pfCancel').onclick = () => $('packForm').classList.add('hidden');
$('pfSave').onclick = async () => {
  try {
    await post('/api/battery/pack', { id: $('pfId').value || undefined, name: $('pfName').value, cells: +$('pfCells').value,
      capacity: +$('pfCap').value, chemistry: $('pfChem').value, note: $('pfNote').value, retired: $('pfRetired').checked });
    $('packForm').classList.add('hidden'); await load();
  } catch (e) { $('pfMsg').textContent = e.message; }
};
$('pfDelete').onclick = async () => {
  if (!confirm('Delete this pack? Its flights stay, without a pack.')) return;
  try { await post('/api/battery/delete-pack', { id: $('pfId').value }); $('packForm').classList.add('hidden'); st.pack = null; await load(); }
  catch (e) { $('pfMsg').textContent = e.message.includes('403') || /this computer/.test(e.message) ? 'Deleting works on the computer only.' : e.message; }
};
document.querySelectorAll('.filters button').forEach((b) => b.addEventListener('click', () => {
  st.filter = b.dataset.f;
  document.querySelectorAll('.filters button').forEach((x) => x.classList.toggle('on', x === b));
  renderFlights();
}));
window.addEventListener('resize', () => { if (st.o) { renderDetail(); drawFlight(); } });
window.addEventListener('fpv3d:theme', () => { if (st.o) { render(); drawFlight(); } });
load();
