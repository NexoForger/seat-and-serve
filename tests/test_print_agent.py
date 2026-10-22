"""Remote printer agent contracts; no ERP server or physical printer needed."""

import base64
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock


class AgentTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('agent_test_target', Path(__file__).resolve().parents[1] / 'tools/print_agent.py')
        self.agent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.agent)
        self.temp = tempfile.TemporaryDirectory()
        self.db = self.agent.open_journal(Path(self.temp.name) / 'agent.sqlite')
        self.agent.send = Mock(return_value={'status': 'Queued'})
        self.job = dict(name='JOB1', claim_token='claim1', kind='Cash Drawer', expires_unix=time.time()+30,
            target={'driver':'escpos_usb', 'address':'Xprinter_USB'}, payload=base64.b64encode(b'\x1bp\x00\x32\xfa').decode())

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def run_cycle(self, call):
        return self.agent.run_once(call, self.db, 'OUTLET', 'register-1', {'Xprinter_USB'}, set())

    def test_prints_once_and_retries_only_the_acknowledgement_after_network_failure(self):
        failed = False
        claimed = False
        def call(method, args):
            nonlocal failed, claimed
            if method == 'claim':
                if claimed: return []
                claimed = True
                return [self.job]
            if not failed:
                failed = True
                raise OSError('acknowledgement connection lost')
            self.assertEqual(args['status'], 'Queued')
            return {'status':'Queued'}
        with self.assertRaises(OSError): self.run_cycle(call)
        self.run_cycle(call)
        self.agent.send.assert_called_once()
        self.assertEqual(self.db.execute('SELECT acknowledged FROM jobs').fetchone()[0], 1)

    def test_crash_during_dispatch_becomes_unknown_without_repeating_hardware(self):
        self.db.execute("INSERT INTO jobs(name,claim_token,status) VALUES ('JOB1','claim1','Dispatching')")
        self.db.commit()
        calls = []
        def call(method, args):
            calls.append((method,args))
            return [] if method == 'claim' else {'status':args['status']}
        self.run_cycle(call)
        self.assertEqual(calls[0][1]['status'], 'Unknown')
        self.agent.send.assert_not_called()

    def test_expired_drawer_and_unapproved_queue_never_send(self):
        for target, expires in ((self.job['target'], time.time()-1), ({'driver':'escpos_usb','address':'Other'},0)):
            self.job['name'] += 'x'
            self.job['target'], self.job['expires_unix'] = target, expires
            acknowledgements = []
            def call(method, args):
                if method == 'claim': return [self.job]
                acknowledgements.append(args)
                return {'status':args['status']}
            self.run_cycle(call)
            self.assertEqual(acknowledgements[-1]['status'], 'Unknown')
        self.agent.send.assert_not_called()

    def test_erp_requires_https_and_a_service_token(self):
        with self.assertRaises(ValueError): self.agent.remote('http://erp.example.com','key:secret')
        with self.assertRaises(ValueError): self.agent.remote('https://erp.example.com','')
