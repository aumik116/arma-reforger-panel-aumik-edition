const CACHE_NAME = 'arma-panel-v2';

// Do not cache on installation; panel data must remain live
self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.map(key => caches.delete(key)))
    )
  );
  self.clients.claim();
});

// Always use the network for current panel data
self.addEventListener('fetch', event => {
  event.respondWith(
    fetch(event.request).catch(() =>
      caches.match(event.request)
    )
  );
});