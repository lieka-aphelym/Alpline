// fpv3d: dark / light theme + Full / Lite badge. Loaded as a plain script in <head> so the page never flashes the
// wrong colours; adds the [dark] [light] switch next to the title and remembers the choice.
(function () {
  var KEY = 'fpv3d:theme', root = document.documentElement;
  function get() { try { return localStorage.getItem(KEY) || 'dark'; } catch (e) { return 'dark'; } }
  function set(t) {
    root.dataset.theme = t;
    try { localStorage.setItem(KEY, t); } catch (e) { /* private mode */ }
    document.querySelectorAll('.themeSw button').forEach(function (b) { b.classList.toggle('on', b.dataset.t === t); });
    window.dispatchEvent(new CustomEvent('fpv3d:theme', { detail: t }));
  }
  root.dataset.theme = get();
  // Full / Lite / phone: the ONE place this is decided (env.js hands it to the modules). The mode comes from the
  // launcher or --lite through /api/mode.js; ?mode=lite|full in the address overrides it.
  var mode = (new URLSearchParams(location.search).get('mode') || window.FPV3D_MODE) === 'lite' ? 'lite' : 'full';
  var phone = matchMedia('(pointer: coarse)').matches && Math.min(screen.width, screen.height) < 900;
  window.ALPLINE = { mode: mode, lite: mode === 'lite', phone: phone, light: mode === 'lite' || phone };
  root.dataset.mode = mode; if (phone) root.dataset.phone = '1';
  // installed app (phone / desktop): the service worker keeps the app's own files so it opens instantly and says when
  // the computer can't be reached. Only on secure pages (https, or this computer), as browsers require.
  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/viewer/sw.js', { scope: '/viewer/' }).catch(function () {}); });
  }
  // errors: a small notice on the page (also on the phone, where there are no developer tools) and an entry in
  // logs/errors.txt on the computer, instead of failing silently
  var seen = {}, bar = null, reports = 0;
  function oops(msg, stack) {
    msg = String(msg || 'unknown error').slice(0, 300);
    if (/ResizeObserver loop|^Script error\.?$/.test(msg) || /extension:\/\//.test(stack || '')) return;
    if (seen[msg]) return; seen[msg] = 1;
    if (reports++ < 10) {
      try {
        fetch('/api/client-error', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ page: location.pathname + location.search, message: msg, stack: String(stack || '').slice(0, 4000) }) }).catch(function () {});
      } catch (e) { /* offline */ }
    }
    if (!document.body) { window.addEventListener('DOMContentLoaded', function () { show(msg); }); return; }
    show(msg);
  }
  function show(msg) {
    if (!bar) {
      bar = document.createElement('div'); bar.className = 'alpOops'; bar.setAttribute('role', 'alert');
      var t = document.createElement('span'), r = document.createElement('button'), x = document.createElement('button');
      r.type = x.type = 'button'; r.textContent = '[reload]'; x.textContent = '×'; x.title = 'Close';
      r.addEventListener('click', function () { location.reload(); });
      x.addEventListener('click', function () { bar.remove(); bar = null; });
      bar.append(t, r, x); document.body.appendChild(bar);
    }
    bar.firstChild.textContent = 'Something went wrong: ' + msg + ' · details saved on the computer in logs/errors.txt';
  }
  window.addEventListener('error', function (e) {
    if (e.target && e.target !== window) return;                    // a missing image or tile: not a program error
    oops(e.message, e.error && e.error.stack);
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e.reason || {};
    if (r.name === 'AbortError') return;
    oops(r.message || r, r.stack);
  });
  window.alpOops = oops;
  // the app's name comes from the server (fpv3d/brand.py, through /api/mode.js): when it is not the one written in the
  // pages, every text and title is updated once the page is there (and remembered for the offline page)
  var WRITTEN = 'Alpline', WRITTEN_BY = 'lieka', brand = window.APP_BRAND;
  try { if (brand) localStorage.setItem('fpv3d:brand', JSON.stringify(brand)); else brand = JSON.parse(localStorage.getItem('fpv3d:brand') || 'null'); } catch (e) { /* private mode */ }
  brand = brand || { name: WRITTEN, by: WRITTEN_BY };
  window.APP_BRAND = brand;
  function rebrand(text) {
    return text.split(WRITTEN.toUpperCase()).join(brand.name.toUpperCase()).split(WRITTEN).join(brand.name).split('by ' + WRITTEN_BY).join('by ' + brand.by);
  }
  if (brand.name !== WRITTEN || brand.by !== WRITTEN_BY) {
    window.addEventListener('DOMContentLoaded', function () {
      document.title = rebrand(document.title);
      var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n, todo = [];
      while ((n = w.nextNode())) if (n.nodeValue.toLowerCase().indexOf(WRITTEN.toLowerCase()) >= 0 || n.nodeValue.indexOf(WRITTEN_BY) >= 0) todo.push(n);
      todo.forEach(function (t) { if (!t.parentElement.closest('script,style')) t.nodeValue = rebrand(t.nodeValue); });
      document.querySelectorAll('[title*="' + WRITTEN + '"]').forEach(function (el) { el.title = rebrand(el.title); });
    });
  }
  window.ALPLINE.app = matchMedia('(display-mode: standalone)').matches || /[?&]app=1/.test(location.search);
  if (window.ALPLINE.app) root.dataset.app = '1';
  // the logo is busy (steady spin, branches pulse) while something loads or builds: alpBusy(true) ... alpBusy(false)
  var busyN = 0;
  window.alpBusy = function (on) { busyN = Math.max(0, busyN + (on ? 1 : -1)); root.classList.toggle('alp-busy', busyN > 0); };
  // play the spin-up again (the viewer calls it when its loading screen goes away)
  window.alpIntro = function () {
    document.querySelectorAll('svg.logo').forEach(function (s) { s.classList.remove('lg-intro'); void s.getBoundingClientRect(); s.classList.add('lg-intro'); });
  };
  // the spin-up plays once when the page opens; afterwards the class goes, so a later busy spin never replays it
  document.addEventListener('animationend', function (e) {
    var svg = e.target.closest && e.target.closest('svg.lg-intro');
    if (svg && e.target.classList.contains('lg-w2')) svg.classList.remove('lg-intro');
  });
  // Alpline logo: tab icon + the propeller swirl in front of the name (colours follow the theme)
  var LOGO = '<svg class="logo lg-intro" viewBox="0 0 64 64" aria-hidden="true"><g class="lg-sw"><path d="M32.00 3.85 L33.70 3.64 L35.41 3.72 L37.11 3.94 L38.78 4.29 L40.42 4.76 L42.03 5.35 L43.59 6.04 L45.10 6.83 L46.55 7.72 L47.94 8.70 L49.25 9.77 L50.49 10.92 L51.64 12.14 L52.71 13.44 L53.68 14.79 L54.56 16.20 L55.34 17.66 L56.02 19.16 L56.59 20.70 L57.06 22.25 L57.42 23.83 L57.67 25.42 L57.82 27.01 L57.86 28.60 L57.79 30.17 L57.62 31.72 L57.34 33.24 L56.97 34.73 L56.50 36.18 L55.93 37.58 L55.28 38.92 L54.55 40.21 L53.74 41.42 L52.85 42.57 L51.90 43.64 L50.89 44.62 L49.83 45.52 L48.72 46.34 L47.56 47.06 L46.38 47.69 L45.17 48.23 L43.94 48.66 L42.70 49.00 L41.46 49.24 L40.21 49.37 L38.98 49.39 L37.76 49.28 L36.53 48.91 L36.45 48.62 L37.36 48.08 L38.29 47.66 L39.20 47.22 L40.10 46.76 L40.98 46.26 L41.83 45.72 L42.67 45.14 L43.47 44.52 L44.25 43.86 L45.00 43.15 L45.72 42.41 L46.40 41.62 L47.05 40.80 L47.65 39.93 L48.22 39.03 L48.74 38.09 L49.22 37.12 L49.65 36.12 L50.03 35.08 L50.36 34.01 L50.64 32.92 L50.86 31.79 L51.02 30.65 L51.12 29.48 L51.15 28.30 L51.12 27.10 L51.03 25.89 L50.87 24.66 L50.64 23.43 L50.33 22.20 L49.95 20.97 L49.50 19.75 L48.97 18.53 L48.37 17.33 L47.69 16.14 L46.93 14.98 L46.09 13.84 L45.18 12.74 L44.18 11.67 L43.12 10.64 L41.97 9.66 L40.76 8.73 L39.47 7.86 L38.11 7.03 L36.68 6.27 L35.19 5.57 L33.63 4.90 L32.00 4.15 Z" style="fill:var(--t-fg)"/><path d="M56.38 46.07 L55.71 47.65 L54.79 49.09 L53.75 50.45 L52.61 51.73 L51.38 52.91 L50.07 54.01 L48.69 55.02 L47.25 55.93 L45.75 56.74 L44.21 57.45 L42.63 58.06 L41.01 58.55 L39.38 58.94 L37.72 59.22 L36.06 59.38 L34.40 59.44 L32.75 59.38 L31.11 59.22 L29.49 58.95 L27.91 58.58 L26.36 58.10 L24.86 57.52 L23.41 56.85 L22.02 56.09 L20.69 55.25 L19.43 54.32 L18.25 53.32 L17.15 52.25 L16.13 51.12 L15.20 49.94 L14.36 48.70 L13.62 47.42 L12.97 46.11 L12.42 44.77 L11.97 43.42 L11.62 42.05 L11.37 40.68 L11.22 39.31 L11.17 37.95 L11.22 36.61 L11.36 35.29 L11.60 34.01 L11.93 32.77 L12.35 31.57 L12.85 30.43 L13.45 29.35 L14.16 28.35 L15.09 27.47 L15.38 27.55 L15.39 28.60 L15.30 29.62 L15.22 30.62 L15.17 31.63 L15.16 32.64 L15.20 33.65 L15.29 34.67 L15.42 35.68 L15.60 36.68 L15.84 37.68 L16.13 38.68 L16.47 39.66 L16.86 40.63 L17.30 41.59 L17.80 42.53 L18.35 43.45 L18.95 44.35 L19.61 45.23 L20.32 46.08 L21.08 46.90 L21.89 47.68 L22.75 48.43 L23.66 49.14 L24.62 49.81 L25.63 50.44 L26.68 51.01 L27.78 51.54 L28.92 52.01 L30.10 52.42 L31.32 52.77 L32.57 53.06 L33.86 53.28 L35.18 53.43 L36.52 53.51 L37.89 53.51 L39.28 53.44 L40.68 53.28 L42.09 53.04 L43.51 52.72 L44.94 52.31 L46.36 51.81 L47.77 51.22 L49.18 50.54 L50.57 49.77 L51.94 48.92 L53.30 47.98 L54.65 46.96 L56.12 45.92 Z" style="fill:var(--t-fg)"/><path d="M7.62 46.07 L6.59 44.70 L5.80 43.19 L5.15 41.61 L4.61 39.98 L4.20 38.32 L3.90 36.64 L3.72 34.94 L3.65 33.24 L3.70 31.54 L3.85 29.85 L4.12 28.17 L4.50 26.53 L4.98 24.92 L5.57 23.35 L6.26 21.83 L7.04 20.36 L7.91 18.96 L8.87 17.62 L9.91 16.35 L11.03 15.17 L12.22 14.07 L13.46 13.06 L14.77 12.13 L16.12 11.31 L17.52 10.58 L18.95 9.96 L20.41 9.43 L21.88 9.01 L23.37 8.70 L24.87 8.48 L26.36 8.38 L27.83 8.37 L29.29 8.46 L30.73 8.66 L32.13 8.95 L33.49 9.33 L34.80 9.80 L36.06 10.35 L37.26 10.99 L38.40 11.70 L39.47 12.48 L40.46 13.33 L41.37 14.23 L42.20 15.19 L42.93 16.20 L43.57 17.26 L44.08 18.37 L44.38 19.62 L44.17 19.83 L43.25 19.32 L42.42 18.73 L41.58 18.15 L40.73 17.61 L39.86 17.10 L38.97 16.62 L38.05 16.19 L37.11 15.80 L36.14 15.46 L35.16 15.16 L34.15 14.92 L33.13 14.72 L32.10 14.57 L31.04 14.48 L29.98 14.44 L28.91 14.45 L27.82 14.53 L26.74 14.66 L25.65 14.84 L24.56 15.09 L23.47 15.40 L22.39 15.77 L21.32 16.21 L20.26 16.70 L19.22 17.26 L18.19 17.89 L17.19 18.58 L16.21 19.33 L15.26 20.14 L14.35 21.02 L13.47 21.97 L12.64 22.97 L11.85 24.04 L11.11 25.16 L10.42 26.34 L9.79 27.58 L9.23 28.88 L8.73 30.22 L8.30 31.61 L7.95 33.05 L7.67 34.53 L7.47 36.05 L7.36 37.60 L7.33 39.19 L7.38 40.81 L7.51 42.46 L7.72 44.14 L7.88 45.92 Z" style="fill:var(--t-fg)"/></g><g class="lg-tr"><path d="M32 28 L32 45.5" class="lg-stem" style="stroke:var(--t-acc);fill:none" stroke-width="2.6" stroke-linecap="butt"/><path d="M24 36.1 L32 28.1 L40 36.1" class="lg-w0" style="--o:1;--dy:0.0px;stroke:var(--t-acc);fill:none" stroke-width="2.6" stroke-linecap="square" stroke-linejoin="miter" opacity="1"/><path d="M24 31.3 L32 23.3 L40 31.3" class="lg-w1" style="--o:1;--dy:-4.8px;stroke:var(--t-acc);fill:none" stroke-width="2.6" stroke-linecap="square" stroke-linejoin="miter" opacity="1"/><path d="M24 26.5 L32 18.5 L40 26.5" class="lg-w2" style="--o:1;--dy:-9.6px;stroke:var(--t-acc);fill:none" stroke-width="2.6" stroke-linecap="square" stroke-linejoin="miter" opacity="1"/></g></svg>';
  (function () {
    var l = document.createElement('link'); l.rel = 'icon'; l.type = 'image/svg+xml'; l.href = 'brand/icon.svg';
    document.head.appendChild(l);
  })();
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-logo]').forEach(function (e) { e.insertAdjacentHTML('afterbegin', LOGO); });
    if (document.getElementById('loading')) window.alpBusy(true);   // the viewer: busy until its loading screen goes
    var h1 = document.querySelector('#panel header h1, header h1');
    if (!h1) return;
    if (!h1.querySelector('svg.logo')) h1.insertAdjacentHTML('afterbegin', LOGO);
    var sw = document.createElement('span');
    sw.className = 'themeSw'; sw.title = 'Dark for indoors, light for sunlight at the field';
    ['dark', 'light'].forEach(function (t) {
      var b = document.createElement('button');
      b.type = 'button'; b.dataset.t = t; b.textContent = t;
      b.addEventListener('click', function () { set(t); });
      sw.appendChild(b);
    });
    h1.insertAdjacentElement('afterend', sw);
    set(get());
    // Full / Lite mode badge (the mode is chosen when the program starts: launcher or --lite)
    var m = window.ALPLINE.mode;
    var b = document.querySelector('small.lite');
    if (b) { b.textContent = m === 'lite' ? 'lite' : 'full'; b.title = m === 'lite'
      ? 'Lite mode: lighter 3D and lighter defaults for new locations (choose in the launcher)'
      : 'Full mode (choose Lite in the launcher for slower computers)'; }
  });
})();
