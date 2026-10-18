import copy
import unittest
from unittest.mock import Mock
from workshop import Workshop, normalize_asset
from test_panel import PanelTests

ASSET=dict(modId='AAAA', name='Test Mod', version='2', versions=[{'version':'1'},{'version':'2'}], dependencies=[dict(asset=dict(id='BBBB',name='Core'),version='3',published=True,dependencies=[])])

class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.workshop=Workshop();self.workshop.detail=Mock(return_value=copy.deepcopy(ASSET))
    def test_dependency_preview_and_scope_and_stale_guard(self):
        plan=self.workshop.preview([], (1,'a'),'AAAA','add',dependencies=True)
        self.assertEqual([m['modId'] for m in plan['mods']],['AAAA','BBBB'])
        self.assertTrue(all('version' not in m for m in plan['mods']))
        self.assertEqual(self.workshop.apply(plan['token'],(1,'a'),[]),plan['mods'])
        for identity,mods in [((2,'a'),[]),((1,'b'),[]),((1,'a'),[{'modId':'CCCC'}])]:
            with self.assertRaises(ValueError):self.workshop.apply(plan['token'],identity,mods)
    def test_existing_explicit_dependency_pin_is_preserved(self):
        current=[dict(modId='BBBB',name='Core',version='3')]
        plan=self.workshop.preview(current,1,'AAAA','add',dependencies=True)
        self.assertEqual(plan['mods'][0],current[0])
        self.assertNotIn('version',plan['mods'][1])
    def test_old_release_does_not_guess_dependencies(self):
        with self.assertRaises(ValueError):self.workshop.preview([],1,'AAAA','add','1',True)
        self.assertEqual(self.workshop.preview([],1,'AAAA','add','1')['mods'][0]['version'],'1')
    def test_dependency_pin_conflict_and_conservative_removal(self):
        current=[dict(modId='BBBB',version='9'),dict(modId='AAAA')]
        with self.assertRaises(ValueError):self.workshop.preview(current,1,'AAAA','add',dependencies=True)
        plan=self.workshop.preview(current,1,'AAAA','remove')
        self.assertEqual(plan['mods'],current[:1]);self.assertTrue(plan['notes'])
    def test_scenarios_are_verified_and_require_configuration_permission(self):
        self.workshop.detail.return_value['scenarios']=[dict(id='{04E4EE1532324317}Missions/GM_CampNeptune.conf')]
        scenario=self.workshop.detail.return_value['scenarios'][0]['id']
        plan=self.workshop.preview([],1,'AAAA','add',scenario=scenario,current_scenario='old')
        self.assertEqual(len(plan['mods']),2)
        with self.assertRaises(ValueError):self.workshop.apply(plan['token'],1,[], 'old')
        with self.assertRaises(ValueError):self.workshop.apply(plan['token'],1,[], 'changed',True)
        mods,selected=self.workshop.apply(plan['token'],1,[],'old',True,True)
        self.assertEqual(selected,scenario)
        with self.assertRaises(ValueError):self.workshop.preview([],1,'AAAA','add',scenario='invented')
        with self.assertRaises(ValueError):self.workshop.preview([dict(modId='AAAA',version='1')],1,'AAAA','add',scenario=scenario)
    def test_scenarios_only_exposed_for_terrains(self):
        client=Workshop()
        resource='{04E4EE1532324317}Missions/GM_CampNeptune.conf'
        asset=dict(id='AAAA',tags=[dict(name='TERRAINS')])
        client.fetch=Mock(return_value=dict(asset=asset,assetVersionDetail=dict(scenarios=[dict(name='Terrain mission',gameId=resource),dict(gameId='invalid') ])))
        self.assertEqual(client.detail('AAAA')['scenarios'][0]['id'],resource)
        asset['tags']=[dict(name='VEHICLES')]
        self.assertEqual(client.detail('AAAA')['scenarios'],[])
    def test_invalid_filters_never_fetch(self):
        self.workshop.fetch=Mock()
        for values in [('x','evil','',1),('x','newest','EVIL',1),('x','newest','',0),('x'*121,'newest','',1)]:
            with self.assertRaises(ValueError):self.workshop.catalog(*values)
        self.workshop.fetch.assert_not_called()
    def test_untrusted_thumbnail_and_unpublished_releases_filtered(self):
        result=normalize_asset(dict(id='AAAA',previews=[dict(url='https://evil.example/image/a')],versions=[dict(version='secret',published=False,approved=True)]))
        self.assertIsNone(result['thumbnail']);self.assertEqual(result['versions'],[])

class WorkshopAPITests(unittest.TestCase):
    setUp=PanelTests.setUp
    login=PanelTests.login
    post=PanelTests.post
    create=PanelTests.create
    def test_use_scenario_saves_mods_and_mission_atomically(self):
        asset=copy.deepcopy(ASSET)
        scenario='{04E4EE1532324317}Missions/GM_CampNeptune.conf'
        asset['scenarios']=[dict(id=scenario)]
        self.module.workshop.detail=Mock(return_value=asset)
        plan=self.admin.get('/api/mods/workshop/AAAA/preview',query_string={'scenario':scenario}).json
        self.assertTrue(plan['ok'],plan)
        saved=self.post(self.admin,'/api/mods/workshop/apply',{'token':plan['token']})
        self.assertTrue(saved.json['ok'],saved.json)
        cfg=self.module.read_config()
        self.assertEqual(cfg['game']['scenarioId'],scenario)
        self.assertEqual(len(cfg['game']['mods']),2)
        self.assertTrue(all('version' not in mod for mod in cfg['game']['mods']))
        self.assertTrue(self.admin.get('/api/config/backups').json['backups'])

    def test_workshop_permissions_csrf_and_save_backup(self):
        self.module.workshop.detail=Mock(return_value=copy.deepcopy(ASSET))
        self.create('workshop-viewer','viewer');viewer=self.login('workshop-viewer')
        self.assertEqual(viewer.get('/api/mods/workshop/AAAA/preview').status_code,403)
        plan=self.admin.get('/api/mods/workshop/AAAA/preview?dependencies=1').json
        self.assertTrue(plan['ok'],plan)
        self.assertEqual(self.admin.post('/api/mods/workshop/apply',json={'token':plan['token']}).status_code,403)
        self.assertEqual(self.post(viewer,'/api/mods/workshop/apply',{'token':plan['token']}).status_code,403)
        result=self.post(self.admin,'/api/mods/workshop/apply',{'token':plan['token']})
        self.assertTrue(result.json['ok'],result.json)
        self.assertEqual(len(result.json['mods']),2)
        self.assertTrue(self.admin.get('/api/config/backups').json['backups'])
