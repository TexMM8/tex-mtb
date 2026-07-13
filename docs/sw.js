// Apex service worker — v2 (aggiornamenti sempre freschi)
const CACHE = 'apex-v2';
const ICONS = ['./icons/icon-192.png','./icons/icon-512.png','./icons/apple-touch-icon.png','./icons/favicon.png'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ICONS)).catch(()=>{}));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  const isNav = e.request.mode === 'navigate' || url.pathname.endsWith('/') || url.pathname.endsWith('index.html');
  // App e dati: sempre dalla rete (fresco). Cache solo come rete di riserva offline.
  if (isNav || url.pathname.includes('/data/') || url.pathname.endsWith('.html')) {
    e.respondWith(
      fetch(e.request).then(r => {
        const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy));
        return r;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  // Icone/immagini: cache-first (non cambiano spesso).
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
