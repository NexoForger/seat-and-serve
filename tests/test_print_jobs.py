import importlib.util
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get
    def reload(self): pass


def reject(message, *args): raise ValueError(message)


class PrintJobTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.db = Mock()
        self.frappe.db.get_value.return_value = None
        self.frappe.conf = {'trt_print_agents':{'register-1':'agent@example.com'}}
        self.frappe.session = Row(user='agent@example.com')
        self.frappe.utils = Mock()
        self.frappe.throw = reject
        self.frappe.PermissionError = PermissionError
        self.api = types.ModuleType('table_remote_till.api')
        self.api._staff_outlet = Mock()
        spec = importlib.util.spec_from_file_location('jobs_test_target', Path(__file__).resolve().parents[1] / 'table_remote_till/print_jobs.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe':self.frappe}): spec.loader.exec_module(self.module)
        self.deps = patch.dict(sys.modules, {'table_remote_till.api':self.api})
        self.deps.start()

    def tearDown(self): self.deps.stop()

    def test_agent_access_requires_outlet_assignment_and_bound_identity(self):
        self.module._agent_access('OUTLET','register-1')
        self.api._staff_outlet.assert_called_once_with('OUTLET')
        with self.assertRaises(ValueError): self.module._agent_access('OUTLET','other-agent')

    def test_cash_job_is_invoice_unique_and_is_not_dispatched_before_commit(self):
        self.frappe.get_doc = Mock(return_value=Mock(insert=Mock(return_value=Row(name='JOB'))))
        device = Row(name='PRINTER', outlet='OUTLET', register='REGISTER', driver='escpos_usb', address='Xprinter_USB',
            settings_json='{"print_agent":"register-1"}')
        self.module.enqueue(device, b'bytes', 'Cash Drawer', invoice='INV', job_key='drawer:INV')
        data = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(data['status'],'Pending')
        self.assertEqual(data['job_key'],'drawer:INV')
        self.assertGreater(data['expires_unix'],time.time())
        self.frappe.db.commit.assert_not_called()
        self.frappe.db.get_value.return_value=Row(name='JOB',status='Claimed')
        self.frappe.get_doc.reset_mock()
        self.module.enqueue(device,b'bytes','Cash Drawer',invoice='INV',job_key='drawer:INV')
        self.frappe.get_doc.assert_not_called()

    def test_claim_expires_offline_drawer_jobs_and_reserves_valid_jobs(self):
        self.frappe.db.sql.return_value=[Row(name='EXPIRED'),Row(name='VALID')]
        self.frappe.get_doc=Mock(side_effect=[
            Row(name='EXPIRED',expires_unix=time.time()-10),
            Row(name='VALID',expires_unix=0,kind='Receipt',payload_base64='Ynl0ZXM=',target_json='{}')])
        result=self.module.claim('OUTLET','register-1')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['name'],'VALID')
        self.assertIn('FOR UPDATE SKIP LOCKED',self.frappe.db.sql.call_args.args[0])
        self.assertEqual(self.frappe.db.set_value.call_args_list[0].args[2]['status'],'Unknown')
        self.assertEqual(self.frappe.db.set_value.call_args_list[1].args[2]['status'],'Claimed')

    def test_acknowledgement_is_bound_to_claim_and_is_idempotent(self):
        job=Row(name='JOB',outlet='OUTLET',agent='register-1',claim_token='secret',claimed_by='agent@example.com',status='Claimed')
        self.frappe.get_doc=Mock(return_value=job)
        with self.assertRaises(ValueError): self.module.acknowledge('JOB','wrong','Sent')
        self.frappe.db.set_value.assert_not_called()
        self.module.acknowledge('JOB','secret','Sent')
        job['status']='Sent'
        self.frappe.db.set_value.reset_mock()
        self.assertEqual(self.module.acknowledge('JOB','secret','Sent'),{'status':'Sent'})
        self.frappe.db.set_value.assert_not_called()
