// Panel requests always use the network, including after an application update.
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(key => key.startsWith('arma-panel-')).map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});
