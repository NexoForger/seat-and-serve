"""Verify payment commit ordering and duplicate suppression without moving hardware."""

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get


class DrawerTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.db = Mock()
        self.frappe.db.exists.return_value = False
        self.frappe.conf = {}
        self.frappe.utils = Mock()
        self.frappe.utils.now_datetime.return_value = "2026-10-22 12:00:00"
        self.frappe.log_error = Mock()
        self.frappe.get_traceback = Mock(return_value="printer unavailable")
        self.device = Row(name="PRINTER", title="Xprinter", driver="escpos_tcp", address="192.168.0.46:9100",
            settings_json='{"drawer_enabled":true}')
        self.receipt = types.ModuleType("table_remote_till.receipt")
        self.receipt.configured_printer = Mock(return_value=self.device)
        self.receipt.test_receipt = Mock()
        spec = importlib.util.spec_from_file_location("drawer_test_target",
            Path(__file__).resolve().parents[1] / "table_remote_till/printer_api.py")
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": self.frappe, "table_remote_till.receipt": self.receipt}):
            spec.loader.exec_module(self.module)
        self.module._send_drawer = Mock(return_value={"transport": "lan", "status": "Sent"})
        self.order = Row(name="ORDER", outlet="OUTLET", register="REGISTER")

    def test_cash_action_is_registered_after_commit_and_is_invoice_unique(self):
        inserted = Mock(name="inserted")
        inserted.name = "EVENT"
        self.frappe.get_doc = Mock(return_value=Mock(insert=Mock(return_value=inserted)))
        self.module.schedule_cash_drawer(self.order, "INV-1", [{"amount": 10}])
        data = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(data["status"], "Pending")
        self.assertEqual(data["event_type"], "cash_drawer")
        self.assertEqual(data["event_id"], self.module._event_id("INV-1"))
        self.frappe.db.after_commit.add.assert_called_once()
        self.module._send_drawer.assert_not_called()
        self.frappe.db.commit.assert_not_called()  # Payment retains its original transaction boundary.

    def test_tab_payments_have_distinct_keys_and_retries_do_not_repeat(self):
        inserted = Row(name="EVENT")
        self.frappe.get_doc = Mock(return_value=Mock(insert=Mock(return_value=inserted)))
        for payment in ('PAY-1', 'PAY-2'):
            self.module.schedule_cash_drawer(self.order, 'INV-1', [{'amount': 10}], payment_id=payment)
        keys = [call.args[0]['event_id'] for call in self.frappe.get_doc.call_args_list]
        self.assertEqual(keys, [self.module._event_id('INV-1:PAY-1'), self.module._event_id('INV-1:PAY-2')])
        self.frappe.db.exists.return_value = True
        self.module.schedule_cash_drawer(self.order, 'INV-1', [{'amount': 10}], payment_id='PAY-2')
        self.assertEqual(self.frappe.get_doc.call_count, 2)

    def test_no_cash_no_drawer_and_disabled_printers_do_not_schedule(self):
        self.module.schedule_cash_drawer(self.order, "INV-1", [])
        self.receipt.configured_printer.assert_not_called()
        self.device["settings_json"] = '{}'
        self.module.schedule_cash_drawer(self.order, "INV-1", [{"amount": 10}])
        self.frappe.db.after_commit.add.assert_not_called()

    def test_duplicate_invoice_does_not_register_another_callback(self):
        self.frappe.db.exists.return_value = True
        self.module.schedule_cash_drawer(self.order, "INV-1", [{"amount": 10}])
        self.frappe.db.after_commit.add.assert_not_called()

    def test_remote_agent_cash_pulse_is_only_enqueued_in_payment_transaction(self):
        self.device['settings_json']='{"drawer_enabled":true,"print_agent":"register-1"}'
        jobs=types.ModuleType('table_remote_till.print_jobs')
        jobs.enqueue=Mock()
        with patch.dict(sys.modules, {'table_remote_till.print_jobs':jobs}):
            self.module.schedule_cash_drawer(self.order,'INV-1',[{'amount':10}])
        self.assertEqual(jobs.enqueue.call_args.args[2],'Cash Drawer')
        self.assertEqual(jobs.enqueue.call_args.kwargs['job_key'],self.module._event_id('INV-1'))
        self.frappe.db.commit.assert_not_called()
        self.frappe.db.after_commit.add.assert_not_called()
        self.module._send_drawer.assert_not_called()

    def test_device_hardware_test_requires_write_and_outlet_manager_access(self):
        api=types.ModuleType('table_remote_till.api')
        api._staff_outlet=Mock(side_effect=PermissionError)
        doc=Mock(outlet='OUTLET',kind='Receipt Printer',enabled=1)
        self.frappe.get_doc=Mock(return_value=doc)
        with patch.dict(sys.modules, {'table_remote_till.api':api}):
            with self.assertRaises(PermissionError): self.module._manager_device('PRINTER')
        doc.check_permission.assert_called_once_with('write')
        api._staff_outlet.assert_called_once_with('OUTLET','allow_manager')

    def test_dispatch_claim_is_durable_before_the_pulse(self):
        self.frappe.get_doc = Mock(return_value=Row(event_type="cash_drawer", status="Pending",
            payload_json=json.dumps({"device": dict(self.device), "invoice": "INV-1"})))
        def send(device):
            self.frappe.db.commit.assert_called_once()
            self.assertEqual(self.frappe.db.set_value.call_args.args[2]["status"], "Conflict")
            return {"status": "Sent"}
        self.module._send_drawer.side_effect = send
        self.module._dispatch_drawer("EVENT")
        self.assertEqual(self.frappe.db.set_value.call_args.args[2]["status"], "Applied")
        self.assertEqual(self.frappe.db.commit.call_count, 2)

    def test_unknown_or_sent_action_is_never_repeated(self):
        for status in ("Conflict", "Applied"):
            self.frappe.get_doc = Mock(return_value=Row(event_type="cash_drawer", status=status))
            self.module._dispatch_drawer("EVENT")
        self.module._send_drawer.assert_not_called()

    def test_printer_failure_after_commit_does_not_fail_checkout_or_retry(self):
        self.frappe.get_doc = Mock(return_value=Row(event_type="cash_drawer", status="Pending",
            payload_json=json.dumps({"device": dict(self.device), "invoice": "INV-1"})))
        self.module._send_drawer.side_effect = OSError("offline")
        self.module._dispatch_drawer("EVENT")
        self.module._send_drawer.assert_called_once()
        self.frappe.log_error.assert_called_once()
        self.assertEqual(self.frappe.db.set_value.call_args.args[2]["status"], "Conflict")
