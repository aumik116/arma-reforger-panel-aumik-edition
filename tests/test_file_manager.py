import io
import json
import unittest
from pathlib import Path
import test_panel
import test_instances

class FileManagerTests(unittest.TestCase):
    setUp=test_panel.PanelTests.setUp
    login=test_panel.PanelTests.login
    post=test_panel.PanelTests.post
    create=test_panel.PanelTests.create

    def profile(self):
        folder=self.root/'profile';folder.mkdir(exist_ok=True)
        self.module.PROFILE_DIR=str(folder)
        return folder

    def entry(self,name):
        return next(item for item in self.admin.get('/api/files').json['entries'] if item['name']==name)

    def upload(self,name,content,root='profile',client=None,parents=False):
        client=client or self.admin
        csrf=client.get('/api/csrf').json['csrf']
        return client.post('/api/files/upload',data={'root':root,'path':name,'create_parents':'true' if parents else 'false','file':(io.BytesIO(content),name)},headers={'X-CSRF-Token':csrf})

    def test_large_binary_upload_download_and_no_overwrite(self):
        folder=self.profile();content=b'abc\0'*(750*1024)
        result=self.upload('sample.bin',content)
        self.assertTrue(result.json['ok'],result.json)
        self.assertEqual((folder/'sample.bin').read_bytes(),content)
        self.assertFalse(self.entry('sample.bin')['text'])
        with self.admin.get('/api/files/download?root=profile&path=sample.bin') as downloaded:
            self.assertEqual(downloaded.data,content)
        self.assertEqual(self.upload('sample.bin',b'replacement').status_code,400)
        self.assertEqual((folder/'sample.bin').read_bytes(),content)
        self.assertEqual(list(folder.glob('.panel-upload-*')),[])

    def test_folder_upload_preserves_paths_merges_and_refuses_unsafe_parents(self):
        folder=self.profile()
        for name in ('Configs/AI/settings.json','Configs/AI/other.txt','Configs/logs/settings.json'):
            response=self.upload(name,b'original',parents=True)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual((folder/name).read_bytes(),b'original')
        self.assertEqual(self.upload('Configs/AI/settings.json',b'new',parents=True).status_code,400)
        self.assertEqual((folder/'Configs/AI/settings.json').read_bytes(),b'original')
        self.assertEqual(self.upload('missing/test.txt',b'new').status_code,400)
        self.assertEqual(self.upload('Configs/AI/other.txt/child',b'new',parents=True).status_code,400)
        for name in ('new/../escape','new/.panel-trash/escape','/absolute/file','bad\\path/file'):
            self.assertEqual(self.upload(name,b'bad',parents=True).status_code,400,name)
        self.assertFalse((folder/'new').exists())
        outside=self.root/'outside';outside.mkdir()
        (folder/'linked').symlink_to(outside,target_is_directory=True)
        self.assertEqual(self.upload('linked/child/test.txt',b'bad',parents=True).status_code,400)
        self.assertEqual(list(outside.iterdir()),[])
        self.assertEqual(self.upload('read-only/test.txt',b'bad',root='logs',parents=True).status_code,400)
        self.create('folder-operator','operator')
        self.assertEqual(self.upload('denied/test.txt',b'bad',client=self.login('folder-operator'),parents=True).status_code,403)
        self.assertFalse((folder/'denied').exists())
        self.assertEqual(self.admin.post('/api/files/upload',data={'root':'profile','path':'csrf/test.txt','create_parents':'true','file':(io.BytesIO(b'bad'),'test.txt')}).status_code,403)
        self.assertFalse((folder/'csrf').exists())

    def test_create_rename_trash_restore_and_conflicts(self):
        folder=self.profile()
        self.assertTrue(self.post(self.admin,'/api/files/create',dict(root='profile',path='folder',kind='folder')).json['ok'])
        self.assertTrue(self.post(self.admin,'/api/files/create',dict(root='profile',path='folder/test.json',kind='file')).json['ok'])
        self.assertEqual(json.loads((folder/'folder/test.json').read_text()),{})
        row=self.entry('folder')
        rename=self.post(self.admin,'/api/files/rename',dict(root='profile',path='folder',destination='renamed',revision=row['revision']))
        self.assertTrue(rename.json['ok'],rename.json)
        row=self.entry('renamed')
        deleted=self.post(self.admin,'/api/files/delete',dict(root='profile',path='renamed',revision=row['revision']))
        self.assertTrue(deleted.json['ok'],deleted.json)
        self.assertFalse((folder/'renamed').exists())
        trash=self.admin.get('/api/files/trash').json['entries'];self.assertEqual(trash[0]['path'],'renamed')
        self.assertEqual(self.admin.get('/api/files?root=profile&path=.panel-trash').status_code,400)
        (folder/'renamed').mkdir()
        self.assertEqual(self.post(self.admin,'/api/files/restore',dict(token=deleted.json['token'])).status_code,400)
        (folder/'renamed').rmdir()
        restored=self.post(self.admin,'/api/files/restore',dict(token=deleted.json['token']))
        self.assertTrue(restored.json['ok'],restored.json)
        self.assertTrue((folder/'renamed/test.json').is_file())
        self.assertEqual(self.admin.get('/api/files/trash').json['entries'],[])

    def test_permissions_csrf_and_readonly_roots(self):
        self.profile();self.create('file-manager','manager');manager=self.login('file-manager')
        for route in ('create','rename','delete','restore'):
            self.assertEqual(self.post(manager,'/api/files/'+route,{}).status_code,403)
            self.assertEqual(self.admin.post('/api/files/'+route,json={}).status_code,403)
        self.assertEqual(manager.get('/api/files/trash').status_code,403)
        self.assertEqual(self.upload('x.txt',b'foo',client=manager).status_code,403)
        for root in ('logs','server','workshop','server-config'):
            self.assertEqual(self.upload('x.txt',b'foo',root=root).status_code,400)
            self.assertEqual(self.post(self.admin,'/api/files/create',dict(root=root,path='folder',kind='folder')).status_code,400)

    def test_paths_symlinks_stale_revision_and_main_config_protected(self):
        folder=self.profile();(folder/'test.txt').write_text('original')
        row=self.entry('test.txt');(folder/'test.txt').write_text('changed')
        self.assertEqual(self.post(self.admin,'/api/files/delete',dict(root='profile',path='test.txt',revision=row['revision'])).status_code,400)
        for name in ('../escape','/absolute','folder/../escape','.panel-trash/escape','C:escape','bad\\path'):
            self.assertEqual(self.upload(name,b'bad').status_code,400,name)
        (folder/'test.txt').write_text(json.dumps({'game':{}}))
        self.module.SERVER_CONFIG=str(folder/'test.txt')
        row=self.entry('test.txt')
        for action in ('delete','rename'):
            self.assertEqual(self.post(self.admin,'/api/files/'+action,dict(root='profile',path='test.txt',destination='renamed.txt',revision=row['revision'])).status_code,400)
        self.assertTrue((folder/'test.txt').exists())

    def test_readonly_game_and_workshop_show_binary_files(self):
        for root,setting in [('server','SERVER_DIR'),('workshop','WORKSHOP_DIR')]:
            folder=self.root/root;folder.mkdir();(folder/'test.pak').write_bytes(b'abc')
            setattr(self.module,setting,str(folder))
            response=self.admin.get('/api/files',query_string={'root':root})
            self.assertEqual(response.json['entries'][0]['name'],'test.pak')
            self.assertFalse(response.json['entries'][0]['editable'])
            with self.admin.get('/api/files/download',query_string={'root':root,'path':'test.pak'}) as downloaded:
                self.assertEqual(downloaded.data,b'abc')

class FileScopeTests(unittest.TestCase):
    setUp=test_panel.PanelTests.setUp
    login=test_panel.PanelTests.login
    instance=test_instances.InstanceTests.instance
    def test_file_mutations_and_trash_stay_in_selected_server(self):
        first=self.instance('files-first');second=self.instance('files-second')
        csrf=self.admin.get('/api/csrf').json['csrf']
        headers={'X-CSRF-Token':csrf,'X-Server-ID':first.id}
        created=self.admin.post('/api/files/create',json=dict(root='profile',path='test.json',kind='file'),headers=headers)
        self.assertTrue(created.json['ok'],created.json)
        self.assertTrue((first.paths['profile']/'test.json').exists())
        self.assertFalse((second.paths['profile']/'test.json').exists())
        uploaded=self.admin.post('/api/files/upload',data=dict(root='profile',path='folder/nested/test.txt',create_parents='true',file=(io.BytesIO(b'first only'),'test.txt')),headers=headers)
        self.assertEqual(uploaded.status_code,200,uploaded.json)
        self.assertTrue((first.paths['profile']/'folder/nested/test.txt').exists())
        self.assertFalse((second.paths['profile']/'folder').exists())
        row=next(item for item in self.admin.get('/api/files',headers=headers).json['entries'] if item['name']=='test.json')
        deleted=self.admin.post('/api/files/delete',json=dict(root='profile',path='test.json',revision=row['revision']),headers=headers)
        token=deleted.json['token']
        wrong={'X-CSRF-Token':csrf,'X-Server-ID':second.id}
        self.assertEqual(self.admin.get('/api/files/trash',headers=wrong).json['entries'],[])
        self.assertEqual(self.admin.post('/api/files/restore',json=dict(token=token),headers=wrong).status_code,400)
        self.assertTrue(self.admin.post('/api/files/restore',json=dict(token=token),headers=headers).json['ok'])
