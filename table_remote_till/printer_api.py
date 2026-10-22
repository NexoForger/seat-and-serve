"""Manager hardware tests and one drawer action per committed cash invoice."""

from __future__ import annotations

from functools import partial
import hashlib
import json
import time
from types import SimpleNamespace

import frappe

from table_remote_till.printing import PrintError, drawer_bytes, send, settings, target
from table_remote_till.receipt import configured_printer, test_receipt


def _manager_device(device_name):
	from table_remote_till.api import _staff_outlet
	device = frappe.get_doc("TRT Device", device_name)
	device.check_permission("write")
	_staff_outlet(device.outlet, "allow_manager")
	if device.kind != "Receipt Printer" or not device.enabled:
		frappe.throw("Choose an enabled Receipt Printer")
	return device


@frappe.whitelist(methods=["POST"])
def test_print(device_name):
	device = _manager_device(device_name)
	return test_receipt(device.outlet, device.register, device=device)


@frappe.whitelist(methods=["POST"])
def test_drawer(device_name):
	device = _manager_device(device_name)
	frappe.logger("table_remote_till_devices", allow_site=True).info(json.dumps({
		"action": "drawer_test", "device": device.name, "user": frappe.session.user}))
	try:
		if settings(device).get("print_agent"):
			from table_remote_till.print_jobs import enqueue
			result = enqueue(device, drawer_bytes(device), "Drawer Test")
		else:
			result = _send_drawer(device)
	except PrintError as error:
		frappe.throw(str(error))
	return {"printer": device.title, **result}


def _send_drawer(device):
	return send(device, drawer_bytes(device))


def _event_id(invoice_name):
	return "cash-drawer:" + hashlib.sha256(invoice_name.encode()).hexdigest()


def schedule_cash_drawer(order, invoice_name, tenders):
	"""Called only by cash_checkout, inside its transaction, after invoice submission.

	A unique invoice event prevents checkout retries, reprints, kitchen dispatch,
	and multiple table tickets from creating another drawer pulse.
	"""
	if not any(float(row.get("amount", 0)) > 0 for row in tenders):
		return  # E.g. a bill covered entirely by loyalty points.
	device = configured_printer(order.outlet, order.register)
	if not device:
		return
	error = ""
	try:
		if not settings(device)["drawer_enabled"]:
			return
		target(device)
	except PrintError as failure:
		error = str(failure)
	event_id = _event_id(invoice_name)
	if (frappe.db.exists("TRT Sync Event", {"event_id": event_id})
		or frappe.db.exists("TRT Print Job", {"job_key": event_id})):
		return
	if not error and settings(device).get("print_agent"):
		from table_remote_till.print_jobs import enqueue
		enqueue(device, drawer_bytes(device), "Cash Drawer", order=order.name,
			invoice=invoice_name, job_key=event_id)
		return  # The job becomes visible to the agent only after this payment commits.
	device_snapshot = {key: getattr(device, key, None)
		for key in ("name", "title", "driver", "address", "settings_json")}
	event = frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": order.outlet, "register": order.register, "order": order.name,
		"event_type": "cash_drawer", "status": "Conflict" if error else "Pending",
		"error": error, "received_at": frappe.utils.now_datetime(),
		"payload_json": json.dumps({"invoice": invoice_name, "device": device_snapshot})}).insert(ignore_permissions=True)
	if not error:
		frappe.db.after_commit.add(partial(_dispatch_drawer, event.name))


def _dispatch_drawer(event_name):
	"""Claim durably before hardware I/O. Never automatically repeat an uncertain pulse."""
	try:
		frappe.db.sql("SELECT name FROM `tabTRT Sync Event` WHERE name=%s FOR UPDATE", event_name)
		event = frappe.get_doc("TRT Sync Event", event_name)
		if event.event_type != "cash_drawer" or event.status != "Pending":
			frappe.db.commit()
			return
		payload = json.loads(event.payload_json)
		# Conflict means delivery may be unknown if this process stops during I/O.
		frappe.db.set_value("TRT Sync Event", event_name, {"status": "Conflict",
			"error": "Drawer delivery started; result unknown. Check the drawer before any manual test."})
		frappe.db.commit()
		result = _send_drawer(SimpleNamespace(**payload["device"]))
		frappe.db.set_value("TRT Sync Event", event_name, {"status": "Applied", "error": "",
			"payload_json": json.dumps({**payload, "delivery": result})})
		frappe.db.commit()
	except Exception:
		# The payment has already committed. Never report that checkout rolled back
		# or retry the pulse because a socket/queue/bridge did not confirm it.
		frappe.db.rollback()
		frappe.log_error(title="TRT cash drawer delivery", message=frappe.get_traceback())


@frappe.whitelist()
def drawer_status(order_name):
	from table_remote_till.api import _staff_outlet
	order = frappe.get_doc("TRT Order", order_name)
	_staff_outlet(order.outlet)
	if not order.pos_invoice:
		return {"status": "Disabled"}
	job = frappe.db.get_value("TRT Print Job", {"job_key": _event_id(order.pos_invoice)},
		["status", "error", "expires_unix"], as_dict=True)
	if job:
		expired = job.status in ("Pending", "Claimed") and job.expires_unix and job.expires_unix <= time.time()
		status = "Conflict" if expired or job.status == "Unknown" else "Applied" if job.status in ("Sent", "Queued") else "Pending"
		return {"status": status, "error": job.error, "delivery": job.status, "agent": True}
	event = frappe.db.get_value("TRT Sync Event", {"event_id": _event_id(order.pos_invoice)},
		["status", "error", "payload_json"], as_dict=True)
	if not event:
		return {"status": "Disabled"}
	delivery = json.loads(event.payload_json).get("delivery", {})
	return {"status": event.status, "error": event.error, "delivery": delivery.get("status")}
