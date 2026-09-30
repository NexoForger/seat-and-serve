"""Idempotent, manager-driven setup of a business's first POS outlet.

The wizard creates operational masters. Tax, payroll, live payments, opening
balances, and source-history migration remain explicit business decisions.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import frappe
from frappe.utils import flt, now_datetime, today


CHANNELS = {"Table", "Tab", "Takeaway", "Retail", "Kiosk", "QR", "Pickup"}
BUSINESS_TYPES = {"Restaurant/Pub", "Retail", "Mixed"}


def _checked(value):
	return value is True or value == 1 or value == "1"


def _name(value, label):
	value = str(value or "").strip()
	if not value or len(value) > 100 or any(ord(char) < 32 for char in value):
		frappe.throw(f"Enter a valid {label} (1–100 characters)")
	return value


def _linked(doctype, name, **expected):
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(f"Select an existing {doctype}")
	row = frappe.db.get_value(doctype, name, list(expected), as_dict=True) if expected else None
	for field, value in expected.items():
		if row.get(field) != value:
			frappe.throw(f"{doctype} {name} has an incompatible {field}")
	return name


def _account(company, name):
	_linked("Account", name, company=company, is_group=0)
	return name


def _cost_center(company, name):
	_linked("Cost Center", name, company=company, is_group=0)
	return name


def _existing_title(doctype, **filters):
	return frappe.db.get_value(doctype, filters, "name")


def normalize(raw):
	"""Validate every reference before creating any ERPNext document."""
	raw = frappe.parse_json(raw) if isinstance(raw, str) else raw
	if not isinstance(raw, dict):
		frappe.throw("Onboarding data must be an object")
	company_name = _linked("Company", raw.get("company"), is_group=0)
	company = frappe.get_doc("Company", company_name)
	if company.default_currency not in ("USD", "LBP"):
		frappe.throw("This onboarding flow requires a USD or LBP company currency")
	if not company.default_receivable_account:
		frappe.throw("Complete the company chart of accounts and receivable account first")
	_account(company.name, company.default_receivable_account)
	business_type = raw.get("business_type")
	if business_type not in BUSINESS_TYPES:
		frappe.throw("Choose restaurant/pub, retail, or mixed business")
	outlet_title = _name(raw.get("outlet_title"), "outlet name")
	branch = _name(raw.get("branch"), "branch name")
	register_title = _name(raw.get("register_title") or "Main Register", "register name")
	channels = raw.get("channels") or []
	if not isinstance(channels, list) or not channels or len(channels) != len(set(channels)) or set(channels) - CHANNELS:
		frappe.throw("Choose one or more valid channels")
	if business_type == "Retail" and "Retail" not in channels:
		frappe.throw("A retail business requires the Retail channel")
	if business_type == "Restaurant/Pub" and not set(channels).intersection({"Table", "Tab", "Takeaway"}):
		frappe.throw("A restaurant or pub requires a staff service channel")
	warehouse = raw.get("warehouse") or None
	price_list = raw.get("price_list") or None
	profile = raw.get("pos_profile") or None
	if profile:
		_linked("POS Profile", profile, company=company.name, currency=company.default_currency, disabled=0)
		profile_doc = frappe.get_doc("POS Profile", profile)
		warehouse = warehouse or profile_doc.warehouse
		price_list = price_list or profile_doc.selling_price_list
	if warehouse:
		_linked("Warehouse", warehouse, company=company.name, is_group=0, disabled=0)
	if price_list:
		_linked("Price List", price_list, currency=company.default_currency, selling=1, enabled=1)
	if profile and (profile_doc.warehouse != warehouse or profile_doc.selling_price_list != price_list):
		frappe.throw("Selected POS Profile must use the selected warehouse and price list")
	customer = raw.get("customer") or None
	if customer:
		_linked("Customer", customer, disabled=0)
	else:
		if not frappe.db.exists("Customer Group", {"is_group": 0}):
			frappe.throw("Create a leaf Customer Group before onboarding")
		if not frappe.db.exists("Territory", {"is_group": 0}):
			frappe.throw("Create a leaf Territory before onboarding")
	cash_mode = raw.get("cash_mode") or "Cash"
	_linked("Mode of Payment", cash_mode, type="Cash", enabled=1)
	if not frappe.db.exists("Mode of Payment Account", {"parent": cash_mode,
		"company": company.name, "default_account": ["!=", ""]}):
		frappe.throw("Configure a company cash account on the selected Mode of Payment")
	if profile and cash_mode not in [row.mode_of_payment for row in profile_doc.payments]:
		frappe.throw("Cash mode is not enabled on the selected POS Profile")
	write_off_account = raw.get("write_off_account") or None
	cost_center = raw.get("cost_center") or None
	if not profile:
		_account(company.name, write_off_account)
		_cost_center(company.name, cost_center)
	tax_template = raw.get("tax_template") or None
	if tax_template:
		_linked("Sales Taxes and Charges Template", tax_template, company=company.name, disabled=0)
	fx_rate = raw.get("lbp_per_usd")
	if fx_rate not in (None, ""):
		fx_rate = flt(fx_rate)
		if fx_rate <= 0 or fx_rate > 1_000_000_000:
			frappe.throw("Enter a positive LBP per USD rate")
		if not _checked(raw.get("approve_fx_rate")):
			frappe.throw("Approve the USD/LBP rate before creating it")
	else:
		fx_rate = None
	if _checked(raw.get("enable_lbp")) and not frappe.db.exists("Currency", "LBP"):
		frappe.throw("LBP currency is missing from ERPNext")
	if _checked(raw.get("set_pos_invoice_mode")) and not frappe.db.exists("DocType", "POS Invoice"):
		frappe.throw("ERPNext POS Invoice is unavailable")
	if _checked(raw.get("seed_sample_data")):
		if not frappe.db.exists("Item Group", {"is_group": 0}):
			frappe.throw("Create a leaf Item Group before seeding sample items")
		if not frappe.db.exists("UOM", "Nos"):
			frappe.throw("Create the Nos unit of measure before seeding sample items")
	return {
		"company": company.name, "business_type": business_type,
		"outlet_title": outlet_title, "branch": branch, "register_title": register_title,
		"channels": sorted(channels), "warehouse": warehouse, "price_list": price_list,
		"pos_profile": profile, "customer": customer, "cash_mode": cash_mode,
		"write_off_account": write_off_account, "cost_center": cost_center,
		"tax_template": tax_template, "lbp_per_usd": fx_rate,
		"enable_lbp": _checked(raw.get("enable_lbp")),
		"set_pos_invoice_mode": _checked(raw.get("set_pos_invoice_mode")),
		"seed_sample_data": _checked(raw.get("seed_sample_data")),
	}


def preview(config):
	config = normalize(config)
	company = frappe.get_doc("Company", config["company"])
	setup_name = frappe.db.get_value("TRT Business Setup", {"company": company.name}, "name")
	if setup_name and frappe.db.get_value("TRT Business Setup", setup_name,
		"business_type") != config["business_type"]:
		frappe.throw("Existing business setup has another business type; review it in Desk")
	outlet = _existing_title("TRT Outlet", company=company.name, title=config["outlet_title"])
	if outlet:
		frappe.throw("An outlet with this name already exists. Edit it in Desk or choose a new name")
	warehouse_name = config["warehouse"] or f"{config['outlet_title']} - {company.abbr}"
	price_list_name = config["price_list"] or f"TRT {config['outlet_title']} Selling"
	profile_name = config["pos_profile"] or f"TRT {config['outlet_title']}"
	customer_name = config["customer"] or f"TRT Walk-in {company.name}"
	if not config["warehouse"] and frappe.db.exists("Warehouse", warehouse_name):
		_linked("Warehouse", warehouse_name, company=company.name, is_group=0, disabled=0)
	if not config["price_list"] and frappe.db.exists("Price List", price_list_name):
		_linked("Price List", price_list_name, currency=company.default_currency, selling=1, enabled=1)
	if not config["pos_profile"] and frappe.db.exists("POS Profile", profile_name):
		frappe.throw("Generated POS Profile name already exists; select it explicitly or rename the outlet")
	if not config["customer"] and frappe.db.exists("Customer", customer_name):
		_linked("Customer", customer_name, disabled=0)
	actions = []
	def action(label, name, create=True):
		actions.append({"label": label, "name": name, "action": "Create" if create else "Use existing"})
	action("Business setup", company.name, not frappe.db.exists("TRT Business Setup", {"company": company.name}))
	action("Branch", config["branch"], not frappe.db.exists("Branch", config["branch"]))
	action("Warehouse", warehouse_name, not frappe.db.exists("Warehouse", warehouse_name))
	action("Selling price list", price_list_name, not frappe.db.exists("Price List", price_list_name))
	action("Walk-in customer", customer_name, not frappe.db.exists("Customer", customer_name))
	action("POS Profile", profile_name, not frappe.db.exists("POS Profile", profile_name))
	action("Outlet", config["outlet_title"])
	action("Register", config["register_title"])
	action("Staff assignment", frappe.session.user)
	if config["business_type"] != "Retail":
		action("Service area", "Main")
		action("Kitchen station", "Kitchen")
	action("Starter menu", "Catalog" if config["business_type"] == "Retail" else "Main Menu")
	if config["seed_sample_data"]:
		action("Demo items and prices", "Clearly labeled sample catalog")
		if config["business_type"] != "Retail":
			action("Demo table", "T1")
	if config["lbp_per_usd"]:
		action("Approved USD/LBP rate", str(config["lbp_per_usd"]))
	if config["enable_lbp"] and not frappe.db.get_value("Currency", "LBP", "enabled"):
		action("Enable LBP currency", "LBP")
	if config["set_pos_invoice_mode"] and frappe.db.get_single_value("POS Settings", "invoice_type") != "POS Invoice":
		action("Set POS Invoice mode", "Site-wide POS Settings")
	return {"config": config, "actions": actions,
		"remaining": ["Review tax and payroll with the business", "Add items and prices",
			"Open a POS shift", "Import and reconcile source history",
			"Certify live payments and devices before rollout",
			*(["Remove sample items before live use"] if config["seed_sample_data"] else [])]}


def _insert(doctype, **fields):
	return frappe.get_doc({"doctype": doctype, **fields}).insert(ignore_permissions=True)


def apply(raw, request_id):
	try:
		request_id = str(uuid.UUID(str(request_id)))
	except (ValueError, TypeError, AttributeError):
		frappe.throw("A UUID request ID is required")
	config = normalize(raw)
	fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
	frappe.db.sql("SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE", config["company"])
	prior = frappe.db.get_value("TRT Onboarding Run", {"request_id": request_id},
		["request_hash", "result_json"], as_dict=True)
	if prior:
		if prior.request_hash != fingerprint:
			frappe.throw("Request ID belongs to different onboarding data")
		return frappe.parse_json(prior.result_json)
	preview(config)
	frappe.db.savepoint("trt_onboarding")
	try:
		result = _apply_normalized(config)
		_insert("TRT Onboarding Run", request_id=request_id, company=config["company"],
			outlet=result["outlet"], request_hash=fingerprint, status="Applied",
			result_json=json.dumps(result), run_by=frappe.session.user, run_at=now_datetime())
	except Exception:
		frappe.db.rollback(save_point="trt_onboarding")
		raise
	return result


def _apply_normalized(config):
	company = frappe.get_doc("Company", config["company"])
	created = []
	def make(doctype, **fields):
		doc = _insert(doctype, **fields)
		created.append({"doctype": doctype, "name": doc.name})
		return doc
	setup_name = frappe.db.get_value("TRT Business Setup", {"company": company.name}, "name")
	if not setup_name:
		make("TRT Business Setup", company=company.name, business_type=config["business_type"],
			country=company.country, base_currency=company.default_currency, cash_currency="LBP")
	elif frappe.db.get_value("TRT Business Setup", setup_name, "business_type") != config["business_type"]:
		frappe.throw("Existing business setup has another business type; review it in Desk")
	if not frappe.db.exists("Branch", config["branch"]):
		make("Branch", branch=config["branch"])
	warehouse = config["warehouse"] or f"{config['outlet_title']} - {company.abbr}"
	if not frappe.db.exists("Warehouse", warehouse):
		warehouse = make("Warehouse", warehouse_name=config["outlet_title"], company=company.name,
			is_group=0).name
	price_list = config["price_list"] or f"TRT {config['outlet_title']} Selling"
	if not frappe.db.exists("Price List", price_list):
		make("Price List", price_list_name=price_list, currency=company.default_currency,
			selling=1, enabled=1)
	customer = config["customer"] or f"TRT Walk-in {company.name}"
	if not frappe.db.exists("Customer", customer):
		group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
		customer = make("Customer", customer_name=customer, customer_type="Individual",
			customer_group=group, territory=territory).name
	profile = config["pos_profile"] or f"TRT {config['outlet_title']}"
	if not frappe.db.exists("POS Profile", profile):
		profile_doc = frappe.get_doc({"doctype": "POS Profile", "name": profile,
			"company": company.name, "currency": company.default_currency,
			"warehouse": warehouse, "selling_price_list": price_list,
			"customer": customer, "write_off_account": config["write_off_account"],
			"write_off_cost_center": config["cost_center"], "write_off_limit": 0,
			"income_account": company.default_income_account,
			"expense_account": company.default_expense_account,
			"payments": [{"mode_of_payment": config["cash_mode"], "default": 1}]})
		if config["tax_template"]:
			profile_doc.taxes_and_charges = config["tax_template"]
		profile_doc.insert(ignore_permissions=True)
		created.append({"doctype": "POS Profile", "name": profile_doc.name})
		profile = profile_doc.name
	channel_fields = {"Table": "enable_tables", "Tab": "enable_tabs",
		"Takeaway": "enable_takeaway", "Retail": "enable_retail",
		"Kiosk": "enable_kiosk", "QR": "enable_qr", "Pickup": "enable_pickup"}
	outlet_fields = {field: int(channel in config["channels"])
		for channel, field in channel_fields.items()}
	outlet = make("TRT Outlet", title=config["outlet_title"], company=company.name,
		branch=config["branch"], warehouse=warehouse, pos_profile=profile,
		price_list=price_list, walk_in_customer=customer,
		receivable_account=company.default_receivable_account,
		tax_template=config["tax_template"], base_currency=company.default_currency,
		cash_currency="LBP", enabled=1, **outlet_fields)
	register = make("TRT Register", title=config["register_title"], outlet=outlet.name,
		pos_profile=profile, enabled=1)
	make("TRT Staff Assignment", user=frappe.session.user, outlet=outlet.name,
		allow_till=1, allow_kitchen=1, allow_manager=1, enabled=1)
	area = station = None
	if config["business_type"] != "Retail":
		area = make("TRT Service Area", title="Main", outlet=outlet.name, enabled=1)
		station = make("TRT Kitchen Station", title="Kitchen", outlet=outlet.name, enabled=1)
	menu = make("TRT Menu", title="Catalog" if config["business_type"] == "Retail" else "Main Menu",
		outlet=outlet.name, enabled=1, show_on_till=1,
		show_on_kiosk=int("Kiosk" in config["channels"]),
		show_on_menu=int(bool({"QR", "Pickup"}.intersection(config["channels"]))))
	if config["seed_sample_data"]:
		_seed_samples(config, outlet, price_list, menu, area, station, created)
	if config["enable_lbp"] and not frappe.db.get_value("Currency", "LBP", "enabled"):
		frappe.db.set_value("Currency", "LBP", "enabled", 1)
	if config["lbp_per_usd"]:
		make("TRT FX Rate", outlet=outlet.name, effective_date=today(),
			lbp_per_usd=config["lbp_per_usd"], approved_by=frappe.session.user,
			approved_on=now_datetime(), enabled=1)
	if config["set_pos_invoice_mode"]:
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
	return {"company": company.name, "outlet": outlet.name, "register": register.name,
		"pos_profile": profile, "warehouse": warehouse, "price_list": price_list,
		"customer": customer, "created": created,
		"next_url": f"/app/trt-outlet/{outlet.name}",
		"remaining": ["Add items and prices", "Review and approve tax/payroll rules",
			"Open a POS shift", "Import and reconcile source history",
			*(["Remove sample items before live use"] if config["seed_sample_data"] else [])]}


def _seed_samples(config, outlet, price_list, menu, area, station, created):
	"""Create sample sale items with raw-material BOMs and no financial history."""
	from table_remote_till.demo_seed import (
		SAMPLE_RECIPES, _create_sample_bom, _ensure_raw_materials,
	)

	raw_created = []
	_ensure_raw_materials(raw_created)
	created.extend({"doctype": doctype, "name": name} for doctype, name in raw_created)
	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	marker = hashlib.sha256(outlet.name.encode()).hexdigest()[:8].upper()
	base = 100000 if outlet.base_currency == "LBP" else 1
	food = [("F1", "SAMPLE Classic Burger", 8), ("F2", "SAMPLE Fries", 3),
		("F3", "SAMPLE Soft Drink", 2)]
	retail = [("R1", "SAMPLE Bottled Water", 2), ("R2", "SAMPLE Notebook", 5),
		("R3", "SAMPLE Snack Bar", 3)]
	rows = retail if config["business_type"] == "Retail" else food + (retail if config["business_type"] == "Mixed" else [])
	for suffix, title, rate in rows:
		item_code = f"TRT-SAMPLE-{marker}-{suffix}"
		item = _insert("Item", item_code=item_code, item_name=title, item_group=group,
			stock_uom="Nos", is_stock_item=0, is_sales_item=1,
			description="S&S (Seat & Serve) sample item. Remove before live sales.")
		created.append({"doctype": "Item", "name": item.name})
		recipe = {
			"F1": SAMPLE_RECIPES["BURGER"], "F2": SAMPLE_RECIPES["FRIES"],
			"F3": SAMPLE_RECIPES["COLA"], "R1": SAMPLE_RECIPES["WATER"],
			"R2": (("NOTEBOOKUNIT", 1),), "R3": (("SNACKBARUNIT", 1),),
		}[suffix]
		bom_name = _create_sample_bom(item.name, outlet.company, recipe)
		if bom_name:
			created.append({"doctype": "BOM", "name": bom_name})
		price = _insert("Item Price", item_code=item.name, price_list=price_list,
			selling=1, price_list_rate=rate * base, valid_from=today())
		created.append({"doctype": "Item Price", "name": price.name})
		menu.append("items", {"item": item.name, "name_en": title,
			"station": station.name if station and suffix.startswith("F") else None,
			"available": 1})
	menu.save(ignore_permissions=True)
	if area:
		table = _insert("TRT Table", title="T1", area=area.name,
			outlet=outlet.name, seats=4, enabled=1)
		created.append({"doctype": "TRT Table", "name": table.name})
