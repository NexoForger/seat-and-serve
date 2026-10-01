from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from table_remote_till.table_remote_till.doctype.trt_menu.trt_menu import TRTMenu


class TestTRTMenu(TestCase):
	def setUp(self):
		self.menu = SimpleNamespace(outlet="Outlet", items=[SimpleNamespace(item="DRINK")])
		self.frappe_patch = patch("table_remote_till.table_remote_till.doctype.trt_menu.trt_menu.frappe")
		self.mock_frappe = self.frappe_patch.start()
		self.addCleanup(self.frappe_patch.stop)
		self.mock_frappe.db.get_value.side_effect = self._item_value
		self.mock_frappe.get_all.return_value = []
		self.mock_frappe.db.exists.return_value = False
		self.mock_frappe.throw.side_effect = frappe.ValidationError

	def _item_value(self, doctype, name, fields, as_dict=False):
		if doctype == "TRT Outlet":
			return "Company"
		if fields == "item_name":
			return "Drink"
		return SimpleNamespace(is_stock_item=1, is_purchase_item=1, is_sales_item=1)

	def test_purchased_stock_item_without_bom_is_allowed(self):
		TRTMenu.validate(self.menu)

	def test_manufactured_item_without_bom_is_rejected(self):
		self.mock_frappe.db.get_value.side_effect = lambda doctype, name, fields, as_dict=False: (
			SimpleNamespace(is_stock_item=0, is_purchase_item=0, is_sales_item=1)
			if isinstance(fields, list) else self._item_value(doctype, name, fields, as_dict)
		)

		with self.assertRaises(frappe.ValidationError):
			TRTMenu.validate(self.menu)
		self.mock_frappe.db.exists.assert_not_called()

	def test_existing_unapproved_bom_is_rejected(self):
		self.mock_frappe.db.exists.return_value = True

		with self.assertRaises(frappe.ValidationError):
			TRTMenu.validate(self.menu)
