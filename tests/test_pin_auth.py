"""PIN authentication and route isolation contracts without a running ERP site."""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    def __getattr__(self, key):
        return self.get(key)
    def __setattr__(self, key, value):
        self[key] = value


class Counter:
    def __init__(self):
        self.count = {}
        self.expiry = {}
    def make_key(self, key):
        return key
    def incr(self, key):
        self.count[key] = self.count.get(key, 0) + 1
        return self.count[key]
    def delete(self, key):
        self.count.pop(key, None)
    def expire(self, key, seconds):
        self.expiry[key] = seconds


class PINTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.whitelist = lambda **kw: lambda fn: fn
        self.frappe.PermissionError = PermissionError
        self.frappe.AuthenticationError = type('AuthenticationError', (Exception,), {})
        def reject(message, exception=ValueError):
            raise exception(message)
        self.frappe.throw = reject
        self.frappe.session = Row(user='Guest', sid='guest', data=Row())
        self.frappe.flags = Row()
        self.frappe.local = Row(session=self.frappe.session, login_manager=Mock(), session_obj=Mock())
        self.frappe.cache = Counter()
        self.frappe.get_roles = Mock(return_value=['TRT Cashier'])
        self.frappe.request = Row(path='/till', host_url='http://erp.local/')
        self.frappe.get_request_header = Mock(return_value=None)
        self.frappe.form_dict = Row()
        self.frappe.db = Mock()
        self.row = Row(name='ASSIGN-1', user='cashier@example.com', outlet='OUTLET-A', enabled=1,
            allow_till=1, allow_manager=0, allow_kitchen=0, till_pin_enabled=1, till_pin_revision='revision-a')
        self.frappe.db.get_value.side_effect = self.lookup
        self.passwords = types.ModuleType('frappe.utils.password')
        self.passwords.check_password = Mock()
        self.passwords.update_password = Mock()
        self.passwords.remove_encrypted_password = Mock()
        rate = types.ModuleType('frappe.rate_limiter')
        rate.rate_limit = lambda **kw: lambda fn: fn
        sessions = types.ModuleType('frappe.sessions')
        sessions.get_csrf_token = Mock(return_value='new-csrf')
        self.patches = patch.dict(sys.modules, {'frappe':self.frappe, 'frappe.rate_limiter':rate,
            'frappe.utils.password':self.passwords, 'frappe.sessions':sessions})
        self.patches.start()
        self.addCleanup(self.patches.stop)
        spec = importlib.util.spec_from_file_location('pin_test_target', Path(__file__).resolve().parents[1] / 'table_remote_till/pin_auth.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.frappe.local.login_manager.login_as.side_effect = self.create_session

    def lookup(self, doctype, name, field=None, **kwargs):
        if doctype == 'TRT Staff Assignment':
            if isinstance(name, dict):
                return (self.row.name if field == 'name' else self.row) if name.get('till_login_code') == 'staff-a' else None
            return self.row
        return 1

    def create_session(self, user):
        self.frappe.session.user = user
        self.frappe.session.sid = 'new-sid'
        self.frappe.session.data = Row()
        self.module.on_session_creation()

    def sign_in(self):
        return self.module.login('STAFF-A', '001234')

    def test_guest_can_only_see_locked_state(self):
        self.assertEqual(self.module.state()['authenticated'], False)
        self.assertIsNone(self.module.state()['user'])
        self.frappe.request = None
        self.frappe.local.session = None
        self.module.before_request()  # OPTIONS / setup with no session

    def test_login_hashes_are_checked_and_restriction_is_persisted_before_response(self):
        result = self.sign_in()
        self.assertEqual(result['csrf_token'], 'new-csrf')
        self.assertEqual(self.frappe.session.user, self.row.user)
        self.passwords.check_password.assert_called_once_with('ASSIGN-1', '001234',
            doctype='TRT Staff Assignment', fieldname='till_pin_secret', delete_tracker_cache=False)
        self.frappe.local.session_obj.update.assert_called_once_with(force=True)
        self.assertNotIn('001234', repr(self.frappe.session.data))
        self.assertEqual(self.frappe.session.data.trt_pin_scope['outlet'], 'OUTLET-A')
        self.assertTrue(self.module.state()['authenticated'])

    def test_incorrect_pin_and_unknown_code_use_generic_error(self):
        self.passwords.check_password.side_effect = self.frappe.AuthenticationError('Wrong hash')
        for code, pin in [('staff-a','001234'), ('unknown','001234'), ('staff-a','123')]:
            with self.assertRaisesRegex(self.frappe.AuthenticationError, 'Incorrect staff code or PIN'):
                self.module.login(code, pin)
        self.frappe.local.login_manager.login_as.assert_not_called()

    def test_lockout_is_account_scoped_and_case_insensitive(self):
        self.passwords.check_password.side_effect = self.frappe.AuthenticationError()
        for _ in range(5):
            with self.assertRaises(self.frappe.AuthenticationError):
                self.module.login('StAfF-A', '001234')
        with self.assertRaisesRegex(self.frappe.AuthenticationError, 'Too many PIN attempts'):
            self.module.login('staff-a', '001234')
        self.assertEqual(self.passwords.check_password.call_count, 5)
        self.assertEqual(list(self.frappe.cache.expiry.values()), [300])

    def test_pin_session_blocks_desk_rest_and_legacy_cmd_bypass(self):
        self.sign_in()
        for path, cmd in [('/app', None), ('/api/resource/User',None),
                          ('/api/method/frappe.client.get',None),
                          ('/api/method/table_remote_till.api.bootstrap','frappe.client.get'),
                          ('/api/v2/method/table_remote_till.api.bootstrap',None)]:
            self.frappe.request.path = path
            self.frappe.form_dict = Row(cmd=cmd)
            with self.subTest(path=path, cmd=cmd), self.assertRaises(PermissionError):
                self.module.before_request()
        self.frappe.form_dict = Row()
        for path in ['/till','/till/scanner','/assets/table_remote_till/till/app.js',
                     '/api/method/table_remote_till.api.bootstrap', '/api/method/table_remote_till.items.create_item',
                     '/api/method/table_remote_till.barcodes.exchange']:
            self.frappe.request.path = path
            self.module.before_request()

    def test_revoked_changed_assignment_or_disabled_user_cannot_continue(self):
        self.sign_in()
        self.row.till_pin_revision = 'rotated'
        self.assertFalse(self.module.state()['authenticated'])
        self.frappe.request.path = '/api/method/table_remote_till.api.bootstrap'
        with self.assertRaises(self.frappe.AuthenticationError):
            self.module.before_request()
        self.frappe.request.path = '/till'
        self.module.before_request()  # Expired sessions can still render the PIN screen.
        self.row.till_pin_revision = 'revision-a'
        self.row.outlet = 'OUTLET-B'
        self.assertFalse(self.module.state()['authenticated'])
        self.row.outlet = 'OUTLET-A'
        self.row.enabled = 0
        self.assertFalse(self.module.state()['authenticated'])
        self.frappe.request.path = '/api/method/table_remote_till.pin_auth.logout'
        self.module.before_request()  # Revoked users can always sign out.

    def test_expiry_and_outlet_and_manager_permissions(self):
        self.sign_in()
        self.assertTrue(self.module.check_outlet('OUTLET-A'))
        with self.assertRaises(PermissionError):
            self.module.check_outlet('OUTLET-B')
        with self.assertRaises(PermissionError):
            self.module.check_outlet('OUTLET-A', 'allow_manager')
        self.row.allow_manager = 1
        self.assertTrue(self.module.check_outlet('OUTLET-A','allow_manager'))
        self.frappe.session.data.trt_pin_scope['expires'] = 0
        self.assertFalse(self.module.state()['authenticated'])

    def test_pin_session_cannot_set_other_pins_even_for_system_manager(self):
        self.sign_in()
        self.frappe.get_roles.return_value = ['System Manager']
        with self.assertRaises(PermissionError):
            self.module.set_pin('ASSIGN-1', 'staff-a', '123456')
        with self.assertRaises(PermissionError):
            self.module.revoke_pin('ASSIGN-1')

    def test_admin_sets_hashed_pin_and_revision_and_can_revoke(self):
        self.frappe.session.user = 'admin@example.com'
        self.frappe.get_roles.return_value = ['System Manager']
        doc = Row(**self.row)
        doc.db_set = Mock()
        self.frappe.get_doc = Mock(return_value=doc)
        self.module.set_pin('ASSIGN-1', 'Staff-A', '001234')
        self.passwords.update_password.assert_called_once_with('ASSIGN-1', '001234',
            doctype='TRT Staff Assignment', fieldname='till_pin_secret')
        written = doc.db_set.call_args.args[0]
        self.assertEqual(written['till_login_code'], 'staff-a')
        self.assertEqual(written['till_pin_enabled'], 1)
        self.assertNotEqual(written['till_pin_revision'], self.row.till_pin_revision)
        self.module.revoke_pin('ASSIGN-1')
        self.assertEqual(doc.db_set.call_args.args[0]['till_pin_enabled'], 0)
        self.passwords.remove_encrypted_password.assert_called_once()

    def test_normal_erp_session_is_unchanged(self):
        self.frappe.session.user = 'manager@example.com'
        self.frappe.request.path = '/app'
        self.module.before_request()
        self.assertTrue(self.module.state()['authenticated'])
        self.assertFalse(self.module.check_outlet('OUTLET-A'))

    def test_system_manager_pin_does_not_bypass_outlet_checks(self):
        self.sign_in()
        self.frappe.get_roles.return_value = ['System Manager']
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'table_remote_till/api.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_staff_outlet')
        namespace = dict(frappe=self.frappe, _staff=Mock(), KITCHEN_ROLES=set(), STAFF_ROLES=set())
        with patch.dict(sys.modules, {'table_remote_till.pin_auth':self.module}):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'api.py','exec'),namespace)
            with self.assertRaises(PermissionError):
                namespace['_staff_outlet']('OUTLET-B')

    def test_cross_origin_login_rejected_without_creating_session(self):
        self.frappe.get_request_header.return_value = 'http://evil.example'
        with self.assertRaises(PermissionError):
            self.sign_in()
        self.frappe.local.login_manager.login_as.assert_not_called()

    def test_cashier_pin_cannot_use_manager_roles_even_if_user_is_system_manager(self):
        self.sign_in()
        self.frappe.get_roles.return_value = ['System Manager']
        self.assertEqual(self.module.effective_roles(), {'TRT Cashier'})
        self.row.allow_manager = 1
        self.assertIn('System Manager', self.module.effective_roles())
