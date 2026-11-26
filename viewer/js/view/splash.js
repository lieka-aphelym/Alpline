// The 3D view's loading screen, look "K": the place's own aerial photo appears blurred and in coarse blocks, and
// turns sharp as the scene really loads (terrain, photo, signal shadows), until "ready".
//
// The frame of the photo shows as soon as the scene's file is read, and a small copy of the photo from the local
// server (/api/preview, a few tens of kB) fills it almost at once: waiting for the whole photo (up to 10 MB and more)
// used to leave the older drawn loading screen up for a moment first. Without the server (the online demo) the
// whole photo is used. The drawn Alps (theme.js) show only for a place without a photo, or when it cannot be read.

const $ = (id) => document.getElementById(id);
let box = null, shown = false;

function setProgress(p) {
  if (box) box.style.setProperty('--p', String(Math.max(0, Math.min(1, p))));
}

/** Once scene.json is read: put the photo on the loading screen (if the place has one). */
export function splashPhoto(S) {
  const l = $('loading');
  if (!l || box) return;
  if (!S.meta?.ortho) { l.classList.add('drawn'); return; }
  const g = S.meta.grid, ratio = (g.max_e - g.min_e) / (g.max_n - g.min_n);
  box = document.createElement('div');
  box.className = 'spPhoto';
  box.style.setProperty('--ratio', String(Math.min(2, Math.max(0.5, ratio))));
  box.innerHTML = '<img alt=""><i class="spGrid"></i><span class="spLbl"></span><span class="spReady">ready</span>';
  box.querySelector('.spLbl').textContent = S.meta.title || S.meta.name || '';
  const img = box.querySelector('img');
  const whole = S.base + S.meta.ortho, scene = S.base.split('/').filter(Boolean).pop();
  let tried = false;
  img.onload = () => {
    if (!box) return;
    shown = true;
    box.classList.add('on');
  };
  img.onerror = () => {
    if (!box) return;
    if (!tried) { tried = true; img.src = whole; return; }         // no server (online demo): the whole photo
    box.remove(); box = null;                                       // no photo after all: the drawn Alps
    l.classList.remove('hasPhoto'); l.classList.add('drawn');
  };
  const px = Math.min(720, Math.round(560 * (window.devicePixelRatio || 1)));   // the frame is 560 px wide at most
  img.src = `/api/preview?scene=${encodeURIComponent(scene)}&px=${px}`;
  l.insertBefore(box, l.firstChild);
  l.classList.add('hasPhoto');                    // the empty frame at once; the photo fades in when it arrives
  setProgress(0.1);
}

/** How far the loading has got, 0 to 1: the photo is that sharp. */
export function splashProgress(p) { setProgress(p); }

/** Before the loading screen goes: the photo shows sharp for a moment, with "ready". */
export async function splashDone() {
  if (!box || !shown) return;
  setProgress(1);
  box.classList.add('ready');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  await new Promise((ok) => setTimeout(ok, still ? 200 : 900));
}
