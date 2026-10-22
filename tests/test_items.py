"""Standalone tests for quick item creation's validation and retry contracts."""
import contextlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import types
import unittest
import uuid
from unittest.mock import Mock, patch

from test_shifts import Row, reject


class ItemTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.throw = reject
        self.frappe.db = Mock()
        self.frappe.UniqueValidationError = type('UniqueValidationError', (Exception,), {})
        self.frappe.DuplicateEntryError = type('DuplicateEntryError', (Exception,), {})
        self.frappe.ValidationError = ValueError
        self.frappe.clear_messages = Mock()
        self.frappe.parse_json = json.loads
        self.frappe.get_doc = Mock()
        utils = types.ModuleType('frappe.utils')
        utils.now_datetime = lambda: '2026-10-10 10:00:00'
        utils.today = lambda: '2026-10-10'
        api = types.ModuleType('table_remote_till.api')
        api._as_admin = contextlib.nullcontext
        api._outlet = Mock(return_value=Row(name='OUTLET-A', company='Company', price_list='Selling', base_currency='USD'))
        api._payload = lambda value: value
        api._staff = Mock()
        api._staff_outlet = Mock()
        spec = importlib.util.spec_from_file_location('items_test_target',
            Path(__file__).resolve().parents[1] / 'table_remote_till/items.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': self.frappe, 'frappe.utils': utils,
                                      'table_remote_till.api': api}):
            spec.loader.exec_module(self.module)
        self.details = {'name': 'Sandwich', 'price': 8, 'group': 'Food', 'uom': 'Nos',
                        'station': '', 'menu': 'MENU-A', 'ingredients': [{'item': 'RAW', 'qty': .2}]}
        self.request = str(uuid.uuid4())
        self.raw = Row(stock_uom='Kg', disabled=0, has_variants=0, is_stock_item=1,
                       is_purchase_item=1, is_sales_item=0, include_item_in_manufacturing=1)

    def test_manager_and_outlet_authorization(self):
        self.module._manager('OUTLET-A')
        self.module._staff.assert_called_once_with({'System Manager', 'TRT Manager'})
        self.module._staff_outlet.assert_called_once_with('OUTLET-A', ability='allow_manager')
        self.module._staff.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.module.create_item('OUTLET-A', self.details, self.request)
        self.frappe.db.sql.assert_not_called()

    def test_reject_invalid_prices_and_quantities(self):
        self.assertEqual(self.module._number(0, 'price'), 0)
        for value in ('', None, True, -1, math.nan, math.inf, 'no'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module._number(value, 'price')
        with self.assertRaises(ValueError):
            self.module._number(0, 'quantity', positive=True)

    def test_recipe_requires_raw_material_and_stock_uom(self):
        self.frappe.db.get_value.side_effect = lambda doctype, *args, **kwargs: self.raw if doctype == 'Item' else 0
        self.assertEqual(self.module._recipe(self.details['ingredients']),
                         [{'item_code': 'RAW', 'qty': .2, 'uom': 'Kg'}])
        self.raw.is_sales_item = 1
        with self.assertRaises(ValueError):
            self.module._recipe(self.details['ingredients'])

    def test_empty_duplicate_and_fractional_whole_units_rejected(self):
        self.frappe.db.get_value.side_effect = lambda doctype, *args, **kwargs: self.raw if doctype == 'Item' else 1
        self.assertIsNone(self.module._recipe([]))
        for rows in ( [{'item': 'RAW', 'qty': .2}], [{'item': 'RAW', 'qty': 1}] * 2):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.module._recipe(rows)

    def test_cross_outlet_menu_rejected_before_creating_anything(self):
        self.frappe.db.get_value.return_value = None
        self.frappe.db.exists.side_effect = lambda doctype, filters: doctype != 'TRT Menu'
        with self.assertRaises(ValueError):
            self.module.create_item('OUTLET-A', self.details, self.request)
        self.frappe.get_doc.assert_not_called()

    def test_retry_returns_saved_item_and_rejects_changed_payload(self):
        self.details['barcode'] = '0001'
        fingerprint = self.module.hashlib.sha256(json.dumps(self.details, sort_keys=True).encode()).hexdigest()
        result = {'item': 'ITEM-1', 'menu': 'MENU-A', 'name': 'Sandwich'}
        self.frappe.db.get_value.return_value = Row(outlet='OUTLET-A', event_type='create_item',
            payload_json=json.dumps({'fingerprint': fingerprint, 'result': result}))
        self.assertEqual(self.module.create_item('OUTLET-A', self.details, self.request), result)
        self.frappe.get_doc.assert_not_called()
        with self.assertRaises(ValueError):
            self.module.create_item('OUTLET-A', {**self.details, 'price': 9}, self.request)

    def test_create_links_submitted_recipe_price_and_menu(self):
        self.frappe.db.exists.side_effect = lambda doctype, *a, **k: doctype != 'Item Barcode'
        self.details['barcode'] = ' 00Ab123 '
        self.frappe.db.get_value.side_effect = lambda doctype, *args, **kwargs: self.raw if doctype == 'Item' else None
        docs = {}
        payloads = {}
        def document(data, name=None):
            doctype = data if isinstance(data, str) else data['doctype']
            doc = Mock()
            doc.name = {'Item': 'ITEM-1', 'TRT Menu': 'MENU-A'}.get(doctype, doctype + '-1')
            docs[doctype] = doc
            payloads[doctype] = data
            return doc
        self.frappe.get_doc.side_effect = document
        result = self.module.create_item('OUTLET-A', self.details, self.request)
        self.assertEqual(result['item'], 'ITEM-1')
        self.assertEqual(payloads['BOM']['items'], [{'item_code': 'RAW', 'qty': .2, 'uom': 'Kg'}])
        docs['Item'].append.assert_called_once_with('barcodes', {'barcode': '00Ab123', 'uom': 'Nos'})
        docs['BOM'].submit.assert_called_once()
        self.assertEqual(payloads['Item Price']['price_list_rate'], 8)
        self.assertEqual(payloads['Item Price']['valid_from'], '2026-10-10')
        self.assertEqual(docs['TRT Menu'].append.call_args.args[1]['item'], 'ITEM-1')
        self.assertEqual(payloads['TRT Sync Event']['event_id'], self.request)

    def test_barcode_normalization(self):
        for value in (None, '', '  '):
            self.assertEqual(self.module._barcode(value), '')
        self.assertEqual(self.module._barcode(' 00Ab '), '00Ab')
        for value in (123, 'a\nb', 'x' * 141, 'a\x7fb'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module._barcode(value)

    def test_duplicate_does_not_create_item(self):
        self.frappe.db.exists.return_value = True
        self.frappe.db.get_value.return_value = None
        self.details.update(barcode='00123', ingredients=[])
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            self.module.create_item('OUTLET-A', self.details, self.request)
        self.frappe.get_doc.assert_not_called()

    def test_duplicate_race_is_sanitized(self):
        self.frappe.db.exists.side_effect = lambda doctype, *a, **k: doctype != 'Item Barcode'
        self.frappe.db.get_value.return_value = None
        self.details.update(barcode='00123', ingredients=[])
        self.frappe.get_doc.return_value.insert.side_effect = self.frappe.UniqueValidationError('private item')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.module.create_item('OUTLET-A', self.details, self.request)
        self.frappe.clear_messages.assert_called_once()
        self.assertEqual(self.frappe.get_doc.call_count, 1)

    def test_availability_hides_other_outlet_item(self):
        self.frappe.db.get_value.return_value = 'PRIVATE-ITEM'
        self.frappe.get_all = Mock(return_value=[])
        self.assertEqual(self.module.barcode_available('OUTLET-A', '00123'), {'available': False})
        self.frappe.get_all.return_value = ['MENU-A']
        self.frappe.db.exists.return_value = True
        self.assertEqual(self.module.barcode_available('OUTLET-A', '00123')['item_name'], 'PRIVATE-ITEM')

    def test_barcode_availability_allows_original_committed_retry_only(self):
        event = Row(outlet='OUTLET-A', event_type='create_item', payload_json=json.dumps({'result': {'item': 'ITEM-1'}}))
        self.frappe.db.get_value.side_effect = lambda doctype, *a, **k: event if doctype == 'TRT Sync Event' else 'ITEM-1'
        self.assertEqual(self.module.barcode_available('OUTLET-A', '001', self.request), {'available': True})
        event.outlet = 'OUTLET-B'
        self.frappe.get_all = Mock(return_value=[])
        self.assertEqual(self.module.barcode_available('OUTLET-A', '001', self.request), {'available': False})

    def test_item_without_barcode_or_recipe_remains_supported(self):
        self.details.update(barcode='', ingredients=[])
        self.frappe.db.exists.return_value = True
        self.frappe.db.get_value.return_value = None
        docs = []
        def document(*args):
            doc = Mock(name='document')
            doc.name = 'CREATED'
            docs.append((args, doc))
            return doc
        self.frappe.get_doc.side_effect = document
        self.module.create_item('OUTLET-A', self.details, self.request)
        docs[0][1].append.assert_not_called()
        self.assertNotIn('BOM', [args[0].get('doctype') for args, _ in docs if isinstance(args[0], dict)])
