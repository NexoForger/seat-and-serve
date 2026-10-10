"""Standalone contract tests for shift cash validation and reconciliation.

Run: python3 -m unittest discover -s tests
"""
import contextlib
import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class Closing:
    def __init__(self, rows):
        self.payment_reconciliation = rows

    def append(self, field, value):
        row = Row(value)
        getattr(self, field).append(row)
        return row


def reject(message, *args):
    raise ValueError(message)


class ShiftTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.throw = reject
        self.frappe.db = Mock()
        self.frappe.PermissionError = PermissionError
        self.frappe.session = Row(user='cashier@example.com')
        utils = types.ModuleType('frappe.utils')
        utils.flt = lambda value: float(value or 0)
        utils.now_datetime = lambda: '2026-10-10 10:00:00'
        api = types.ModuleType('table_remote_till.api')
        api._as_admin = contextlib.nullcontext
        api._outlet = Mock()
        api._payload = lambda value: value
        api._staff_outlet = Mock()
        spec = importlib.util.spec_from_file_location('shift_test_target',
            Path(__file__).resolve().parents[1] / 'table_remote_till/shifts.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': self.frappe, 'frappe.utils': utils,
                                      'table_remote_till.api': api}):
            spec.loader.exec_module(self.module)

    def test_counts_require_each_mode_and_finite_nonnegative_numbers(self):
        self.assertEqual(self.module._counts({'Cash': '0', 'Card': '12.50'}, ['Cash', 'Card']),
                         {'Cash': 0, 'Card': 12.5})
        for invalid in (-1, '', None, True, math.nan, math.inf, 'abc'):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.module._counts({'Cash': invalid}, ['Cash'])
        for invalid in ({}, {'Cash': 1, 'Other': 2}, []):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.module._counts(invalid, ['Cash'])

    def test_reconciliation_adds_float_and_preserves_negative_refund_totals(self):
        closing = Closing([Row(mode_of_payment='Cash', expected_amount=25),
                           Row(mode_of_payment='Card', expected_amount=-10)])
        dependency = types.ModuleType('closing_dependency')
        dependency.make_closing_entry_from_opening = Mock(return_value=closing)
        opening = Row(balance_details=[Row(mode_of_payment='Cash', opening_amount=100),
                                       Row(mode_of_payment='Spare drawer', opening_amount=50)])
        with patch.dict(sys.modules, {
            'erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry': dependency}):
            result = self.module._closing(opening)
        totals = {row.mode_of_payment: row.expected_amount for row in result.payment_reconciliation}
        self.assertEqual(totals, {'Cash': 125, 'Card': -10, 'Spare drawer': 50})

    def test_active_shift_includes_previous_days_but_not_drafts(self):
        self.module.active_opening('POS-A')
        filters = self.frappe.db.get_value.call_args.args[1]
        self.assertEqual(filters, {'pos_profile': 'POS-A', 'status': 'Open', 'docstatus': 1})

    def test_authorization_precedes_profile_access(self):
        self.module._staff_outlet.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.module._context('OUTLET-B', lock=True)
        self.frappe.db.sql.assert_not_called()

    def test_duplicate_open_does_not_create_entry(self):
        self.module._context = Mock(return_value=Row(name='POS-A'))
        self.module.active_opening = Mock(return_value='OPEN-1')
        self.frappe.get_doc = Mock()
        with self.assertRaises(ValueError):
            self.module.open_shift('OUTLET-A', {'Cash': 100})
        self.frappe.get_doc.assert_not_called()

    def test_close_rejects_other_outlets_even_on_retry(self):
        self.module._context = Mock(return_value=Row(name='POS-A', company='Company'))
        self.frappe.get_doc = Mock(return_value=Row(pos_profile='POS-B', company='Company'))
        with self.assertRaises(ValueError):
            self.module.close_shift('OUTLET-A', 'OPEN-B', {'Cash': 100})
        self.frappe.db.get_value.assert_not_called()

    def test_close_retry_returns_existing_without_recreating(self):
        self.module._context = Mock(return_value=Row(name='POS-A', company='Company'))
        self.frappe.get_doc = Mock(return_value=Row(name='OPEN-1', pos_profile='POS-A', company='Company'))
        self.frappe.db.get_value.return_value = Row(name='CLOSE-1', status='Queued')
        self.module._closing = Mock()
        self.assertEqual(self.module.close_shift('OUTLET-A', 'OPEN-1', {'Cash': 100}).name, 'CLOSE-1')
        self.module._closing.assert_not_called()

    def test_closing_records_actual_count_and_difference(self):
        self.module._context = Mock(return_value=Row(name='POS-A', company='Company'))
        self.frappe.get_doc = Mock(return_value=Row(name='OPEN-1', pos_profile='POS-A', company='Company'))
        self.frappe.db.get_value.return_value = None
        self.module.active_opening = Mock(return_value='OPEN-1')
        closing = Mock(name='closing')
        closing.name = 'CLOSE-1'
        closing.status = 'Submitted'
        closing.payment_reconciliation = [Row(mode_of_payment='Cash', expected_amount=150)]
        self.module._closing = Mock(return_value=closing)
        self.module.close_shift('OUTLET-A', 'OPEN-1', {'Cash': 145})
        row = closing.payment_reconciliation[0]
        self.assertEqual((row.closing_amount, row.difference), (145, -5))
        closing.submit.assert_called_once()
