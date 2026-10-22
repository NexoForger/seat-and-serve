"""ESC/POS transports shared by receipt printing and independent drawer pulses."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import sys


class PrintError(Exception):
	pass


def settings(device):
	try:
		value = json.loads(device.settings_json or "{}")
	except (ValueError, TypeError) as error:
		raise PrintError("Printer Settings JSON must be a JSON object") from error
	if not isinstance(value, dict):
		raise PrintError("Printer Settings JSON must be a JSON object")
	if value.get("print_agent") and (not isinstance(value["print_agent"], str)
		or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value["print_agent"])):
		raise PrintError("Print agent must contain 1 to 64 letters, numbers, dashes or underscores")
	for key in ("auto_cut", "drawer_enabled"):
		if key in value and type(value[key]) is not bool:
			raise PrintError(f"{key} must be true or false")
	pin = value.get("drawer_pin", 0)
	pulse = value.get("drawer_pulse_ms", 100)
	if type(pin) is not int or pin not in (0, 1):
		raise PrintError("Drawer output must be 0 (pin 2) or 1 (pin 5)")
	if type(pulse) is not int or not 20 <= pulse <= 250 or pulse % 2:
		raise PrintError("Drawer pulse must be an even number from 20 to 250 ms")
	return {**value, "auto_cut": value.get("auto_cut", True),
		"drawer_enabled": value.get("drawer_enabled", False), "drawer_pin": pin,
		"drawer_pulse_ms": pulse}


def target(device):
	driver = (device.driver or "escpos_tcp").lower()
	address = (device.address or "").strip()
	if driver == "escpos_usb":
		if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,126}", address):
			raise PrintError("USB Address must be a local printer queue name, such as Xprinter_USB")
		return driver, address
	if driver != "escpos_tcp":
		raise PrintError("Receipt printer driver must be escpos_tcp (LAN) or escpos_usb (USB)")
	host, separator, port_text = address.partition(":")
	try:
		ipaddress.IPv4Address(host)
		port = int(port_text) if separator else 9100
		if not 1 <= port <= 65535:
			raise ValueError("port")
	except ValueError as error:
		raise PrintError("LAN Address must be an IPv4 address, optionally followed by :port") from error
	return driver, (host, port)


def drawer_bytes(device):
	config = settings(device)
	if not config["drawer_enabled"]:
		raise PrintError("Enable the printer's cash drawer before testing it")
	# ESC p: connector output 0/1; ON/OFF durations use units of 2 ms.
	return bytes((0x1B, 0x70, config["drawer_pin"], config["drawer_pulse_ms"] // 2, 250))


def submit_usb(queue, payload):
	if sys.platform == "win32":
		return _submit_windows(queue, payload)
	try:
		result = subprocess.run(["lp", "-d", queue, "-o", "raw", "-t", "S&S receipt / drawer", "-"],
			input=payload, capture_output=True, timeout=10, check=True)
	except FileNotFoundError as error:
		raise PrintError("CUPS lp is missing. Install CUPS on the printer's Mac or Linux/Pi host.") from error
	except subprocess.TimeoutExpired as error:
		raise PrintError("USB submission timed out; result unknown. Check the queue before sending again.") from error
	except subprocess.CalledProcessError as error:
		raise PrintError(f"USB queue rejected the job: {error.stderr.decode(errors='replace')[:500]}") from error
	return {"transport": "usb", "status": "Queued", "job": result.stdout.decode(errors="replace").strip()}


def _submit_windows(queue, payload):
	"""Send RAW ESC/POS to a Windows-installed USB printer queue."""
	import ctypes
	from ctypes import wintypes
	class DocInfo(ctypes.Structure):
		_fields_ = [("name", wintypes.LPWSTR), ("output", wintypes.LPWSTR), ("datatype", wintypes.LPWSTR)]
	spool = ctypes.WinDLL("winspool.drv", use_last_error=True)
	spool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID]
	spool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DocInfo)]
	spool.StartDocPrinterW.restype = wintypes.DWORD
	spool.StartPagePrinter.argtypes = [wintypes.HANDLE]
	spool.WritePrinter.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
	for name in ("EndPagePrinter", "EndDocPrinter", "ClosePrinter"):
		getattr(spool, name).argtypes = [wintypes.HANDLE]
	handle = wintypes.HANDLE()
	if not spool.OpenPrinterW(queue, ctypes.byref(handle), None):
		raise PrintError(f"Cannot open Windows printer queue: {ctypes.get_last_error()}")
	try:
		job = spool.StartDocPrinterW(handle, 1, ctypes.byref(DocInfo("S&S receipt / drawer", None, "RAW")))
		if not job:
			raise PrintError("Windows print spooler rejected the job")
		try:
			if not spool.StartPagePrinter(handle):
				raise PrintError("Windows print spooler could not start a page")
			try:
				written = wintypes.DWORD()
				buffer = ctypes.create_string_buffer(payload)
				if not spool.WritePrinter(handle, buffer, len(payload), ctypes.byref(written)) or written.value != len(payload):
					raise PrintError("Windows USB write incomplete; result unknown")
			finally:
				if not spool.EndPagePrinter(handle):
					raise PrintError("Windows could not finalize the page; result unknown")
		finally:
			if not spool.EndDocPrinter(handle):
				raise PrintError("Windows could not finalize the job; result unknown")
	finally:
		spool.ClosePrinter(handle)
	return {"transport": "usb", "status": "Queued", "job": str(job)}


def send(device, payload):
	driver, destination = target(device)
	if driver == "escpos_tcp":
		try:
			with socket.create_connection(destination, timeout=5) as connection:
				connection.settimeout(10)
				connection.sendall(payload)
		except OSError as error:
			raise PrintError("LAN printer unavailable; delivery may be unknown. Check the printer before retrying.") from error
		return {"transport": "lan", "status": "Sent"}
	return submit_usb(destination, payload)
