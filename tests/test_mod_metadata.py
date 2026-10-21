import json
import unittest
from mod_metadata import parse_workshop_page, scenario_preview
from unittest.mock import Mock


class MetadataTests(unittest.TestCase):
    def test_current_and_pinned_sizes_and_trusted_thumbnail(self):
        asset = {'id': 'ABC', 'currentVersionNumber': '2', 'currentVersionSize': 4096,
                 'versions': [{'version': '1', 'totalFileSize': 1024, 'scenarios':[{'gameId':'older-scenario'}]}, {'version': 'bad', 'totalFileSize': -1}],
                 'previews': [{'url': 'https://evil.example/image.png'}, {'url': 'https://ar-gcp-cdn.bistudio.com/image/abc/test.jpg'}]}
        page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({'props': {'pageProps': {'asset': asset, 'assetVersionDetail':{'scenarios':[{'gameId':'active-scenario'}]}}}}) + '</script>'
        data = parse_workshop_page(page, 'ABC')
        self.assertEqual(data['sizes'], {'1': 1024, '2': 4096})
        self.assertEqual(data['current_version'], '2')
        self.assertEqual(data['scenario_ids'], ['active-scenario','older-scenario'])
        self.assertTrue(data['thumbnail'].startswith('https://ar-gcp-cdn.bistudio.com/'))
        with self.assertRaises(ValueError):
            parse_workshop_page(page, 'DEF')

    def test_unavailable_page_does_not_invent_sizes(self):
        with self.assertRaises(ValueError):
            parse_workshop_page('<h1>Not found</h1>', 'ABC')

    def test_preview_never_uses_an_unrelated_mod_and_retries_pending_metadata(self):
        metadata = Mock()
        metadata.get.side_effect = lambda key: {
            'AAA':{'status':'available','scenario_ids':['other'],'thumbnail':'wrong'},
            'BBB':{'status':'available','scenario_ids':['active'],'thumbnail':'right'},
            'CCC':{'status':'pending'},
        }[key]
        mods = [{'modId':'aaa'},{'modId':'bbb'}]
        self.assertEqual(scenario_preview(metadata,'active',mods)['thumbnail'], 'right')
        self.assertIsNone(scenario_preview(metadata,'unknown',mods)['thumbnail'])
        self.assertEqual(scenario_preview(metadata,'unknown',[{'modId':'ccc'}])['status'],'pending')
