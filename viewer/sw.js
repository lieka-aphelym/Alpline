// Alpline app (phone / installed): keeps the app's own files so it opens instantly and can say when the computer
// can't be reached. Always asks the computer first (network first): the copy is only used when it doesn't answer.
// Data (/api/, /scenes/) is never stored here: it always comes live from the computer running Alpline.
const CACHE = 'alpline-v1';
const SHELL = ['/viewer/offline.html', '/viewer/theme.css', '/viewer/theme.js', '/viewer/drone.js', '/viewer/brand/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin || !u.pathname.startsWith('/viewer/')) return;   // /api, /scenes: live only
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && r.type === 'basic') { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return r;
  }).catch(async () => (await caches.match(e.request))
    || (e.request.mode === 'navigate' ? caches.match('/viewer/offline.html') : Response.error())));
});
