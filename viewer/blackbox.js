// Flights tab: [download from the drone]. Starts `fpv3d blackbox` on the server (POST /api/blackbox) and shows its
// progress lines; flights added to this location are loaded right away, others get a link to their location.
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function initBlackbox({ S, $, onAdded }) {
  const btn = $('bbGet'), box = $('bbLog');
  if (!btn) return;
  const show = (lines, status) => {
    box.classList.remove('hidden');
    box.innerHTML = lines.filter((l) => !l.startsWith('ADDED ')).map((l) => {
      const cls = /→ added|^done: [1-9]/.test(l) ? 'ok' : /^(No |The |error|Traceback)|could not|failed/i.test(l) ? 'bad' : '';
      return `<div class="${cls}">${esc(l)}</div>`;
    }).join('') + (status === 'running' ? '<div class="muted">…</div>' : '');
    box.scrollTop = box.scrollHeight;
  };
  btn.onclick = async () => {
    btn.disabled = true; window.alpBusy?.(true);
    show(['starting…'], 'running');
    try {
      const r = await fetch('/api/blackbox', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene: S.meta.name, only_here: $('bbHere').checked }) });
      const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status);
      let k;
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 700));
        k = await (await fetch(`/api/jobs/${j.job}`)).json();
        show(k.lines || [], k.status);
        if (k.status !== 'running') break;
      }
      const added = (k.lines || []).filter((l) => l.startsWith('ADDED ')).map((l) => l.split(' ').slice(1));
      const here = added.filter(([scene]) => scene === S.meta.name);
      const other = [...new Set(added.filter(([scene]) => scene !== S.meta.name).map(([scene]) => scene))];
      if (other.length) {
        box.insertAdjacentHTML('beforeend', `<div>open ${other.map((n) => `<a href="?scene=${encodeURIComponent(n)}">${esc(n)}</a>`).join(', ')} to see the other flights</div>`);
      }
      if (here.length) await onAdded(`tracks/${here.at(-1)[1]}.json`);
    } catch (e) {
      show([`could not start: ${e.message}`], 'failed');
    } finally { btn.disabled = false; window.alpBusy?.(false); }
  };
}
