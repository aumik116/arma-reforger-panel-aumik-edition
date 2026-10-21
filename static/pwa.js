// Optional installed-app support; normal panel use does not require a worker.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js', {updateViaCache: 'none'}).catch(() => {});
}
