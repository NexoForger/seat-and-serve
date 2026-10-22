"""Hardware transport tests use loopback sockets and a fake USB spooler."""

import json
import socket
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from table_remote_till import printing


def device(**values):
    return SimpleNamespace(
        **{"driver": "escpos_tcp", "address": "192.168.0.46:9100", "settings_json": "{}", **values})


class PrintingTests(unittest.TestCase):
    def test_targets_and_drawer_settings(self):
        self.assertEqual(printing.target(device()), ("escpos_tcp", ("192.168.0.46", 9100)))
        self.assertEqual(printing.target(device(driver="escpos_usb", address="Xprinter_USB")), ("escpos_usb", "Xprinter_USB"))
        for bad in ("hostname:9100", "192.168.0.46:0", "192.168.0.46:65536"):
            with self.assertRaises(printing.PrintError):
                printing.target(device(address=bad))
        for bad in ("", "-bad", "queue;touch /tmp/x", "../file"):
            with self.assertRaises(printing.PrintError):
                printing.target(device(driver="escpos_usb", address=bad))
        self.assertFalse(printing.settings(device())["drawer_enabled"])
        for bad in ('[]', '{', '{"drawer_enabled":"false"}', '{"drawer_pin":2}', '{"drawer_pulse_ms":101}'):
            with self.assertRaises(printing.PrintError):
                printing.settings(device(settings_json=bad))

    def test_drawer_is_a_separate_five_byte_command(self):
        for pin in (0, 1):
            config = json.dumps({"drawer_enabled": True, "drawer_pin": pin, "drawer_pulse_ms": 100})
            self.assertEqual(printing.drawer_bytes(device(settings_json=config)), bytes((27, 112, pin, 50, 250)))
        with self.assertRaises(printing.PrintError):
            printing.drawer_bytes(device())

    def test_lan_sends_exact_bytes(self):
        received = []
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(3)
            def receive():
                with listener.accept()[0] as connection:
                    connection.settimeout(3)
                    while chunk := connection.recv(1024):
                        received.append(chunk)
            worker = threading.Thread(target=receive)
            worker.start()
            payload = b"\x1b@TEST PAGE\n\n\x1dV\x00"
            result = printing.send(device(address=f"127.0.0.1:{listener.getsockname()[1]}"), payload)
            worker.join(4)
        self.assertEqual(result["status"], "Sent")
        self.assertEqual(b"".join(received), payload)

    def test_usb_sends_raw_bytes_and_reports_queue_acceptance(self):
        payload = b"\x1bp\x00\x32\xfa"
        with patch.object(printing.subprocess, "run", return_value=SimpleNamespace(stdout=b"request id is Xprinter_USB-1\n")) as run:
            result = printing.send(device(driver="escpos_usb", address="Xprinter_USB"), payload)
        self.assertEqual(result["status"], "Queued")
        self.assertEqual(run.call_args.args[0], ["lp", "-d", "Xprinter_USB", "-o", "raw", "-t", "S&S receipt / drawer", "-"])
        self.assertEqual(run.call_args.kwargs["input"], payload)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_usb_timeout_is_not_retried(self):
        with patch.object(printing.subprocess, "run", side_effect=subprocess.TimeoutExpired("lp", 10)) as run:
            with self.assertRaisesRegex(printing.PrintError, "result unknown"):
                printing.send(device(driver="escpos_usb", address="Xprinter_USB"), b"bytes")
        self.assertEqual(run.call_count, 1)

