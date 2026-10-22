import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image


class ReceiptTransportTests(unittest.TestCase):
    def setUp(self):
        frappe=ModuleType('frappe')
        utils=ModuleType('frappe.utils')
        utils.flt=lambda value:float(value or 0)
        utils.strip_html=lambda value:value
        spec=importlib.util.spec_from_file_location('receipt_test_target',Path(__file__).resolve().parents[1]/'table_remote_till/receipt.py')
        self.module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'frappe':frappe,'frappe.utils':utils}): spec.loader.exec_module(self.module)
        self.device=SimpleNamespace(driver='escpos_tcp',address='192.168.0.46:9100',settings_json='{"drawer_enabled":true}')
        self.module.send=Mock(return_value={'status':'Sent'})
        self.image=Image.new('1',(8,8),1)

    def test_receipt_does_not_append_drawer_pulse_even_when_drawer_enabled(self):
        self.module._send(self.device,self.image,kind='Receipt',order='ORDER',invoice='INV')
        payload=self.module.send.call_args.args[1]
        self.assertEqual(payload,self.module.escpos_bytes(self.image))
        self.assertFalse(payload.endswith(bytes((27,112,0,50,250))))

    def test_remote_receipt_only_enqueues_and_does_not_open_a_server_socket(self):
        self.device.settings_json='{"drawer_enabled":true,"print_agent":"register-1"}'
        jobs=ModuleType('table_remote_till.print_jobs')
        jobs.enqueue=Mock(return_value={'status':'Pending'})
        with patch.dict(sys.modules,{'table_remote_till.print_jobs':jobs}):
            result=self.module._send(self.device,self.image,kind='Receipt',order='ORDER',invoice='INV')
        self.assertEqual(result['status'],'Pending')
        self.assertEqual(jobs.enqueue.call_args.args[2],'Receipt')
        self.module.send.assert_not_called()
