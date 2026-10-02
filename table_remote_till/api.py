"""POS commands. All writes are server priced, version checked, and idempotent."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import timedelta

import frappe
from frappe.utils import flt, get_datetime, now_datetime
from frappe.utils.password import get_encryption_key
from table_remote_till.cleanup import EMPTY_ADDON_TTL, expire_empty_addon_drafts
from table_remote_till.payments import configured_provider
from table_remote_till.promotions import discount_for_bill, loyalty_for_bill
from table_remote_till.receipt import configured_printer, print_invoice


STAFF_ROLES = {"System Manager", "TRT Manager", "TRT Cashier"}
KITCHEN_ROLES = STAFF_ROLES | {"TRT Kitchen"}
ORDER_FIELDS = [
	"name", "order_number", "outlet", "register", "channel", "table", "guest_count", "parent_order", "reservation", "tab_label", "customer", "status",
	"currency", "exchange_rate", "net_total", "tax_total", "grand_total", "revision", "pos_invoice",
	"promotion", "manual_discount_type", "manual_discount_value", "manual_discount_reason", "loyalty_points_to_redeem", "loyalty_amount_redeemed",
]
OPEN_ORDER_STATUSES = ("Draft", "Sent", "Preparing", "Ready", "Served")
BILL_ORDER_STATUSES = OPEN_ORDER_STATUSES + ("Settled",)
GUEST_APPEARANCE_DEFAULTS = {
	"brand_logo": "", "primary_color": "#171917", "accent_color": "#e8f574",
	"page_color": "#f7f8f3", "surface_color": "#ffffff", "text_color": "#171917",
	"muted_color": "#686d67", "heading_font": "Manrope", "body_font": "DM Sans",
	"brand_title_en": "", "brand_title_ar": "", "brand_tagline_en": "", "brand_tagline_ar": "",
	"hero_title_en": "", "hero_title_ar": "",
	"hero_subtitle_en": "", "hero_subtitle_ar": "", "hero_image": "",
	"layout_style": "Cards", "card_style": "Rounded", "loading_message_en": "",
	"loading_message_ar": "", "loading_style": "Food", "empty_style": "Illustrated",
	"success_style": "Sparkle", "motion_style": "Playful",
}
GUEST_APPEARANCE_FIELDS = tuple(GUEST_APPEARANCE_DEFAULTS)


def _payload(value):
	return frappe.parse_json(value) if isinstance(value, str) else (value or {})


def _staff(allowed=STAFF_ROLES):
	if frappe.session.user == "Guest" or not set(frappe.get_roles()).intersection(allowed):
		frappe.throw("POS role required", frappe.PermissionError)


def _staff_outlet(outlet, ability="allow_till"):
	_staff(KITCHEN_ROLES if ability == "allow_kitchen" else STAFF_ROLES)
	if "System Manager" in frappe.get_roles():
		return
	if not frappe.db.exists("TRT Staff Assignment", {"user": frappe.session.user,
		"outlet": outlet, "enabled": 1, ability: 1}) and not frappe.db.exists(
		"TRT Staff Assignment", {"user": frappe.session.user, "outlet": outlet,
			"enabled": 1, "allow_manager": 1}):
		frappe.throw("You are not assigned to this outlet", frappe.PermissionError)


def _sign(value):
	key = (get_encryption_key() + ":table-remote-till-guest-v1").encode()
	return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def _issue_token(scope):
	scope = {**scope, "exp": int(time.time()) + 3600}
	value = base64.urlsafe_b64encode(json.dumps(scope, separators=(",", ":")).encode()).decode().rstrip("=")
	return value + "." + _sign(value)


def _guest_scope(token, outlet, channel):
	try:
		value, signature = token.split(".", 1)
		if not hmac.compare_digest(signature, _sign(value)):
			raise ValueError("signature")
		scope = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
		if not isinstance(scope, dict):
			raise ValueError("scope")
		if int(scope["exp"]) < time.time():
			raise ValueError("expired")
	except (AttributeError, KeyError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
		frappe.throw("Invalid or expired ordering link", frappe.PermissionError)
	if scope.get("outlet") != outlet or scope.get("channel") != channel:
		frappe.throw("Ordering link does not match outlet or channel", frappe.PermissionError)
	return scope


def _authorize(outlet, channel, guest_token=None):
	if frappe.session.user != "Guest":
		_staff_outlet(outlet)
		return None
	if channel not in ("QR", "Pickup", "Kiosk") or not guest_token:
		frappe.throw("Ordering link required", frappe.PermissionError)
	return _guest_scope(guest_token, outlet, channel)


def _outlet(name):
	doc = frappe.get_cached_doc("TRT Outlet", name)
	if not doc.enabled:
		frappe.throw("Outlet is disabled")
	return doc


def _guest_appearance(company):
	"""Return only public, validated presentation settings for a Company's guest pages."""
	settings = dict(GUEST_APPEARANCE_DEFAULTS)
	if not company:
		return settings

	row = frappe.db.get_value("TRT Guest Appearance", {"company": company}, list(GUEST_APPEARANCE_FIELDS), as_dict=True)
	if not row:
		return settings

	for field in GUEST_APPEARANCE_FIELDS:
		value = row.get(field)
		if value is None:
			continue
		if field.endswith("_color"):
			if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
				settings[field] = value
		elif field in ("brand_logo", "hero_image"):
			if isinstance(value, str) and value.startswith(("/files/", "/assets/")) and ".." not in value.split("/"):
				settings[field] = value
		elif field in ("heading_font", "body_font"):
			if value in {"Manrope", "DM Sans", "Lato", "Nunito"}:
				settings[field] = value
		elif field == "layout_style" and value in {"Cards", "Compact list"}:
			settings[field] = value
		elif field == "card_style" and value in {"Soft", "Rounded", "Square"}:
			settings[field] = value
		elif field == "loading_style" and value in {"Food", "Sparkle", "Dots"}:
			settings[field] = value
		elif field == "empty_style" and value in {"Illustrated", "Simple"}:
			settings[field] = value
		elif field == "success_style" and value in {"Confetti", "Sparkle", "Check"}:
			settings[field] = value
		elif field == "motion_style" and value in {"Playful", "Calm", "Reduced"}:
			settings[field] = value
		elif isinstance(value, str):
			settings[field] = value[:500]
	return settings


def _price(item_code, price_list):
	item = frappe.db.get_value(
		"Item", item_code, ["item_name", "disabled", "is_sales_item"], as_dict=True
	)
	if not item or item.disabled or not item.is_sales_item:
		frappe.throw("Item is unavailable")
	rows = frappe.get_all(
		"Item Price",
		filters={"item_code": item_code, "price_list": price_list, "selling": 1,
			"valid_from": ["<=", frappe.utils.today()]},
		fields=["price_list_rate", "valid_upto"], order_by="valid_from desc, modified desc", limit=20,
	)
	rows = [row for row in rows if not row.valid_upto or row.valid_upto >= frappe.utils.today()]
	if not rows:
		frappe.throw(f"No selling price for {item_code} in {price_list}")
	return item.item_name, flt(rows[0].price_list_rate)


def _menu_entry(outlet, channel, item_code):
	menus = frappe.get_all("TRT Menu", filters={"outlet": outlet.name, "enabled": 1}, pluck="name")
	for menu_name in menus:
		menu = frappe.get_cached_doc("TRT Menu", menu_name)
		if channel in ("QR", "Pickup") and not menu.show_on_menu:
			continue
		if channel == "Kiosk" and not menu.show_on_kiosk:
			continue
		if channel not in ("QR", "Pickup", "Kiosk") and not menu.show_on_till:
			continue
		for row in menu.items:
			if row.item == item_code and row.available:
				return row
	if channel in ("Retail", "Till") and outlet.enable_retail:
		return None
	frappe.throw("Item is not available on this channel")


def _modifier_choices(entry, requested):
	requested = requested or []
	if not isinstance(requested, list) or any(not isinstance(code, str) for code in requested):
		frappe.throw("Choose valid modifier options")
	group_name = entry.modifier_group if entry else None
	if not group_name:
		if requested:
			frappe.throw("This item has no modifiers")
		return []
	group = frappe.get_cached_doc("TRT Modifier Group", group_name)
	if len(requested) < (group.minimum or 0):
		frappe.throw(f"Choose at least {group.minimum} options for {group.title}")
	if len(requested) != len(set(requested)):
		frappe.throw("Choose each modifier only once")
	options = {row.item: row for row in group.options}
	if any(code not in options for code in requested):
		frappe.throw("Modifier is not available for this item")
	selected = []
	for code in requested:
		row = options[code]
		if frappe.db.get_value("Item", code, "disabled"):
			frappe.throw("Modifier is unavailable")
		selected.append({"item": code, "name_en": row.name_en or frappe.db.get_value("Item", code, "item_name"),
			"name_ar": row.name_ar, "price_delta": flt(row.price_delta)})
	return selected


def _snapshot(order):
	data = {key: order.get(key) for key in ORDER_FIELDS}
	data["lines"] = [
		{
			"name": line.name, "item": line.item, "item_name": line.item_name,
			"qty": line.qty, "rate": line.rate, "amount": line.amount,
			"station": line.station, "note": line.note,
			"modifiers": frappe.parse_json(line.modifiers_json) if line.modifiers_json else [],
		}
		for line in order.lines
	]
	data["bill"] = _bill_snapshot(order)
	return data


def _table_session_orders(order, include_settled=True):
	"""Return the root table order and all of its add-on descendants."""
	if order.channel != "Table" or not order.table:
		return [order]
	statuses = BILL_ORDER_STATUSES if include_settled else OPEN_ORDER_STATUSES
	rows = frappe.get_all("TRT Order", filters={
		"outlet": order.outlet, "table": order.table, "channel": "Table",
		"status": ["in", statuses],
	}, fields=["name", "parent_order", "creation"], order_by="creation asc")
	by_name = {row.name: row for row in rows}
	if order.name not in by_name:
		by_name[order.name] = frappe._dict({"name": order.name, "parent_order": order.parent_order,
			"creation": order.creation})
	root_name = order.name
	seen = set()
	while root_name and root_name not in seen:
		seen.add(root_name)
		parent_name = by_name.get(root_name).parent_order if by_name.get(root_name) else None
		if not parent_name or parent_name not in by_name:
			break
		root_name = parent_name
	names = []
	frontier = [root_name]
	while frontier:
		name = frontier.pop(0)
		if name in names:
			continue
		names.append(name)
		frontier.extend(row.name for row in rows if row.parent_order == name)
	return [order if name == order.name else frappe.get_doc("TRT Order", name)
		for name in names]


def _root_order_name(order_name):
	"""Resolve an add-on parent to the first order in its table session."""
	current = order_name
	seen = set()
	while current and current not in seen:
		seen.add(current)
		parent = frappe.db.get_value("TRT Order", current, "parent_order")
		if not parent:
			return current
		current = parent
	return current


def _bill_snapshot(order):
	orders = _table_session_orders(order)
	root = next((ticket for ticket in orders if not ticket.parent_order), orders[0])
	lines = [line for ticket in orders for line in ticket.lines]
	totals = {"net_total": sum(flt(ticket.net_total) for ticket in orders),
		"tax_total": sum(flt(ticket.tax_total) for ticket in orders),
		"grand_total": sum(flt(ticket.grand_total) for ticket in orders)}
	discount = {"amount": 0, "label": None, "code": root.promotion}
	loyalty = {"program": None, "available_points": 0,
		"points": int(root.loyalty_points_to_redeem or 0), "amount": 0, "conversion_factor": 0}
	billing_errors = []
	invoice_names = {ticket.pos_invoice for ticket in orders if ticket.pos_invoice}
	if lines and all(ticket.status in ("Settled", "Returned") for ticket in orders) and len(invoice_names) == 1:
		# Paid bills retain the submitted invoice amounts if tax or promotion settings change.
		invoice = frappe.db.get_value("POS Invoice", next(iter(invoice_names)),
			["net_total", "total_taxes_and_charges", "rounded_total", "grand_total",
				"discount_amount", "loyalty_program", "loyalty_points", "loyalty_amount"], as_dict=True)
		if invoice:
			totals = {"net_total": flt(invoice.net_total),
				"tax_total": flt(invoice.total_taxes_and_charges),
				"grand_total": flt(invoice.rounded_total or invoice.grand_total)}
			discount["amount"] = max(0, flt(invoice.discount_amount) - flt(root.loyalty_amount_redeemed))
			loyalty.update({"program": invoice.loyalty_program,
				"points": int(root.loyalty_points_to_redeem or 0),
				"amount": flt(root.loyalty_amount_redeemed)})
	elif lines:
		outlet = _outlet(order.outlet)
		preview = frappe._dict({"lines": lines, "customer": root.customer,
			"currency": order.currency, "exchange_rate": order.exchange_rate})
		_reprice(preview, outlet)
		try:
			discount = discount_for_bill(root, outlet, flt(preview.grand_total))
		except frappe.ValidationError as exc:
			billing_errors.append(str(exc))
		if discount["amount"]:
			_reprice(preview, outlet, discount["amount"])
		totals = {key: flt(preview[key]) for key in totals}
		try:
			loyalty = loyalty_for_bill(root, outlet, totals["grand_total"])
		except frappe.ValidationError as exc:
			billing_errors.append(str(exc))
		if loyalty["amount"]:
			_reprice(preview, outlet, discount["amount"] + loyalty["amount"])
			totals = {key: flt(preview[key]) for key in totals}
	return {
		"ticket_count": len(orders),
		"root_revision": root.revision,
		"item_count": sum(flt(line.qty) for line in lines),
		**totals,
		"customer": root.customer,
		"customer_name": frappe.db.get_value("Customer", root.customer, "customer_name") if root.customer else None,
		"promotion": root.promotion,
		"manual_discount_type": root.manual_discount_type,
		"manual_discount_value": flt(root.manual_discount_value),
		"manual_discount_reason": root.manual_discount_reason,
		"discount_amount": discount["amount"], "discount_label": discount["label"],
		"billing_errors": billing_errors,
		"loyalty": loyalty,
		"amount_due": max(0, flt(totals["grand_total"])),
		"order_numbers": [ticket.order_number for ticket in orders],
		"pos_invoice": next((ticket.pos_invoice for ticket in orders if ticket.pos_invoice), None),
		"orders": [{"name": ticket.name, "order_number": ticket.order_number,
			"status": ticket.status, "grand_total": flt(ticket.grand_total),
			"pos_invoice": ticket.pos_invoice} for ticket in orders],
	}


def _use_tax_inclusive_prices(invoice):
	"""Treat every configured sales tax as included in the displayed item rate."""
	for tax in invoice.get("taxes") or []:
		tax.included_in_print_rate = 1


def _reprice(order, outlet, discount_amount=0):
	"""Use ERPNext's POS calculator without adding tax on top of item prices."""
	if not order.lines:
		order.net_total = order.tax_total = order.grand_total = 0
		return
	if not outlet.pos_profile or not outlet.price_list:
		frappe.throw("Outlet requires a POS Profile and selling Price List")
	invoice = frappe.new_doc("POS Invoice")
	invoice.company = outlet.company
	invoice.pos_profile = outlet.pos_profile
	invoice.customer = order.customer or outlet.walk_in_customer or frappe.db.get_value("POS Profile", outlet.pos_profile, "customer")
	if not invoice.customer:
		frappe.throw("Outlet requires a walk-in customer")
	invoice.is_pos = 1
	invoice.currency = order.currency
	invoice.conversion_rate = order.exchange_rate or 1
	invoice.selling_price_list = outlet.price_list
	invoice.price_list_currency = order.currency
	invoice.plc_conversion_rate = 1
	invoice.taxes_and_charges = outlet.tax_template or frappe.db.get_value(
		"POS Profile", outlet.pos_profile, "taxes_and_charges")
	invoice.set_warehouse = outlet.warehouse
	for line in order.lines:
		invoice.append("items", {"item_code": line.item, "item_name": line.item_name,
			"qty": line.qty, "rate": line.rate, "warehouse": outlet.warehouse})
	invoice.set_taxes()
	_use_tax_inclusive_prices(invoice)
	invoice.ignore_pricing_rule = 1
	for item, line in zip(invoice.items, order.lines, strict=True):
		item.rate = line.rate
		item.price_list_rate = line.rate
	invoice.calculate_taxes_and_totals()
	if discount_amount:
		invoice.apply_discount_on = "Grand Total"
		invoice.discount_amount = discount_amount
		invoice.calculate_taxes_and_totals()
	order.net_total = invoice.net_total
	order.tax_total = invoice.total_taxes_and_charges
	order.grand_total = invoice.rounded_total or invoice.grand_total


def _release_kitchen(order):
	stations = {}
	for line in order.lines:
		if line.station:
			stations.setdefault(line.station, []).append(line)
	for station, lines in stations.items():
		station_title = frappe.db.get_value("TRT Kitchen Station", station, "title") or "Kitchen"
		ticket = frappe.get_doc({"doctype": "TRT Kitchen Ticket", "order": order.name,
			"ticket_label": f"{order.order_number} · {station_title}",
			"station": station, "status": "Queued", "revision": 1, "sent_at": now_datetime()})
		for line in lines:
			modifiers = frappe.parse_json(line.modifiers_json) if line.modifiers_json else []
			note = "\n".join(filter(None, [
				", ".join(option["name_en"] for option in modifiers), line.note]))
			ticket.append("lines", {"order_line": line.name, "item": line.item,
				"qty": line.qty, "note": note, "status": "Queued"})
		ticket.insert(ignore_permissions=True)


@frappe.whitelist()
def bootstrap():
	_staff(KITCHEN_ROLES)
	allowed = None if "System Manager" in frappe.get_roles() else frappe.get_all(
		"TRT Staff Assignment", filters={"user": frappe.session.user, "enabled": 1},
		pluck="outlet")
	return {
		"user": frappe.session.user,
		"roles": frappe.get_roles(),
		"outlets": frappe.get_all(
			"TRT Outlet", filters={"enabled": 1, **({"name": ["in", allowed]} if allowed is not None else {})},
			fields=["name", "title", "company", "base_currency", "cash_currency", "enable_tables", "enable_tabs", "enable_takeaway", "enable_retail"],
		),
	}


@frappe.whitelist()
def register_tables(outlet):
	"""Return human-readable table cards and their open orders for the waiter register."""
	_staff_outlet(outlet)
	settings = _outlet(outlet)
	if not settings.enable_tables:
		return []
	tables = frappe.get_all("TRT Table", filters={"outlet": outlet, "enabled": 1},
		fields=["name", "title", "seats", "area"], order_by="title asc")
	areas = {row.name: row.title for row in frappe.get_all("TRT Service Area",
		filters={"outlet": outlet}, fields=["name", "title"])}
	orders = frappe.get_all("TRT Order", filters={"outlet": outlet,
		"table": ["in", [row.name for row in tables]],
		"status": ["in", ["Draft", "Sent", "Preparing", "Ready", "Served"]]},
		fields=["name", "order_number", "table", "status", "guest_count", "grand_total",
			"parent_order", "runner_dispatched_at", "creation", "modified"],
		order_by="creation desc") if tables else []
	line_counts = {}
	if orders:
		for line in frappe.get_all("TRT Order Line", filters={"parent": ["in", [row.name for row in orders]]},
			fields=["parent"]):
			line_counts[line.parent] = line_counts.get(line.parent, 0) + 1
	by_table = {}
	cutoff = now_datetime() - EMPTY_ADDON_TTL
	for order in orders:
		order["line_count"] = line_counts.get(order.name, 0)
		order["expired_empty_addon"] = bool(order.parent_order and order.status == "Draft"
			and not order["line_count"] and get_datetime(order.modified) <= cutoff)
		by_table.setdefault(order.table, []).append(order)
	result = []
	for table in tables:
		open_orders = by_table.get(table.name, [])
		result.append({
			"name": table.name, "title": table.title, "seats": table.seats or 0,
			"area": table.area, "area_title": areas.get(table.area) or "Dining room",
			"guest_count": max([int(row.guest_count or 0) for row in open_orders] or [0]),
			"orders": open_orders,
		})
	if tables:
		upcoming = frappe.db.sql("""SELECT `table`, reservation_number, guest_name,
			party_size, starts_at, status FROM `tabTRT Reservation`
			WHERE outlet=%s AND status IN ('Confirmed', 'Seated')
			AND ends_at > %s AND starts_at < %s ORDER BY starts_at""",
			(outlet, now_datetime(), now_datetime() + timedelta(days=1)), as_dict=True)
		by_reservation = {}
		for booking in upcoming:
			by_reservation.setdefault(booking.table, booking)
		for row in result:
			booking = by_reservation.get(row["name"])
			row["next_reservation"] = ({"reservation_number": booking.reservation_number,
				"guest_name": booking.guest_name, "party_size": booking.party_size,
				"time": get_datetime(booking.starts_at).strftime("%H:%M"),
				"status": booking.status} if booking else None)
	return result


@frappe.whitelist(methods=["POST"])
def cleanup_empty_addon_drafts(outlet):
	"""Remove expired empty add-ons for a waiter's outlet."""
	_staff_outlet(outlet)
	return {"removed": expire_empty_addon_drafts(outlet)}


@frappe.whitelist()
def register_order(outlet, order_name):
	"""Load a saved ticket for a waiter returning to its table."""
	_staff_outlet(outlet)
	order = frappe.get_doc("TRT Order", order_name)
	if order.outlet != outlet:
		frappe.throw("Order is outside outlet", frappe.PermissionError)
	return _snapshot(order)


@frappe.whitelist(allow_guest=True)
def public_outlets(channel="Pickup"):
	if channel not in ("Pickup", "Kiosk", "QR"):
		frappe.throw("Invalid public channel")
	flag = {"Pickup": "enable_pickup", "Kiosk": "enable_kiosk", "QR": "enable_qr"}[channel]
	outlets = frappe.get_all("TRT Outlet", filters={"enabled": 1, flag: 1},
		fields=["name", "title", "base_currency", "company"])
	for outlet in outlets:
		outlet["appearance"] = _guest_appearance(outlet.pop("company", None))
	return outlets


@frappe.whitelist(allow_guest=True)
def catalog(outlet, channel="Till"):
	settings = _outlet(outlet)
	if channel == "QR" and not settings.enable_qr:
		frappe.throw("QR ordering is disabled")
	if channel == "Kiosk" and not settings.enable_kiosk:
		frappe.throw("Kiosk ordering is disabled")
	if channel == "Pickup" and not settings.enable_pickup:
		frappe.throw("Pickup ordering is disabled")
	if channel not in ("QR", "Kiosk", "Pickup"):
		_staff_outlet(outlet)
	menus = frappe.get_all("TRT Menu", filters={"outlet": outlet, "enabled": 1}, pluck="name")
	items = []
	modifier_groups = {}
	for menu_name in menus:
		menu = frappe.get_cached_doc("TRT Menu", menu_name)
		if channel in ("QR", "Pickup") and not menu.show_on_menu:
			continue
		if channel == "Kiosk" and not menu.show_on_kiosk:
			continue
		if channel not in ("QR", "Pickup", "Kiosk") and not menu.show_on_till:
			continue
		for row in menu.items:
			if not row.available:
				continue
			try:
				name, rate = _price(row.item, settings.price_list)
			except frappe.ValidationError:
				continue
			modifier = None
			if row.modifier_group:
				if row.modifier_group not in modifier_groups:
					group = frappe.get_cached_doc("TRT Modifier Group", row.modifier_group)
					modifier_groups[row.modifier_group] = {"name": group.name, "title": group.title,
						"minimum": group.minimum or 0,
						"options": [{"item": option.item,
							"name_en": option.name_en or frappe.db.get_value("Item", option.item, "item_name"),
							"name_ar": option.name_ar, "price_delta": flt(option.price_delta)}
							for option in group.options]}
				modifier = modifier_groups[row.modifier_group]
			items.append({
				"item": row.item, "name_en": row.name_en or name,
				"name_ar": row.name_ar, "category": row.category,
				"rate": flt(row.price_override) if flt(row.price_override) > 0 else rate,
				"station": row.station, "modifier_group": modifier,
				"deal_kind": row.deal_kind, "deal_description": row.deal_description,
			})
	if channel == "Retail" and settings.enable_retail:
		known = {row["item"] for row in items}
		prices = frappe.get_all("Item Price", filters={"price_list": settings.price_list, "selling": 1},
			fields=["item_code"], limit_page_length=1000)
		for price in prices:
			if price.item_code in known:
				continue
			try:
				name, rate = _price(price.item_code, settings.price_list)
			except frappe.ValidationError:
				continue
			items.append({"item": price.item_code, "name_en": name,
				"name_ar": "", "category": "Retail", "rate": rate, "station": None})
	return {"outlet": outlet, "currency": settings.base_currency, "items": items}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def guest_link(outlet, channel="Pickup", table=None, qr_secret=None):
	settings = _outlet(outlet)
	if channel == "QR":
		if not settings.enable_qr or not table or not qr_secret:
			frappe.throw("Valid table QR code required", frappe.PermissionError)
		stored = frappe.db.get_value("TRT Table", table, ["outlet", "qr_secret", "title"], as_dict=True)
		if not stored or stored.outlet != outlet or not stored.qr_secret or not hmac.compare_digest(stored.qr_secret, qr_secret):
			frappe.throw("Invalid table QR code", frappe.PermissionError)
	elif channel == "Pickup":
		if not settings.enable_pickup:
			frappe.throw("Pickup ordering is disabled")
	elif channel == "Kiosk":
		if not settings.enable_kiosk:
			frappe.throw("Kiosk ordering is disabled")
	else:
		frappe.throw("Invalid guest channel")
	return {"token": _issue_token({"outlet": outlet, "channel": channel,
		"table": table, "session": secrets.token_urlsafe(18)}),
		"table_title": stored.title if channel == "QR" else None}


@frappe.whitelist(allow_guest=True)
def order_command(command, event_id, order_name=None, expected_revision=None, guest_token=None):
	"""Apply one idempotent command; Frappe commits the POST as one transaction."""
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	command = _payload(command)
	if not isinstance(command, dict) or not event_id:
		frappe.throw("Command object and event ID required")
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id},
		["order", "payload_json", "status"], as_dict=True)
	if prior:
		if frappe.parse_json(prior.payload_json) != command:
			frappe.throw("Event ID belongs to another command")
		if prior.status == "Expired" or not prior.order:
			frappe.throw("Draft expired; start a new add-on")
		prior_order = frappe.get_doc("TRT Order", prior.order)
		scope = _authorize(prior_order.outlet, prior_order.channel, guest_token)
		if scope and prior_order.guest_session != scope.get("session"):
			frappe.throw("Order does not belong to ordering session", frappe.PermissionError)
		return _snapshot(prior_order)
	action = command.get("action")
	if action == "create":
		if expected_revision is None or int(expected_revision) != 0:
			frappe.throw("New orders require revision zero")
		outlet = _outlet(command.get("outlet"))
		channel = command.get("channel")
		if channel not in ("Till", "Table", "Tab", "Takeaway", "Retail", "Kiosk", "QR", "Pickup"):
			frappe.throw("Invalid sales channel")
		scope = _authorize(outlet.name, channel, guest_token)
		if channel == "Table" and not outlet.enable_tables:
			frappe.throw("Tables are disabled")
		if channel == "Retail" and not outlet.enable_retail:
			frappe.throw("Retail is disabled")
		if channel == "Tab" and not outlet.enable_tabs:
			frappe.throw("Tabs are disabled")
		if channel == "Takeaway" and not outlet.enable_takeaway:
			frappe.throw("Takeaway is disabled")
		if channel == "Kiosk" and not outlet.enable_kiosk:
			frappe.throw("Kiosk is disabled")
		if channel == "QR" and not outlet.enable_qr:
			frappe.throw("QR ordering is disabled")
		if channel == "Pickup" and not outlet.enable_pickup:
			frappe.throw("Pickup ordering is disabled")
		table = command.get("table")
		if table and frappe.db.get_value("TRT Table", table, "outlet") != outlet.name:
			frappe.throw("Table is outside outlet")
		guest_count = int(command.get("guest_count") or 0)
		if guest_count < 0:
			frappe.throw("Guest count cannot be negative")
		if table:
			seats = frappe.db.get_value("TRT Table", table, "seats") or 0
			if seats and guest_count > seats:
				frappe.throw(f"Guest count cannot exceed {seats} seats")
		parent_order = command.get("parent_order")
		if parent_order:
			parent = frappe.db.get_value("TRT Order", parent_order,
				["outlet", "table", "channel", "status"], as_dict=True)
			if (not parent or parent.outlet != outlet.name or parent.table != table or parent.channel != "Table"
				or parent.status in ("Settled", "Void")):
				frappe.throw("Add-on order must belong to the same open table")
			parent_order = _root_order_name(parent_order)
			# Checkout holds the root row while collecting every add-on. Take the
			# same lock before creating a child so the final invoice cannot miss it.
			frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", parent_order)
			root = frappe.db.get_value("TRT Order", parent_order,
				["outlet", "table", "channel", "status"], as_dict=True)
			if (not root or root.outlet != outlet.name or root.table != table
				or root.channel != "Table" or root.status not in OPEN_ORDER_STATUSES):
				frappe.throw("Add-on order must belong to the same open table")
		reservation = command.get("reservation")
		if reservation and (channel != "Table" or parent_order):
			frappe.throw("Only a new table order can seat a reservation")
		if channel == "Table" and table and not parent_order:
			frappe.db.sql("SELECT name FROM `tabTRT Table` WHERE name=%s FOR UPDATE", table)
			if frappe.db.exists("TRT Order", {"table": table,
				"status": ["in", OPEN_ORDER_STATUSES]}):
				frappe.throw("This table has an open ticket; add items to its table session")
			from table_remote_till.reservations import block_walk_in

			block_walk_in(table, reservation)
		if command.get("register") and frappe.db.get_value("TRT Register", command["register"], "outlet") != outlet.name:
			frappe.throw("Register is outside outlet")
		order = frappe.new_doc("TRT Order")
		order.update({
			"outlet": outlet.name, "register": command.get("register"), "channel": channel,
			"table": table, "guest_count": guest_count, "parent_order": parent_order,
			"reservation": reservation,
			"tab_label": command.get("tab_label"),
			"customer": (command.get("customer") if not scope else None) or outlet.walk_in_customer,
			"exchange_rate": 1, "status": "Draft", "revision": 1,
			"guest_session": scope.get("session") if scope else None,
		})
		if scope and order.table != scope.get("table"):
			frappe.throw("Table does not match ordering link", frappe.PermissionError)
		if order.table and frappe.db.get_value("TRT Table", order.table, "outlet") != outlet.name:
			frappe.throw("Table is outside outlet")
		order.insert(ignore_permissions=True)
		if reservation:
			booking = frappe.get_doc("TRT Reservation", reservation)
			booking.order = order.name
			booking.status = "Seated"
			booking.save(ignore_permissions=True)
	else:
		if not order_name:
			frappe.throw("Order name required")
		frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", order_name)
		order = frappe.get_doc("TRT Order", order_name)
		scope = _authorize(order.outlet, order.channel, guest_token)
		if scope and order.guest_session != scope.get("session"):
			frappe.throw("Order does not belong to ordering session", frappe.PermissionError)
		if int(expected_revision or -1) != order.revision:
			frappe.throw("Order changed; refresh before retrying", frappe.TimestampMismatchError)
		if order.status in ("Settled", "Void"):
			frappe.throw("Order is closed")
		if action in ("add_line", "set_qty") and order.status != "Draft":
			frappe.throw("Sent orders cannot be changed; start a new order")
		outlet = _outlet(order.outlet)
		if action == "add_line":
			item_code = command.get("item")
			qty = flt(command.get("qty", 1))
			if qty <= 0:
				frappe.throw("Quantity must be positive")
			entry = _menu_entry(outlet, order.channel, item_code)
			name, rate = _price(item_code, outlet.price_list)
			if entry and flt(entry.price_override) > 0:
				rate = flt(entry.price_override)
			modifiers = _modifier_choices(entry, command.get("modifiers"))
			rate += sum(option["price_delta"] for option in modifiers)
			deal_contents = (entry.deal_description or "").strip() if entry and entry.deal_kind else ""
			guest_note = (command.get("note") or "").strip()
			line_note = "\n".join(filter(None, [deal_contents, guest_note]))
			display_name = (entry.name_en or name) if entry else name
			order.append("lines", {"item": item_code, "item_name": display_name, "qty": qty,
				"rate": rate, "amount": qty * rate, "station": entry.station if entry else None,
				"note": line_note, "modifiers_json": json.dumps(modifiers, ensure_ascii=False)})
			_reprice(order, outlet)
		elif action == "set_qty":
			line = next((row for row in order.lines if row.name == command.get("line")), None)
			if not line:
				frappe.throw("Order line not found")
			qty = flt(command.get("qty"))
			if qty < 0:
				frappe.throw("Quantity cannot be negative")
			if qty == 0:
				order.remove(line)
			else:
				line.qty = qty
				line.amount = qty * line.rate
			_reprice(order, outlet)
		elif action == "send":
			if not order.lines:
				frappe.throw("Cannot send an empty order")
			if frappe.session.user == "Guest":
				frappe.throw("Guest order must be paid before kitchen release", frappe.PermissionError)
			order.status = "Sent"
			_release_kitchen(order)
		elif action == "void":
			_staff({"System Manager", "TRT Manager"})
			order.status = "Void"
		else:
			frappe.throw("Unknown order action")
		order.revision += 1
		order.save(ignore_permissions=True)
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": order.outlet, "register": order.register, "order": order.name,
		"event_type": action, "payload_json": json.dumps(command),
		"status": "Applied", "received_at": now_datetime()}).insert(ignore_permissions=True)
	frappe.publish_realtime("trt_order", {"order": order.name, "revision": order.revision}, after_commit=True)
	return _snapshot(order)


@frappe.whitelist()
def register_customers(outlet, query=""):
	"""Small, staff-only customer picker for named bills and loyalty."""
	_staff_outlet(outlet)
	query = str(query or "").strip()
	if len(query) < 2:
		return []
	if len(query) > 80:
		frappe.throw("Customer search is too long")
	like = f"%{query}%"
	return frappe.db.sql("""SELECT name, customer_name, mobile_no FROM `tabCustomer`
		WHERE disabled=0 AND (name LIKE %s OR customer_name LIKE %s OR mobile_no LIKE %s)
		ORDER BY customer_name LIMIT 20""", (like, like, like), as_dict=True)


@frappe.whitelist(methods=["POST"])
def configure_bill(order_name, config, event_id, expected_revision):
	"""Set one bill's customer, coupon or manager discount, and loyalty redemption."""
	_staff()
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	config = _payload(config)
	if not isinstance(config, dict) or not event_id:
		frappe.throw("Bill settings and event ID required")
	order = frappe.get_doc("TRT Order", order_name)
	_staff_outlet(order.outlet)
	root_name = _root_order_name(order_name) if order.channel == "Table" else order_name
	frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", root_name)
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id},
		["order", "payload_json"], as_dict=True)
	if prior:
		if prior.order != order_name or frappe.parse_json(prior.payload_json) != config:
			frappe.throw("Event ID belongs to another bill change")
		return _snapshot(frappe.get_doc("TRT Order", order_name))
	root = frappe.get_doc("TRT Order", root_name)
	if root.outlet != order.outlet or (order.channel == "Table" and root.table != order.table):
		frappe.throw("Ticket is outside this bill")
	if int(expected_revision) != root.revision:
		frappe.throw("Bill changed; refresh before retrying", frappe.TimestampMismatchError)
	if root.status in ("Settled", "Void"):
		frappe.throw("Paid or void bills cannot be changed")
	customer = config.get("customer") or _outlet(root.outlet).walk_in_customer
	if not customer or not frappe.db.exists("Customer", {"name": customer, "disabled": 0}):
		frappe.throw("Choose an enabled customer")
	coupon = str(config.get("coupon_code") or "").strip().upper()
	manual_type = config.get("manual_discount_type") or None
	manual_value = flt(config.get("manual_discount_value")) if manual_type else 0
	manual_reason = str(config.get("manual_discount_reason") or "").strip() if manual_type else None
	if coupon and manual_type:
		frappe.throw("Use either a coupon or a manual discount")
	if manual_type and manual_type not in ("Percentage", "Amount"):
		frappe.throw("Choose percentage or amount discount")
	manual_changed = (manual_type != root.manual_discount_type or
		manual_value != flt(root.manual_discount_value) or
		manual_reason != (root.manual_discount_reason or ""))
	if manual_changed and (manual_type or root.manual_discount_type):
		_staff({"System Manager", "TRT Manager"})
	try:
		points = int(config.get("loyalty_points") or 0)
	except (TypeError, ValueError):
		frappe.throw("Loyalty points must be a whole number")
	if points < 0:
		frappe.throw("Loyalty points cannot be negative")
	root.customer = customer
	root.promotion = coupon or None
	root.manual_discount_type = manual_type
	root.manual_discount_value = manual_value
	root.manual_discount_reason = manual_reason
	root.loyalty_points_to_redeem = points
	root.revision += 1
	root.save(ignore_permissions=True)
	result = _snapshot(frappe.get_doc("TRT Order", order_name))
	if result["bill"]["billing_errors"]:
		frappe.throw(result["bill"]["billing_errors"][0])
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": root.outlet, "register": root.register, "order": order_name,
		"event_type": "configure_bill", "payload_json": json.dumps(config),
		"status": "Applied", "received_at": now_datetime()}).insert(ignore_permissions=True)
	return result


@frappe.whitelist()
def checkout_options(outlet):
	_staff_outlet(outlet)
	settings = _outlet(outlet)
	profile = frappe.get_cached_doc("POS Profile", settings.pos_profile)
	modes = [payment.mode_of_payment for payment in profile.payments
		if frappe.db.get_value("Mode of Payment", payment.mode_of_payment, "type") == "Cash"]
	rate = frappe.get_all("TRT FX Rate", filters={"outlet": outlet, "enabled": 1,
		"effective_date": ["<=", frappe.utils.today()]},
		fields=["lbp_per_usd", "effective_date"], order_by="effective_date desc, modified desc", limit=1)
	return {"cash_modes": modes, "base_currency": settings.base_currency,
		"fx_rate": rate[0] if rate else None,
		"receipt_printer_available": bool(frappe.db.exists("TRT Device", {"outlet": outlet,
			"kind": "Receipt Printer", "enabled": 1})),
		"opening_entry": frappe.db.get_value("POS Opening Entry", {"pos_profile": profile.name,
			"status": "Open", "posting_date": frappe.utils.today()}, "name"),
		"pos_invoice_mode": frappe.db.get_single_value("POS Settings", "invoice_type") == "POS Invoice"}


@frappe.whitelist(methods=["POST"])
def print_receipt(order_name, copy=False):
	"""Print or reprint the invoice for a settled staff order."""
	order = frappe.get_doc("TRT Order", order_name)
	_staff_outlet(order.outlet)
	if order.status != "Settled" or not order.pos_invoice:
		frappe.throw("Pay the order before printing a receipt")
	device = configured_printer(order.outlet, order.register)
	if not device:
		frappe.throw("Configure an enabled Receipt Printer in TRT Device for this outlet")
	return print_invoice(order.pos_invoice, order.name, device, copy=frappe.utils.cint(copy) == 1)


@frappe.whitelist()
def cash_checkout(order_name, tenders, event_id, expected_revision):
	"""Settle a ticket, or the complete linked table session, in one POS Invoice."""
	_staff()
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	if not event_id:
		frappe.throw("Event ID required")
	tenders = frappe.parse_json(tenders) if isinstance(tenders, str) else tenders
	if not isinstance(tenders, list):
		frappe.throw("Cash tenders must be a list")
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id},
		["order", "payload_json"], as_dict=True)
	if prior:
		if prior.order != order_name or frappe.parse_json(prior.payload_json) != tenders:
			frappe.throw("Event ID belongs to another checkout")
		prior_order = frappe.get_doc("TRT Order", order_name)
		_staff_outlet(prior_order.outlet)
		return _snapshot(prior_order)
	order = frappe.get_doc("TRT Order", order_name)
	_staff_outlet(order.outlet)
	outlet = _outlet(order.outlet)
	if order.channel in ("QR", "Pickup", "Kiosk"):
		frappe.throw("Guest orders require online payment")
	if order.channel == "Table":
		# All table checkouts and add-on creates lock the root first. This makes
		# the ticket list stable while one invoice is created.
		root_name = _root_order_name(order.name)
		frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", root_name)
		order = frappe.get_doc("TRT Order", order_name)
		root = frappe.get_doc("TRT Order", root_name)
		if (root.outlet != order.outlet or root.table != order.table or root.channel != "Table"
			or root.status == "Void"):
			frappe.throw("Linked tickets cannot be combined")
		group = _table_session_orders(order, include_settled=True)
		ordered_names = [ticket.name for ticket in group]
		group_names = sorted(set(ordered_names))
		frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name IN %(names)s ORDER BY name FOR UPDATE",
			{"names": tuple(group_names)})
		group = [frappe.get_doc("TRT Order", name) for name in ordered_names]
		order = next(ticket for ticket in group if ticket.name == order_name)
	else:
		frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", order_name)
		order = frappe.get_doc("TRT Order", order_name)
		group = [order]
	# A concurrent checkout may have recorded this event while we waited for
	# the session lock; validate its payload before returning the paid bill.
	locked_prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id},
		["order", "payload_json"], as_dict=True)
	if locked_prior:
		if locked_prior.order != order_name or frappe.parse_json(locked_prior.payload_json) != tenders:
			frappe.throw("Event ID belongs to another checkout")
		return _snapshot(order)
	if all(ticket.status == "Settled" and ticket.pos_invoice for ticket in group):
		invoice_names = {ticket.pos_invoice for ticket in group}
		if len(invoice_names) == 1:
			return _snapshot(order)
	if any(ticket.status == "Settled" or ticket.pos_invoice for ticket in group):
		frappe.throw("This table session is already partially settled")
	if int(expected_revision) != order.revision:
		frappe.throw("Order changed; refresh before checkout", frappe.TimestampMismatchError)
	if any(ticket.status not in OPEN_ORDER_STATUSES for ticket in group) or not any(ticket.lines for ticket in group):
		frappe.throw("Order cannot be settled")
	if any(ticket.outlet != order.outlet or ticket.channel != order.channel or ticket.currency != order.currency
		for ticket in group):
		frappe.throw("Linked tickets cannot be combined")
	company_currency = frappe.db.get_value("Company", outlet.company, "default_currency")
	if order.currency != company_currency:
		frappe.throw("Outlet selling currency must match company currency for cash checkout")
	profile = frappe.get_doc("POS Profile", outlet.pos_profile)
	if profile.company != outlet.company:
		frappe.throw("POS Profile company does not match outlet")
	if frappe.db.get_single_value("POS Settings", "invoice_type") != "POS Invoice":
		frappe.throw("Set ERPNext POS Settings invoice type to POS Invoice before checkout")
	opening = frappe.db.get_value("POS Opening Entry", {"pos_profile": profile.name,
		"status": "Open", "posting_date": frappe.utils.today()}, "name")
	if not opening:
		frappe.throw("Open today's POS Opening Entry before checkout")
	base = order.currency
	fx = None
	if any(row.get("currency") != base for row in tenders):
		if {base, *(row.get("currency") for row in tenders)} - {"USD", "LBP"}:
			frappe.throw("Only USD/LBP mixed cash is configured")
		rates = frappe.get_all("TRT FX Rate", filters={"outlet": outlet.name,
			"enabled": 1, "effective_date": ["<=", frappe.utils.today()]},
			fields=["lbp_per_usd", "approved_by", "approved_on"],
			order_by="effective_date desc, modified desc", limit=1)
		if not rates or not rates[0].approved_by or not rates[0].approved_on or flt(rates[0].lbp_per_usd) <= 0:
			frappe.throw("Approved USD/LBP exchange rate required")
		fx = flt(rates[0].lbp_per_usd)
	root_order = next((ticket for ticket in group if not ticket.parent_order), group[0])
	if root_order.promotion:
		frappe.db.sql("SELECT name FROM `tabTRT Promotion` WHERE name=%s FOR UPDATE", root_order.promotion)
	if root_order.loyalty_points_to_redeem:
		frappe.db.sql("SELECT name FROM `tabCustomer` WHERE name=%s FOR UPDATE", root_order.customer)
	bill = _bill_snapshot(order)
	if bill["billing_errors"]:
		frappe.throw(bill["billing_errors"][0])
	bill_total = flt(bill["grand_total"])
	amount_due = flt(bill["amount_due"])
	if amount_due > 0 and not tenders:
		frappe.throw("At least one cash tender is required")
	amounts = {}
	converted = []
	for row in tenders:
		if not isinstance(row, dict) or flt(row.get("amount")) <= 0:
			frappe.throw("Tender amount must be positive")
		currency = row.get("currency")
		mode = row.get("mode_of_payment")
		if currency not in ("USD", "LBP") or frappe.db.get_value("Mode of Payment", mode, "type") != "Cash":
			frappe.throw("Tender must use a configured cash payment mode and USD/LBP")
		amount = flt(row["amount"])
		in_base = amount if currency == base else amount / fx if base == "USD" else amount * fx
		amounts[mode] = amounts.get(mode, 0) + in_base
		converted.append((mode, currency, amount))
	invoice = frappe.new_doc("POS Invoice")
	invoice.company = outlet.company
	invoice.customer = root_order.customer or outlet.walk_in_customer or profile.customer
	invoice.debit_to = outlet.receivable_account or frappe.db.get_value(
		"Company", outlet.company, "default_receivable_account")
	if not invoice.debit_to or frappe.db.get_value("Account", invoice.debit_to, "company") != outlet.company:
		frappe.throw("Configure an outlet receivable account in the same company")
	invoice.pos_profile = profile.name
	invoice.is_pos = 1
	invoice.currency = base
	invoice.selling_price_list = outlet.price_list
	invoice.set_warehouse = outlet.warehouse
	if order.channel == "Table":
		ticket_numbers = ", ".join(ticket.order_number for ticket in group)
		invoice.remarks = f"S&S (Seat & Serve) table {order.table}; tickets {ticket_numbers}; cashier {frappe.session.user}"
	else:
		invoice.remarks = f"S&S (Seat & Serve) order {order.order_number}; cashier {frappe.session.user}"
	if root_order.promotion:
		invoice.remarks += f"; coupon {root_order.promotion}"
	elif root_order.manual_discount_type:
		invoice.remarks += f"; manager discount: {root_order.manual_discount_reason}"
	if root_order.loyalty_points_to_redeem:
		invoice.remarks += f"; loyalty {root_order.loyalty_points_to_redeem} points"
	all_lines = [line for ticket in group for line in ticket.lines]
	for line in all_lines:
		invoice.append("items", {"item_code": line.item, "item_name": line.item_name,
			"qty": line.qty, "rate": line.rate, "warehouse": outlet.warehouse})
	# ERPNext's party detail loader checks Account permissions even for an exact,
	# server-selected receivable account. Populate those internals with the trusted
	# service identity, then restore the cashier before writing the invoice.
	actor = frappe.session.user
	try:
		frappe.set_user("Administrator")
		invoice.set_missing_values()
	finally:
		frappe.set_user(actor)
	invoice.ignore_pricing_rule = 1
	if outlet.tax_template and invoice.taxes_and_charges != outlet.tax_template:
		invoice.taxes_and_charges = outlet.tax_template
		invoice.set("taxes", [])
		invoice.set_taxes()
	_use_tax_inclusive_prices(invoice)
	for item, line in zip(invoice.items, all_lines, strict=True):
		item.rate = line.rate
		item.price_list_rate = line.rate
	invoice.calculate_taxes_and_totals()
	if bill["discount_amount"] or bill["loyalty"]["amount"]:
		invoice.apply_discount_on = "Grand Total"
		invoice.discount_amount = flt(bill["discount_amount"]) + flt(bill["loyalty"]["amount"])
		invoice.calculate_taxes_and_totals()
	if bill["loyalty"]["program"]:
		invoice.loyalty_program = bill["loyalty"]["program"]
	if bill["loyalty"]["points"]:
		invoice.loyalty_points = bill["loyalty"]["points"]
	invoice_total = flt(invoice.rounded_total or invoice.grand_total)
	if abs(invoice_total - flt(bill_total)) > (0.01 if base == "USD" else 1):
		frappe.throw("Invoice price or tax changed; refresh order before checkout")
	if abs(sum(amounts.values()) - amount_due) > (0.01 if base == "USD" else 1):
		frappe.throw("Cash tender must equal the remaining amount after loyalty redemption")
	profile_modes = {payment.mode_of_payment: payment for payment in invoice.payments}
	if not set(amounts).issubset(profile_modes):
		frappe.throw("Cash mode is not enabled in this POS Profile")
	for payment in invoice.payments:
		payment.amount = amounts.get(payment.mode_of_payment, 0)
	# Loyalty is entered after POS defaults are loaded. Recalculate the paid total
	# with both tender rows and ERPNext's loyalty credit before invoice validation.
	invoice.calculate_taxes_and_totals()
	actor = frappe.session.user
	try:
		frappe.set_user("Administrator")
		invoice.insert(ignore_permissions=True)
		invoice.flags.ignore_permissions = True
		invoice.submit()
	finally:
		frappe.set_user(actor)
	if bill["loyalty"]["points"]:
		# ERPNext POS Invoice's before_save counts payment rows but excludes native
		# loyalty credit, so native redemption fails full-payment validation. Apply
		# the credit as a tax-aware invoice discount and use ERPNext's point ledger.
		invoice.apply_loyalty_points()
		root_order.loyalty_amount_redeemed = bill["loyalty"]["amount"]
	if root_order.promotion:
		frappe.get_doc({"doctype": "TRT Promotion Redemption",
			"promotion": root_order.promotion, "order": root_order.name,
			"pos_invoice": invoice.name, "customer": root_order.customer,
			"redeemed_at": now_datetime()}).insert(ignore_permissions=True)
	for index, (mode, currency, amount) in enumerate(converted):
		frappe.get_doc({"doctype": "TRT Payment Attempt", "order": root_order.name,
			"mode": "Cash", "currency": currency, "amount": amount,
			"exchange_rate": fx or 1, "status": "Captured", "provider": mode,
			"idempotency_key": f"{event_id}:{index}", "pos_invoice": invoice.name,
			"order_revision": root_order.revision}).insert(ignore_permissions=True)
	for ticket in group:
		if ticket.status == "Draft":
			_release_kitchen(ticket)
		ticket.status = "Settled"
		ticket.pos_invoice = invoice.name
		ticket.exchange_rate = fx or 1
		ticket.revision += 1
		ticket.save(ignore_permissions=True)
	if root_order.reservation:
		booking = frappe.get_doc("TRT Reservation", root_order.reservation)
		if booking.status == "Seated" and booking.order == root_order.name:
			booking.status = "Completed"
			booking.save(ignore_permissions=True)
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": order.outlet, "register": order.register, "order": order.name,
		"event_type": "cash_checkout", "payload_json": json.dumps(tenders),
		"status": "Applied", "received_at": now_datetime()}).insert(ignore_permissions=True)
	return _snapshot(order)


@frappe.whitelist()
def return_order(order_name, event_id, expected_revision):
	"""Create one full POS Invoice return for a settled till order.

	Partial line returns need a return-specific quantity and stock policy, so the
	first release deliberately accepts only a full invoice return. ERPNext owns
	tax, stock, payment reversal, and duplicate-return validation.
	"""
	_staff()
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	if not event_id:
		frappe.throw("Event ID required")
	payload = {"order": order_name, "kind": "full_return"}
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id},
		["order", "payload_json"], as_dict=True)
	if prior:
		stored = frappe.parse_json(prior.payload_json)
		if prior.order != order_name or stored.get("order") != order_name or stored.get("kind") != "full_return":
			frappe.throw("Event ID belongs to another return")
		return stored.get("result") or {
			"order": order_name, "status": "Returned",
		}
	frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", order_name)
	order = frappe.get_doc("TRT Order", order_name)
	_staff_outlet(order.outlet)
	if int(expected_revision) != order.revision:
		frappe.throw("Order changed; refresh before return", frappe.TimestampMismatchError)
	if order.status != "Settled" or not order.pos_invoice:
		frappe.throw("Only a settled order can be returned")
	if frappe.db.exists("POS Invoice", {"name": order.pos_invoice, "docstatus": 0}):
		frappe.throw("The source POS Invoice is not submitted")
	if frappe.db.exists("POS Invoice", {"return_against": order.pos_invoice, "docstatus": 1}):
		frappe.throw("This POS Invoice has already been returned")
	source = frappe.get_doc("POS Invoice", order.pos_invoice)
	if source.docstatus != 1 or source.is_return:
		frappe.throw("The source POS Invoice cannot be returned")
	from erpnext.accounts.doctype.pos_invoice.pos_invoice import make_sales_return
	actor = frappe.session.user
	try:
		# ERPNext validates the source, derives negative items/payments, and
		# posts the stock and accounting reversal under the service identity.
		frappe.set_user("Administrator")
		return_doc = make_sales_return(source.name)
		return_doc.remarks = f"S&S (Seat & Serve) full return for order {order.order_number}"
		return_doc.insert(ignore_permissions=True)
		return_doc.submit()
	finally:
		frappe.set_user(actor)
	order.revision += 1
	order.save(ignore_permissions=True)
	result = {"order": order.name, "status": "Returned", "return_invoice": return_doc.name,
		"revision": order.revision}
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": order.outlet, "register": order.register, "order": order.name,
		"event_type": "return", "payload_json": json.dumps({**payload, "result": result}),
		"status": "Applied", "received_at": now_datetime()}).insert(ignore_permissions=True)
	return result


@frappe.whitelist(allow_guest=True)
def payment_intent(order_name, idempotency_key, expected_revision, guest_token=None):
	"""Create a sandbox intent; live providers must implement this interface."""
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	order = frappe.get_doc("TRT Order", order_name)
	scope = _authorize(order.outlet, order.channel, guest_token)
	if scope and order.guest_session != scope.get("session"):
		frappe.throw("Order does not belong to ordering session", frappe.PermissionError)
	if int(expected_revision) != order.revision:
		frappe.throw("Order changed; refresh before payment", frappe.TimestampMismatchError)
	if order.status != "Draft" or not order.lines or flt(order.grand_total) <= 0:
		frappe.throw("Order is not ready for online payment")
	prior = frappe.db.get_value("TRT Payment Attempt", {"idempotency_key": idempotency_key}, "name")
	if prior:
		attempt = frappe.get_doc("TRT Payment Attempt", prior)
		if attempt.order != order.name:
			frappe.throw("Payment key belongs to another order")
		return {"attempt": prior, "provider": attempt.provider, "status": attempt.status}
	outlet = _outlet(order.outlet)
	provider = configured_provider(outlet)
	intent = provider.create_intent(amount=flt(order.grand_total), currency=order.currency,
		key=idempotency_key)
	attempt = frappe.get_doc({"doctype": "TRT Payment Attempt", "order": order.name,
		"mode": "Online", "currency": order.currency, "amount": order.grand_total,
		"exchange_rate": order.exchange_rate, "status": intent.status, "provider": intent.provider,
		"provider_reference": intent.provider_reference,
		"idempotency_key": idempotency_key, "order_revision": order.revision}).insert(ignore_permissions=True)
	return {"attempt": attempt.name, "provider": intent.provider, "status": attempt.status,
		"checkout_url": intent.checkout_url}


@frappe.whitelist(allow_guest=True)
def sandbox_capture(attempt_name, expected_revision, guest_token=None):
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	attempt = frappe.get_doc("TRT Payment Attempt", attempt_name)
	frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", attempt.order)
	order = frappe.get_doc("TRT Order", attempt.order)
	scope = _authorize(order.outlet, order.channel, guest_token)
	if scope and order.guest_session != scope.get("session"):
		frappe.throw("Order does not belong to ordering session", frappe.PermissionError)
	outlet = _outlet(order.outlet)
	provider = configured_provider(outlet)
	if attempt.provider != "Sandbox" or provider.name != "Sandbox":
		frappe.throw("Sandbox payment is disabled", frappe.PermissionError)
	if attempt.status == "Captured":
		return {"attempt": attempt.name, "order": order.name, "status": order.status}
	if int(expected_revision) != order.revision:
		frappe.throw("Order changed; refresh before payment", frappe.TimestampMismatchError)
	if attempt.status != "Pending" or order.status != "Draft" or flt(attempt.amount) != flt(order.grand_total):
		frappe.throw("Payment no longer matches this order")
	if attempt.order_revision != order.revision:
		frappe.throw("Payment intent is for an earlier order revision")
	attempt.status = provider.capture(reference=attempt.provider_reference,
		amount=flt(attempt.amount), currency=attempt.currency)
	attempt.save(ignore_permissions=True)
	order.status = "Sent"
	order.revision += 1
	_release_kitchen(order)
	order.save(ignore_permissions=True)
	frappe.publish_realtime("trt_order", {"order": order.name, "revision": order.revision}, after_commit=True)
	return {"attempt": attempt.name, "order": order.name, "status": order.status}


@frappe.whitelist()
def kitchen_tickets(outlet, status="Queued"):
	_staff_outlet(outlet, "allow_kitchen")
	station_rows = frappe.get_all("TRT Kitchen Station", filters={"outlet": outlet},
		fields=["name", "title"])
	stations = {row.name: row.title for row in station_rows}
	if not stations:
		return []
	filters = {"station": ["in", list(stations)]}
	if status != "All":
		filters["status"] = status
	rows = frappe.get_all("TRT Kitchen Ticket", filters=filters,
		fields=["name", "order", "station", "status", "revision", "sent_at"], order_by="creation asc")
	order_names = list({row.order for row in rows})
	order_details = {
		row.name: row for row in frappe.get_all(
			"TRT Order", filters={"name": ["in", order_names]},
			fields=["name", "order_number", "channel", "table", "parent_order", "tab_label",
				"runner_dispatched_at", "runner_dispatched_by"],
		)
	} if order_names else {}
	parent_names = list({row.parent_order for row in order_details.values() if row.parent_order})
	parent_numbers = {row.name: row.order_number for row in frappe.get_all(
		"TRT Order", filters={"name": ["in", parent_names]}, fields=["name", "order_number"]
	)} if parent_names else {}
	table_names = list({row.table for row in order_details.values() if row.table})
	table_titles = {row.name: row.title for row in frappe.get_all(
		"TRT Table", filters={"name": ["in", table_names]}, fields=["name", "title"]
	)} if table_names else {}
	lines_by_ticket = {}
	item_codes = set()
	order_line_names = set()
	if rows:
		for line in frappe.get_all("TRT Ticket Line", filters={"parent": ["in", [row.name for row in rows]]},
			fields=["name", "parent", "order_line", "item", "qty", "note", "status"], order_by="parent asc, idx asc"):
			lines_by_ticket.setdefault(line.parent, []).append(line)
			item_codes.add(line.item)
			if line.order_line:
				order_line_names.add(line.order_line)
	order_line_titles = {row.name: row.item_name for row in frappe.get_all(
		"TRT Order Line", filters={"name": ["in", list(order_line_names)]},
		fields=["name", "item_name"])} if order_line_names else {}
	item_names = {row.name: row.item_name for row in frappe.get_all(
		"Item", filters={"name": ["in", list(item_codes)]}, fields=["name", "item_name"]
	)} if item_codes else {}
	for row in rows:
		order = order_details.get(row.order)
		row["channel"] = order.channel if order else ""
		row["order_number"] = order.order_number if order else ""
		row["parent_order_number"] = parent_numbers.get(order.parent_order, "") if order else ""
		row["table"] = order.table if order else ""
		row["tab_label"] = order.tab_label if order else ""
		row["table_title"] = table_titles.get(row["table"], row["table"])
		row["station_title"] = stations.get(row.station, row.station)
		row["runner_dispatched_at"] = order.runner_dispatched_at if order else None
		row["runner_dispatched_by"] = order.runner_dispatched_by if order else None
		row["lines"] = lines_by_ticket.get(row.name, [])
		for line in row["lines"]:
			line["item_name"] = order_line_titles.get(line.order_line) or item_names.get(line.item, line.item)
			line["status"] = line.status or (row.status if row.status in ("Preparing", "Ready", "Served") else "Queued")
	return rows


KITCHEN_LINE_STATUSES = ("Queued", "Preparing", "Ready", "Served")


def _kitchen_line_status(line, ticket):
	return line.status or (ticket.status if ticket.status in KITCHEN_LINE_STATUSES else "Queued")


def _roll_up_ticket(ticket):
	statuses = [_kitchen_line_status(line, ticket) for line in ticket.lines]
	if not statuses:
		return ticket.status
	if all(status == "Served" for status in statuses):
		return "Served"
	if all(status in ("Ready", "Served") for status in statuses):
		return "Ready"
	if any(status != "Queued" for status in statuses):
		return "Preparing"
	return "Queued"


def _roll_up_order(order):
	if order.status in ("Draft", "Settled", "Void"):
		return
	statuses = frappe.get_all("TRT Kitchen Ticket", filters={"order": order.name,
		"status": ["!=", "Cancelled"]}, pluck="status")
	if not statuses:
		return
	if all(status == "Served" for status in statuses):
		new_status = "Served"
	elif all(status in ("Ready", "Served") for status in statuses):
		new_status = "Ready"
	elif any(status != "Queued" for status in statuses):
		new_status = "Preparing"
	else:
		new_status = "Sent"
	if order.status != new_status:
		order.status = new_status
		order.save(ignore_permissions=True)
		frappe.publish_realtime("trt_order", {"order": order.name, "status": new_status}, after_commit=True)


@frappe.whitelist()
def set_kitchen_line_status(ticket_name, line_name, status, event_id, expected_revision):
	"""Change one preparation line and derive its ticket and order status."""
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	if status not in KITCHEN_LINE_STATUSES or not event_id:
		frappe.throw("Invalid item status")
	lookup = frappe.db.get_value("TRT Kitchen Ticket", ticket_name, ["order", "station"], as_dict=True)
	if not lookup:
		frappe.throw("Ticket not found")
	station_outlet = frappe.db.get_value("TRT Kitchen Station", lookup.station, "outlet")
	_staff_outlet(station_outlet, "allow_kitchen")
	frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", lookup.order)
	frappe.db.sql("SELECT name FROM `tabTRT Kitchen Ticket` WHERE name=%s FOR UPDATE", ticket_name)
	ticket = frappe.get_doc("TRT Kitchen Ticket", ticket_name)
	if ticket.order != lookup.order or ticket.station != lookup.station:
		frappe.throw("Ticket changed; refresh before retrying", frappe.TimestampMismatchError)
	payload = {"ticket": ticket_name, "line": line_name, "status": status}
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id}, "payload_json")
	if prior:
		if frappe.parse_json(prior) != payload:
			frappe.throw("Event ID belongs to another command")
		return {"name": ticket.name, "status": ticket.status, "revision": ticket.revision}
	if int(expected_revision) != ticket.revision:
		frappe.throw("Ticket changed; refresh before retrying", frappe.TimestampMismatchError)
	if ticket.status == "Cancelled":
		frappe.throw("Cancelled tickets cannot be changed")
	if frappe.db.get_value("TRT Order", ticket.order, "status") == "Void":
		frappe.throw("Voided orders cannot be changed")
	line = next((row for row in ticket.lines if row.name == line_name), None)
	if not line:
		frappe.throw("Item is not on this ticket")
	for row in ticket.lines:
		row.status = _kitchen_line_status(row, ticket)
	line.status = status
	ticket.status = _roll_up_ticket(ticket)
	ticket.revision += 1
	ticket.save(ignore_permissions=True)
	order = frappe.get_doc("TRT Order", ticket.order)
	_roll_up_order(order)
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": order.outlet, "order": order.name, "event_type": "kitchen_line_status",
		"payload_json": json.dumps(payload), "status": "Applied",
		"received_at": now_datetime()}).insert(ignore_permissions=True)
	frappe.publish_realtime("trt_kitchen", {"ticket": ticket.name, "status": ticket.status}, after_commit=True)
	return {"name": ticket.name, "status": ticket.status, "revision": ticket.revision}


@frappe.whitelist()
def kitchen_order_action(order_name, action, event_id):
	"""One-tap kitchen actions across all station tickets of an order."""
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	if action not in ("start", "ready", "dispatch_runner", "served") or not event_id:
		frappe.throw("Invalid kitchen action")
	frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", order_name)
	order = frappe.get_doc("TRT Order", order_name)
	_staff_outlet(order.outlet, "allow_kitchen")
	payload = {"order": order_name, "action": action}
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id}, "payload_json")
	if prior:
		if frappe.parse_json(prior) != payload:
			frappe.throw("Event ID belongs to another command")
		return {"name": order.name, "status": order.status,
			"runner_dispatched_at": order.runner_dispatched_at}
	if order.status == "Void":
		frappe.throw("Voided orders cannot be changed")
	ticket_names = frappe.get_all("TRT Kitchen Ticket", filters={"order": order.name,
		"status": ["!=", "Cancelled"]}, pluck="name", order_by="name asc")
	if not ticket_names:
		frappe.throw("Order has no active kitchen tickets")
	for name in ticket_names:
		frappe.db.sql("SELECT name FROM `tabTRT Kitchen Ticket` WHERE name=%s FOR UPDATE", name)
	tickets = [frappe.get_doc("TRT Kitchen Ticket", name) for name in ticket_names]
	statuses = [_kitchen_line_status(line, ticket) for ticket in tickets for line in ticket.lines]
	if action in ("dispatch_runner", "served") and (
		not statuses or any(status not in ("Ready", "Served") for status in statuses)):
		frappe.throw("All items must be ready first")
	if action == "dispatch_runner":
		if not order.runner_dispatched_at:
			order.runner_dispatched_at = now_datetime()
			order.runner_dispatched_by = frappe.session.user
			order.save(ignore_permissions=True)
	else:
		changed = False
		for ticket in tickets:
			before = ticket.status
			ticket_changed = False
			for line in ticket.lines:
				current = _kitchen_line_status(line, ticket)
				target = ("Preparing" if current == "Queued" else current) if action == "start" else (
					"Ready" if current in ("Queued", "Preparing") else current) if action == "ready" else "Served"
				line.status = target
				ticket_changed |= target != current
			ticket.status = _roll_up_ticket(ticket)
			if ticket.status != before or ticket_changed:
				ticket.revision += 1
				ticket.save(ignore_permissions=True)
				changed = True
		if changed:
			_roll_up_order(order)
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": order.outlet, "order": order.name, "event_type": "kitchen_order_action",
		"payload_json": json.dumps(payload), "status": "Applied",
		"received_at": now_datetime()}).insert(ignore_permissions=True)
	frappe.publish_realtime("trt_kitchen", {"order": order.name, "action": action}, after_commit=True)
	return {"name": order.name, "status": order.status,
		"runner_dispatched_at": order.runner_dispatched_at}


@frappe.whitelist()
def set_ticket_status(ticket_name, status, event_id, expected_revision):
	_staff(KITCHEN_ROLES)
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	if status not in ("Preparing", "Ready", "Served", "Cancelled") or not event_id:
		frappe.throw("Invalid ticket status")
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id}, "payload_json")
	if prior:
		payload = frappe.parse_json(prior)
		if payload.get("ticket") != ticket_name or payload.get("status") != status:
			frappe.throw("Event ID belongs to another command")
		ticket = frappe.get_doc("TRT Kitchen Ticket", ticket_name)
		_staff_outlet(frappe.db.get_value("TRT Kitchen Station", ticket.station, "outlet"), "allow_kitchen")
		return {"name": ticket.name, "status": ticket.status, "revision": ticket.revision}
	lookup = frappe.db.get_value("TRT Kitchen Ticket", ticket_name, ["order", "station"], as_dict=True)
	if not lookup:
		frappe.throw("Ticket not found")
	_staff_outlet(frappe.db.get_value("TRT Kitchen Station", lookup.station, "outlet"), "allow_kitchen")
	frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", lookup.order)
	frappe.db.sql("SELECT name FROM `tabTRT Kitchen Ticket` WHERE name=%s FOR UPDATE", ticket_name)
	ticket = frappe.get_doc("TRT Kitchen Ticket", ticket_name)
	if ticket.order != lookup.order or ticket.station != lookup.station:
		frappe.throw("Ticket changed; refresh before retrying", frappe.TimestampMismatchError)
	if int(expected_revision) != ticket.revision:
		frappe.throw("Ticket changed; refresh before retrying", frappe.TimestampMismatchError)
	allowed = {"Queued": "Preparing", "Preparing": "Ready", "Ready": "Served"}
	if status == "Cancelled":
		_staff({"System Manager", "TRT Manager"})
	elif allowed.get(ticket.status) != status:
		frappe.throw("Invalid preparation transition")
	ticket.status = status
	if status in KITCHEN_LINE_STATUSES:
		for line in ticket.lines:
			line.status = status
	ticket.revision += 1
	ticket.save(ignore_permissions=True)
	order = frappe.get_doc("TRT Order", ticket.order)
	_roll_up_order(order)
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": order.outlet, "order": order.name, "event_type": "ticket_status",
		"payload_json": json.dumps({"ticket": ticket_name, "status": status}),
		"status": "Applied", "received_at": now_datetime()}).insert(ignore_permissions=True)
	frappe.publish_realtime("trt_kitchen", {"ticket": ticket.name, "status": status}, after_commit=True)
	return {"name": ticket.name, "status": ticket.status, "revision": ticket.revision}
