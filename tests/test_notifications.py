import json
import unittest
from unittest.mock import Mock,patch
import test_panel
import test_instances
from notifications import validate_webhook

URL='https://discord.com/api/webhooks/123456789012345678/'+'a'*60

class NotificationTests(unittest.TestCase):
    setUp=test_panel.PanelTests.setUp
    login=test_panel.PanelTests.login
    post=test_panel.PanelTests.post
    create=test_panel.PanelTests.create
    instance=test_instances.InstanceTests.instance

    def settings(self,**changes):
        data=dict(webhook=URL,routine=True,role='',clear_webhook=False);data.update(changes)
        return self.post(self.admin,'/api/notifications/settings',data)

    def test_webhook_validation_and_secret_redaction(self):
        for url in ['http://discord.com/api/webhooks/123/token','https://evil.example/api/webhooks/123/token',URL+'?x=1',URL+'#fragment','https://discord.com.evil.example/api/webhooks/123/token']:
            with self.assertRaises(ValueError):validate_webhook(url)
        self.assertTrue(self.settings().json['ok'])
        response=self.admin.get('/api/notifications/settings')
        self.assertTrue(response.json['configured']);self.assertNotIn(URL,response.get_data(as_text=True))
        self.assertTrue(self.settings(webhook='').json['ok'])
        self.assertEqual(self.module.notifications.settings('')['webhook'],URL)
        self.assertTrue(self.settings(webhook='',clear_webhook=True).json['ok'])
        self.assertFalse(self.admin.get('/api/notifications/settings').json['configured'])
        self.assertNotIn(URL,self.admin.get('/api/activity').get_data(as_text=True))

    def test_observer_baseline_crash_dedup_and_update_result(self):
        service=self.module.notifications
        service.observe('',123,dict(state='idle'))
        self.assertEqual(self.admin.get('/api/notifications').json['events'],[])
        service.observe('',0,dict(state='idle'))
        service.observe('',0,dict(state='idle'))
        service.emit('','unexpected_stop','another')
        events=self.admin.get('/api/notifications').json['events'];self.assertEqual(len(events),1)
        service.observe('',0,dict(started=1,action='update',state='failed'))
        service.observe('',0,dict(started=1,action='update',state='failed'))
        self.assertEqual(len(self.admin.get('/api/notifications').json['events']),2)
        service.observe('',456,dict(state='idle'))
        service.observe('',789,dict(state='idle'))
        self.assertEqual(self.admin.get('/api/notifications').json['events'][0]['kind'],'unexpected_restart')

    def test_delivery_role_whitelist_and_secret_safe_failure(self):
        role='123456789012345678'
        self.assertTrue(self.settings(role=role).json['ok'])
        service=self.module.notifications
        service.emit('','start_failed','failure-1')
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False);response.status=200
        opener=Mock();opener.open.return_value=response
        with patch('notifications.build_opener',return_value=opener):service.deliver()
        payload=json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(payload['allowed_mentions'],dict(parse=[],roles=[role]))
        self.assertIn('<@&'+role+'>',payload['content'])
        self.assertEqual(self.admin.get('/api/notifications').json['events'][0]['delivery'],'sent')
        service.emit('','test','failure-2')
        with patch('notifications.build_opener',side_effect=ValueError(URL)):
            service.deliver()
        text=self.admin.get('/api/notifications').get_data(as_text=True)
        self.assertNotIn(URL,text)
        self.assertEqual(self.admin.get('/api/notifications').json['events'][0]['delivery'],'pending')

    def test_permissions_server_scope_and_corrupt_config(self):
        first=self.instance('notify-first');second=self.instance('notify-second')
        self.create('notify-manager','manager');manager=self.login('notify-manager')
        self.assertEqual(manager.get('/api/notifications/settings').status_code,403)
        self.assertEqual(self.post(manager,'/api/notifications/settings',dict(routine=True)).status_code,403)
        self.assertEqual(self.admin.post('/api/notifications/settings',json=dict(routine=True)).status_code,403)
        self.module.notifications.emit(first.id,'test','first')
        self.assertEqual(len(self.admin.get('/api/notifications',headers={'X-Server-ID':first.id}).json['events']),1)
        self.assertEqual(self.admin.get('/api/notifications',headers={'X-Server-ID':second.id}).json['events'],[])
        self.config.write_text('broken config')
        self.assertTrue(self.settings().json['ok'])

    def test_settings_change_cancels_queue_and_routine_preference(self):
        self.settings(routine=False)
        service=self.module.notifications
        service.emit('','started','a');service.emit('','start_failed','b')
        events=self.admin.get('/api/notifications').json['events']
        self.assertEqual([row['delivery'] for row in events],['pending','local'])
        self.settings()
        self.assertEqual(self.admin.get('/api/notifications').json['events'][0]['delivery'],'cancelled')

    def test_same_event_source_is_idempotent(self):
        service=self.module.notifications
        service.baseline('',0)
        service.emit('','started','same');service.emit('','started','same')
        self.assertEqual(len(self.admin.get('/api/notifications').json['events']),1)

    def test_control_wrappers_suppress_intentional_stop_and_survive_storage_error(self):
        from types import SimpleNamespace
        from flask import Flask
        from notifications import install
        fake=SimpleNamespace(app=Flask('control-notifications'),server_registry=self.module.server_registry,
            selected_instance=lambda:None,start_server=Mock(return_value='started'),stop_server=Mock(return_value='stopped'),
            get_server_pid=Mock(return_value=123),clear_server_access=Mock())
        install(fake)
        self.assertEqual(fake.start_server(),'started')
        fake.get_server_pid.return_value=0
        self.assertEqual(fake.stop_server(),'stopped')
        fake.notifications.observe('',0,dict(state='idle'))
        kinds=[row['kind'] for row in self.admin.get('/api/notifications').json['events']]
        self.assertNotIn('unexpected_stop',kinds)
        with patch.object(fake.notifications,'emit',side_effect=RuntimeError('storage unavailable')):
            self.assertEqual(fake.start_server(),'started')

    def test_initial_install_failure_is_observed_once(self):
        from types import SimpleNamespace
        service=self.module.notifications
        server=self.instance('notification-install')
        pending=SimpleNamespace(id=server.id,state='provisioning',directory=server.directory)
        failed=SimpleNamespace(id=server.id,state='failed',directory=server.directory)
        with patch.object(self.module.server_registry,'list',return_value=[pending]),patch.object(service,'deliver'):
            service.tick()
        with patch.object(self.module.server_registry,'list',return_value=[failed]),patch.object(service,'deliver'):
            service.tick();service.tick()
        rows=self.admin.get('/api/notifications',headers={'X-Server-ID':server.id}).json['events']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['kind'],'provision_failed')
