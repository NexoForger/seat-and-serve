"""Cash-count prompts backed by ERPNext opening and closing entries."""

import math

import frappe
from frappe.utils import flt, now_datetime

from table_remote_till.api import _as_admin, _outlet, _payload, _staff_outlet


def active_opening(profile):
	return frappe.db.get_value("POS Opening Entry", {
		"pos_profile": profile, "status": "Open", "docstatus": 1}, "name")


def _context(outlet, lock=False):
	_staff_outlet(outlet)
	settings = _outlet(outlet)
	if lock:
		frappe.db.sql("SELECT name FROM `tabPOS Profile` WHERE name=%s FOR UPDATE", settings.pos_profile)
	profile = frappe.get_doc("POS Profile", settings.pos_profile)
	if profile.disabled or profile.company != settings.company:
		frappe.throw("Configure an enabled POS Profile for this outlet's company")
	if frappe.db.get_single_value("POS Settings", "invoice_type") != "POS Invoice":
		frappe.throw("Configure POS Invoice mode before using shifts")
	return profile


def _closing(opening):
	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import make_closing_entry_from_opening

	with _as_admin():
		closing = make_closing_entry_from_opening(opening)
	rows = {row.mode_of_payment: row for row in closing.payment_reconciliation}
	for balance in opening.balance_details:
		row = rows.get(balance.mode_of_payment)
		if row is None:
			row = closing.append("payment_reconciliation", {"mode_of_payment": balance.mode_of_payment,
				"expected_amount": 0})
			rows[balance.mode_of_payment] = row
		row.opening_amount = flt(balance.opening_amount)
		row.expected_amount = flt(row.expected_amount) + row.opening_amount
	return closing


def _counts(value, modes):
	value = _payload(value)
	if not isinstance(value, dict) or set(value) != set(modes):
		frappe.throw("Enter a counted amount for every payment method")
	result = {}
	for mode, amount in value.items():
		try:
			if isinstance(amount, bool) or amount is None or amount == "":
				raise ValueError
			amount = float(amount)
		except (TypeError, ValueError):
			frappe.throw("Enter a valid counted amount")
		if not math.isfinite(amount) or amount < 0:
			frappe.throw("Counted amounts must be finite and non-negative")
		result[mode] = amount
	return result


@frappe.whitelist()
def shift_details(outlet):
	profile = _context(outlet)
	opening = active_opening(profile.name)
	pending = None
	if opening:
		pending = frappe.db.get_value("POS Closing Entry", {"pos_opening_entry": opening,
			"docstatus": 1}, ["name", "status"], as_dict=True)
		closing = _closing(frappe.get_doc("POS Opening Entry", opening))
		rows = [{"mode_of_payment": row.mode_of_payment, "expected_amount": row.expected_amount}
			for row in closing.payment_reconciliation]
	else:
		rows = [{"mode_of_payment": row.mode_of_payment, "expected_amount": 0}
			for row in profile.payments]
	if not rows:
		frappe.throw("Configure payment methods in the POS Profile first")
	return {"opening_entry": opening, "pending_closing": pending,
		"currency": frappe.get_cached_value("Company", profile.company, "default_currency"), "rows": rows}


@frappe.whitelist(methods=["POST"])
def open_shift(outlet, amounts):
	profile = _context(outlet, lock=True)
	if active_opening(profile.name):
		frappe.throw("A shift is already open. Refresh to see it.")
	counts = _counts(amounts, [row.mode_of_payment for row in profile.payments])
	if not counts:
		frappe.throw("Configure payment methods first")
	entry = frappe.get_doc({"doctype": "POS Opening Entry", "company": profile.company,
		"pos_profile": profile.name, "user": frappe.session.user, "period_start_date": now_datetime(),
		"balance_details": [{"mode_of_payment": mode, "opening_amount": amount}
			for mode, amount in counts.items()]})
	with _as_admin():
		entry.insert(ignore_permissions=True)
		entry.flags.ignore_permissions = True
		entry.submit()
	return {"name": entry.name, "status": entry.status}


@frappe.whitelist(methods=["POST"])
def close_shift(outlet, opening_entry, amounts):
	profile = _context(outlet, lock=True)
	opening = frappe.get_doc("POS Opening Entry", opening_entry)
	if opening.pos_profile != profile.name or opening.company != profile.company:
		frappe.throw("Shift does not belong to this outlet", frappe.PermissionError)
	existing = frappe.db.get_value("POS Closing Entry", {"pos_opening_entry": opening.name,
		"docstatus": 1}, ["name", "status"], as_dict=True)
	if existing:
		return existing
	if opening.name != active_opening(profile.name):
		frappe.throw("This shift is no longer open. Refresh before closing.")
	closing = _closing(opening)
	counts = _counts(amounts, [row.mode_of_payment for row in closing.payment_reconciliation])
	for row in closing.payment_reconciliation:
		row.closing_amount = counts[row.mode_of_payment]
		row.difference = row.closing_amount - flt(row.expected_amount)
	with _as_admin():
		closing.insert(ignore_permissions=True)
		closing.flags.ignore_permissions = True
		closing.submit()
	return {"name": closing.name, "status": closing.status}
