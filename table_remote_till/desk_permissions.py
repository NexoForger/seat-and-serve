"""Restrict TRT Desk records to branches assigned to the current manager."""

import json

import frappe


DIRECT_OUTLET = {
	"TRT Device", "TRT FX Rate", "TRT Kitchen Station", "TRT Menu", "TRT Onboarding Run",
	"TRT Order", "TRT Promotion", "TRT Register", "TRT Reservation", "TRT Service Area",
	"TRT Staff Assignment", "TRT Sync Event", "TRT Table",
}
VIA_ORDER = {"TRT Kitchen Ticket", "TRT Payment Attempt", "TRT Promotion Redemption"}
GLOBAL_MANAGER_BLOCKED = {
	"TRT Business Setup", "TRT Guest Appearance", "TRT Import Job", "TRT Legacy Record",
	"TRT Modifier Group",
}
SCOPED = DIRECT_OUTLET | VIA_ORDER | GLOBAL_MANAGER_BLOCKED | {"TRT Outlet"}
MANAGER_READ_ONLY = {
	"TRT FX Rate", "TRT Kitchen Ticket", "TRT Order", "TRT Payment Attempt",
	"TRT Promotion Redemption", "TRT Staff Assignment", "TRT Sync Event",
}


def audit_denial(user, doctype, name, action):
	frappe.logger("table_remote_till_security", allow_site=True).warning(json.dumps({
		"user": user, "doctype": doctype, "name": name, "action": action,
		"decision": "deny"}, ensure_ascii=False))


def _deny(user, doc, ptype):
	audit_denial(user, doc.doctype, doc.name, ptype or "read")
	return False


def _branches(user):
	"""Manager assignments grant Desk access to their outlet's branch."""
	if not user or user == "Guest" or "TRT Manager" not in frappe.get_roles(user):
		return set()
	assigned = frappe.get_all("TRT Staff Assignment", filters={
		"user": user, "enabled": 1, "allow_manager": 1}, pluck="outlet")
	if not assigned:
		return set()
	return {branch for branch in frappe.get_all("TRT Outlet", filters={
		"name": ["in", assigned]}, pluck="branch") if branch}


def _branch_sql(user):
	branches = sorted(_branches(user))
	return ", ".join(frappe.db.escape(branch) for branch in branches)


def query_conditions(user=None, doctype=None):
	"""Apply to lists, link searches, reports, and exports through Frappe permissions."""
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	branches = _branch_sql(user)
	if not branches or doctype not in SCOPED or doctype in GLOBAL_MANAGER_BLOCKED:
		return "1=0"
	if doctype == "TRT Outlet":
		return f"`tabTRT Outlet`.`branch` IN ({branches})"
	if doctype in DIRECT_OUTLET:
		return (f"EXISTS (SELECT 1 FROM `tabTRT Outlet` scoped_outlet WHERE "
			f"scoped_outlet.name = `tab{doctype}`.`outlet` AND scoped_outlet.branch IN ({branches}))")
	return (f"EXISTS (SELECT 1 FROM `tabTRT Order` scoped_order "
		f"JOIN `tabTRT Outlet` scoped_outlet ON scoped_outlet.name = scoped_order.outlet "
		f"WHERE scoped_order.name = `tab{doctype}`.`order` AND scoped_outlet.branch IN ({branches}))")


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Apply the same branch rule to direct document reads and writes."""
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	if "TRT Manager" not in frappe.get_roles(user):
		return _deny(user, doc, ptype)
	if doc.doctype not in SCOPED or doc.doctype in GLOBAL_MANAGER_BLOCKED:
		return _deny(user, doc, ptype)
	if doc.doctype in MANAGER_READ_ONLY and ptype not in (None, "read", "print", "report", "export"):
		return _deny(user, doc, ptype)
	branches = _branches(user)
	if not branches:
		return _deny(user, doc, ptype)
	if doc.doctype == "TRT Outlet":
		# Creating outlets and assigning branches remains a System Manager action.
		allowed = bool(doc.name and doc.branch in branches and frappe.db.exists("TRT Outlet", doc.name))
		return True if allowed else _deny(user, doc, ptype)
	if doc.doctype in DIRECT_OUTLET:
		outlet = doc.get("outlet")
	else:
		outlet = frappe.db.get_value("TRT Order", doc.get("order"), "outlet") if doc.get("order") else None
	allowed = bool(outlet and frappe.db.get_value("TRT Outlet", outlet, "branch") in branches)
	return True if allowed else _deny(user, doc, ptype)
