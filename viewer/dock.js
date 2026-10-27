// fpv3d lite: let a floating box (the playback bar) be dragged anywhere by its grip.
// The position is remembered per browser; double-click the grip to put it back in its default place.
export function makeMovable(el, grip, key) {
  const load = () => { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } };
  const save = (p) => { try { p ? localStorage.setItem(key, JSON.stringify(p)) : localStorage.removeItem(key); } catch { /* private mode */ } };
  function place(p) {
    if (!p) { el.style.left = el.style.top = el.style.bottom = el.style.transform = ''; el.classList.remove('moved'); return; }
    const r = el.getBoundingClientRect();
    const x = Math.max(4, Math.min(innerWidth - r.width - 4, p.x * innerWidth));
    const y = Math.max(4, Math.min(innerHeight - r.height - 4, p.y * innerHeight));
    Object.assign(el.style, { left: `${x}px`, top: `${y}px`, bottom: 'auto', transform: 'none' });
    el.classList.add('moved');
  }
  let start = null;
  grip.addEventListener('pointerdown', (e) => {
    const r = el.getBoundingClientRect();
    start = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    grip.setPointerCapture(e.pointerId); e.preventDefault();
  });
  grip.addEventListener('pointermove', (e) => {
    if (!start) return;
    place({ x: (e.clientX - start.dx) / innerWidth, y: (e.clientY - start.dy) / innerHeight });
  });
  grip.addEventListener('pointerup', () => {
    if (!start) return; start = null;
    const r = el.getBoundingClientRect();
    save({ x: r.left / innerWidth, y: r.top / innerHeight });
  });
  grip.addEventListener('dblclick', () => { save(null); place(null); });
  addEventListener('resize', () => place(load()));
  // the box may be hidden at start (no flight yet): place it once it has a size
  new ResizeObserver(() => { if (el.offsetWidth) place(load()); }).observe(el);
  place(load());
}
