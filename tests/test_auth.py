"""Security tests run with authentication AND CSRF enabled on temporary data."""

from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from app import create_app
from app.auth import auth_db, set_owner_password, token_digest
from app.database import get_session
from app.models import Pallet, Shoe


class TokenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = {'method': attrs.get('method', 'get').lower(), 'token': False}
            self.forms.append(self.current)
        if tag == 'input' and attrs.get('name') == 'csrf_token':
            self.token = attrs.get('value')
            if self.current is not None:
                self.current['token'] = True

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.new_app()
        self.client = self.app.test_client()
        self.password = secrets.token_urlsafe(24)

    def new_app(self, **config):
        app = create_app({'TESTING': True, 'DATA_ROOT': self.root, **config})
        self.addCleanup(app.extensions['inventory_db']['engine'].dispose)
        self.addCleanup(app.extensions['offline_gate'].close)
        return app

    def initialize(self):
        with self.app.app_context():
            set_owner_password(self.password, initialize=True)

    def token(self, client=None, path='/login'):
        parser = TokenParser()
        parser.feed((client or self.client).get(path).get_data(as_text=True))
        return parser.token

    def login(self, client=None, password=None, remember=False, target='/'):
        client = client or self.client
        return client.post('/login', data={'csrf_token': self.token(client), 'password': password or self.password,
                                          'remember': 'yes' if remember else '', 'next': target})

    def test_unconfigured_app_is_closed_and_shows_local_setup(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 503)
        self.assertIn('init-owner', response.get_data(as_text=True))
        self.assertNotIn('name="password"', response.get_data(as_text=True))

    def test_private_views_redirect_and_files_require_login(self):
        self.initialize()
        for path in ('/', '/db-inspector', '/pallets/1', '/shoes/1'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.client.get('/media/PALETY/private.jpg').status_code, 401)
        self.assertEqual(self.client.post('/pallets', data={}).status_code, 401)
        self.assertEqual(self.client.get('/health').status_code, 200)
        response = self.client.get('/static/styles.css')
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_no_remote_account_setup_endpoint(self):
        for path in ('/register', '/setup', '/init-owner', '/reset-owner-password'):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_password_is_hashed_and_not_in_session(self):
        self.initialize()
        with self.app.app_context(), auth_db() as db:
            hashed = db.execute('SELECT password_hash FROM owner').fetchone()[0]
        self.assertNotIn(self.password, hashed)
        self.assertTrue(hashed.startswith('scrypt:'))
        self.assertEqual(self.login().status_code, 303)
        with self.client.session_transaction() as cookie:
            self.assertNotIn(self.password, str(dict(cookie)))

    def test_good_login_rotates_session_and_allows_inventory(self):
        self.initialize()
        with self.client.session_transaction() as cookie:
            cookie['old_data'] = 'must be removed'
        response = self.login()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, '/')
        with self.client.session_transaction() as cookie:
            self.assertNotIn('old_data', cookie)
            self.assertIn('auth_token', cookie)
        self.assertEqual(self.client.get('/db-inspector').status_code, 200)

    def test_bad_password_rejected_without_echoing_password(self):
        self.initialize()
        wrong = secrets.token_urlsafe(20)
        response = self.login(password=wrong)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(wrong, response.get_data(as_text=True))
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_login_requires_csrf(self):
        self.initialize()
        for token in (None, 'tampered'):
            data = {'password': self.password}
            if token:
                data['csrf_token'] = token
            self.assertEqual(self.client.post('/login', data=data).status_code, 400)
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_write_requires_csrf_and_preserves_data(self):
        self.initialize()
        self.login()
        data = {'code': 'CSRF_BOX', 'delivery_date': '2026-01-01', 'purchase_gross': '100'}
        self.assertEqual(self.client.post('/pallets', data=data).status_code, 400)
        data['csrf_token'] = self.token(path='/')
        self.assertEqual(self.client.post('/pallets', data=data).status_code, 302)
        with self.app.app_context(), get_session() as db:
            self.assertEqual(db.query(Pallet).count(), 1)

    def test_foreign_session_token_is_rejected(self):
        self.initialize()
        foreign = self.app.test_client()
        foreign_token = self.token(foreign)
        self.assertEqual(self.client.post('/login', data={'csrf_token': foreign_token, 'password': self.password}).status_code, 400)

    def test_expired_csrf_is_rejected(self):
        self.initialize()
        token = self.token()
        with patch('itsdangerous.timed.time.time', return_value=time.time() + 7200):
            self.assertEqual(self.client.post('/login', data={'csrf_token': token, 'password': self.password}).status_code, 400)

    def test_logout_needs_post_and_csrf_then_revokes_session(self):
        self.initialize()
        self.login()
        self.assertEqual(self.client.get('/logout').status_code, 405)
        self.assertEqual(self.client.post('/logout').status_code, 400)
        old_cookie = self.client.get_cookie('session').value
        response = self.client.post('/logout', data={'csrf_token': self.token(path='/')})
        self.assertEqual(response.status_code, 303)
        self.client.set_cookie('session', old_cookie)
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_reset_revokes_all_devices_and_old_password(self):
        self.initialize()
        other = self.app.test_client()
        self.login(remember=True)
        self.login(client=other)
        with self.app.app_context():
            set_owner_password(self.password + 'new')
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(other.get('/').status_code, 302)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password=self.password + 'new').status_code, 303)

    def test_session_expires_on_server(self):
        self.initialize()
        self.login()
        with self.app.app_context(), auth_db() as db:
            db.execute('UPDATE auth_sessions SET expires_at = 1')
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_remembered_device_has_bounded_persistent_cookie(self):
        self.initialize()
        response = self.login(remember=True)
        self.assertIn('Expires=', response.headers['Set-Cookie'])
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])
        with self.app.app_context(), auth_db() as db:
            expiry = db.execute('SELECT expires_at FROM auth_sessions').fetchone()[0]
            self.assertAlmostEqual(expiry - time.time(), 30 * 24 * 60 * 60, delta=5)

    def test_regular_session_has_shorter_lifetime(self):
        self.initialize()
        response = self.login()
        self.assertNotIn('Expires=', response.headers['Set-Cookie'])
        with self.app.app_context(), auth_db() as db:
            expiry = db.execute('SELECT expires_at FROM auth_sessions').fetchone()[0]
            self.assertAlmostEqual(expiry - time.time(), 12 * 60 * 60, delta=5)

    def test_auth_database_never_stores_raw_session_token(self):
        self.initialize()
        self.login()
        with self.client.session_transaction() as cookie:
            raw = cookie['auth_token']
        with self.app.app_context(), auth_db() as db:
            stored = db.execute('SELECT token_hash FROM auth_sessions').fetchone()[0]
        self.assertNotEqual(raw, stored)
        self.assertEqual(stored, token_digest(raw))

    def test_throttle_persists_across_application_restart(self):
        self.initialize()
        for _ in range(5):
            self.assertEqual(self.login(password='wrong password').status_code, 401)
        restarted = self.new_app()
        other = restarted.test_client()
        response = self.login(client=other)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers['Retry-After']), 0)

    def test_throttle_expires_and_ignores_forwarded_ip_header(self):
        self.initialize()
        token = self.token()
        now = int(time.time())
        with patch('app.auth.time.time', return_value=now):
            for i in range(5):
                response = self.client.post('/login', data={'csrf_token': token, 'password': 'wrong'}, headers={'X-Forwarded-For': f'10.0.0.{i}'})
                self.assertEqual(response.status_code, 401)
            self.assertEqual(self.login().status_code, 429)
        with patch('app.auth.time.time', return_value=now + 301):
            self.assertEqual(self.login().status_code, 303)

    def test_global_throttle_applies_across_real_client_addresses(self):
        self.initialize()
        self.app.config['LOGIN_GLOBAL_RATE_LIMIT'] = 3
        token = self.token()
        for i in range(3):
            response = self.client.post('/login', data={'csrf_token': token, 'password': 'wrong'},
                                        environ_overrides={'REMOTE_ADDR': f'10.0.0.{i + 1}'})
            self.assertEqual(response.status_code, 401)
        response = self.client.post('/login', data={'csrf_token': token, 'password': self.password},
                                    environ_overrides={'REMOTE_ADDR': '10.0.0.99'})
        self.assertEqual(response.status_code, 429)

    def test_authenticated_media_is_accessible_but_auth_database_is_not(self):
        self.initialize()
        folder = self.app.config['PHOTOS_ROOT'] / 'test'
        folder.mkdir()
        (folder / 'image.jpg').write_bytes(b'test image bytes')
        self.login()
        response = self.client.get('/media/PALETY/test/image.jpg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        response.close()
        self.assertEqual(self.client.get('/media/.auth.sqlite3').status_code, 404)

    def test_invalid_or_unknown_cookie_never_authenticates(self):
        self.initialize()
        self.client.set_cookie('session', 'not-a-valid-signed-cookie')
        self.assertEqual(self.client.get('/').status_code, 302)
        with self.client.session_transaction() as cookie:
            cookie['auth_token'] = 'unknown-opaque-token'
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_auth_storage_failure_is_closed_not_bypassed(self):
        self.initialize()
        self.login()
        with self.assertLogs(self.app.logger, level='ERROR'), patch('app.auth.sqlite3.connect', side_effect=sqlite3.OperationalError('private path')):
            response = self.client.get('/')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private path', response.get_data(as_text=True))

    def test_external_and_encoded_redirects_are_blocked(self):
        self.initialize()
        targets = ('https://evil.example', '//evil.example', '/\\evil.example', '/%2f%2fevil.example', '/%0aevil', '/logout')
        for target in targets:
            with self.subTest(target=target):
                with self.app.app_context(), auth_db() as db:
                    db.execute('DELETE FROM login_attempts')
                client = self.app.test_client()
                response = self.login(client=client, target=target)
                self.assertEqual(response.location, '/')

    def test_local_redirect_is_kept(self):
        self.initialize()
        self.assertEqual(self.login(target='/?shoe_q=ABC').location, '/?shoe_q=ABC')

    def test_cli_init_reset_and_validation(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['init-owner'], input='short\nshort\n')
        self.assertNotEqual(result.exit_code, 0)
        result = runner.invoke(args=['init-owner'], input=f'{self.password}\n{self.password}\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn(self.password, result.output)
        result = runner.invoke(args=['init-owner'], input=f'{self.password}\n{self.password}\n')
        self.assertNotEqual(result.exit_code, 0)
        new = secrets.token_urlsafe(24)
        result = runner.invoke(args=['reset-owner-password'], input=f'{new}\n{new}\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.login(password=new).status_code, 303)

    def test_cannot_disable_security_in_normal_mode(self):
        for config in ({'AUTH_DISABLED': True}, {'WTF_CSRF_ENABLED': False}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                create_app({'DATA_ROOT': self.root / 'forbidden', **config})

    def test_private_pages_are_not_cached_or_frameable(self):
        self.initialize()
        self.login()
        response = self.client.get('/')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_all_inventory_post_forms_have_csrf_token(self):
        self.initialize()
        with self.app.app_context(), get_session() as db:
            pallet = Pallet(code='FORM_BOX', delivery_date=date.today(), purchase_gross=100)
            db.add(pallet)
            db.flush()
            shoe = Shoe(pallet_id=pallet.id, internal_id='FORM1', name='Form fixture')
            db.add(shoe)
            db.commit()
            pid, sid = pallet.id, shoe.id
        self.login()
        for path in ('/', f'/pallets/{pid}', f'/shoes/{sid}'):
            with self.subTest(path=path):
                parser = TokenParser()
                parser.feed(self.client.get(path).get_data(as_text=True))
                forms = [form for form in parser.forms if form['method'] == 'post']
                self.assertTrue(forms)
                self.assertTrue(all(form['token'] for form in forms))


if __name__ == '__main__':
    unittest.main()
