"""Relay contract tests with an isolated Redis stand-in; no ERP or camera required."""
import contextlib
import copy
import importlib.util
from pathlib import Path
import sys
import types
import unittest
import uuid
from unittest.mock import Mock, patch


class Cache:
    def __init__(self):
        self.values = {}
    def make_key(self, key):
        return key
    def lock(self, *args, **kwargs):
        return contextlib.nullcontext()
    def get_value(self, key, **kwargs):
        return copy.deepcopy(self.values.get(key))
    def set_value(self, key, value, **kwargs):
        assert 0 < kwargs['expires_in_sec'] <= 900
        self.values[key] = copy.deepcopy(value)
    def delete_value(self, key):
        self.values.pop(key, None)


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        def reject(message, exception=ValueError):
            raise exception(message)
        self.frappe.throw = reject
        self.frappe.PermissionError = PermissionError
        self.frappe.session = types.SimpleNamespace(user='manager', sid='desktop-session')
        self.frappe.cache = Cache()
        rate = types.ModuleType('frappe.rate_limiter')
        rate.rate_limit = lambda **kwargs: lambda fn: fn
        spec = importlib.util.spec_from_file_location('barcode_test_target', Path(__file__).resolve().parents[1] / 'table_remote_till/barcodes.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': self.frappe, 'frappe.rate_limiter': rate}):
            spec.loader.exec_module(self.module)
        self.module._manager = Mock()
        self.clock = patch.object(self.module.time, 'time', return_value=1000)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.pair = self.module.start('OUTLET-A', 'tab-a', 'draft-a')
        self.desktop = dict(**self.pair, tab='tab-a')
        self.frappe.session.sid = 'phone-session'
        self.phone = self.module.exchange(self.pair['token'], 'join')['phone_secret']
        self.mobile = dict(token=self.pair['token'], phone_secret=self.phone)

    def scan(self, **kwargs):
        return self.module.exchange(**self.mobile, action='scan', draft='draft-a', barcode=' 001aB ', scan_id=str(uuid.uuid4()), **kwargs)
    def computer(self, action, **kwargs):
        self.frappe.session.sid = 'desktop-session'
        return self.module.exchange(**self.desktop, action=action, **kwargs)

    def test_transfer_ack_retry_and_reconnect(self):
        scan_id = str(uuid.uuid4())
        payload = dict(action='scan', draft='draft-a', barcode='001aB', scan_id=scan_id)
        self.module.exchange(**self.mobile, **payload)
        self.module.exchange(**self.mobile, **payload)
        self.assertEqual(self.module.exchange(**self.mobile, action='join')['phone_secret'], self.phone)
        result = self.computer('poll')
        self.assertEqual(result['scan']['barcode'], '001aB')
        self.computer('ack', scan_id=scan_id)
        self.frappe.session.sid = 'phone-session'
        self.module.exchange(**self.mobile, **payload)
        self.assertIsNone(self.computer('poll')['scan'])

    def test_old_draft_and_disarmed_form_reject_scans(self):
        self.computer('arm', draft=None)
        self.frappe.session.sid = 'phone-session'
        with self.assertRaisesRegex(ValueError, 'form changed'):
            self.scan()
        self.computer('arm', draft='draft-b')
        self.frappe.session.sid = 'phone-session'
        with self.assertRaisesRegex(ValueError, 'form changed'):
            self.scan()

    def test_tab_session_and_account_isolation(self):
        self.frappe.session.user = 'other-manager'
        with self.assertRaises(PermissionError):
            self.module.exchange(**self.mobile, action='state')
        self.frappe.session.user = 'manager'
        self.frappe.session.sid = 'other-phone-session'
        with self.assertRaises(PermissionError):
            self.module.exchange(**self.mobile, action='scan')
        self.frappe.session.sid = 'desktop-session'
        with self.assertRaises(PermissionError):
            self.module.exchange(**{**self.desktop, 'tab': 'another-tab'}, action='poll')
        self.module._manager.side_effect = PermissionError('outlet denied')
        with self.assertRaises(PermissionError):
            self.computer('poll')

    def test_one_phone_per_pairing(self):
        with self.assertRaisesRegex(ValueError, 'already paired'):
            self.module.exchange(self.pair['token'], 'join')

    def test_idle_and_absolute_expiry_despite_polling(self):
        self.now.return_value = 1899
        self.computer('poll')
        self.now.return_value = 1900
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.computer('poll')
        state = self.frappe.cache.values[self.module._key(self.pair['token'])]
        state['activity'] = 4599
        self.now.return_value = 4600
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.computer('poll')

    def test_disconnect_from_either_device(self):
        self.module.exchange(**self.mobile, action='disconnect')
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.computer('poll')
        self.frappe.session.sid = 'desktop-session'
        new = self.module.start('OUTLET-A', 'tab-a', 'draft-a')
        self.module.exchange(**new, tab='tab-a', action='disconnect')
        self.assertNotIn(self.module._key(new['token']), self.frappe.cache.values)

    def test_pending_scan_not_overwritten_and_invalid_values_rejected(self):
        with self.assertRaises(ValueError):
            self.module.exchange(**self.mobile, action='scan', draft='draft-a', barcode='a\nb', scan_id=str(uuid.uuid4()))
        self.scan()
        with self.assertRaisesRegex(ValueError, 'previous scan'):
            self.scan()

    def test_phone_cannot_arm_or_read_desktop_and_secrets_are_hashed(self):
        with self.assertRaises(PermissionError):
            self.module.exchange(**self.mobile, action='arm', draft='draft-hijacked')
        state = self.frappe.cache.values[self.module._key(self.pair['token'])]
        self.assertNotIn(self.phone, repr(state))
        self.assertNotIn(self.pair['desktop_secret'], repr(state))
        self.assertNotIn(self.pair['token'], repr(state))
