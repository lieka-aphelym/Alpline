// fpv3d: dark / light theme + Full / Lite badge. Loaded as a plain script in <head> so the page never flashes the
// wrong colours; adds the [dark] [light] switch next to the title and remembers the choice.
(function () {
  var KEY = 'fpv3d:theme', root = document.documentElement;
  function get() { try { return localStorage.getItem(KEY) || 'dark'; } catch (e) { return 'dark'; } }
  function set(t) {
    root.dataset.theme = t;
    try { localStorage.setItem(KEY, t); } catch (e) { /* private mode */ }
    document.querySelectorAll('.themeSw button').forEach(function (b) {
      b.classList.toggle('on', b.dataset.t === t); b.setAttribute('aria-pressed', String(b.dataset.t === t));
    });
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
  // Alpline logo: an edelweiss that is also a propeller (tools/make_brand.py writes FLOWER; colours follow the theme)
  var FLOWER = '<g class="lg-sw"><path d="M32.00 26.00 L40.00 15.92 L41.00 2.00 L24.00 15.92 Z" style="fill:var(--t-fg)"/><path d="M37.20 35.00 L41.93 46.97 L53.48 54.79 L49.93 33.11 Z" style="fill:var(--t-fg)"/><path d="M26.80 35.00 L14.07 33.11 L1.52 39.21 L22.07 46.97 Z" style="fill:var(--t-fg)"/><g transform="rotate(60 32 32)"><path class="lg-ch lg-w0" style="--dy:-4px;stroke:var(--t-fg);fill:none" d="M27.00 20.00 L34.00 12.00 L37.00 20.00" stroke-width="2.4" stroke-linecap="square"/></g><g transform="rotate(180 32 32)"><path class="lg-ch lg-w1" style="--dy:-4px;stroke:var(--t-fg);fill:none" d="M27.00 20.00 L34.00 12.00 L37.00 20.00" stroke-width="2.4" stroke-linecap="square"/></g><g transform="rotate(300 32 32)"><path class="lg-ch lg-w2" style="--dy:-4px;stroke:var(--t-fg);fill:none" d="M27.00 20.00 L34.00 12.00 L37.00 20.00" stroke-width="2.4" stroke-linecap="square"/></g></g><path class="lg-hub" d="M32.00 41.00 L24.21 27.50 L39.79 27.50 Z" style="fill:var(--t-acc)"/>';
  var LOGO = '<svg class="logo lg-intro" viewBox="0 0 64 64" aria-hidden="true">' + FLOWER + '</svg>';
  // the viewer's loading screen: the Alps in three layers, the pilot, and a line of sight that just clears the summit
  // to the flower (the flower is the drone). theme.css draws the line, then the flower comes in and spins.
  var SCENE = '<svg class="spScene" viewBox="0 0 160 90" aria-hidden="true">' +
    '<path class="spR3" d="M0 60 30 40 52 50 78 22 102 44 126 30 160 48V90H0Z"/>' +
    '<path class="spR2" d="M0 70 34 54 60 60 92 34 126 56 160 50V90H0Z"/>' +
    '<path class="spR1" d="M0 82 44 62 64 70 88 44 124 72 160 64V90H0Z"/>' +
    '<rect class="spPilot" x="13.5" y="61.5" width="5" height="5"/>' +
    '<path class="spLine" pathLength="1" d="M16 64 L125 22.8"/>' +
    '<svg class="logo" x="120" y="8" width="24" height="24" viewBox="0 0 64 64"><g class="spPop">' + FLOWER + '</g></svg></svg>';
  (function () {
    var l = document.createElement('link'); l.rel = 'icon'; l.type = 'image/svg+xml'; l.href = 'brand/icon.svg';
    document.head.appendChild(l);
  })();
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-logo]').forEach(function (e) { e.insertAdjacentHTML('afterbegin', LOGO); });
    document.querySelectorAll('[data-scene]').forEach(function (e) { e.insertAdjacentHTML('afterbegin', SCENE); });
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
