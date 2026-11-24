// fpv3d — tabbed side panel: icon rail + one group of sections at a time.
// Markup: <aside id=panel><nav class=rail><button data-tab=x>…</button>…</nav><div id=pbody>… <section data-tab=x> …
// Clicking the active tab (or the collapse button / h1) hides the panel body.
export function initTabs(panel, { storageKey = 'fpv3d:tab', fallback } = {}) {
  const rail = panel.querySelector('.rail'), body = panel.querySelector('#pbody');
  const buttons = [...rail.querySelectorAll('button[data-tab]')];
  const load = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const save = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };
  let current = null;
  function show(tab, { keepOpen = false } = {}) {
    if (!buttons.some((b) => b.dataset.tab === tab)) tab = fallback || buttons[0].dataset.tab;
    if (tab === current && !keepOpen) { toggle(); return; }
    current = tab;
    panel.classList.remove('collapsed');
    for (const b of buttons) { b.classList.toggle('on', b.dataset.tab === tab); b.setAttribute('aria-pressed', String(b.dataset.tab === tab)); }
    let first = true;
    for (const el of body.querySelectorAll('[data-tab]')) {
      const on = el.dataset.tab === tab;
      el.classList.toggle('tab-hidden', !on);
      el.classList.toggle('tab-first', on && first && el.tagName === 'SECTION');
      if (on && el.tagName === 'SECTION') first = false;
    }
    body.scrollTop = 0;
    save(storageKey, tab);
    panel.dispatchEvent(new CustomEvent('tabchange', { detail: tab }));
  }
  function toggle(force) {
    const c = panel.classList.toggle('collapsed', force);
    rail.querySelector('.railCollapse')?.setAttribute('aria-expanded', String(!c));
    save(storageKey + ':collapsed', c ? '1' : '0');
  }
  for (const b of buttons) b.onclick = () => show(b.dataset.tab);
  rail.querySelector('.railCollapse')?.addEventListener('click', () => toggle());
  /** dim tabs whose sections are all hidden by the app (e.g. no video support, no tracks) */
  function refreshDim() {
    for (const b of buttons) {
      const secs = [...body.querySelectorAll(`section[data-tab="${b.dataset.tab}"]`)];
      b.classList.toggle('dim', secs.length > 0 && secs.every((s) => s.hidden || s.style.display === 'none'));
    }
  }
  show(load(storageKey) || fallback || buttons[0].dataset.tab, { keepOpen: true });
  if (load(storageKey + ':collapsed') === '1') toggle(true);
  return { show, toggle, refreshDim, get current() { return current; } };
}

/** make a non-button element (a list row, a name) work like a button: Tab reaches it, Enter and Space press it */
export function pressable(el, fn) {
  el.tabIndex = 0; el.setAttribute('role', 'button'); el.onclick = fn;
  el.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); fn(e); } };
}
