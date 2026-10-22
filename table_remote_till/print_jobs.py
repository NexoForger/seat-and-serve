"""Outbound-only print agent queue. Claimed jobs are never physically replayed."""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import time

import frappe

from table_remote_till.printing import settings, target


def enqueue(device, payload, kind, order=None, invoice=None, job_key=None):
	agent = settings(device).get("print_agent")
	if not agent:
		raise ValueError("Configure a print agent on this device")
	target(device)
	if job_key:
		prior = frappe.db.get_value("TRT Print Job", {"job_key": job_key}, ["name", "status"], as_dict=True)
		if prior:
			return {"transport": "agent", "status": prior.status, "job": prior.name}
	job = frappe.get_doc({"doctype": "TRT Print Job", "outlet": device.outlet,
		"register": device.register, "device": device.name, "agent": agent,
		"order": order, "pos_invoice": invoice, "kind": kind, "job_key": job_key,
		"status": "Pending", "expires_unix": time.time() + 30 if "Drawer" in kind else 0,
		"payload_base64": base64.b64encode(payload).decode("ascii"),
		"target_json": json.dumps({"driver": device.driver or "escpos_tcp", "address": device.address})
	}).insert(ignore_permissions=True)
	return {"transport": "agent", "status": "Pending", "job": job.name}


def _agent_access(outlet, agent):
	from table_remote_till.api import _staff_outlet
	_staff_outlet(outlet)
	allowed = frappe.conf.get("trt_print_agents") or {}
	if not isinstance(allowed, dict) or allowed.get(agent) != frappe.session.user:
		frappe.throw("This service user is not assigned to this print agent", frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def claim(outlet, agent):
	_agent_access(outlet, agent)
	rows = frappe.db.sql("""SELECT name FROM `tabTRT Print Job`
		WHERE outlet=%s AND agent=%s AND status='Pending'
		ORDER BY CASE WHEN kind IN ('Cash Drawer', 'Drawer Test') THEN 0 ELSE 1 END, creation
		LIMIT 5 FOR UPDATE SKIP LOCKED""", (outlet, agent), as_dict=True)
	jobs = []
	for row in rows:
		job = frappe.get_doc("TRT Print Job", row.name)
		if job.expires_unix and job.expires_unix <= time.time():
			frappe.db.set_value("TRT Print Job", job.name, {"status": "Unknown",
				"error": "Drawer action expired while the agent was offline. No pulse was sent."})
			continue
		token = secrets.token_urlsafe(32)
		frappe.db.set_value("TRT Print Job", job.name, {"status": "Claimed", "claim_token": token,
			"claimed_by": frappe.session.user, "claimed_at": frappe.utils.now_datetime()})
		jobs.append({"name": job.name, "claim_token": token, "kind": job.kind,
			"expires_unix": job.expires_unix, "payload": job.payload_base64,
			"expires_in": max(0, job.expires_unix - time.time()) if job.expires_unix else None,
			"target": json.loads(job.target_json)})
	return jobs


@frappe.whitelist(methods=["POST"])
def acknowledge(job_name, claim_token, status, error=""):
	job = frappe.get_doc("TRT Print Job", job_name)
	_agent_access(job.outlet, job.agent)
	frappe.db.sql("SELECT name FROM `tabTRT Print Job` WHERE name=%s FOR UPDATE", job_name)
	job.reload()
	if (not claim_token or not job.claim_token or job.claimed_by != frappe.session.user
		or not hmac.compare_digest(job.claim_token, claim_token)):
		frappe.throw("Invalid print job claim", frappe.PermissionError)
	if status not in ("Sent", "Queued", "Unknown"):
		frappe.throw("Invalid print delivery status")
	if job.status != "Claimed":
		if job.status == status:
			return {"status": job.status}  # An acknowledgement may be retried; hardware is not.
		frappe.throw("Print job already completed")
	frappe.db.set_value("TRT Print Job", job.name, {"status": status,
		"error": str(error or "")[:500], "finished_at": frappe.utils.now_datetime()})
	return {"status": status}
