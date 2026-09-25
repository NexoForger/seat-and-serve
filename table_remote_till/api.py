"""POS commands. All writes are server priced, version checked, and idempotent."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time

import frappe
from frappe.utils import flt, now_datetime
from frappe.utils.password import get_encryption_key
from table_remote_till.payments import configured_provider


STAFF_ROLES = {"System Manager", "TRT Manager", "TRT Cashier"}
KITCHEN_ROLES = STAFF_ROLES | {"TRT Kitchen"}
ORDER_FIELDS = [
	"name", "outlet", "register", "channel", "table", "tab_label", "customer", "status",
	"currency", "exchange_rate", "net_total", "tax_total", "grand_total", "revision", "pos_invoice",
]


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


def _snapshot(order):
	data = {key: order.get(key) for key in ORDER_FIELDS}
	data["lines"] = [
		{
			"name": line.name, "item": line.item, "item_name": line.item_name,
			"qty": line.qty, "rate": line.rate, "amount": line.amount,
			"station": line.station, "note": line.note,
		}
		for line in order.lines
	]
	return data


def _reprice(order, outlet):
	"""Use ERPNext's own POS invoice calculator as the quote source."""
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
	invoice.ignore_pricing_rule = 1
	for item, line in zip(invoice.items, order.lines, strict=True):
		item.rate = line.rate
		item.price_list_rate = line.rate
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
		ticket = frappe.get_doc({"doctype": "TRT Kitchen Ticket", "order": order.name,
			"station": station, "status": "Queued", "revision": 1, "sent_at": now_datetime()})
		for line in lines:
			ticket.append("lines", {"order_line": line.name, "item": line.item,
				"qty": line.qty, "note": line.note})
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
			fields=["name", "title", "company", "base_currency", "cash_currency", "enable_tables", "enable_tabs", "enable_retail"],
		),
	}


@frappe.whitelist(allow_guest=True)
def public_outlets(channel="Pickup"):
	if channel not in ("Pickup", "Kiosk", "QR"):
		frappe.throw("Invalid public channel")
	flag = {"Pickup": "enable_pickup", "Kiosk": "enable_kiosk", "QR": "enable_qr"}[channel]
	return frappe.get_all("TRT Outlet", filters={"enabled": 1, flag: 1},
		fields=["name", "title", "base_currency"])


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
			items.append({
				"item": row.item, "name_en": row.name_en or name,
				"name_ar": row.name_ar, "category": row.category,
				"rate": flt(row.price_override) if flt(row.price_override) > 0 else rate,
				"station": row.station,
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
		stored = frappe.db.get_value("TRT Table", table, ["outlet", "qr_secret"], as_dict=True)
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
		"table": table, "session": secrets.token_urlsafe(18)})}


@frappe.whitelist(allow_guest=True)
def order_command(command, event_id, order_name=None, expected_revision=None, guest_token=None):
	"""Apply one idempotent command; Frappe commits the POST as one transaction."""
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	command = _payload(command)
	if not isinstance(command, dict) or not event_id:
		frappe.throw("Command object and event ID required")
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id},
		["order", "payload_json"], as_dict=True)
	if prior:
		if frappe.parse_json(prior.payload_json) != command:
			frappe.throw("Event ID belongs to another command")
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
		if command.get("register") and frappe.db.get_value("TRT Register", command["register"], "outlet") != outlet.name:
			frappe.throw("Register is outside outlet")
		order = frappe.new_doc("TRT Order")
		order.update({
			"outlet": outlet.name, "register": command.get("register"), "channel": channel,
			"table": command.get("table"), "tab_label": command.get("tab_label"),
			"customer": (command.get("customer") if not scope else None) or outlet.walk_in_customer,
			"exchange_rate": 1, "status": "Draft", "revision": 1,
			"guest_session": scope.get("session") if scope else None,
		})
		if scope and order.table != scope.get("table"):
			frappe.throw("Table does not match ordering link", frappe.PermissionError)
		if order.table and frappe.db.get_value("TRT Table", order.table, "outlet") != outlet.name:
			frappe.throw("Table is outside outlet")
		order.insert(ignore_permissions=True)
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
			order.append("lines", {"item": item_code, "item_name": name, "qty": qty,
				"rate": rate, "amount": qty * rate, "station": entry.station if entry else None,
				"note": command.get("note")})
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
		"opening_entry": frappe.db.get_value("POS Opening Entry", {"pos_profile": profile.name,
			"status": "Open", "posting_date": frappe.utils.today()}, "name"),
		"pos_invoice_mode": frappe.db.get_single_value("POS Settings", "invoice_type") == "POS Invoice"}


@frappe.whitelist()
def cash_checkout(order_name, tenders, event_id, expected_revision):
	"""Settle exact cash tender through an ERPNext POS Invoice and open session."""
	_staff()
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	if not event_id:
		frappe.throw("Event ID required")
	tenders = _payload(tenders)
	if not isinstance(tenders, list) or not tenders:
		frappe.throw("At least one cash tender is required")
	prior = frappe.db.get_value("TRT Sync Event", {"event_id": event_id},
		["order", "payload_json"], as_dict=True)
	if prior:
		if prior.order != order_name or frappe.parse_json(prior.payload_json) != tenders:
			frappe.throw("Event ID belongs to another checkout")
		prior_order = frappe.get_doc("TRT Order", order_name)
		_staff_outlet(prior_order.outlet)
		return _snapshot(prior_order)
	frappe.db.sql("SELECT name FROM `tabTRT Order` WHERE name=%s FOR UPDATE", order_name)
	order = frappe.get_doc("TRT Order", order_name)
	_staff_outlet(order.outlet)
	if int(expected_revision) != order.revision:
		frappe.throw("Order changed; refresh before checkout", frappe.TimestampMismatchError)
	if order.status not in ("Draft", "Sent") or not order.lines or order.pos_invoice:
		frappe.throw("Order cannot be settled")
	outlet = _outlet(order.outlet)
	if order.channel in ("QR", "Pickup", "Kiosk"):
		frappe.throw("Guest orders require online payment")
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
	if abs(sum(amounts.values()) - flt(order.grand_total)) > (0.01 if base == "USD" else 1):
		frappe.throw("Cash tender must equal the server-calculated total")
	invoice = frappe.new_doc("POS Invoice")
	invoice.company = outlet.company
	invoice.customer = order.customer or outlet.walk_in_customer or profile.customer
	invoice.debit_to = outlet.receivable_account or frappe.db.get_value(
		"Company", outlet.company, "default_receivable_account")
	if not invoice.debit_to or frappe.db.get_value("Account", invoice.debit_to, "company") != outlet.company:
		frappe.throw("Configure an outlet receivable account in the same company")
	invoice.pos_profile = profile.name
	invoice.is_pos = 1
	invoice.currency = base
	invoice.selling_price_list = outlet.price_list
	invoice.set_warehouse = outlet.warehouse
	invoice.remarks = f"Table Remote Till order {order.name}; cashier {frappe.session.user}"
	for line in order.lines:
		invoice.append("items", {"item_code": line.item, "qty": line.qty,
			"rate": line.rate, "warehouse": outlet.warehouse})
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
	for item, line in zip(invoice.items, order.lines, strict=True):
		item.rate = line.rate
		item.price_list_rate = line.rate
	invoice.calculate_taxes_and_totals()
	if abs(flt(invoice.rounded_total or invoice.grand_total) - flt(order.grand_total)) > 0.01:
		frappe.throw("Invoice price or tax changed; refresh order before checkout")
	profile_modes = {payment.mode_of_payment: payment for payment in invoice.payments}
	if not set(amounts).issubset(profile_modes):
		frappe.throw("Cash mode is not enabled in this POS Profile")
	for payment in invoice.payments:
		payment.amount = amounts.get(payment.mode_of_payment, 0)
	actor = frappe.session.user
	try:
		frappe.set_user("Administrator")
		invoice.insert(ignore_permissions=True)
		invoice.flags.ignore_permissions = True
		invoice.submit()
	finally:
		frappe.set_user(actor)
	for index, (mode, currency, amount) in enumerate(converted):
		frappe.get_doc({"doctype": "TRT Payment Attempt", "order": order.name,
			"mode": "Cash", "currency": currency, "amount": amount,
			"exchange_rate": fx or 1, "status": "Captured", "provider": mode,
			"idempotency_key": f"{event_id}:{index}", "pos_invoice": invoice.name,
			"order_revision": order.revision}).insert(ignore_permissions=True)
	if order.status == "Draft":
		_release_kitchen(order)
	order.status = "Settled"
	order.pos_invoice = invoice.name
	order.exchange_rate = fx or 1
	order.revision += 1
	order.save(ignore_permissions=True)
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
		return_doc.remarks = f"Table Remote Till full return for order {order.name}"
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
	stations = frappe.get_all("TRT Kitchen Station", filters={"outlet": outlet}, pluck="name")
	if not stations:
		return []
	filters = {"station": ["in", stations]}
	if status != "All":
		filters["status"] = status
	rows = frappe.get_all("TRT Kitchen Ticket", filters=filters,
		fields=["name", "order", "station", "status", "revision", "sent_at"], order_by="creation asc")
	for row in rows:
		row["lines"] = frappe.get_all("TRT Ticket Line", filters={"parent": row.name},
			fields=["item", "qty", "note"], order_by="idx asc")
	return rows


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
	frappe.db.sql("SELECT name FROM `tabTRT Kitchen Ticket` WHERE name=%s FOR UPDATE", ticket_name)
	ticket = frappe.get_doc("TRT Kitchen Ticket", ticket_name)
	_staff_outlet(frappe.db.get_value("TRT Kitchen Station", ticket.station, "outlet"), "allow_kitchen")
	if int(expected_revision) != ticket.revision:
		frappe.throw("Ticket changed; refresh before retrying", frappe.TimestampMismatchError)
	allowed = {"Queued": "Preparing", "Preparing": "Ready", "Ready": "Served"}
	if status == "Cancelled":
		_staff({"System Manager", "TRT Manager"})
	elif allowed.get(ticket.status) != status:
		frappe.throw("Invalid preparation transition")
	ticket.status = status
	ticket.revision += 1
	ticket.save(ignore_permissions=True)
	order = frappe.get_doc("TRT Order", ticket.order)
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": event_id,
		"outlet": order.outlet, "order": order.name, "event_type": "ticket_status",
		"payload_json": json.dumps({"ticket": ticket_name, "status": status}),
		"status": "Applied", "received_at": now_datetime()}).insert(ignore_permissions=True)
	frappe.publish_realtime("trt_kitchen", {"ticket": ticket.name, "status": status}, after_commit=True)
	return {"name": ticket.name, "status": ticket.status, "revision": ticket.revision}
