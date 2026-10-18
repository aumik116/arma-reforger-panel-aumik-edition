import concurrent.futures
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from config_editor import revision
from scheduler import ScheduleStore
import test_instances
import test_panel


class ScheduleStoreTests(unittest.TestCase):
    def test_atomic_claim_recurrence_recovery_and_server_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ScheduleStore(Path(directory)/'panel.sqlite3')
            store.create('first',1,dict(name='Backup',action='backup',run_at=2000,interval_seconds=3600),now=1000)
            row=store.pending(2000)[0]
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:store.claim(row,10000),range(2)))
            self.assertEqual(sum(result is not None for result in results),1)
            schedules,runs=store.list('first')
            self.assertEqual(schedules[0]['run_at'],12800)
            self.assertEqual(len(runs),1)
            self.assertEqual(store.list('second'),([],[]))
            self.assertFalse(store.heartbeat())
            self.assertTrue(store.heartbeat(write=True))
            store.recover()
            self.assertEqual(store.list('first')[1][0]['state'],'interrupted')
            with self.assertRaises(ValueError):store.change('second',row['id'],False,now=10000)
            store.change('first',row['id'],remove=True)
            self.assertFalse(store.pending(20000))

    def test_validation_and_history_survive_reopening_and_failed_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'panel.sqlite3';store=ScheduleStore(path)
            for data in [dict(name='bad',action='shell',run_at=2000),dict(name='bad',action='restart',run_at=1200),dict(name='bad',action='backup',run_at=2000,interval_seconds=1)]:
                with self.assertRaises(ValueError):store.create('',1,data,now=1000)
            store.observe('first',dict(available=True,checked_at=100,players=[dict(name='One',identity='uuid')]))
            store.observe('first',dict(available=True,checked_at=200,players=[dict(name='Renamed',identity='uuid')]))
            store.observe('first',dict(available=False,players=[]))
            store=ScheduleStore(path)
            history=store.history('first','Renamed',0)
            self.assertEqual((history[0]['first_seen'],history[0]['last_seen']),(100,200))
            self.assertEqual(store.history('second','',0),[])


class OperatorToolsTests(unittest.TestCase):
    setUp=test_panel.PanelTests.setUp
    login=test_panel.PanelTests.login
    create=test_panel.PanelTests.create
    post=test_panel.PanelTests.post
    instance=test_instances.InstanceTests.instance

    def submit(self,path,data,server=''):
        headers={'X-CSRF-Token':self.admin.get('/api/csrf').json['csrf']}
        if server:headers['X-Server-ID']=server
        return self.admin.post(path,json=data,headers=headers)

    def schedule(self,action='restart',server=''):
        tools=self.module.operator_tools;due=time.time()+600
        tools.store.create(server,1,dict(name='Night task',action=action,run_at=due))
        return tools,due

    def test_permissions_csrf_and_startup_isolation(self):
        first=self.instance('first');self.instance('second')
        self.assertEqual(self.admin.post('/api/startup',json={'max_fps':45}).status_code,403)
        self.assertTrue(self.submit('/api/startup',{'max_fps':45},'first').json['ok'])
        self.assertEqual(self.module.server_registry.get(first.id).max_fps,45)
        self.assertEqual(self.module.server_registry.get('second').max_fps,60)
        self.assertTrue(self.submit('/api/startup',{'max_fps':35}).json['ok'])
        self.assertEqual(self.module.server_registry.existing_max_fps(),35)
        from runtime_ops import launch_server
        with patch('runtime_ops.os.chdir'),patch('runtime_ops.os.execv') as execute:
            launch_server(str(self.root/'config.env'))
            self.assertIn('-maxFPS=35',execute.call_args.args[1])
        self.create('operator','operator');client=self.login('operator')
        for path in ('/api/startup','/api/schedules','/api/players/admins'):
            self.assertEqual(client.get(path).status_code,403)
        self.assertEqual(client.get('/api/players/history').status_code,200)
        csrf=client.get('/api/csrf').json['csrf']
        self.assertEqual(client.post('/api/schedules',json={},headers={'X-CSRF-Token':csrf}).status_code,403)

    def test_history_and_admin_changes_target_selected_server_and_reject_stale_config(self):
        identity='00000000-0000-0000-0000-000000000001'
        first=self.instance('first');second=self.instance('second')
        self.module.operator_tools.store.observe('first',dict(available=True,players=[dict(name='Player One',identity=identity)]))
        self.assertEqual(len(self.admin.get('/api/players/history',headers={'X-Server-ID':'first'}).json['players']),1)
        self.assertEqual(self.admin.get('/api/players/history',headers={'X-Server-ID':'second'}).json['players'],[])
        version=revision(json.loads(first.paths['config'].read_text()))
        self.assertTrue(self.submit('/api/players/admin',dict(identity=identity,grant=True,revision=version),'first').json['ok'])
        self.assertEqual(json.loads(first.paths['config'].read_text())['game']['admins'],[identity])
        self.assertNotIn('admins',json.loads(second.paths['config'].read_text())['game'])
        self.assertEqual(self.submit('/api/players/admin',dict(identity=identity,grant=False,revision=version),'first').status_code,409)

    def test_restart_warnings_delivered_once_and_before_execution(self):
        tools,due=self.schedule();self.module.get_server_pid=lambda:4242
        with patch.object(tools,'broadcast') as broadcast,patch.object(self.module,'stop_server') as stop,patch.object(self.module,'start_server') as start,patch.object(self.module,'software_manager',SimpleNamespace(busy=lambda:False)):
            tools.tick(due-300);tools.tick(due-290);tools.tick(due-60)
            self.assertEqual(broadcast.call_count,2)
            tools.tick(due,dispatch=tools.execute);tools.tick(due+1,dispatch=tools.execute)
            stop.assert_called_once();start.assert_called_once()
        self.assertEqual(tools.store.list('')[1][0]['state'],'success')

    def test_failed_warnings_and_missed_runs_do_not_stop_server(self):
        tools,due=self.schedule();self.module.get_server_pid=lambda:4242
        with patch.object(tools,'broadcast',side_effect=ValueError('RCON unavailable')),patch.object(self.module,'stop_server') as stop,patch.object(self.module,'software_manager',SimpleNamespace(busy=lambda:False)):
            tools.tick(due-300);tools.tick(due-60);tools.tick(due,dispatch=tools.execute)
            stop.assert_not_called()
        self.assertIn('warnings',tools.store.list('')[1][0]['message'])
        tools,due=self.schedule(action='backup')
        with patch('operator_tools.time.time',return_value=due+200),patch('operator_tools.config_backups.backup_current') as backup:
            tools.tick(due+200,dispatch=tools.execute);backup.assert_not_called()

    def test_update_restores_previous_running_state_only_after_success(self):
        for running,success in ((True,True),(False,True),(True,False)):
            with self.subTest(running=running,success=success):
                tools,due=self.schedule(action='update');self.module.get_server_pid=lambda:4242 if running else None
                manager=SimpleNamespace(busy=lambda:False,launch=Mock(),status=lambda:dict(state='success' if success else 'failed',message='Steam failed'))
                with patch.object(tools,'broadcast'),patch.object(self.module,'software_manager',manager),patch.object(self.module,'stop_server') as stop,patch.object(self.module,'start_server') as start:
                    tools.tick(due-300);tools.tick(due-60);tools.tick(due,dispatch=tools.execute)
                    self.assertEqual(stop.call_count,int(running));self.assertEqual(start.call_count,int(running and success))
                    self.assertEqual(manager.launch.call_count,1)

    def test_deleted_server_disables_schedules_and_removed_owner_cannot_execute(self):
        self.instance('first');tools,due=self.schedule('backup','first')
        self.module.server_registry.remove('first')
        self.assertEqual(tools.store.pending(due),[])
        tools,due=self.schedule('backup')
        with tools.store.connect() as conn:conn.execute("UPDATE users SET role='viewer' WHERE id=1")
        with patch('operator_tools.config_backups.backup_current') as backup:
            tools.tick(due,dispatch=tools.execute);backup.assert_not_called()
        self.assertIn('administrator access',tools.store.list('')[1][0]['message'])

    def test_scheduled_backup_uses_selected_server_and_api_enforces_scope(self):
        import config_backups
        first=self.instance('first');second=self.instance('second')
        due=time.time()+600
        with patch('operator_tools.sys.platform','linux'):
            result=self.submit('/api/schedules',dict(name='Config backup',action='backup',run_at=due),'first')
        self.assertTrue(result.json['ok'],result.json)
        schedule_id=result.json['id']
        self.assertEqual(self.submit(f'/api/schedules/{schedule_id}',{'enabled':False},'second').status_code,400)
        self.module.operator_tools.tick(due,dispatch=self.module.operator_tools.execute)
        self.assertEqual(len(config_backups.list_backups(first.paths['config'])),1)
        self.assertEqual(config_backups.list_backups(second.paths['config']),[])
        self.assertEqual(config_backups.list_backups(self.config),[])
