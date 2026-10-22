"""Unit boundaries, roster persistence and promotion rules using isolated panel databases."""
import sys
from datetime import date, timedelta
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_panel


class UnitTests(unittest.TestCase):
    setUp=test_panel.PanelTests.setUp
    login=test_panel.PanelTests.login
    post=test_panel.PanelTests.post
    create=test_panel.PanelTests.create

    def unit(self,name='Alpha'):
        response=self.post(self.admin,'/api/units',dict(name=name,tag=name[:1],servers=['']))
        self.assertEqual(response.status_code,200,response.json)
        return response.json['id']

    def detail(self,unit,client=None):
        return (client or self.admin).get(f'/api/units/{unit}').json

    def change(self,unit,path,data,client=None):
        client=client or self.admin
        return self.post(client,f'/api/units/{unit}/{path}',dict(data,revision=self.detail(unit,client)['unit']['revision']))

    def member(self,unit,**changes):
        return self.change(unit,'roster',dict(game_name='Ranger',status='active',**changes))

    def test_unit_isolation_staff_controls_and_recorded_identity_scope(self):
        a=self.unit();b=self.unit('Bravo')
        self.create('alpha-staff','viewer')
        self.assertTrue(self.change(a,'staff',dict(username='alpha-staff',role='staff',capabilities=['roster'])).json['ok'])
        staff=self.login('alpha-staff')
        self.assertEqual([u['id'] for u in staff.get('/api/units').json['units']],[a])
        for suffix in ('','/identities','/roster.csv','/health'):
            self.assertEqual(staff.get(f'/api/units/{b}{suffix}').status_code,404)
        self.assertEqual(self.post(staff,'/api/units',dict(name='No')).status_code,403)
        self.assertEqual(self.change(a,'staff',dict(username='alpha-staff',role='admin'),staff).status_code,403)
        identity='00000000-0000-0000-0000-000000000001'
        self.assertEqual(self.member(a,identity=identity).status_code,400)
        self.module.operator_tools.store.observe('private',dict(available=True,players=[dict(name='Private',identity=identity)]))
        self.assertEqual(self.member(a,identity=identity).status_code,400)
        self.module.operator_tools.store.observe('',dict(available=True,players=[dict(name='Ranger',identity=identity)]))
        self.assertEqual(len(staff.get(f'/api/units/{a}/identities').json['players']),1)
        self.assertTrue(self.change(a,'roster',dict(game_name='Ranger',identity=identity,status='active'),staff).json['ok'])
        self.assertEqual(self.member(a,identity=identity).status_code,400)
        self.assertTrue(self.member(b,identity=identity).json['ok'])
        self.assertEqual(self.admin.post(f'/api/units/{a}/roster',json={}).status_code,403)
        self.assertEqual(staff.get('/api/users').status_code,403)
        # Unit events must not leak through the existing server activity feed.
        self.create('server-manager','manager')
        manager=self.login('server-manager')
        self.assertFalse(any(e['details'].get('unit_id') for e in manager.get('/api/activity').json['events']))
        # Staff can use their unit even when they have no hosting access.
        user=next(u for u in self.admin.get('/api/users').json['users'] if u['username']=='alpha-staff')
        self.assertTrue(self.post(self.admin,'/api/users',dict(id=user['id'],username=user['username'],role='viewer',access_all=False,server_roles={},panel_admin=False)).json['ok'])
        staff=self.login('alpha-staff')
        self.assertEqual(staff.get('/api/servers').json['servers'],[])
        self.assertEqual(staff.get(f'/api/units/{a}').status_code,200)
        self.assertFalse(staff.get(f'/api/units/{a}/health').json['servers'][0]['can_open'])

    def test_rank_paygrade_paths_certificates_positions_and_archival(self):
        unit=self.unit()
        catalog=dict(certificates=['Medical','Leadership'],positions=['Platoon Sergeant','Company Medic'],paygrades=[dict(name='E-4',days=0),dict(name='E-5',days=30,certificates=['Leadership'])],ranks=[dict(name='Cpl',paygrade='E-4',next_rank='Sgt'),dict(name='Sgt',paygrade='E-5',certificates=['Medical']),dict(name='HM2',paygrade='E-5')])
        self.assertTrue(self.change(unit,'catalog',dict(catalog=catalog)).json['ok'])
        last=(date.today()-timedelta(days=40)).isoformat()
        result=self.member(unit,rank='Cpl',last_promo=last,position='Platoon Sergeant;Company Medic',certificates='Leadership')
        self.assertTrue(result.json['ok'],result.json)
        member=self.detail(unit)['roster'][0]
        self.assertEqual(member['promotion']['next_rank'],'Sgt')
        self.assertEqual(member['promotion']['missing'],['Medical'])
        self.assertEqual(member['promotion']['next_date'],(date.fromisoformat(last)+timedelta(days=30)).isoformat())
        self.assertFalse(member['promotion']['eligible'])
        member['archived']=False
        member['certificates']='Leadership;Medical'
        self.assertTrue(self.change(unit,'roster',member).json['ok'])
        self.assertTrue(self.detail(unit)['roster'][0]['promotion']['eligible'])
        member['archived']=True
        self.assertTrue(self.change(unit,'roster',member).json['ok'])
        self.assertFalse(self.detail(unit)['roster'][0]['promotion']['eligible'])
        self.assertEqual(self.change(unit,'catalog',dict(catalog={})).status_code,400)
        self.assertTrue(self.change(unit,'positions/rename',dict(old='Company Medic',name='Company Corpsman')).json['ok'])
        self.assertIn('Company Corpsman',self.detail(unit)['roster'][0]['position'])
        self.assertNotIn('Company Medic',self.detail(unit)['unit']['catalog']['positions'])
        catalog['positions']=['Platoon Sergeant','Company Corpsman']
        catalog['ranks'][1]['next_rank']='Cpl'
        self.assertEqual(self.change(unit,'catalog',dict(catalog=catalog)).status_code,400)

    def test_stale_saves_and_formula_safe_export(self):
        unit=self.unit()
        self.assertTrue(self.member(unit,notes='=HYPERLINK("bad")').json['ok'])
        before=self.detail(unit)
        self.assertEqual(self.post(self.admin,f'/api/units/{unit}/roster',dict(game_name='Wrong',status='active',revision=1)).status_code,409)
        self.assertEqual(self.detail(unit),before)
        exported=self.admin.get(f'/api/units/{unit}/roster.csv')
        self.assertIn("'=HYPERLINK",exported.text)
        self.assertEqual(len(self.detail(unit)['roster']),1)
        self.assertEqual(self.detail(unit)['roster'][0]['identity'],'')

    def test_member_records_keep_unit_boundaries_permissions_and_note_history(self):
        a=self.unit();b=self.unit('Bravo')
        first=self.member(a,notes='Existing summary').json['id']
        second=self.member(b).json['id']
        path=f'/api/units/{a}/roster/{first}/record'
        self.create('record-viewer','viewer')
        self.assertTrue(self.change(a,'staff',dict(username='record-viewer',role='staff')).json['ok'])
        viewer=self.login('record-viewer')
        self.assertEqual(viewer.get(path).json['member']['notes'],'Existing summary')
        self.assertFalse(viewer.get(path).json['can_write'])
        self.assertEqual(self.post(viewer,path,dict(note='Not allowed')).status_code,403)
        self.assertEqual(viewer.get(f'/api/units/{b}/roster/{second}/record').status_code,404)
        self.assertEqual(self.admin.get(f'/api/units/{a}/roster/{second}/record').status_code,404)
        self.assertEqual(self.post(self.admin,f'/api/units/{a}/roster/{second}/record',dict(note='Wrong member')).status_code,404)
        self.assertEqual(self.admin.post(path,json=dict(note='Missing CSRF')).status_code,403)
        for note in ('  ', 'x'*4001, ['invalid']):
            self.assertEqual(self.post(self.admin,path,dict(note=note)).status_code,400)
        self.assertTrue(self.change(a,'staff',dict(username='record-viewer',role='staff',capabilities=['roster'])).json['ok'])
        self.assertTrue(self.post(viewer,path,dict(note='Completed vehicle qualification.\nReviewed by staff.')).json['ok'])
        self.assertTrue(self.post(self.admin,path,dict(note='<script>literal text</script>')).json['ok'])
        result=viewer.get(path).json
        self.assertEqual([r['author_name'] for r in result['notes']],['admin','record-viewer'])
        self.assertEqual(result['notes'][1]['note'],'Completed vehicle qualification.\nReviewed by staff.')
        cursor=result['notes'][0]['id']
        self.assertEqual(len(viewer.get(path+'?before='+str(cursor)).json['notes']),1)
        self.assertEqual(viewer.get(path+'?before=-1').status_code,400)
        member=self.detail(a)['roster'][0];member['archived']=True
        self.assertTrue(self.change(a,'roster',member).json['ok'])
        self.assertEqual(len(viewer.get(path).json['notes']),2)
        self.assertTrue(self.change(a,'staff',dict(username='record-viewer',role='remove')).json['ok'])
        self.assertEqual(viewer.get(path).status_code,404)

    def test_account_links_and_note_authors_are_scoped_to_each_unit(self):
        a=self.unit();b=self.unit('Bravo')
        account=self.create('linked-staff','viewer')
        self.assertTrue(self.change(a,'staff',dict(username='linked-staff',role='staff',capabilities=['roster'])).json['ok'])
        self.assertTrue(self.change(b,'staff',dict(username='linked-staff',role='staff',capabilities=['roster'])).json['ok'])
        first=self.change(a,'roster',dict(game_name='Sgt. Ranger',status='active',panel_user_id=account['id'])).json['id']
        second=self.change(b,'roster',dict(game_name='HM2. Ranger',status='active',panel_user_id=account['id'])).json['id']
        self.assertEqual(self.member(a,panel_user_id=account['id']).status_code,400)
        self.assertEqual(self.member(a,panel_user_id=True).status_code,400)
        self.assertEqual(self.member(a,panel_user_id=999999).status_code,400)
        linked=self.login('linked-staff')
        for unit,member,name in ((a,first,'Sgt. Ranger'),(b,second,'HM2. Ranger')):
            path=f'/api/units/{unit}/roster/{member}/record'
            self.assertTrue(self.post(linked,path,dict(note='Unit-specific note')).json['ok'])
            self.assertEqual(linked.get(path).json['notes'][0]['author_name'],name)
            self.assertEqual(linked.get(path).json['member']['panel_username'],'linked-staff')
        member=self.detail(a)['roster'][0];member['game_name']='Renamed';member['archived']=False
        self.assertTrue(self.change(a,'roster',member).json['ok'])
        path=f'/api/units/{a}/roster/{first}/record'
        self.assertEqual(linked.get(path).json['notes'][0]['author_name'],'Sgt. Ranger')
        self.assertTrue(self.post(linked,path,dict(note='New name')).json['ok'])
        self.assertEqual(linked.get(path).json['notes'][0]['author_name'],'Renamed')
        member=self.detail(a,linked)['roster'][0];member['archived']=False;member['discord']='new_handle'
        self.assertTrue(self.change(a,'roster',member,linked).json['ok'])
        member['panel_user_id']=None
        self.assertEqual(self.change(a,'roster',member,linked).status_code,403)
        outsider=self.create('outside-account','viewer')
        self.assertNotIn(outsider['id'],[u['id'] for u in linked.get(f'/api/units/{a}').json['accounts']])
        self.assertEqual(self.change(a,'roster',dict(game_name='Other',status='active',panel_user_id=outsider['id']),linked).status_code,403)
        self.assertFalse(next(u for u in self.admin.get('/api/users').json['users'] if u['id']==outsider['id'])['units'])
        # Account deletion clears links without removing roster records or old note names.
        for unit in (a,b):
            self.assertTrue(self.change(unit,'staff',dict(username='linked-staff',role='remove')).json['ok'])
        self.assertTrue(self.post(self.admin,'/api/users/delete',dict(id=account['id'])).json['ok'])
        self.assertIsNone(self.detail(a)['roster'][0]['panel_user_id'])
        self.assertEqual(self.admin.get(path).json['notes'][0]['author_name'],'Renamed')

    def test_member_deletion_removes_notes_keeps_accounts_and_never_reuses_record_ids(self):
        unit=self.unit()
        self.create('roster-editor','viewer')
        self.assertTrue(self.change(unit,'staff',dict(username='roster-editor',role='staff',capabilities=['roster'])).json['ok'])
        editor=self.login('roster-editor')
        member=self.member(unit,panel_user_id=1).json['id']
        record=f'/api/units/{unit}/roster/{member}/record'
        endpoint=f'/api/units/{unit}/roster/{member}/delete'
        self.assertTrue(self.post(self.admin,record,dict(note='Saved note')).json['ok'])
        revision=self.detail(unit)['unit']['revision']
        payload=dict(confirm_name='Ranger',revision=revision)
        self.assertEqual(self.post(editor,endpoint,payload).status_code,403)
        self.assertEqual(self.admin.post(endpoint,json=payload).status_code,403)
        self.assertEqual(self.post(self.admin,endpoint,dict(payload,confirm_name='wrong')).status_code,400)
        self.assertEqual(self.post(self.admin,endpoint,dict(payload,revision=0)).status_code,409)
        self.assertEqual(len(self.admin.get(record).json['notes']),1)
        self.assertTrue(self.post(self.admin,endpoint,payload).json['ok'])
        self.assertEqual(self.admin.get(record).status_code,404)
        self.assertEqual(self.detail(unit)['roster'],[])
        self.assertTrue(next(u for u in self.admin.get('/api/users').json['users'] if u['id']==1)['is_owner'])
        with self.module.operator_tools.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM unit_member_notes WHERE member_id=?',(member,)).fetchone()[0],0)
        replacement=self.member(unit).json['id']
        self.assertGreater(replacement,member)
        self.assertEqual(self.admin.get(record).status_code,404)

    def test_account_unit_changes_are_atomic_and_last_admin_is_protected(self):
        unit=self.unit();user=self.create('unit-lead','viewer')
        self.assertTrue(self.change(unit,'staff',dict(username='unit-lead',role='admin')).json['ok'])
        self.assertTrue(self.change(unit,'staff',dict(username='admin',role='remove')).json['ok'])
        lead=self.login('unit-lead')
        self.assertEqual(self.change(unit,'staff',dict(username='unit-lead',role='remove'),lead).status_code,400)
        result=self.post(self.admin,'/api/users',dict(id=user['id'],username='unit-lead',role='viewer',enabled=False,panel_admin=False))
        self.assertEqual(result.status_code,400)
        self.assertTrue(next(u for u in self.admin.get('/api/users').json['users'] if u['id']==user['id'])['enabled'])
        self.assertEqual(self.post(self.admin,'/api/users/delete',dict(id=user['id'])).status_code,400)
        stale=self.post(self.admin,'/api/users',dict(id=user['id'],username='unit-lead',role='viewer',units=[],unit_revisions={str(unit):0}))
        self.assertEqual(stale.status_code,409)
        self.assertEqual(lead.get(f'/api/units/{unit}').status_code,200)


if __name__=='__main__':
    unittest.main()
