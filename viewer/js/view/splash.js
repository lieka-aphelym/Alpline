// The 3D view's loading screen, look "K": the place's own aerial photo appears blurred and in coarse blocks, and
// turns sharp as the scene really loads (terrain, photo, signal shadows), until "ready". Before the scene's file is
// read, and for a place without a photo, the drawn Alps stay (theme.js). The photo is the very file the 3D view
// loads next, so the browser fetches it once.

const $ = (id) => document.getElementById(id);
let box = null, shown = false;

function setProgress(p) {
  if (box) box.style.setProperty('--p', String(Math.max(0, Math.min(1, p))));
}

/** Once scene.json is read: put the photo on the loading screen (if the place has one). */
export function splashPhoto(S) {
  const l = $('loading');
  if (!l || !S.meta?.ortho || box) return;
  const g = S.meta.grid, ratio = (g.max_e - g.min_e) / (g.max_n - g.min_n);
  box = document.createElement('div');
  box.className = 'spPhoto';
  box.style.setProperty('--ratio', String(Math.min(2, Math.max(0.5, ratio))));
  box.innerHTML = '<img alt=""><i class="spGrid"></i><span class="spLbl"></span><span class="spReady">ready</span>';
  box.querySelector('.spLbl').textContent = S.meta.title || S.meta.name || '';
  const img = box.querySelector('img');
  img.onload = () => {
    if (!box) return;
    shown = true;
    box.classList.add('on');
    l.classList.add('hasPhoto');                  // the drawn Alps give way to the photo
  };
  img.src = S.base + S.meta.ortho;
  l.insertBefore(box, l.firstChild);
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
