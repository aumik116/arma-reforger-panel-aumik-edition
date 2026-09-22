"""Bounded, cached metadata reads from public Arma Workshop pages."""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_workshop_page(page, mod_id):
    match = re.search(r'<script\b[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not match:
        raise ValueError('Workshop metadata unavailable')
    asset = json.loads(match.group(1))['props']['pageProps']['asset']
    if asset.get('id', '').upper() != mod_id:
        raise ValueError('Workshop ID mismatch')
    sizes = {}
    for version in asset.get('versions', []):
        size = version.get('totalFileSize')
        if type(size) is int and size >= 0:
            sizes[str(version['version'])] = size
    current = str(asset.get('currentVersionNumber', ''))
    size = asset.get('currentVersionSize')
    if current and type(size) is int and size >= 0:
        sizes[current] = size
    image = None
    for preview in asset.get('previews', []):
        candidate = preview.get('url', '')
        parsed = urlparse(candidate)
        if parsed.scheme == 'https' and parsed.netloc == 'ar-gcp-cdn.bistudio.com' and parsed.path.startswith('/image/'):
            image = candidate
            break
    return {'status': 'available', 'current_version': current, 'sizes': sizes, 'thumbnail': image}


class ModMetadata:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.pending = {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='workshop')

    def _fetch(self, mod_id):
        try:
            request = Request('https://reforger.armaplatform.com/workshop/' + mod_id,
                              headers={'User-Agent': 'ReforgerServerPanel/1.0', 'Accept': 'text/html'})
            with build_opener(NoRedirect).open(request, timeout=8) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('Workshop page too large')
            result = parse_workshop_page(raw.decode('utf-8'), mod_id)
        except Exception:
            result = {'status': 'unavailable', 'sizes': {}, 'thumbnail': None}
        with self.lock:
            self.cache[mod_id] = (time.monotonic(), result)
            self.pending.pop(mod_id, None)
            while len(self.cache) > 512:
                self.cache.pop(next(iter(self.cache)))
        return result

    def get(self, mod_id):
        if not re.fullmatch(r'[0-9A-F]{1,32}', mod_id):
            return {'status': 'unavailable', 'sizes': {}, 'thumbnail': None}
        with self.lock:
            cached = self.cache.get(mod_id)
            if cached and time.monotonic() - cached[0] < (3600 if cached[1]['status'] == 'available' else 300):
                return cached[1]
            if mod_id not in self.pending:
                if len(self.pending) >= 16:
                    return {'status': 'pending'}
                self.pending[mod_id] = self.pool.submit(self._fetch, mod_id)
            return {'status': 'pending'}
