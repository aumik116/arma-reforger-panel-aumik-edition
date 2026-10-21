"""Shared, demand-driven two-second snapshots and authenticated SSE delivery."""
import json
import threading
import time

from concurrent.futures import ThreadPoolExecutor

from flask import Response, request


def install(api):
    cache = {}
    lock = threading.Lock()
    players = {}
    player_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='live-players')

    def dispatch(path, cookie, server=None):
        headers = {'Cookie': cookie}
        if server is not None:
            headers['X-Server-ID'] = server
        with api.app.test_request_context(path, headers=headers):
            response = api.app.full_dispatch_request()
            return response.status_code, response.get_json()

    original_metrics = api.app.view_functions['api_metrics']

    def snapshot():
        instance = api.selected_instance()
        key = instance.id if instance else ''
        with lock:
            previous = cache.get(key)
            if previous and time.monotonic() - previous[0] < 2:
                return previous[1]
            data = original_metrics().get_json()
            pid = api.get_server_pid()
            previous_players = players.get(key)
            count = data.get('player_count')
            if count is None and previous and time.monotonic() - previous[0] < 15:
                count = previous[1].get('players')
            if previous_players and previous_players[1].done():
                try:
                    code, roster = previous_players[1].result()
                    count = len(roster['players']) if code == 200 and roster.get('available') else None
                except Exception:
                    count = None  # Player query failures must not stall resource readings.
            if (not previous_players or previous_players[1].done() and time.monotonic() - previous_players[0] >= 10) and sum(not item[1].done() for item in players.values()) < 8:
                players[key] = (time.monotonic(), player_pool.submit(dispatch, '/api/players', request.headers.get('Cookie', ''), key))
            data.update(players=count if pid else 0,
                        uptime=api.format_uptime(api.get_process_uptime(pid)) if pid else '—')
            cache[key] = (time.monotonic(), data)
            for old in list(cache):
                if time.monotonic() - cache[old][0] > 300:
                    cache.pop(old)
                    players.pop(old, None)
            return data

    api.app.view_functions['api_metrics'] = lambda: api.jsonify(snapshot())
    original_host = api.app.view_functions['api_host_metrics']
    host_cache = [0, None]

    def host_snapshot():
        with lock:
            if time.monotonic() - host_cache[0] >= 2:
                host_cache[:] = [time.monotonic(), original_host().get_json()]
            return api.jsonify(host_cache[1])

    api.app.view_functions['api_host_metrics'] = host_snapshot
    api.PANEL_WIDE_ENDPOINTS.add('live_metrics_stream')

    @api.app.get('/api/live-metrics')
    def live_metrics_stream():
        # Dispatch ordinary authenticated endpoints for every frame, so permission
        # changes and deleted servers take effect without waiting for reconnect.
        cookie = request.headers.get('Cookie', '')
        selected = request.headers.get('X-Server-ID', '')
        fleet = request.args.get('fleet') == '1'

        def read(path, server=None):
            return dispatch(path, cookie, server)

        def frames():
            yield 'retry: 3000\n\n'
            # Periodic reconnect also releases the request thread and renews auth.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                started = time.monotonic()
                if fleet:
                    code, listing = read('/api/servers')
                    if code != 200:
                        return
                    ids = [s['id'] for s in listing['servers'] if s['state'] == 'ready']
                    if listing.get('legacy_server'):
                        ids.append('')
                else:
                    ids = [selected]
                readings = {}
                for server in ids:
                    code, data = read('/api/metrics', server)
                    if code == 401:
                        return
                    readings[server] = data if code == 200 else None
                code, host = read('/api/host-metrics')
                if code != 200:
                    return
                yield 'data: ' + json.dumps(dict(servers=readings, host=host)) + '\n\n'
                time.sleep(max(0, 2 - (time.monotonic() - started)))

        return Response(frames(), mimetype='text/event-stream', headers={
            'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no'})
