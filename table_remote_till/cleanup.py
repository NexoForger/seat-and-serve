"""Expire abandoned, empty dine-in add-on drafts."""

from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime


EMPTY_ADDON_TTL = timedelta(minutes=5)


def expire_empty_addon_drafts(outlet=None):
	"""Remove add-on drafts idle for five minutes without affecting table bills."""
	cutoff = now_datetime() - EMPTY_ADDON_TTL
	filters = {"channel": "Table", "status": "Draft", "parent_order": ["is", "set"],
		"modified": ["<=", cutoff]}
	if outlet:
		filters["outlet"] = outlet
	candidates = frappe.get_all("TRT Order", filters=filters, pluck="name", limit_page_length=0)
	removed = []
	for index, name in enumerate(candidates):
		frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", name)
		if not frappe.db.exists("TRT Order", name):
			continue
		order = frappe.get_doc("TRT Order", name)
		if (order.channel != "Table" or order.status != "Draft" or not order.parent_order
			or (outlet and order.outlet != outlet) or order.pos_invoice
			or get_datetime(order.modified) > cutoff or order.lines):
			continue
		if (frappe.db.exists("TRT Order Line", {"parent": name})
			or frappe.db.exists("TRT Order", {"parent_order": name})
			or frappe.db.exists("TRT Kitchen Ticket", {"order": name})
			or frappe.db.exists("TRT Payment Attempt", {"order": name})):
			continue
		# Keep idempotency keys, but detach their link to the expired order.
		# A replay must report expiry rather than silently create a second draft.
		savepoint = f"empty_addon_{index}"
		frappe.db.savepoint(savepoint)
		try:
			for event_name in frappe.get_all("TRT Sync Event", filters={"order": name},
				pluck="name", limit_page_length=0):
				frappe.db.set_value("TRT Sync Event", event_name,
					{"order": None, "status": "Expired"}, update_modified=False)
			frappe.delete_doc("TRT Order", name, ignore_permissions=True)
		except frappe.LinkExistsError:
			frappe.db.rollback(save_point=savepoint)
			continue
		removed.append(name)
	return removed
