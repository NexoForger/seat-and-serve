"""Regressions for rollback deleting a closing while its invoices consolidate."""

import contextlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class ClosingTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.db = Mock()
        self.frappe.db.get_value.return_value = None
        self.frappe.db.exists.return_value = True
        self.frappe.enqueue = Mock()
        self.frappe.publish_realtime = Mock()
        self.frappe.log_error = Mock()
        self.frappe.get_traceback = Mock(return_value='Original consolidation traceback')
        utils = types.ModuleType('frappe.utils')
        utils.strip_html = lambda value: value
        spec = importlib.util.spec_from_file_location('closing_test_target',
            Path(__file__).resolve().parents[1] / 'table_remote_till/pos_closing.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe':self.frappe,'frappe.utils':utils}):
            spec.loader.exec_module(self.module)
        module = self.module
        class Base:
            def on_submit(self):
                self.native_called = True
                raise RuntimeError('Native synchronous consolidation must not run before commit')
        class Closing(module.DeferredTRTClosing, Base):
            name = 'POS-CLO-2026-00001'
            pos_profile = 'PROFILE'
            company = 'COMPANY'
            pos_opening_entry = 'OPEN-1'
            docstatus = 1
            status = 'Queued'
            pos_invoices = []
            native_called = False
            def get(self, field): return 'POS Invoice' if field == 'invoice_type' else getattr(self,field,None)
        self.closing = Closing()
        self.closing.set_status = Mock()
        self.closing.db_set = Mock()
        self.closing.update_sales_invoices_closing_entry = Mock()
        self.frappe.get_doc = Mock(return_value=self.closing)
        self.core = types.ModuleType('erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log')
        self.core.get_invoice_customer_map = Mock(return_value={'Customer':{}})
        self.core.create_merge_logs = Mock()
        api = types.ModuleType('table_remote_till.api')
        api._as_admin = contextlib.nullcontext
        self.dependencies = patch.dict(sys.modules, {self.core.__name__:self.core,'table_remote_till.api':api})
        self.dependencies.start()

    def tearDown(self): self.dependencies.stop()

    def test_submit_saves_queued_and_defers_processing_until_after_commit(self):
        self.closing.on_submit()
        self.assertFalse(self.closing.native_called)
        self.closing.set_status.assert_called_once_with(update=True,status='Queued')
        args = self.frappe.enqueue.call_args.kwargs
        self.assertTrue(args['enqueue_after_commit'])
        self.assertEqual(args['closing_name'],self.closing.name)
        self.assertEqual(args['queue'],'long')
        self.core.create_merge_logs.assert_not_called()
        self.frappe.db.commit.assert_not_called()

    def test_non_trt_profiles_keep_native_behavior(self):
        self.frappe.db.exists.return_value = False
        with self.assertRaisesRegex(RuntimeError,'Native synchronous'):
            self.closing.on_submit()
        self.frappe.enqueue.assert_not_called()

    def test_worker_uses_native_accounting_once_with_durable_parent(self):
        self.module.process_closing(self.closing.name)
        self.core.create_merge_logs.assert_called_once_with({'Customer':{}},self.closing)
        self.closing.update_sales_invoices_closing_entry.assert_called_once()
        self.assertTrue(self.frappe.publish_realtime.call_args.kwargs['after_commit'])

    def test_merge_failure_keeps_original_error_and_existing_closing_reference(self):
        self.core.create_merge_logs.side_effect = RuntimeError('Valuation rate not found for ITEM')
        with self.assertRaisesRegex(RuntimeError,'Valuation rate not found'):
            self.module.process_closing(self.closing.name)
        self.frappe.db.set_value.assert_called_once_with('POS Closing Entry',self.closing.name,
            {'status':'Failed','error_message':'Valuation rate not found for ITEM'})
        self.frappe.db.commit.assert_called_once()
        self.assertEqual(self.frappe.log_error.call_args.kwargs['reference_name'],self.closing.name)

    def test_completed_closing_is_not_reprocessed_or_relabelled_failed(self):
        self.closing.status='Submitted'
        self.module.process_closing(self.closing.name)
        self.core.create_merge_logs.assert_not_called()
        self.closing.status='Queued'
        self.core.create_merge_logs.side_effect=RuntimeError('Realtime notification failed after accounting committed')
        self.frappe.db.get_value.return_value='Submitted'
        self.module.process_closing(self.closing.name)
        self.frappe.db.set_value.assert_not_called()
