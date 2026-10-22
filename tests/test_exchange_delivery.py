"""Outlet FX display snapshots, receipt totals, and delivery validation."""
import ast
import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class Row(dict):
    def __getattr__(self, name):
        return self.get(name)


class ExchangeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.get_all = Mock()
        self.frappe.db = Mock()
        def reject(message, *args):
            raise ValueError(message)
        self.frappe.throw = reject
        utils = types.ModuleType('frappe.utils')
        utils.flt = lambda v: float(v or 0)
        utils.today = lambda: '2026-10-22'
        utils.strip_html = lambda v:v
        self.modules = patch.dict(sys.modules, {'frappe':self.frappe, 'frappe.utils':utils})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.exchange = self.load('exchange')
        self.receipt = self.load('receipt')

    def load(self, name):
        spec = importlib.util.spec_from_file_location(name+'_test_target', ROOT/'table_remote_till'/f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_only_valid_approved_outlet_rate_is_used(self):
        row = Row(lbp_per_usd=89500, approved_by='manager', approved_on='2026-10-22')
        self.frappe.get_all.return_value = [row]
        self.assertEqual(self.exchange.approved_lbp_rate('OUT'),89500)
        self.assertEqual(self.frappe.get_all.call_args.kwargs['filters']['outlet'],'OUT')
        for rate in (0,-1,float('nan'),float('inf')):
            row['lbp_per_usd']=rate
            self.assertIsNone(self.exchange.approved_lbp_rate('OUT'))
        row['lbp_per_usd']=89500
        row['approved_by']=None
        self.assertIsNone(self.exchange.approved_lbp_rate('OUT'))

    def receipt_rows(self, rate=89500, currency='USD'):
        invoice=types.SimpleNamespace(currency=currency,name='INV',posting_date='2026-10-22',posting_time='12:00',customer_name=None,remarks='',owner='cashier',items=[],total=10,discount_amount=0,total_taxes_and_charges=0,taxes=[],rounded_total=0,grand_total=10,payments=[])
        order=types.SimpleNamespace(order_number='1',table=None,lbp_per_usd=rate,exchange_rate=1,channel='Delivery',delivery_name='Recipient',delivery_phone='+961 1 234567',delivery_address='Street, building, floor')
        company=types.SimpleNamespace(company_name='Shop',name='Shop',tax_id=None)
        return self.receipt._receipt_rows(invoice,order,types.SimpleNamespace(title='Outlet'),company)

    def test_receipt_places_lbp_and_original_rate_after_usd_total(self):
        rows=self.receipt_rows()
        total=next(i for i,row in enumerate(rows) if row[0]=='pair' and row[1][0]=='TOTAL')
        self.assertEqual(rows[total+1],('pair',('TOTAL (LBP)','895,000 LBP'),'body'))
        self.assertIn('Exchange rate: 1 USD = 89,500 LBP', rows[total+2][1])
        self.frappe.get_all.assert_not_called()  # Reprints never read today's rate.
        self.assertTrue(any('Street, building, floor' in str(row) for row in rows))
        self.assertTrue(any('Recipient' in str(row) for row in rows))

    def test_missing_historical_rate_is_not_fabricated(self):
        rows=self.receipt_rows(rate=0)
        self.assertIn(('pair',('TOTAL (LBP)','Unavailable'),'small'),rows)
        self.assertFalse(any(row[0]=='pair' and row[1][0]=='TOTAL (LBP)' for row in self.receipt_rows(currency='LBP')))

    def test_delivery_contact_and_address_are_required_and_bounded(self):
        tree=ast.parse((ROOT/'table_remote_till/api.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_delivery_details')
        namespace=dict(frappe=self.frappe,re=re)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'api.py','exec'),namespace)
        validate=namespace['_delivery_details']
        payload=dict(delivery_name=' Name ',delivery_phone=' +961123456 ',delivery_address=' Street\nFloor 2 ')
        self.assertEqual(validate(payload)['delivery_name'],'Name')
        for field in payload:
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate({**payload,field:''})
        with self.assertRaises(ValueError):
            validate({**payload,'delivery_address':'x'*501})
