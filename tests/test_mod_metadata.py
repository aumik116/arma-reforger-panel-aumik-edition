import json
import unittest
from mod_metadata import parse_workshop_page


class MetadataTests(unittest.TestCase):
    def test_current_and_pinned_sizes_and_trusted_thumbnail(self):
        asset = {'id': 'ABC', 'currentVersionNumber': '2', 'currentVersionSize': 4096,
                 'versions': [{'version': '1', 'totalFileSize': 1024}, {'version': 'bad', 'totalFileSize': -1}],
                 'previews': [{'url': 'https://evil.example/image.png'}, {'url': 'https://ar-gcp-cdn.bistudio.com/image/abc/test.jpg'}]}
        page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({'props': {'pageProps': {'asset': asset}}}) + '</script>'
        data = parse_workshop_page(page, 'ABC')
        self.assertEqual(data['sizes'], {'1': 1024, '2': 4096})
        self.assertEqual(data['current_version'], '2')
        self.assertTrue(data['thumbnail'].startswith('https://ar-gcp-cdn.bistudio.com/'))
        with self.assertRaises(ValueError):
            parse_workshop_page(page, 'DEF')

    def test_unavailable_page_does_not_invent_sizes(self):
        with self.assertRaises(ValueError):
            parse_workshop_page('<h1>Not found</h1>', 'ABC')
