"""Tab cash stays in native POS payments or consolidated-invoice Payment Entries."""
import contextlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


def reject(message):
    raise ValueError(message)


class TabPayments(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.throw = reject
        self.frappe.db = Mock()
        self.frappe.session = Row(user='cashier')
        self.frappe.get_all = Mock(return_value=[])
        self.utils = types.ModuleType('frappe.utils')
        self.utils.flt = lambda value: float(value or 0)
        self.utils.get_datetime = lambda value: value
        self.utils.now_datetime = lambda: 'now'
        spec = importlib.util.spec_from_file_location('tabs_target', Path(__file__).resolve().parents[1] / 'table_remote_till/tab_payments.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': self.frappe, 'frappe.utils': self.utils}):
            spec.loader.exec_module(self.module)

    def test_partial_then_final_and_overpayment(self):
        self.assertEqual(self.module.validate_amount(30, 100, 'USD', True), 70)
        self.assertEqual(self.module.validate_amount(70, 70, 'USD', True), 0)
        self.assertEqual(self.module.validate_amount(100000, 895000, 'LBP', True), 795000)
        for value in (0, -1, 101, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module.validate_amount(value, 100, 'USD', True)
        with self.assertRaisesRegex(ValueError, 'Allow Partial Payment'):
            self.module.validate_amount(30, 100, 'USD', False)

    def test_mixed_cash_is_rounded_and_rejects_invalid_tenders(self):
        rows = self.module.payment_amounts([dict(mode_of_payment='Cash', currency='LBP', amount=895000)], 'USD', 89500, {'Cash'})
        self.assertEqual(rows[0]['base_amount'], 10)
        for amount in ('NaN', 'Infinity', -1, True, 0):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.module.payment_amounts([dict(mode_of_payment='Cash', currency='USD', amount=amount)], 'USD', 89500, {'Cash'})
        with self.assertRaises(ValueError):
            self.module.payment_amounts([dict(mode_of_payment='Card', currency='USD', amount=30)], 'USD', 89500, {'Cash'})

    def test_balance_adds_only_submitted_later_receipts(self):
        self.frappe.get_all.return_value = [Row(payment_entry='PE1', base_amount=20), Row(payment_entry='CANCELLED', base_amount=50)]
        self.frappe.db.get_value.side_effect = lambda dt, name, field: 1 if name == 'PE1' else 2
        result = self.module.balance(Row(name='TAB'), Row(grand_total=100, paid_amount=30))
        self.assertEqual(result, dict(paid_amount=50, amount_due=50))
        self.assertEqual(self.frappe.get_all.call_args.kwargs['filters']['payment_entry'], ['is', 'set'])

    def receive(self, consolidated=False):
        order = Row(name='TAB', channel='Tab', status='Partially Paid', revision=2, currency='USD', pos_invoice='POS', outlet='OUT', order_number='1', register='REG', save=Mock())
        outlet = Row(name='OUT', pos_profile='PROFILE', company='CO')
        invoice = Row(name='POS', docstatus=1, is_return=0, company='CO', pos_profile='PROFILE', currency='USD', grand_total=100, paid_amount=30, consolidated_invoice='SI' if consolidated else None, creation='today', update_payments=Mock())
        profile = Row(name='PROFILE', company='CO', allow_partial_payment=1, payments=[Row(mode_of_payment='Cash')])
        entry = Row(name='PE', insert=Mock(), submit=Mock(), flags=Row(), payment_type='Receive', paid_from_account_currency='USD', paid_amount=20, received_amount=20, references=[Row(reference_doctype='Sales Invoice', reference_name='SI', allocated_amount=20)])
        docs = []
        def get_doc(kind, name=None):
            if isinstance(kind, dict):
                docs.append(kind)
                return Row(insert=Mock())
            return profile if kind == 'POS Profile' else invoice
        self.frappe.get_doc = Mock(side_effect=get_doc)
        self.frappe.db.exists.return_value = False
        self.frappe.db.get_value.side_effect = lambda dt, name, field: 'Cash' if dt == 'Mode of Payment' else 'USD' if dt == 'Account' else None
        api = types.SimpleNamespace(_as_admin=contextlib.nullcontext, _snapshot=lambda o: o)
        drawer = Mock()
        native = Mock(return_value=entry)
        with patch.dict(sys.modules, {
            'table_remote_till.api': api,
            'table_remote_till.exchange': types.SimpleNamespace(approved_lbp_rate=lambda _: 89500),
            'table_remote_till.shifts': types.SimpleNamespace(active_opening=lambda _: 'OPEN'),
            'table_remote_till.printer_api': types.SimpleNamespace(schedule_cash_drawer=drawer),
            'erpnext.accounts.doctype.payment_entry.payment_entry': types.SimpleNamespace(get_payment_entry=native),
            'erpnext.accounts.doctype.sales_invoice.sales_invoice': types.SimpleNamespace(get_bank_cash_account=lambda *args: {'account': 'CASH'}),
        }):
            result = self.module.receive(order, outlet, [dict(mode_of_payment='Cash', currency='USD', amount=20)], 'EVENT', 2)
        self.assertEqual(result.status, 'Partially Paid')
        self.assertEqual(result.revision, 3)
        drawer.assert_called_once_with(order, 'POS', [dict(mode_of_payment='Cash', currency='USD', amount=20)], payment_id='EVENT')
        attempt = next(doc for doc in docs if doc['doctype'] == 'TRT Payment Attempt')
        self.assertEqual(attempt['base_amount'], 20)
        self.assertEqual(attempt['pos_opening_entry'], 'OPEN')
        self.assertEqual(attempt['payment_entry'], 'PE' if consolidated else None)
        if consolidated:
            invoice.update_payments.assert_not_called()
            native.assert_called_once_with('Sales Invoice', 'SI', party_amount=20, bank_account='CASH', bank_amount=20)
            entry.submit.assert_called_once()
            self.assertIn('cashier cashier', entry.remarks)
        else:
            invoice.update_payments.assert_called_once_with([dict(mode_of_payment='Cash', amount=20)])
            native.assert_not_called()

    def test_same_shift_updates_original_invoice(self):
        self.receive()

    def test_later_shift_posts_native_payment_entry(self):
        self.receive(consolidated=True)
