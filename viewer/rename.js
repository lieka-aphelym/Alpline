import { esc } from './esc.js';
// fpv3d viewer: rename or delete the location, rename a flight log (clean ASCII file names; the server keeps the
// NNN_ number of a location). Moves this browser's saved antenna edits and video sync along with the new name.
export const slugify = (s) => s.normalize('NFKD').replace(/[^\x00-\x7f]/g, '').toLowerCase().replace(/[^a-z0-9-]+/g, '_').replace(/_+/g, '_').replace(/^[_-]+|[_-]+$/g, '').slice(0, 60);
export const noEmoji = (s) => s.replace(/[\p{Extended_Pictographic}\u{FE0F}\u{200D}]/gu, '').replace(/\s{2,}/g, ' ').trim();
async function postRename(body) {
  const r = await fetch('/api/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  let j = {}; try { j = await r.json(); } catch { /* not the fpv3d server */ }
  if (!r.ok || j.error) throw new Error(j.error || `server answered ${r.status} (start it with python -m fpv3d serve)`);
  return j;
}
export function initRename({ S, $, refreshTracks }) {
  const msg = (id, text, cls = '') => { $(id).textContent = text; $(id).className = 'small ' + cls; };
  // flight log
  $('trkRenBtn').onclick = () => {
    if (!S.track) return;
    $('trkRen').classList.toggle('hidden'); $('trkRenName').value = S.track.name; msg('trkRenMsg', ''); $('trkRenName').select();
  };
  $('trkRenCancel').onclick = () => $('trkRen').classList.add('hidden');
  $('trkRenName').oninput = () => msg('trkRenMsg', slugify($('trkRenName').value) ? `→ ${slugify($('trkRenName').value)}` : '', 'muted');
  $('trkRenName').onkeydown = (e) => { if (e.key === 'Enter') $('trkRenOk').click(); };
  $('trkRenOk').onclick = async () => {
    const old = S.track?.name, nn = slugify($('trkRenName').value);
    if (!old || !nn) return;
    if (nn === old) { $('trkRen').classList.add('hidden'); return; }
    msg('trkRenMsg', 'renaming…', 'muted');
    try {
      const j = await postRename({ kind: 'log', scene: S.meta.name, old, new: nn });
      try {   // keep the video sync saved for this log
        const pre = `fpv3d:sync:${S.meta.name}:${old}:`;
        for (const k of Object.keys(localStorage)) if (k.startsWith(pre)) { localStorage.setItem(`fpv3d:sync:${S.meta.name}:${j.name}:` + k.slice(pre.length), localStorage.getItem(k)); localStorage.removeItem(k); }
      } catch { /* private mode */ }
      const cmp = $('cmpPick').value;
      await refreshTracks(j.file);
      if (cmp && cmp !== `tracks/${old}.json`) $('cmpPick').value = cmp;
      $('trkRen').classList.add('hidden');
    } catch (e) { msg('trkRenMsg', e.message, 'err'); }
  };
  // location
  const showLoc = () => { $('locNameShow').innerHTML = `<b>${esc(S.meta.title)}</b> <span class="muted">(${esc(S.meta.name)})</span>`; };
  showLoc();
  $('locRenBtn').onclick = () => {
    $('locRen').classList.toggle('hidden'); $('locRenTitle').value = S.meta.title; $('locRenName').value = S.meta.name;
    delete $('locRenName').dataset.touched; msg('locRenMsg', '');
  };
  $('locRenCancel').onclick = () => $('locRen').classList.add('hidden');
  $('locDelBtn').onclick = () => { $('locDel').classList.toggle('hidden'); $('locRen').classList.add('hidden'); };
  $('locDelCancel').onclick = () => $('locDel').classList.add('hidden');
  $('locDelOk').onclick = async () => {
    msg('locDelMsg', 'deleting…', 'muted');
    try {
      const r = await fetch('/api/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: S.meta.name }) });
      let j = {}; try { j = await r.json(); } catch { /* not the fpv3d server */ }
      if (!r.ok || j.error) throw new Error(j.error || `server answered ${r.status}`);
      location.href = 'map.html';
    } catch (e) { msg('locDelMsg', e.message, 'err'); }
  };
  $('locRenTitle').oninput = () => { if (!$('locRenName').dataset.touched) $('locRenName').value = slugify($('locRenTitle').value); };
  $('locRenName').oninput = () => { $('locRenName').dataset.touched = '1'; };
  $('locRenOk').onclick = async () => {
    const nn = slugify($('locRenName').value), title = noEmoji($('locRenTitle').value);
    if (!nn) { msg('locRenMsg', 'file name is empty', 'err'); return; }
    msg('locRenMsg', 'renaming…', 'muted');
    try {
      const old = S.meta.name;
      const j = await postRename({ kind: 'location', old, new: nn, title });
      try {   // move this browser's saved antenna edits / video sync along
        for (const k of Object.keys(localStorage)) {
          const nk = k === `fpv3d:links:${old}` ? `fpv3d:links:${j.name}`
            : k.startsWith(`fpv3d:sync:${old}:`) ? `fpv3d:sync:${j.name}:` + k.slice(`fpv3d:sync:${old}:`.length) : null;
          if (nk && nk !== k) { localStorage.setItem(nk, localStorage.getItem(k)); localStorage.removeItem(k); }
        }
      } catch { /* private mode */ }
      location.search = `?scene=${encodeURIComponent(j.name)}`;
    } catch (e) { msg('locRenMsg', e.message, 'err'); }
  };
}
