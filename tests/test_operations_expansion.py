import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import test_panel
import test_instances
import startup_settings
from moderation import parse_bans

UUID='00000000-0000-0000-0000-000000000001'
OTHER='00000000-0000-0000-0000-000000000002'


class OperationsExpansionTests(unittest.TestCase):
    setUp=test_panel.PanelTests.setUp
    login=test_panel.PanelTests.login
    create=test_panel.PanelTests.create
    instance=test_instances.InstanceTests.instance

    def post(self, client, path, data=None, server=''):
        headers={'X-CSRF-Token':client.get('/api/csrf').json['csrf']}
        if server: headers['X-Server-ID']=server
        return client.post(path,json=data or {},headers=headers)

    def configure_rcon(self, path=None):
        path=path or self.config
        config=json.loads(path.read_text())
        config['rcon']=dict(address='127.0.0.1',port=19999,password='secret',permission='admin')
        path.write_text(json.dumps(config))
        self.module.get_server_pid=lambda:123

    def test_moderation_auth_csrf_validation_and_stale_slot_protection(self):
        self.configure_rcon()
        self.create('operator','operator');operator=self.login('operator')
        self.assertEqual(operator.get('/api/players/bans').status_code,403)
        self.assertEqual(self.post(operator,'/api/players/moderate',dict(action='ban',identity=UUID)).status_code,403)
        self.assertEqual(self.admin.post('/api/players/moderate',json=dict(action='ban',identity=UUID)).status_code,403)
        with patch('player_query.query_command',return_value='Player banned') as query:
            result=self.post(self.admin,'/api/players/moderate',dict(action='ban',identity=UUID,duration=3600,reason='Team killing'))
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(query.call_args.args[-1],f'#ban create {UUID} 3600 Team killing')
            self.assertEqual(self.post(self.admin,'/api/players/moderate',dict(action='ban',identity=UUID,reason='bad\n#kick 1')).status_code,409)
            self.assertEqual(self.post(self.admin,'/api/players/moderate',dict(action='ban',identity=UUID,duration=True)).status_code,409)
        with patch('player_query.query_players',return_value=[dict(id='5',identity=OTHER,name='Someone else')]),patch('player_query.query_command') as query:
            self.assertEqual(self.post(self.admin,'/api/players/moderate',dict(action='kick',identity=UUID)).status_code,409)
            query.assert_not_called()
        with patch('player_query.query_players',return_value=[dict(id='9',identity=UUID,name='Target')]),patch('player_query.query_command',return_value='Kicked') as query:
            self.assertEqual(self.post(self.admin,'/api/players/moderate',dict(action='kick',identity=UUID)).status_code,200)
            self.assertEqual(query.call_args.args[-1],'#kick 9')

    def test_ban_list_parser_and_selected_server_rcon(self):
        first=self.instance('first');self.instance('second');self.configure_rcon(first.paths['config'])
        self.assertEqual(parse_bans(f'BanID ; Player UID ; Duration\n12 ; {UUID} ; 3600'),[dict(id='12',identity=UUID,duration='3600')])
        with patch('player_query.query_command',return_value=f'12 ; {UUID} ; 3600') as query:
            response=self.admin.get('/api/players/bans?page=2',headers={'X-Server-ID':'first'})
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['bans'][0]['identity'],UUID)
            self.assertEqual(query.call_args.args[-1],'#ban list 2')
            self.assertEqual(self.post(self.admin,'/api/players/moderate',dict(action='unban',identity=UUID),server='first').status_code,200)

    def test_launch_validation_persistence_scope_and_actual_argv(self):
        first=self.instance('first');self.instance('second')
        options=dict(no_sound=True,no_throw=True,ai_limit=80,ai_partial_sim=5,log_stats_ms=2000)
        body=dict(max_fps=60,launch_options=options)
        result=self.post(self.admin,'/api/startup',body,server='first')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(startup_settings.load(self.module.server_registry,'second'),startup_settings.DEFAULTS)
        with patch('runtime_ops.os.chdir'),patch('runtime_ops.os.execv') as execute:
            from runtime_ops import launch_server
            launch_server(str(self.root/'config.env'),'first')
            args=execute.call_args.args[1]
            self.assertIn('-noSound',args)
            self.assertEqual(args[args.index('-aiLimit')+1],'80')
            self.assertEqual(args[args.index('-logStats')+1],'2000')
            self.assertEqual(args[args.index('-config')+1],str(first.paths['config']))
        before=startup_settings.load(self.module.server_registry,'first')
        for changes in (dict(ai_limit=-1),dict(no_sound='true'),dict(config='/etc/passwd'),dict(log_stats_ms=0)):
            result=self.post(self.admin,'/api/startup',dict(max_fps=45,launch_options=changes),server='first')
            self.assertEqual(result.status_code,400,result.json)
        self.assertEqual(startup_settings.load(self.module.server_registry,'first'),before)
        self.assertEqual(self.module.server_registry.get('first').max_fps,60)

    def test_diagnostics_handles_corrupt_json_and_invalid_config_fields(self):
        self.config.write_text('broken')
        response=self.admin.get('/api/startup')
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(any(row['label']=='Server configuration' and row['state']=='error' for row in response.json['diagnostics']))
        self.config.write_text(json.dumps(dict(game=dict(name='Test'),rcon=dict(password='x'*33))))
        response=self.admin.get('/api/startup')
        self.assertTrue(any(row['label']=='Configuration fields' and row['state']=='error' for row in response.json['diagnostics']))
        self.assertNotIn('x'*33,json.dumps(response.json['diagnostics']))

    def test_new_schedule_actions_broadcast_validation_run_now_and_warning_guards(self):
        tools=self.module.operator_tools;store=tools.store;now=time.time()
        with self.assertRaises(ValueError):store.create('',1,dict(name='Bad',action='broadcast',run_at=now+600,broadcast=''))
        original=store.create('',1,dict(name='Start',action='start',run_at=now+600))
        manual,warned=store.queue_now('',original,1,now=now)
        self.assertFalse(warned)
        with patch.object(self.module,'start_server') as start:
            tools.tick(now,dispatch=tools.execute);start.assert_called_once()
        schedules,runs=store.list('')
        self.assertEqual(next(row for row in schedules if row['id']==original)['run_at'],now+600)
        stop_id=store.create('',1,dict(name='Stop',action='stop',run_at=now+600))
        copy_id,warned=store.queue_now('',stop_id,1,now=now)
        self.assertTrue(warned)
        copy=next(row for row in store.list('')[0] if row['id']==copy_id)
        self.assertEqual(copy['run_at'],now+360)
        self.module.get_server_pid=lambda:12
        with patch.object(self.module,'stop_server') as stop:
            tools.tick(now+360,dispatch=tools.execute);stop.assert_not_called()
        message_id=store.create('',1,dict(name='Say',action='broadcast',run_at=now+600,broadcast='Training begins soon'))
        store.queue_now('',message_id,1,now=now)
        with patch.object(tools,'broadcast') as broadcast:
            tools.tick(now,dispatch=tools.execute);broadcast.assert_called_once_with('Training begins soon')
        with self.assertRaises(ValueError):store.queue_now('other',original,1,now=now)


class ModerationProtocolTests(unittest.TestCase):
    def test_native_ban_response_can_arrive_after_processing_ack(self):
        from unittest.mock import MagicMock
        from player_query import packet, query_command, unpack
        sock=MagicMock();sock.__enter__.return_value=sock
        sock.recv.side_effect=[packet(b'\x00\x01'),packet(b'\x01\x00Processing Command: #ban list 1'),packet(('\x02\x07BanID ; Player UID ; Duration\n1 ; '+UUID+' ; 3600').encode())]
        with patch('player_query.socket.socket',return_value=sock):
            result=query_command('127.0.0.1',19999,'secret','#ban list 1')
        self.assertEqual(parse_bans(result)[0]['identity'],UUID)
        self.assertIn(b'\x02\x07',[unpack(call.args[0]) for call in sock.send.call_args_list])
