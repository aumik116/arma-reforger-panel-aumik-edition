import unittest
from pathlib import Path
import shutil
import test_panel


class PreferenceTests(unittest.TestCase):
    setUp = test_panel.PanelTests.setUp
    login = test_panel.PanelTests.login
    post = test_panel.PanelTests.post
    create = test_panel.PanelTests.create

    def test_preferences_are_per_account_and_require_csrf(self):
        self.create('viewer', 'viewer')
        viewer = self.login('viewer')
        self.assertEqual(self.admin.get('/api/preferences').json['theme'], 'tactical')
        self.assertEqual(self.admin.post('/api/preferences', json={'theme':'ocean'}).status_code, 403)
        self.assertEqual(self.post(self.admin, '/api/preferences', {'theme':'ocean'}).status_code, 200)
        self.assertEqual(viewer.get('/api/preferences').json['theme'], 'tactical')
        self.assertEqual(self.post(viewer, '/api/preferences', {'theme':'forest'}).status_code, 200)
        self.assertEqual(self.admin.get('/api/preferences').json['theme'], 'ocean')
        for theme in ('tactical', 'original', 'field', 'ocean', 'forest', 'light'):
            self.assertEqual(self.post(viewer, '/api/preferences', {'theme':theme}).status_code, 200)
            self.assertEqual(viewer.get('/api/preferences').json['theme'], theme)
        self.assertEqual(self.post(viewer, '/api/preferences', {'theme':'arbitrary'}).status_code, 400)
        self.assertEqual(self.module.app.test_client().get('/api/preferences').status_code, 401)

    def test_theme_save_works_when_no_game_config_is_readable(self):
        self.config.unlink()
        self.assertEqual(self.post(self.admin, '/api/preferences', {'theme':'light'}).status_code, 200)
        self.assertEqual(self.admin.get('/api/preferences', headers={'X-Server-ID':'missing'}).json['theme'], 'light')

    def test_account_page_is_private_and_independent_of_server_access(self):
        shutil.copy(Path(__file__).resolve().parents[1] / 'account.html', self.root / 'account.html')
        self.create('viewer', 'viewer')
        viewer = self.login('viewer')
        other_session = self.login('viewer')
        self.config.unlink()
        response = viewer.get('/account', headers={'X-Server-ID':'missing'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Confirm new password', response.data)
        self.assertEqual(self.module.app.test_client().get('/account').status_code, 302)
        self.assertEqual(self.post(viewer, '/api/account/password', {'current_password':'wrong', 'password':'replacement-password'}).status_code, 400)
        self.assertEqual(self.post(viewer, '/api/account/password', {'current_password':'test-password', 'password':'replacement-password'}).status_code, 200)
        self.assertEqual(viewer.get('/api/me').status_code, 200)
        self.assertEqual(other_session.get('/api/me').status_code, 401)
        self.assertEqual(self.login('viewer', 'replacement-password').get('/account').status_code, 200)
