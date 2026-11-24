// The instruments: the top bar (place, coordinates, camera modes) and the column on the right of the 3D view
// (video range, how much stays in sight, ground at the pilot, the pilot's position, where the data comes from).
// They show the figures that matter at a glance instead of in sentences inside the tabs. On a phone the column is
// hidden (mobile.css) and the tabs still carry the same answers.
import { toWGS, gridName, isSwiss } from '../core/geo.js';

const $ = (id) => document.getElementById(id);
// the same condition as layout.css: below it the phone layout of mobile.css applies
export const WIDE = '(min-width: 1000px) and (min-height: 501px)';

/** 4800.06 -> "4 800" (a thin space between thousands, as on a map). */
export function groupDigits(v) {
  return String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

/** 45.8326, 6.8652 -> "45.8326 N · 6.8652 E". */
export function fmtLatLon(lat, lon) {
  return `${Math.abs(lat).toFixed(4)} ${lat >= 0 ? 'N' : 'S'} · ${Math.abs(lon).toFixed(4)} ${lon >= 0 ? 'E' : 'W'}`;
}

/** What the heights and the photo are made of, in a few words per line. */
export function dataLines(m) {
  const heights = { swisstopo: 'swisstopo 0.5 m', copernicus: 'worldwide 30 m' };
  const photo = { swisstopo: 'swisstopo 10 cm', worldcover: 'satellite 10 m', sentinel2: 'satellite 10 m' };
  const pick = (list, names) => [...new Set((list || []).map((s) => names[s.name] || s.name))].join(' + ');
  // scenes built before the sources were recorded are Swiss ones: swisstopo for both
  const swiss = [{ name: 'swisstopo' }], old = isSwiss(m.grid.crs);
  const h = pick(m.terrain_sources || (old ? swiss : []), heights) || '–';
  const o = m.ortho ? pick(m.ortho_sources || (old ? swiss : []), photo) || 'yes' : 'none';
  return [['Heights', h], ['Photo', o]];
}

export function initInstruments({ S }) {
  const m = S.meta, crs = m.grid.crs, p = m.pilot;
  const [clat, clon] = m.center_wgs84 || toWGS((m.grid.min_e + m.grid.max_e) / 2, (m.grid.min_n + m.grid.max_n) / 2, crs);
  $('topCoords').textContent = `${fmtLatLon(clat, clon)} · ${(S.W / 1000).toFixed(1)} × ${(S.H / 1000).toFixed(1)} km`;

  // the pilot: local x / y are metres from the grid's south-west corner
  const e = m.grid.min_e + p.x, n = m.grid.min_n + p.y, [plat, plon] = toWGS(e, n, crs);
  $('iGround').textContent = `${groupDigits(p.ground ?? p.z)} m`;
  $('iPilotDeg').textContent = fmtLatLon(plat, plon);
  $('iPilot').innerHTML = `<small>Pilot, ${gridName(crs)}</small><span>E ${groupDigits(e)}</span><span>N ${groupDigits(n)}</span>`;
  $('iData').innerHTML = dataLines(m).map(([k, v]) => `<span><small>${k}</small> ${v}</span>`).join('');
  const info = S.info || {};
  $('iPilotNote').textContent = info.pilotFrom ? `position: ${info.pilotFrom}` : '';
  $('iDataNote').textContent = info.ground || '';
  $('iCredits').innerHTML = info.creditBox || '';

  // on a wide screen the column and the top bar say what the panel said in sentences: the panel keeps the settings
  const moveWide = (el, target) => {
    if (!el) return;
    const home = el.parentNode, next = el.nextSibling;
    const put = () => (matchMedia(WIDE).matches ? target.appendChild(el) : home.insertBefore(el, next));
    matchMedia(WIDE).addEventListener('change', put); put();
  };
  moveWide($('camHint')?.closest('p'), $('viewHint'));      // how to move the camera: a quiet line on the view
  unbracket(document.body);

  // the top bar keeps the place and the camera; the rest (area, look, mode) is under its ··· menu
  const sw = document.querySelector('#topbar .themeSw'), mode = document.querySelector('#topbar small.lite');
  if (sw) $('themeSlot').appendChild(sw);
  if (mode) $('modeSlot').appendChild(mode);
  document.addEventListener('click', (ev) => { if (!$('topMenu').contains(ev.target)) $('topMenu').open = false; });
  $('topMenu').addEventListener('keydown', (ev) => {   // Esc closes the menu and goes back to its ··· button
    if (ev.key === 'Escape' && $('topMenu').open) { $('topMenu').open = false; $('topMenu').querySelector('summary').focus(); }
  });

  // camera modes as buttons; the drop-down stays the one source of truth (the C key cycles it)
  const sel = $('camMode'), short = { orbit: 'Orbit', fly: 'Fly', chase: 'Follow', drone: 'Drone' };
  const box = $('camBtns');
  box.innerHTML = [...sel.options].map((o) => `<button type="button" data-v="${o.value}" title="${o.textContent}" aria-pressed="false">${short[o.value] || o.textContent}</button>`).join('');
  const sync = () => box.querySelectorAll('button').forEach((b) => {
    const on = b.dataset.v === sel.value; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  box.onclick = (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    sel.value = b.dataset.v; sel.onchange?.();
    if (ev.detail) b.blur();   // a mouse click hands W/A/S/D back to the camera; Enter or Space keeps the focus here
  };
  const change = sel.onchange;
  sel.onchange = () => { change?.(); sync(); };
  sync();

  // the instruments card folds to one line (range and sight), the playback bar hides behind a small button;
  // both choices are remembered
  const keep = (k, v) => { try { localStorage.setItem(k, v ? '1' : '0'); } catch { /* private mode */ } };
  const kept = (k) => { try { return localStorage.getItem(k) === '1'; } catch { return false; } };
  const fold = (on) => {
    $('instr').classList.toggle('folded', on); $('iFold').textContent = on ? '+' : '−';
    $('iFold').setAttribute('aria-expanded', on ? 'false' : 'true'); keep('fpv3d:instrFolded', on);
  };
  $('iFold').onclick = () => fold(!$('instr').classList.contains('folded'));
  fold(kept('fpv3d:instrFolded'));
  const tl = (on) => { document.body.classList.toggle('tl-min', on); keep('fpv3d:tlHidden', on); };
  // the pressed button disappears: the focus moves to the one that brings the bar back (and back again)
  $('tlHide').onclick = () => { tl(true); $('tlShow').focus(); };
  $('tlShow').onclick = () => { tl(false); $('tlHide').focus(); };
  tl(kept('fpv3d:tlHidden'));

  // the flight readout (hud.js) sits in the column on a wide screen, and floats over the view on a phone
  const hud = $('hud'), home = hud.parentNode, next = hud.nextSibling, wide = matchMedia(WIDE);
  const place = () => (wide.matches ? $('iHud').appendChild(hud) : home.insertBefore(hud, next));
  wide.addEventListener('change', place); place();

}

/** The signal figures, refreshed whenever the height or the radio setup changes. `sight` / `usable`: percent or null. */
export function updateInstrSignal({ rangeTxt, linkName, agl, sight, usable, hiddenPct }) {
  if (!$('iRange')) return;
  $('iRange').textContent = rangeTxt;
  $('iMini').textContent = sight != null ? `${rangeTxt} · ${sight} %` : rangeTxt;
  $('iRangeNote').textContent = `${linkName} · open sky`;
  if (sight != null) {
    $('iSightLbl').textContent = `In sight at ${agl} m`;
    $('iSight').textContent = `${sight} %`;
    $('iSightBar').style.width = `${sight}%`;
    $('iSightNote').textContent = `usable signal over ${usable} %`;
  } else if (hiddenPct != null) {          // scenes without the 3D volumes: the whole map, not just the range
    $('iSightLbl').textContent = `Not hidden at ${agl} m`;
    $('iSight').textContent = `${100 - hiddenPct} %`;
    $('iSightBar').style.width = `${100 - hiddenPct}%`;
    $('iSightNote').textContent = 'of the whole map';
  }
}

/** Buttons read "[refresh zones]" in the old style; the new layout labels them plainly ("refresh zones"). The
    labels are set in many places (and change while the page runs), so they are cleaned where they appear. */
export function unbracket(root) {
  const clean = (b) => {
    if (b.children.length) return;
    const t = b.textContent, m = /^\s*\[(.+)\]\s*$/.exec(t);
    if (m) b.textContent = m[1];
  };
  const all = () => root.querySelectorAll('button, a.navlink, a.iconbtn').forEach(clean);
  all();
  new MutationObserver((recs) => {
    for (const r of recs) {
      const el = r.target.nodeType === 3 ? r.target.parentElement : r.target;
      if (r.type === 'characterData') { if (el?.matches?.('button, a.navlink')) clean(el); continue; }
      if (el?.matches?.('button, a.navlink')) clean(el);
      r.addedNodes.forEach((n) => { if (n.nodeType !== 1) return; if (n.matches('button, a.navlink')) clean(n); n.querySelectorAll?.('button, a.navlink').forEach(clean); });
    }
  }).observe(root, { subtree: true, childList: true, characterData: true });
}
