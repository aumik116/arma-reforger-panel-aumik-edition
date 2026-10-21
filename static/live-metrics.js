// Fetch streaming preserves the selected-server header used by ordinary requests.
window.liveMetrics = {last: 0, data: null, healthy() { return !document.hidden && Date.now() - this.last < 7000; }};
(() => {
  let controller, retry;
  const label = document.createElement('span');
  label.className = 'feature-note'; label.textContent = 'Metrics: connecting · 10s fallback';
  const anchor = document.getElementById('overview-feedback') || document.querySelector('footer');
  anchor?.insertAdjacentElement('beforebegin', label);
  const fleet = !!document.getElementById('overview-rows');
  async function connect() {
    if (document.hidden) return;
    const active = new AbortController();
    controller = active;
    let watchdog = setInterval(() => { if (Date.now() - received > 8000) active.abort(); }, 2000);
    let received = Date.now();
    try {
      const response = await fetch('/api/live-metrics' + (fleet ? '?fleet=1' : ''), {signal:active.signal});
      if (response.status === 401) { location.href = '/login'; return; }
      if (!response.ok || !response.body) throw new Error('Stream unavailable');
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream:true});
        let end;
        while ((end = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0,end); buffer = buffer.slice(end+2);
          if (!frame.startsWith('data: ')) continue;
          const data = JSON.parse(frame.slice(6));
          received = Date.now();
          label.textContent = 'Metrics: live · ~2s';
          window.liveMetrics.last = received; window.liveMetrics.data = data;
          document.dispatchEvent(new CustomEvent('live-metrics', {detail:data}));
        }
      }
    } catch (_) { /* Ordinary polling remains available while reconnecting. */ }
    finally {
      clearInterval(watchdog);
      if (controller === active) { window.liveMetrics.last = 0; label.textContent = 'Metrics: reconnecting · 10s fallback'; }
      if (!document.hidden && controller === active) retry = setTimeout(connect, 3000);
    }
  }
  document.addEventListener('visibilitychange', () => {
    clearTimeout(retry); controller?.abort(); controller = null; window.liveMetrics.last = 0;
    if (!document.hidden) { clearTimeout(retry); retry = setTimeout(connect, 100); }
  });
  window.addEventListener('pagehide', () => { clearTimeout(retry); controller?.abort(); controller = null; });
  connect();
})();
