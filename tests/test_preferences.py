import unittest
import test_panel


class PreferenceTests(unittest.TestCase):
    setUp = test_panel.PanelTests.setUp
    login = test_panel.PanelTests.login
    post = test_panel.PanelTests.post
    create = test_panel.PanelTests.create

    def test_preferences_are_per_account_and_require_csrf(self):
        self.create('viewer', 'viewer')
        viewer = self.login('viewer')
        self.assertEqual(self.admin.get('/api/preferences').json['theme'], 'original')
        self.assertEqual(self.admin.post('/api/preferences', json={'theme':'ocean'}).status_code, 403)
        self.assertEqual(self.post(self.admin, '/api/preferences', {'theme':'ocean'}).status_code, 200)
        self.assertEqual(viewer.get('/api/preferences').json['theme'], 'original')
        self.assertEqual(self.post(viewer, '/api/preferences', {'theme':'forest'}).status_code, 200)
        self.assertEqual(self.admin.get('/api/preferences').json['theme'], 'ocean')
        self.assertEqual(self.post(viewer, '/api/preferences', {'theme':'arbitrary'}).status_code, 400)
        self.assertEqual(self.module.app.test_client().get('/api/preferences').status_code, 401)

    def test_theme_save_works_when_no_game_config_is_readable(self):
        self.config.unlink()
        self.assertEqual(self.post(self.admin, '/api/preferences', {'theme':'light'}).status_code, 200)
        self.assertEqual(self.admin.get('/api/preferences', headers={'X-Server-ID':'missing'}).json['theme'], 'light')
