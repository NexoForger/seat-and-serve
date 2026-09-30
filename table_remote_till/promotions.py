"""Register bill adjustments backed by explicit coupon records and ERPNext loyalty."""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate, today


def _currency_amount(value, currency):
	return flt(value, 0 if currency == "LBP" else 2)


def discount_for_bill(root, outlet, pre_discount_total, lock=False):
	"""Return a server-calculated additional discount for a complete bill."""
	code = root.get("promotion")
	manual_type = root.get("manual_discount_type")
	if code and manual_type:
		frappe.throw("A bill can use a coupon or a manual discount, not both")
	if code:
		if lock:
			frappe.db.sql("SELECT name FROM `tabTRT Promotion` WHERE name=%s FOR UPDATE", code)
		promo = frappe.db.get_value("TRT Promotion", code,
			["name", "title", "outlet", "enabled", "discount_type", "discount_value",
				"minimum_total", "valid_from", "valid_until", "max_uses"], as_dict=True)
		if not promo or not promo.enabled or promo.outlet != outlet.name:
			frappe.throw("Coupon is unavailable for this outlet")
		current = getdate(today())
		if (promo.valid_from and getdate(promo.valid_from) > current) or (promo.valid_until and getdate(promo.valid_until) < current):
			frappe.throw("Coupon is outside its valid dates")
		if flt(pre_discount_total) < flt(promo.minimum_total):
			frappe.throw("Bill does not meet the coupon minimum")
		if promo.max_uses and frappe.db.count("TRT Promotion Redemption", {"promotion": code}) >= promo.max_uses:
			frappe.throw("Coupon usage limit has been reached")
		kind, value, label = promo.discount_type, flt(promo.discount_value), promo.title
	elif manual_type:
		kind, value, label = manual_type, flt(root.get("manual_discount_value")), "Manual discount"
		if not (root.get("manual_discount_reason") or "").strip():
			frappe.throw("Manual discount needs a reason")
	else:
		return {"amount": 0, "label": None, "code": None}
	if kind not in ("Percentage", "Amount") or value <= 0 or (kind == "Percentage" and value > 100):
		frappe.throw("Invalid discount configuration")
	amount = pre_discount_total * value / 100 if kind == "Percentage" else value
	if amount > pre_discount_total:
		frappe.throw("Discount cannot exceed the bill total")
	return {"amount": _currency_amount(amount, root.currency), "label": label, "code": code}


def loyalty_for_bill(root, outlet, bill_total):
	"""Return available and selected ERPNext points; redemption pays part of the invoice."""
	points = int(root.get("loyalty_points_to_redeem") or 0)
	if points < 0:
		frappe.throw("Loyalty points cannot be negative")
	customer = root.get("customer")
	program = frappe.db.get_value("Customer", customer, "loyalty_program") if customer else None
	if not program:
		if points:
			frappe.throw("Select a customer enrolled in a loyalty program")
		return {"program": None, "available_points": 0, "points": 0,
			"conversion_factor": 0, "amount": 0}
	from erpnext.accounts.doctype.loyalty_program.loyalty_program import get_loyalty_program_details_with_points

	if frappe.db.get_value("Loyalty Program", program, "company") != outlet.company:
		frappe.throw("Customer loyalty program belongs to another company")
	details = get_loyalty_program_details_with_points(customer, program, today(), outlet.company)
	available = max(0, int(details.loyalty_points or 0))
	factor = flt(details.conversion_factor)
	if points and (factor <= 0 or points > available):
		frappe.throw("Insufficient redeemable loyalty points")
	amount = _currency_amount(points * factor, root.currency)
	if amount > _currency_amount(bill_total, root.currency):
		frappe.throw("Loyalty redemption exceeds the bill total")
	return {"program": program, "available_points": available, "points": points,
		"conversion_factor": factor, "amount": amount}
