"""Manager-only quick creation of priced till items with optional recipes."""
import hashlib
import json
import math
import uuid

import frappe
from frappe.utils import now_datetime, today

from table_remote_till.api import _as_admin, _outlet, _payload, _staff, _staff_outlet


def _manager(outlet):
	_staff({"System Manager", "TRT Manager"})
	_staff_outlet(outlet, ability="allow_manager")
	return _outlet(outlet)


def _number(value, label, positive=False):
	try:
		if value is None or isinstance(value, bool) or value == "":
			raise ValueError
		value = float(value)
	except (TypeError, ValueError, OverflowError):
		frappe.throw(f"Enter a valid {label}")
	if not math.isfinite(value) or value < 0 or (positive and value == 0):
		frappe.throw(f"{label} must be {'positive' if positive else 'non-negative'}")
	return value


def _recipe(rows):
	if rows is None or rows == []:
		return None
	if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
		frappe.throw("Add between 1 and 100 ingredients for one sale unit")
	result = []
	seen = set()
	for row in rows:
		if not isinstance(row, dict) or not isinstance(row.get("item"), str):
			frappe.throw("Choose an ingredient")
		code = row["item"]
		if code in seen:
			frappe.throw("Combine repeated ingredients into one quantity")
		seen.add(code)
		item = frappe.db.get_value("Item", code, ["stock_uom", "disabled", "is_stock_item",
			"is_purchase_item", "is_sales_item", "include_item_in_manufacturing", "has_variants"], as_dict=True)
		if not item or item.disabled or item.has_variants or not (item.is_stock_item and item.is_purchase_item
			and item.include_item_in_manufacturing and not item.is_sales_item):
			frappe.throw("Choose an enabled, purchasable raw material")
		qty = _number(row.get("qty"), "ingredient quantity", positive=True)
		if frappe.db.get_value("UOM", item.stock_uom, "must_be_whole_number") and not qty.is_integer():
			frappe.throw(f"{code} requires a whole-number quantity")
		result.append({"item_code": code, "qty": qty, "uom": item.stock_uom})
	return result


@frappe.whitelist()
def item_options(outlet):
	settings = _manager(outlet)
	return {
		"currency": settings.base_currency,
		"groups": frappe.get_all("Item Group", filters={"is_group": 0}, pluck="name", order_by="name"),
		"uoms": frappe.get_all("UOM", filters={"enabled": 1}, pluck="name", order_by="name"),
		"menus": frappe.get_all("TRT Menu", filters={"outlet": outlet, "enabled": 1, "show_on_till": 1},
			fields=["name", "title"], order_by="title"),
		"stations": frappe.get_all("TRT Kitchen Station", filters={"outlet": outlet, "enabled": 1},
			fields=["name", "title"], order_by="title"),
		"ingredients": frappe.get_all("Item", filters={"disabled": 0, "has_variants": 0,
			"is_stock_item": 1, "is_purchase_item": 1, "is_sales_item": 0, "include_item_in_manufacturing": 1},
			fields=["name", "item_name", "stock_uom"], order_by="item_name"),
	}


def _barcode(value):
	from table_remote_till.barcode_values import normalize
	try:
		return normalize(value)
	except ValueError as error:
		frappe.throw(str(error))


@frappe.whitelist()
def barcode_available(outlet, barcode, request_id=None):
	_manager(outlet)
	code = _barcode(barcode)
	item = frappe.db.get_value("Item Barcode", {"barcode": code}, "parent") if code else None
	# A response lost after commit must still be retryable with the original request.
	if item and request_id:
		try:
			request_id = str(uuid.UUID(request_id))
		except (ValueError, TypeError, AttributeError):
			frappe.throw("Invalid save request")
		event = frappe.db.get_value("TRT Sync Event", {"event_id": request_id},
			["outlet", "event_type", "payload_json"], as_dict=True)
		if event and event.outlet == outlet and event.event_type == "create_item":
			stored = frappe.parse_json(event.payload_json)
			if stored.get("result", {}).get("item") == item:
				return {"available": True}
	result = {"available": not bool(item)}
	if item:
		menus = frappe.get_all("TRT Menu", filters={"outlet": outlet}, pluck="name")
		if menus and frappe.db.exists("TRT Menu Entry", {"parent": ["in", menus], "item": item}):
			result["item_name"] = frappe.db.get_value("Item", item, "item_name")
	return result


@frappe.whitelist(methods=["POST"])
def create_item(outlet, details, request_id):
	settings = _manager(outlet)
	try:
		request_id = str(uuid.UUID(request_id))
	except (ValueError, TypeError, AttributeError):
		frappe.throw("Invalid save request; reload the page")
	details = _payload(details)
	if not isinstance(details, dict):
		frappe.throw("Invalid item details")
	fingerprint = hashlib.sha256(json.dumps(details, sort_keys=True).encode()).hexdigest()
	frappe.db.sql("SELECT name FROM `tabTRT Outlet` WHERE name=%s FOR UPDATE", outlet)
	event = frappe.db.get_value("TRT Sync Event", {"event_id": request_id},
		["outlet", "event_type", "payload_json"], as_dict=True)
	if event:
		if event.outlet != outlet or event.event_type != "create_item":
			frappe.throw("Save request already used")
		stored = frappe.parse_json(event.payload_json)
		if stored["fingerprint"] != fingerprint:
			frappe.throw("This request already saved an item. Reload before adding another.")
		return stored["result"]
	name = str(details.get("name") or "").strip()
	name_ar = str(details.get("name_ar") or "").strip()
	if not name or len(name) > 140 or len(name_ar) > 140:
		frappe.throw("Enter an item name of up to 140 characters")
	rate = _number(details.get("price"), "selling price")
	group, uom = details.get("group"), details.get("uom")
	if not frappe.db.exists("Item Group", {"name": group, "is_group": 0}):
		frappe.throw("Choose an item category")
	if not frappe.db.exists("UOM", {"name": uom, "enabled": 1}):
		frappe.throw("Choose an enabled sale unit")
	station = details.get("station")
	if station and not frappe.db.exists("TRT Kitchen Station", {"name": station, "outlet": outlet, "enabled": 1}):
		frappe.throw("Choose a kitchen station in this outlet")
	menu_name = details.get("menu")
	if menu_name and not frappe.db.exists("TRT Menu", {"name": menu_name, "outlet": outlet,
		"enabled": 1, "show_on_till": 1}):
		frappe.throw("Choose an enabled till menu in this outlet")
	if not frappe.db.exists("Price List", {"name": settings.price_list, "enabled": 1,
		"selling": 1, "currency": settings.base_currency}):
		frappe.throw("Configure an enabled selling price list in the outlet currency")
	recipe = _recipe(details.get("ingredients"))
	barcode = _barcode(details.get("barcode"))
	if barcode and frappe.db.exists("Item Barcode", {"barcode": barcode}):
		frappe.throw("This barcode is already assigned to an item")
	with _as_admin():
		item = frappe.get_doc({"doctype": "Item", "item_code": "TRT-" + request_id,
			"item_name": name, "item_group": group, "stock_uom": uom,
			"is_stock_item": 0, "is_sales_item": 1, "is_purchase_item": 0})
		if barcode:
			item.append("barcodes", {"barcode": barcode, "uom": uom})
		try:
			item.insert(ignore_permissions=True)
		except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
			frappe.clear_messages()
			frappe.throw("Item or barcode already exists. Refresh and check the barcode before saving again.")
		except frappe.ValidationError:
			# ERPNext may detect a competing barcode during Item validation.
			if not barcode or not frappe.db.exists("Item Barcode", {"barcode": barcode}):
				raise
			frappe.clear_messages()
			frappe.throw("This barcode is already assigned to an item")
		if recipe:
			bom = frappe.get_doc({"doctype": "BOM", "item": item.name, "company": settings.company,
				"quantity": 1, "is_active": 1, "is_default": 1, "rm_cost_as_per": "Valuation Rate", "items": recipe})
			bom.insert(ignore_permissions=True)
			bom.flags.ignore_permissions = True
			bom.submit()
		frappe.get_doc({"doctype": "Item Price", "item_code": item.name, "price_list": settings.price_list,
			"selling": 1, "price_list_rate": rate, "valid_from": today()}).insert(ignore_permissions=True)
		menu = frappe.get_doc("TRT Menu", menu_name) if menu_name else frappe.get_doc({
			"doctype": "TRT Menu", "title": "Till menu", "outlet": outlet, "enabled": 1, "show_on_till": 1})
		menu.append("items", {"item": item.name, "name_en": name, "name_ar": name_ar,
			"category": group, "station": station, "available": 1})
		menu.save(ignore_permissions=True)
	result = {"item": item.name, "name": name, "menu": menu.name}
	frappe.get_doc({"doctype": "TRT Sync Event", "event_id": request_id, "outlet": outlet,
		"event_type": "create_item", "payload_json": json.dumps({"fingerprint": fingerprint, "result": result}),
		"status": "Applied", "received_at": now_datetime()}).insert(ignore_permissions=True)
	return result


@frappe.whitelist()
def lookup_barcode(outlet, barcode, channel="Till"):
	"""Resolve only items sellable in the caller's outlet and current channel."""
	from table_remote_till.api import catalog
	_staff_outlet(outlet)
	if channel not in ("Till", "Retail", "Table", "Tab", "Takeaway"):
		frappe.throw("Choose a Till sale type before scanning")
	code = _barcode(barcode)
	if not code:
		frappe.throw("Scan a barcode first")
	row = frappe.db.get_value("Item Barcode", {"barcode": code}, ["parent", "uom"], as_dict=True)
	item = next((item for item in catalog(outlet, channel)["items"] if row and item["item"] == row.parent), None) if row else None
	if not item:
		frappe.throw("Barcode not found or item is unavailable in this outlet and sale type")
	if row.uom and row.uom != item.get("uom"):
		frappe.throw("This barcode uses a different sale unit. Select the item manually.")
	return item
