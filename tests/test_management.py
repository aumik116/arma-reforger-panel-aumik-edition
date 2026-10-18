import os
import time
import tempfile
import sqlite3
import unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from scheduler import ScheduleStore,calendar_next,schedule_values
from storage_usage import scan_storage
from instance_control import normalize_limits,limit_args
import test_panel

class ManagementTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(time,'tzset'),'DST server-clock test requires Linux tzset')
    def test_server_clock_dst_gap_and_repeated_time(self):
        previous=os.environ.get('TZ')
        try:
            os.environ['TZ']='America/New_York';time.tzset()
            row=dict(recurrence='daily',local_time='02:30',weekday=0)
            result=calendar_next(row,datetime(2026,3,7,3).timestamp())
            self.assertEqual(datetime.fromtimestamp(result).isoformat(),'2026-03-09T02:30:00')
            row.update(recurrence='weekly',local_time='01:30',weekday=6)
            first=calendar_next(row,datetime(2026,11,1,0).timestamp())
            self.assertEqual(datetime.fromtimestamp(first).fold,0)
            after=calendar_next(row,first+600)
            self.assertEqual(datetime.fromtimestamp(after).date().isoformat(),'2026-11-08')
        finally:
            if previous is None:os.environ.pop('TZ',None)
            else:os.environ['TZ']=previous
            time.tzset()

    def test_server_local_input_calendar_claim_edit_history_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ScheduleStore(Path(folder)/'db')
            now=datetime(2026,10,18,12).timestamp();run_at=now+86400
            identity=store.create('a',1,dict(name='Original',action='backup',local_run_at='2026-10-19T12:00',recurrence='daily'),now=now)
            row=store.pending(run_at)[0];run=store.claim(row,run_at)
            store.finish(run['run_id'],'failed','Test failure')
            job=store.list('a')[0][0];self.assertTrue(job['enabled']);self.assertEqual(datetime.fromtimestamp(job['run_at']).hour,12)
            store.update('a',identity,2,dict(name='Edited',action='restart',run_at=run_at+900,recurrence='weekly'),now=run_at)
            history=store.runs('a',state='failed',search='Original')
            self.assertEqual(history[0]['name'],'Original');self.assertEqual(history[0]['action'],'backup')
            store.change('a',identity,enabled=False,now=run_at)
            store.change('a',identity,enabled=True,now=run_at+10*86400)
            self.assertGreater(store.list('a')[0][0]['run_at'],run_at+10*86400)
            self.assertEqual(store.runs('other'),[])
            with self.assertRaises(ValueError):schedule_values(dict(name='Invalid',action='backup',local_run_at='bad'),now)

    def test_existing_interval_schedules_and_history_migrate(self):
        with tempfile.TemporaryDirectory() as folder:
            database=Path(folder)/'old.sqlite'
            with sqlite3.connect(database) as conn:
                conn.executescript("CREATE TABLE schedules(id INTEGER PRIMARY KEY,server_id TEXT,owner_id INTEGER,name TEXT,action TEXT,run_at REAL,interval_seconds INTEGER,enabled INTEGER DEFAULT 1,deleted INTEGER DEFAULT 0,warning5 INTEGER DEFAULT 0,warning1 INTEGER DEFAULT 0,warning_error TEXT DEFAULT ''); CREATE TABLE schedule_runs(id INTEGER PRIMARY KEY,schedule_id INTEGER,server_id TEXT,scheduled_for REAL,started REAL,finished REAL,state TEXT,message TEXT);")
                conn.execute("INSERT INTO schedules(id,server_id,owner_id,name,action,run_at,interval_seconds) VALUES(1,'a',1,'Original','backup',2000,86400)")
                conn.execute("INSERT INTO schedule_runs VALUES(1,1,'a',1000,1000,1001,'success','Saved')")
            conn.close()
            store=ScheduleStore(database)
            self.assertEqual(store.list('a')[0][0]['recurrence'],'interval')
            store.update('a',1,1,dict(name='Renamed',action='restart',run_at=3000),now=2000)
            self.assertEqual(store.runs('a')[0]['name'],'Original')
            self.assertEqual(store.runs('a')[0]['action'],'backup')

    def test_limits_are_bounded_and_helper_commands_are_fixed(self):
        with patch('instance_control.os.cpu_count',return_value=8):
            self.assertEqual(normalize_limits('0-2,4',1024,2048)['cpus'],'0-2,4')
            args=limit_args('training','0-2,4','1024','2048')
            self.assertEqual(args[:4],['/usr/bin/systemctl','set-property','--runtime','arma-server@training.service'])
            self.assertIn('MemoryHigh=1024000000',args);self.assertIn('MemoryMax=2048000000',args)
            for cpu,high,maximum in [('0;id',0,0),('8',0,0),('3-1',0,0),('',1024,512),('',-1,0),('',True,0)]:
                with self.assertRaises(ValueError):normalize_limits(cpu,high,maximum)
            with self.assertRaises(ValueError):limit_args('../escape','','0','0')
            self.assertIn('MemoryMax=infinity',limit_args('__existing__','','0','0'))

    def test_storage_separates_trash_and_counts_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'profile';profile.mkdir();trash=profile/'.panel-trash';trash.mkdir()
            (profile/'settings.json').write_bytes(b'abc');(trash/'deleted').write_bytes(b'12345')
            os.link(profile/'settings.json',profile/'hardlink')
            result=scan_storage([('profile','Profile',profile),('trash','Trash',trash)])
            self.assertEqual([row['bytes'] for row in result['categories']],[3,5]);self.assertEqual(result['total_bytes'],8)
            self.assertEqual(scan_storage([('profile','Profile',profile)],max_entries=0)['status'],'partial')

class ManagementAPITests(unittest.TestCase):
    setUp=test_panel.PanelTests.setUp
    login=test_panel.PanelTests.login
    post=test_panel.PanelTests.post
    create=test_panel.PanelTests.create
    def test_startup_limits_and_history_permissions(self):
        saved=self.post(self.admin,'/api/startup',dict(max_fps=70,cpus='0',memory_high_mb=512,memory_max_mb=0))
        self.assertTrue(saved.json['ok'],saved.json)
        self.assertEqual(self.admin.get('/api/startup').json['resources']['memory_high_mb'],512)
        rejected=self.post(self.admin,'/api/startup',dict(max_fps=90,cpus='-1',memory_high_mb=512,memory_max_mb=0))
        self.assertEqual(rejected.status_code,400);self.assertEqual(self.admin.get('/api/startup').json['max_fps'],70)
        self.create('management-staff','manager');client=self.login('management-staff')
        self.assertEqual(client.get('/api/schedules/runs').status_code,403)
        self.assertEqual(self.post(client,'/api/startup',dict(max_fps=10)).status_code,403)

    def test_linux_launcher_passes_saved_limits_to_restricted_helper(self):
        import io
        import builtins
        import runtime_ops
        self.module.server_registry.set_resources('__existing__',dict(cpus='0',memory_high_mb=512,memory_max_mb=0))
        original_open=builtins.open;original_isfile=os.path.isfile
        helper='/etc/arma-panel/instance-control.py'
        def opened(path,*args,**kwargs):
            return io.BytesIO(b'def limit_args(') if str(path)==helper else original_open(path,*args,**kwargs)
        def isfile(path):return True if str(path)==helper else original_isfile(path)
        with patch('runtime_ops.sys.platform','linux'),patch('builtins.open',side_effect=opened),patch('runtime_ops.os.path.isfile',side_effect=isfile),patch('runtime_ops.subprocess.run') as command,patch('runtime_ops.os.chdir'),patch('runtime_ops.os.execv') as execute,patch('persistence_saves.prepare_startup_save',return_value=None):
            runtime_ops.launch_server(str(self.root/'config.env'))
        self.assertEqual(command.call_args.args[0],['sudo','-n',helper,'limits','__existing__','0','512','0'])
        execute.assert_called_once()
