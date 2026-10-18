import json
import unittest
from unittest.mock import patch
import test_panel
import test_instances
import server_provisioning as provision


class ServerAccessTests(unittest.TestCase):
    setUp = test_panel.PanelTests.setUp
    login = test_panel.PanelTests.login
    post = test_panel.PanelTests.post
    instance = test_instances.InstanceTests.instance

    def setUp(self):
        test_panel.PanelTests.setUp(self)
        self.first = self.instance('first')
        self.second = self.instance('second')
        result = self.post(self.admin,'/api/users',{'username':'staff','password':'test-password','role':'viewer'})
        self.assertEqual(result.status_code,200,result.json)
        self.staff_id = next(user['id'] for user in self.admin.get('/api/users').json['users'] if user['username']=='staff')
        self.staff = self.login('staff')

    def grant(self, roles):
        result = self.post(self.admin,'/api/users',{'id':self.staff_id,'username':'staff','role':'viewer','access_all':False,'server_roles':roles})
        self.assertEqual(result.status_code,200,result.json)
        self.staff = self.login('staff')

    def test_default_deny_and_per_server_roles_enforced_by_api(self):
        self.assertEqual(self.staff.get('/api/servers').json['servers'],[])
        for route in ('/api/status','/api/metrics','/api/players','/api/files','/api/servers/first/provision'):
            self.assertEqual(self.staff.get(route,headers={'X-Server-ID':'first'}).status_code,403,route)
        self.grant({'first':'viewer','second':'manager'})
        self.assertEqual({server['id'] for server in self.staff.get('/api/servers').json['servers']},{'first','second'})
        self.assertIsNone(self.staff.get('/api/servers').json['legacy_server'])
        self.assertEqual(self.staff.get('/api/status',headers={'X-Server-ID':'first'}).status_code,200)
        csrf = self.staff.get('/api/csrf').json['csrf']
        self.assertEqual(self.staff.post('/api/config',json={'server_name':'Denied'},headers={'X-Server-ID':'first','X-CSRF-Token':csrf}).status_code,403)
        response = self.staff.post('/api/config',json={'server_name':'Allowed'},headers={'X-Server-ID':'second','X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(json.loads(self.first.paths['config'].read_text())['game']['name'],'first')
        self.assertEqual(json.loads(self.second.paths['config'].read_text())['game']['name'],'Allowed')
        self.grant({'first':'admin'})
        self.assertEqual(self.staff.get('/api/users',headers={'X-Server-ID':'first'}).status_code,403)
        self.assertEqual(self.staff.get('/api/status',headers={'X-Server-ID':'second'}).status_code,403)

    def test_permissions_metadata_and_legacy_assignment(self):
        self.grant({'first':'operator','__existing__':'viewer'})
        rows = self.staff.get('/api/servers').json
        self.assertIsNotNone(rows['legacy_server'])
        self.assertIn('control',rows['servers'][0]['permissions'])
        self.assertNotIn('control',rows['legacy_server']['permissions'])
        self.assertEqual(self.staff.get('/api/status').status_code,200)
        self.assertIn('view',self.staff.get('/api/me').json['permissions'])
        self.assertIn('control',self.staff.get('/api/me',headers={'X-Server-ID':'first'}).json['permissions'])

    def test_invalid_assignments_and_owner_restriction_are_atomic(self):
        for roles in ({'missing':'admin'},{'first':'owner'}):
            result = self.post(self.admin,'/api/users',{'id':self.staff_id,'username':'staff','role':'viewer','server_roles':roles})
            self.assertEqual(result.status_code,400,result.json)
        self.assertEqual(self.post(self.admin,'/api/users',{'id':1,'username':'admin','role':'admin','access_all':False}).status_code,400)
        self.assertEqual(self.staff.get('/api/servers').json['servers'],[])
        self.assertEqual(len(self.admin.get('/api/servers').json['servers']),2)

    def test_revocation_is_immediate_and_scheduled_jobs_recheck_access(self):
        self.grant({'first':'admin'})
        store = self.module.operator_tools.store
        row = {'owner_id':self.staff_id,'server_id':'first'}
        self.assertEqual(self.module.operator_tools.authorized(row),'staff')
        self.post(self.admin,'/api/users',{'id':self.staff_id,'username':'staff','role':'viewer','server_roles':{}})
        self.assertEqual(self.staff.get('/api/status',headers={'X-Server-ID':'first'}).status_code,401)
        self.staff = self.login('staff')
        self.assertEqual(self.staff.get('/api/status',headers={'X-Server-ID':'first'}).status_code,403)
        with self.assertRaises(ValueError): self.module.operator_tools.authorized(row)

    def test_unassigned_files_copy_sources_and_audit_are_not_exposed(self):
        self.grant({'first':'manager'})
        self.assertEqual(self.staff.get('/api/files/download?_server=second&root=profile&path=secret.json').status_code,403)
        self.module.audit_event('other','config_editor_save','success',{'server_id':'second'})
        self.module.audit_event('other','config_editor_save','success',{'server_id':'first'})
        events = self.staff.get('/api/activity',headers={'X-Server-ID':'first'}).json['events']
        self.assertFalse(any(event['details'].get('server_id')=='second' for event in events))
        self.assertTrue(any(event['details'].get('server_id')=='first' for event in events))
        self.post(self.admin,'/api/users',{'id':self.staff_id,'username':'staff','role':'admin'})
        self.staff=self.login('staff')
        with patch.object(provision.sys,'platform','linux'), patch.object(provision.Path,'is_file',return_value=True), patch.object(self.module.software_manager._get_current_object(),'executable',return_value='/steamcmd'):
            response=self.post(self.staff,'/api/servers',{'server_id':'copy','name':'Copy','copy_from':'second'})
        self.assertEqual(response.status_code,403,response.json)
