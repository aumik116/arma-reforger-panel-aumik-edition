import copy
import json
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
from unittest.mock import patch
from armahq_compare import ArmaHQCompare, StaleComparison, parse_server_page, server_id

SID = '9c9f76f2-094b-4314-a9b5-b87029ed40e7'
LOCAL = [{'modId':'AAAA', 'name':'Common', 'version':'1'}, {'modId':'BBBB', 'name':'Extra'},
         {'modId':'CCCC', 'name':'Unpinned'}]
REMOTE = [{'modId':'aaaa', 'name':'Common', 'version':'2'}, {'modId':'DDDD', 'name':'Missing', 'version':'3'},
          {'modId':'CCCC', 'name':'Unpinned', 'version':'4'}]


class ComparisonTests(unittest.TestCase):
    def test_slow_fetch_does_not_block_reviewed_changes(self):
        service = ArmaHQCompare()
        comparison = service.compare_json(REMOTE, LOCAL, 1)
        entered, release = threading.Event(), threading.Event()
        response = MagicMock()
        def read(_limit):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Test did not release response')
            return b'[]'
        response.__enter__.return_value.read.side_effect = read
        with patch('armahq_compare.build_opener') as opener, ThreadPoolExecutor(max_workers=2) as pool:
            opener.return_value.open.return_value = response
            fetching = pool.submit(service._fetch, '/api/servers/list')
            try:
                self.assertTrue(entered.wait(2))
                applying = pool.submit(service.apply, comparison['token'], {'missing':['DDDD']}, LOCAL, 1)
                mods, _ = applying.result(timeout=1)
                self.assertEqual(mods[-1]['modId'], 'DDDD')
            finally:
                release.set()
            self.assertEqual(fetching.result(timeout=2), '[]')

    def test_parses_public_flight_data_without_executing_scripts(self):
        record = {'id': SID, 'name':'Server', 'mods':REMOTE, 'modCount':3}
        frame = '0:' + json.dumps({'initialServer':record})
        html = '<script>self.__next_f.push(' + json.dumps([1, frame[:30]]) + ')</script>'
        html += '<script>self.__next_f.push(' + json.dumps([1, frame[30:]]) + ')</script>'
        result = parse_server_page(html, SID)
        self.assertEqual(result['mods'][0]['modId'], 'AAAA')
        with self.assertRaises(ValueError):
            parse_server_page(html, '00000000-0000-0000-0000-000000000000')
        record['modCount'] = 5
        with self.assertRaisesRegex(ValueError,'incomplete'):
            parse_server_page('<script>self.__next_f.push('+json.dumps([1,json.dumps({'initialServer':record})])+')</script>', SID)

    def test_only_explicit_selections_change_and_order_is_preserved(self):
        service=ArmaHQCompare()
        result=service.compare_json(json.dumps({'game':{'mods':REMOTE}}), LOCAL, 1)
        self.assertEqual([m['modId'] for m in result['missing']], ['DDDD'])
        self.assertEqual([m['modId'] for m in result['extra']], ['BBBB'])
        self.assertEqual(len(result['versions']),2)
        changed, counts=service.apply(result['token'], {'missing':['DDDD'], 'versions':['AAAA']}, LOCAL, 1)
        self.assertEqual([m['modId'] for m in changed], ['AAAA','BBBB','CCCC','DDDD'])
        self.assertEqual(changed[0]['version'],'2')
        self.assertNotIn('version',changed[2])
        self.assertEqual(LOCAL[0]['version'],'1')
        self.assertEqual(counts,{'missing':1,'extra':0,'versions':1})
        removed,_=service.apply(result['token'], {'extra':['BBBB']}, LOCAL, 1)
        self.assertEqual([m['modId'] for m in removed],['AAAA','CCCC'])

    def test_stale_expired_cross_account_and_forged_selections_rejected(self):
        service=ArmaHQCompare();result=service.compare_json(REMOTE,LOCAL,1)
        with self.assertRaises(StaleComparison):service.apply(result['token'],{'extra':['BBBB']},LOCAL,2)
        changed=copy.deepcopy(LOCAL);changed[0]['version']='7'
        with self.assertRaises(StaleComparison):service.apply(result['token'],{'extra':['BBBB']},changed,1)
        with self.assertRaises(StaleComparison):service.apply(result['token'],{'missing':['EEEE']},LOCAL,1)
        with self.assertRaises(ValueError):service.apply(result['token'],{},LOCAL,1)
        service.snapshots[result['token']]['at']-=901
        with self.assertRaises(StaleComparison):service.apply(result['token'],{'extra':['BBBB']},LOCAL,1)

    def test_rejects_untrusted_urls_bad_json_and_duplicate_ids(self):
        for url in ['http://www.armahq.com/servers/'+SID,'https://evil.example/servers/'+SID,
                    'https://www.armahq.com@127.0.0.1/servers/'+SID,'https://www.armahq.com:443/servers/'+SID]:
            with self.assertRaises(ValueError):server_id(url)
        self.assertEqual(server_id('https://armahq.com/servers/'+SID+'?foo=1'),SID)
        service=ArmaHQCompare()
        for payload in ['not json',{'game':{}},[{'modId':'AAAA'},{'modId':'aaaa'}],[{'modId':'not hex'}]]:
            with self.assertRaises(ValueError):service.compare_json(payload,LOCAL,1)
        self.assertEqual(service.compare_json({'mods':[]},LOCAL,1)['remoteCount'],0)

    def test_search_filters_name_or_address_and_limits_results(self):
        service=ArmaHQCompare()
        records=[{'id':SID,'name':'Group Main','hostAddress':'203.0.113.1:2001'}]*35
        with patch.object(service,'_fetch',return_value=json.dumps({'servers':records})):
            result=service.search('group');self.assertEqual(result['total'],35);self.assertEqual(len(result['servers']),30)
            self.assertEqual(service.search('203.0.113.1')['total'],35)


if __name__=='__main__':unittest.main()
