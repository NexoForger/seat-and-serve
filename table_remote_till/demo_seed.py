"""Populate the local demo with ERPNext-backed sample restaurant data.

Run with ``bench --site SITE execute table_remote_till.demo_seed.run``.
The sample marker makes the records recognizable and repeat runs are safe.
No invoice, payment, or stock transaction is posted.
"""

from __future__ import annotations

import uuid

import frappe
from frappe.utils import today

from table_remote_till import api


SAMPLE_ITEMS = (
	# code, display name, category, USD price, station
	("BURGER", "Classic Burger", "Burgers", 8.50, "Kitchen"),
	("CHEESEBURGER", "Cheeseburger", "Burgers", 9.50, "Kitchen"),
	("BACONBURGER", "Bacon Burger", "Burgers", 10.50, "Kitchen"),
	("VEGGIEBURGER", "Veggie Burger", "Burgers", 8.75, "Kitchen"),
	("CHICKENSANDWICH", "Grilled Chicken Sandwich", "Sandwiches", 8.25, "Kitchen"),
	("CLUBSANDWICH", "Club Sandwich", "Sandwiches", 9.25, "Kitchen"),
	("CHICKENWRAP", "Chicken Caesar Wrap", "Wraps", 8.75, "Kitchen"),
	("FALAFELWRAP", "Falafel Wrap", "Wraps", 7.25, "Kitchen"),
	("FRIES", "French Fries", "Sides", 3.50, "Kitchen"),
	("SALAD", "Garden Salad", "Sides", 5.50, "Kitchen"),
	("COLA", "Cola", "Drinks", 2.50, "Bar"),
	("LEMONADE", "Fresh Lemonade", "Drinks", 3.75, "Bar"),
	("WATER", "Bottled Water", "Drinks", 1.75, "Bar"),
	("COFFEE", "Coffee", "Drinks", 3.00, "Bar"),
	("BROWNIE", "Chocolate Brownie", "Desserts", 4.50, "Kitchen"),
	("CHEESECAKE", "Cheesecake", "Desserts", 5.50, "Kitchen"),
	("DOUBLESMASH", "Double Smash Burger", "Burgers", 12.50, "Kitchen"),
	("SPICYCHICKEN", "Spicy Chicken Burger", "Burgers", 9.75, "Kitchen"),
	("TUNAMELT", "Tuna Melt", "Sandwiches", 8.50, "Kitchen"),
	("HALLOUMIWRAP", "Halloumi Wrap", "Wraps", 8.25, "Kitchen"),
	("ONIONRINGS", "Onion Rings", "Sides", 4.25, "Kitchen"),
	("SWEETFRIES", "Sweet Potato Fries", "Sides", 4.75, "Kitchen"),
	("GREEKSALAD", "Greek Salad", "Sides", 7.25, "Kitchen"),
	("ICEDTEA", "Iced Tea", "Drinks", 3.25, "Bar"),
	("MILKSHAKE", "Chocolate Milkshake", "Drinks", 5.75, "Bar"),
	("APPLEPIE", "Apple Pie", "Desserts", 4.75, "Kitchen"),
	("BURGERFRIESDEAL", "Burger & Fries Combo", "Combo deals", 10.50, "Kitchen"),
	("CHICKENSALADDEAL", "Chicken & Salad Combo", "Combo deals", 11.50, "Kitchen"),
	("SNACKDUO", "Snack Duo", "Offers", 6.50, "Kitchen"),
)

SAMPLE_DEALS = {
	"BURGERFRIESDEAL": ("Combo", "Classic Burger + French Fries", ("BURGER", "FRIES")),
	"CHICKENSALADDEAL": ("Combo", "Grilled Chicken Sandwich + Garden Salad", ("CHICKENSANDWICH", "SALAD")),
	"SNACKDUO": ("Offer", "French Fries + Onion Rings", ("FRIES", "ONIONRINGS")),
}

# Recipe components are ERPNext stock Items, never saleable menu Items.
# Quantities use each ingredient's stock UOM.
SAMPLE_RAW_MATERIALS = {
	"BUN": ("Burger bun", "Nos"), "BREAD": ("Sandwich bread slice", "Nos"),
	"WRAP": ("Flatbread wrap", "Nos"), "BEEF": ("Ground beef", "Gram"),
	"CHICKEN": ("Chicken breast", "Gram"), "BACON": ("Bacon", "Gram"),
	"CHEESE": ("Cheese", "Gram"), "HALLOUMI": ("Halloumi", "Gram"),
	"TUNA": ("Tuna", "Gram"), "FALAFEL": ("Falafel mix", "Gram"),
	"POTATO": ("Potato", "Gram"), "SWEETPOTATO": ("Sweet potato", "Gram"),
	"ONION": ("Onion", "Gram"), "LETTUCE": ("Lettuce", "Gram"),
	"TOMATO": ("Tomato", "Gram"), "CUCUMBER": ("Cucumber", "Gram"),
	"PICKLE": ("Pickle", "Gram"), "OLIVE": ("Olive", "Gram"),
	"JALAPENOS": ("Jalapeños", "Gram"), "FETA": ("Feta", "Gram"),
	"SAUCE": ("House sauce", "Gram"), "DRESSING": ("Salad dressing", "Gram"),
	"FLOUR": ("Flour", "Gram"), "SUGAR": ("Sugar", "Gram"),
	"CHOCOLATE": ("Chocolate", "Gram"), "EGG": ("Egg", "Nos"),
	"BUTTER": ("Butter", "Gram"), "CREAMCHEESE": ("Cream cheese", "Gram"),
	"BISCUIT": ("Biscuit crumb", "Gram"), "APPLE": ("Apple", "Gram"),
	"MILK": ("Milk", "Litre"), "OATMILK": ("Oat milk", "Litre"),
	"COFFEE": ("Coffee beans", "Gram"), "TEA": ("Tea leaves", "Gram"),
	"LEMON": ("Lemon", "Gram"), "ICE": ("Ice", "Gram"),
	"COLACAN": ("Cola can", "Nos"), "WATERBOTTLE": ("Water bottle", "Nos"),
	"NOTEBOOKUNIT": ("Notebook unit", "Nos"),
	"SNACKBARUNIT": ("Snack bar unit", "Nos"),
}

SAMPLE_RECIPES = {
	"BURGER": (("BUN", 1), ("BEEF", 150), ("LETTUCE", 20), ("TOMATO", 30), ("SAUCE", 20)),
	"CHEESEBURGER": (("BUN", 1), ("BEEF", 150), ("CHEESE", 25), ("PICKLE", 15), ("SAUCE", 20)),
	"BACONBURGER": (("BUN", 1), ("BEEF", 150), ("BACON", 35), ("CHEESE", 25), ("SAUCE", 20)),
	"VEGGIEBURGER": (("BUN", 1), ("FALAFEL", 140), ("LETTUCE", 20), ("TOMATO", 30), ("SAUCE", 20)),
	"CHICKENSANDWICH": (("BREAD", 2), ("CHICKEN", 150), ("LETTUCE", 20), ("SAUCE", 20)),
	"CLUBSANDWICH": (("BREAD", 3), ("CHICKEN", 120), ("BACON", 25), ("TOMATO", 30), ("LETTUCE", 20)),
	"CHICKENWRAP": (("WRAP", 1), ("CHICKEN", 140), ("LETTUCE", 25), ("DRESSING", 25)),
	"FALAFELWRAP": (("WRAP", 1), ("FALAFEL", 150), ("TOMATO", 30), ("CUCUMBER", 30), ("SAUCE", 20)),
	"FRIES": (("POTATO", 220),),
	"SALAD": (("LETTUCE", 80), ("TOMATO", 50), ("CUCUMBER", 50), ("DRESSING", 25)),
	"COLA": (("COLACAN", 1),),
	"LEMONADE": (("LEMON", 80), ("SUGAR", 20), ("ICE", 100)),
	"WATER": (("WATERBOTTLE", 1),),
	"COFFEE": (("COFFEE", 18), ("MILK", 0.15)),
	"BROWNIE": (("FLOUR", 60), ("SUGAR", 40), ("CHOCOLATE", 50), ("EGG", 1), ("BUTTER", 30)),
	"CHEESECAKE": (("CREAMCHEESE", 110), ("BISCUIT", 45), ("SUGAR", 25), ("BUTTER", 20)),
	"DOUBLESMASH": (("BUN", 1), ("BEEF", 220), ("CHEESE", 40), ("SAUCE", 25)),
	"SPICYCHICKEN": (("BUN", 1), ("CHICKEN", 160), ("JALAPENOS", 20), ("LETTUCE", 20), ("SAUCE", 25)),
	"TUNAMELT": (("BREAD", 2), ("TUNA", 130), ("CHEESE", 35), ("ONION", 20)),
	"HALLOUMIWRAP": (("WRAP", 1), ("HALLOUMI", 120), ("TOMATO", 30), ("LETTUCE", 20)),
	"ONIONRINGS": (("ONION", 180), ("FLOUR", 40)),
	"SWEETFRIES": (("SWEETPOTATO", 220),),
	"GREEKSALAD": (("TOMATO", 70), ("CUCUMBER", 70), ("FETA", 60), ("OLIVE", 30), ("DRESSING", 20)),
	"ICEDTEA": (("TEA", 6), ("SUGAR", 15), ("ICE", 120), ("LEMON", 20)),
	"MILKSHAKE": (("MILK", 0.3), ("CHOCOLATE", 35), ("SUGAR", 20), ("ICE", 100)),
	"APPLEPIE": (("APPLE", 140), ("FLOUR", 60), ("BUTTER", 35), ("SUGAR", 30)),
}

# Deal sale items have their own BOMs made solely from the raw materials of the
# included products. This keeps invoice pricing and inventory recipes aligned.
for _deal_code, (_, _, _components) in SAMPLE_DEALS.items():
	_materials = {}
	for _component in _components:
		for _material, _quantity in SAMPLE_RECIPES[_component]:
			_materials[_material] = _materials.get(_material, 0) + _quantity
	SAMPLE_RECIPES[_deal_code] = tuple(_materials.items())

SAMPLE_MODIFIER_INGREDIENTS = {
	"CHEESE": ("CHEESE", 25), "BACON": ("BACON", 35),
	"JALAPENOS": ("JALAPENOS", 20), "CHICKEN": ("CHICKEN", 80),
	"SAUCE": ("SAUCE", 20), "OATMILK": ("OATMILK", 0.15),
}

SAMPLE_MODIFIERS = (
	("Burger extras", (("CHEESE", "Extra cheese", 1.00),
		("BACON", "Crispy bacon", 1.75), ("JALAPENOS", "Jalapeños", 0.75),
		("NOONIONS", "No onions", 0.00))),
	("Sandwich extras", (("CHICKEN", "Extra chicken", 2.50),
		("SAUCE", "Extra sauce", 0.50), ("NOONIONS", "No onions", 0.00))),
	("Drink choices", (("LARGE", "Large size", 1.00),
		("NOICE", "No ice", 0.00), ("OATMILK", "Oat milk", 0.75))),
)

SAMPLE_ORDERS = (
	("table-1", "Table", ("BURGER", "FRIES", "COLA"), 0),
	("table-2", "Table", ("CHICKENSANDWICH", "SALAD", "LEMONADE"), 1),
	("table-3", "Table", ("VEGGIEBURGER", "WATER"), 2),
	("tab-1", "Tab", ("BACONBURGER", "COFFEE", "BROWNIE"), None),
	("takeaway-1", "Takeaway", ("CHICKENWRAP", "FRIES", "COLA"), None),
	("takeaway-2", "Takeaway", ("CLUBSANDWICH", "CHEESECAKE"), None),
	("counter-1", "Till", ("FALAFELWRAP", "LEMONADE"), None),
	("counter-2", "Till", ("CHEESEBURGER", "WATER"), None),
	("kiosk-1", "Kiosk", ("CHEESEBURGER", "FRIES", "COLA"), None),
	("qr-1", "QR", ("FALAFELWRAP", "SALAD", "WATER"), 3),
	("pickup-1", "Pickup", ("CHICKENWRAP", "LEMONADE"), None),
	("retail-1", "Retail", ("COFFEE", "BROWNIE"), None),
)


def _insert(doctype, **fields):
	return frappe.get_doc({"doctype": doctype, **fields}).insert(ignore_permissions=True)


def _ensure_customer(created):
	name = "TRT SAMPLE Guest"
	if frappe.db.exists("Customer", name):
		return name
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if not group or not territory:
		frappe.throw("A leaf Customer Group and Territory are required for sample data")
	doc = _insert("Customer", customer_name=name, customer_type="Individual",
		customer_group=group, territory=territory)
	created.append(("Customer", doc.name))
	return doc.name


def _ensure_items(price_lists, created):
	if not frappe.db.exists("UOM", "Nos"):
		frappe.throw("The Nos unit of measure is required for sample items")
	for code, title, category, rate, _station in SAMPLE_ITEMS:
		group_name = f"TRT SAMPLE {category}"
		if not frappe.db.exists("Item Group", group_name):
			group = _insert("Item Group", item_group_name=group_name,
				parent_item_group="All Item Groups", is_group=0)
			created.append(("Item Group", group.name))
		item_code = f"TRT-SAMPLE-{code}"
		if not frappe.db.exists("Item", item_code):
			item = _insert("Item", item_code=item_code, item_name=f"SAMPLE {title}",
				item_group=group_name, stock_uom="Nos", is_stock_item=0,
				is_sales_item=1,
				description="S&S (Seat & Serve) sample item. Remove before live sales.")
			created.append(("Item", item.name))
		for price_list in price_lists:
			if not frappe.db.exists("Item Price", {"item_code": item_code,
				"price_list": price_list, "selling": 1}):
				price = _insert("Item Price", item_code=item_code, price_list=price_list,
					selling=1, price_list_rate=rate, valid_from=today())
				created.append(("Item Price", price.name))


def _ensure_raw_materials(created):
	group_name = "TRT SAMPLE Raw Materials"
	if not frappe.db.exists("Item Group", group_name):
		group = _insert("Item Group", item_group_name=group_name,
			parent_item_group="All Item Groups", is_group=0)
		created.append(("Item Group", group.name))
	for code, (title, uom) in SAMPLE_RAW_MATERIALS.items():
		if not frappe.db.exists("UOM", uom):
			frappe.throw(f"The {uom} unit of measure is required for sample recipes")
		item_code = f"TRT-SAMPLE-RM-{code}"
		if not frappe.db.exists("Item", item_code):
			item = _insert("Item", item_code=item_code, item_name=f"SAMPLE {title}",
				item_group=group_name, stock_uom=uom, is_stock_item=1,
				is_purchase_item=1, is_sales_item=0, include_item_in_manufacturing=1,
				description="S&S (Seat & Serve) sample raw material. Remove before live use.")
			created.append(("Item", item.name))
		flags = frappe.db.get_value("Item", item_code,
			["is_stock_item", "is_purchase_item", "is_sales_item", "include_item_in_manufacturing"],
			as_dict=True)
		if not (flags.is_stock_item and flags.is_purchase_item and
				flags.include_item_in_manufacturing and not flags.is_sales_item):
			frappe.throw(f"{item_code} must be a purchasable stock raw material, not a sale item")


def _create_sample_bom(item_code, company, ingredients, is_default=True):
	"""Create a submitted ERPNext BOM for one sample sale item."""
	if frappe.db.exists("BOM", {"item": item_code, "company": company,
			"docstatus": 1, "is_active": 1}):
		return None
	bom = frappe.get_doc({"doctype": "BOM", "item": item_code,
		"company": company, "quantity": 1, "is_active": 1,
		"is_default": int(is_default), "rm_cost_as_per": "Valuation Rate",
		"items": [{"item_code": f"TRT-SAMPLE-RM-{raw_code}", "qty": qty,
			"uom": SAMPLE_RAW_MATERIALS[raw_code][1]}
			for raw_code, qty in ingredients]})
	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom.name


def _ensure_boms(companies, created):
	if set(SAMPLE_RECIPES) != {row[0] for row in SAMPLE_ITEMS}:
		frappe.throw("Every sample menu item must have a recipe")
	for code, ingredients in SAMPLE_RECIPES.items():
		item_code = f"TRT-SAMPLE-{code}"
		for company in companies:
			bom_name = _create_sample_bom(item_code, company, ingredients,
				is_default=company == companies[0])
			if bom_name:
				created.append(("BOM", bom_name))


def _ensure_modifier_groups(created):
	group_name = "TRT SAMPLE Modifiers"
	if not frappe.db.exists("Item Group", group_name):
		group = _insert("Item Group", item_group_name=group_name,
			parent_item_group="All Item Groups", is_group=0)
		created.append(("Item Group", group.name))
	groups = {}
	for title, options in SAMPLE_MODIFIERS:
		name = frappe.db.get_value("TRT Modifier Group", {"title": f"SAMPLE {title}"}, "name")
		modifier = frappe.get_doc("TRT Modifier Group", name) if name else frappe.new_doc("TRT Modifier Group")
		if not name:
			modifier.title = f"SAMPLE {title}"
			modifier.minimum = 0
		existing = {row.item for row in modifier.options}
		changed = not bool(name)
		for code, label, delta in options:
			item_code = f"TRT-SAMPLE-MOD-{code}"
			ingredient = SAMPLE_MODIFIER_INGREDIENTS.get(code)
			ingredient_item = f"TRT-SAMPLE-RM-{ingredient[0]}" if ingredient else None
			ingredient_qty = ingredient[1] if ingredient else 0
			if not frappe.db.exists("Item", item_code):
				item = _insert("Item", item_code=item_code, item_name=f"SAMPLE {label}",
					item_group=group_name, stock_uom="Nos", is_stock_item=0,
					is_sales_item=0,
					description="S&S (Seat & Serve) sample modifier. Remove before live sales.")
				created.append(("Item", item.name))
			if item_code not in existing:
				modifier.append("options", {"item": item_code, "name_en": label,
					"price_delta": delta, "ingredient_item": ingredient_item,
					"ingredient_qty": ingredient_qty})
				changed = True
			else:
				row = next(row for row in modifier.options if row.item == item_code)
				if row.ingredient_item != ingredient_item or float(row.ingredient_qty or 0) != ingredient_qty:
					row.ingredient_item = ingredient_item
					row.ingredient_qty = ingredient_qty
					changed = True
		if changed:
			modifier.save(ignore_permissions=True) if name else modifier.insert(ignore_permissions=True)
			if not name:
				created.append(("TRT Modifier Group", modifier.name))
		groups[title] = modifier.name
	return groups


def _modifier_for(category, code, groups):
	if category == "Burgers":
		return groups["Burger extras"]
	if category in ("Sandwiches", "Wraps"):
		return groups["Sandwich extras"]
	if category == "Drinks" and code not in ("WATER", "COLA"):
		return groups["Drink choices"]
	return None


def _ensure_stations(outlet, created):
	stations = {}
	for title in ("Kitchen", "Bar"):
		name = frappe.db.get_value("TRT Kitchen Station",
			{"outlet": outlet.name, "title": title}, "name")
		if not name:
			station = _insert("TRT Kitchen Station", title=title, outlet=outlet.name, enabled=1)
			name = station.name
			created.append(("TRT Kitchen Station", name))
		stations[title] = name
	return stations


def _ensure_tables(outlet, created):
	area = frappe.db.get_value("TRT Service Area", {"outlet": outlet.name, "enabled": 1}, "name")
	if not area:
		area_doc = _insert("TRT Service Area", title="SAMPLE Dining Room",
			outlet=outlet.name, enabled=1)
		area = area_doc.name
		created.append(("TRT Service Area", area))
	tables = []
	for number in range(1, 5):
		title = f"SAMPLE T{number}"
		name = frappe.db.get_value("TRT Table", {"outlet": outlet.name, "title": title}, "name")
		if not name:
			table = _insert("TRT Table", title=title, area=area, outlet=outlet.name,
				seats=4, enabled=1)
			name = table.name
			created.append(("TRT Table", name))
		tables.append(name)
	return tables


def _ensure_menu(outlet, stations, modifier_groups, created):
	name = frappe.db.get_value("TRT Menu", {"outlet": outlet.name, "enabled": 1}, "name")
	if name:
		menu = frappe.get_doc("TRT Menu", name)
	else:
		menu = _insert("TRT Menu", title="SAMPLE Menu", outlet=outlet.name,
			enabled=1, show_on_till=1, show_on_kiosk=1, show_on_menu=1)
		created.append(("TRT Menu", menu.name))
	changed = False
	for field, enabled in (("show_on_till", 1), ("show_on_kiosk", int(bool(outlet.enable_kiosk))),
		("show_on_menu", int(bool(outlet.enable_qr or outlet.enable_pickup)))):
		if enabled and not menu.get(field):
			menu.set(field, 1)
			changed = True
	existing = {row.item: row for row in menu.items}
	for code, title, category, _rate, station in SAMPLE_ITEMS:
		item_code = f"TRT-SAMPLE-{code}"
		modifier_group = _modifier_for(category, code, modifier_groups)
		deal = SAMPLE_DEALS.get(code)
		if item_code in existing:
			if existing[item_code].modifier_group != modifier_group:
				existing[item_code].modifier_group = modifier_group
				changed = True
			if deal and (existing[item_code].deal_kind != deal[0] or
					existing[item_code].deal_description != deal[1]):
				existing[item_code].deal_kind = deal[0]
				existing[item_code].deal_description = deal[1]
				changed = True
			continue
		menu.append("items", {"item": item_code, "category": f"TRT SAMPLE {category}",
			"name_en": title, "station": stations[station], "modifier_group": modifier_group,
			"deal_kind": deal[0] if deal else "", "deal_description": deal[1] if deal else "",
			"available": 1,
			"sort_order": len(menu.items) + 1})
		changed = True
	if changed:
		menu.save(ignore_permissions=True)
	return menu.name


def _ensure_outlet_ready(outlet, customer, created):
	changed = False
	if not outlet.walk_in_customer:
		outlet.walk_in_customer = customer
		changed = True
	if outlet.warehouse and frappe.db.get_value("Warehouse", outlet.warehouse, "is_group"):
		warehouse = frappe.db.get_value("POS Profile", outlet.pos_profile, "warehouse")
		if not warehouse or frappe.db.get_value("Warehouse", warehouse, "is_group"):
			frappe.throw(f"{outlet.title} requires a leaf sales warehouse")
		outlet.warehouse = warehouse
		changed = True
	if changed:
		outlet.save(ignore_permissions=True)
		created.append(("TRT Outlet updated", outlet.name))


def _event(outlet, scenario, action):
	return str(uuid.uuid5(uuid.NAMESPACE_URL, f"trt-sample:{outlet}:{scenario}:{action}"))


def _ensure_promotion(outlet, created):
	"""Give each sample outlet one staff-entered coupon without creating orders."""
	existing = frappe.db.get_value("TRT Promotion", {"outlet": outlet.name,
		"title": "SAMPLE 10% off"}, "name")
	if existing:
		return existing
	code = "SAMPLE10" if not frappe.db.exists("TRT Promotion", "SAMPLE10") else f"SAMPLE10-{outlet.name[:8].upper()}"
	promotion = frappe.get_doc({"doctype": "TRT Promotion", "code": code,
		"title": "SAMPLE 10% off", "outlet": outlet.name, "enabled": 1,
		"discount_type": "Percentage", "discount_value": 10}).insert(ignore_permissions=True)
	created.append(("TRT Promotion", promotion.name))
	return promotion.name


def seed_sample_promotion(outlet):
	"""Seed only a coupon on an existing sample outlet for interactive register testing."""
	if frappe.session.user != "Administrator":
		frappe.throw("Run sample seeding as Administrator", frappe.PermissionError)
	settings = frappe.get_doc("TRT Outlet", outlet)
	created = []
	code = _ensure_promotion(settings, created)
	frappe.db.commit()
	return {"outlet": outlet, "coupon_code": code, "created": bool(created)}


def _ensure_orders(outlet, tables, created):
	channels = {"Table": outlet.enable_tables, "Tab": outlet.enable_tabs,
		"Takeaway": outlet.enable_takeaway, "Till": 1,
		"Kiosk": outlet.enable_kiosk, "QR": outlet.enable_qr,
		"Pickup": outlet.enable_pickup, "Retail": outlet.enable_retail}
	for scenario, channel, codes, table_index in SAMPLE_ORDERS:
		if not channels[channel]:
			continue
		external_id = f"TRT-SAMPLE-{outlet.name}-{scenario}"
		if frappe.db.exists("TRT Order", {"external_id": external_id}):
			continue
		command = {"action": "create", "outlet": outlet.name, "channel": channel}
		if table_index is not None:
			command["table"] = tables[table_index]
		if channel == "Tab":
			command["tab_label"] = "SAMPLE Guest Tab"
		order = api.order_command(command, _event(outlet.name, scenario, "create"),
			expected_revision=0)
		frappe.db.set_value("TRT Order", order["name"], "external_id", external_id)
		for index, code in enumerate(codes):
			order = api.order_command({"action": "add_line", "item": f"TRT-SAMPLE-{code}",
				"qty": 1}, _event(outlet.name, scenario, f"line-{index}"),
				order_name=order["name"], expected_revision=order["revision"])
		order = api.order_command({"action": "send"}, _event(outlet.name, scenario, "send"),
			order_name=order["name"], expected_revision=order["revision"])
		created.append(("TRT Order", order["name"]))


def run(dry_run=False, include_orders=False):
	"""Seed menu masters; orders are opt-in for an empty KDS by default."""
	if frappe.session.user != "Administrator":
		frappe.throw("Run sample seeding as Administrator", frappe.PermissionError)
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() in ("true", "1", "yes")
	if isinstance(include_orders, str):
		include_orders = include_orders.lower() in ("true", "1", "yes")
	created = []
	try:
		outlets = frappe.get_all("TRT Outlet", filters={"enabled": 1},
			fields=["name", "title", "price_list"], order_by="creation asc")
		if not outlets:
			frappe.throw("Create an outlet before seeding sample data")
		customer = _ensure_customer(created)
		_ensure_items({row.price_list for row in outlets if row.price_list}, created)
		_ensure_raw_materials(created)
		companies = list(dict.fromkeys(frappe.db.get_value("TRT Outlet", row.name, "company")
			for row in outlets))
		_ensure_boms(companies, created)
		modifier_groups = _ensure_modifier_groups(created)
		for row in outlets:
			outlet = frappe.get_doc("TRT Outlet", row.name)
			_ensure_outlet_ready(outlet, customer, created)
			stations = _ensure_stations(outlet, created)
			tables = _ensure_tables(outlet, created)
			_ensure_menu(outlet, stations, modifier_groups, created)
			_ensure_promotion(outlet, created)
			if include_orders:
				_ensure_orders(outlet, tables, created)
		result = {"dry_run": bool(dry_run), "outlets": [row.name for row in outlets],
			"created": [{"doctype": doctype, "name": name} for doctype, name in created]}
		if dry_run:
			frappe.db.rollback()
		else:
			frappe.db.commit()
		return result
	except Exception:
		frappe.db.rollback()
		raise


def clear_active_orders(dry_run=False):
	"""Clear unpaid playground orders and their kitchen/idempotency records."""
	if frappe.session.user != "Administrator":
		frappe.throw("Run playground cleanup as Administrator", frappe.PermissionError)
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() in ("true", "1", "yes")
	orders = frappe.get_all("TRT Order", filters={"status": ["in",
		["Draft", "Sent", "Preparing", "Ready", "Served"]]},
		fields=["name", "pos_invoice"])
	names = [row.name for row in orders]
	if any(row.pos_invoice for row in orders) or (names and frappe.db.exists("TRT Payment Attempt",
		{"order": ["in", names]})):
		frappe.throw("An active order has a payment or invoice; review it before cleanup")
	tickets = frappe.get_all("TRT Kitchen Ticket", filters={"order": ["in", names]},
		pluck="name") if names else []
	events = frappe.get_all("TRT Sync Event", filters={"order": ["in", names]},
		pluck="name") if names else []
	result = {"dry_run": bool(dry_run), "orders": len(names),
		"kitchen_tickets": len(tickets), "sync_events": len(events)}
	if dry_run:
		return result
	try:
		for name in events:
			frappe.delete_doc("TRT Sync Event", name, ignore_permissions=True)
		for name in tickets:
			frappe.delete_doc("TRT Kitchen Ticket", name, ignore_permissions=True)
		for name in names:
			frappe.delete_doc("TRT Order", name, ignore_permissions=True)
		frappe.db.commit()
		return result
	except Exception:
		frappe.db.rollback()
		raise


def verify_modifiers():
	"""Exercise pricing, validation, and KDS notes, then roll back the test order."""
	if frappe.session.user != "Administrator":
		frappe.throw("Run modifier verification as Administrator", frappe.PermissionError)
	outlet = frappe.db.get_value("TRT Outlet", {"enabled": 1}, "name")
	if not outlet:
		frappe.throw("An enabled sample outlet is required")
	table = frappe.db.get_value("TRT Table", {"outlet": outlet, "qr_secret": ["!=", ""]},
		["name", "title", "qr_secret"], as_dict=True)
	if table:
		assert api.guest_link(outlet, "QR", table.name, table.qr_secret)["table_title"] == table.title
	try:
		burger = next(row for row in api.catalog(outlet, "Till")["items"]
			if row["item"] == "TRT-SAMPLE-BURGER")
		assert "maximum" not in burger["modifier_group"]
		order = api.order_command({"action": "create", "outlet": outlet, "channel": "Till"},
			str(uuid.uuid4()), expected_revision=0)
		assert order["order_number"].startswith("TRT-")
		try:
			api.order_command({"action": "add_line", "item": "TRT-SAMPLE-BURGER", "qty": 1,
				"modifiers": ["TRT-SAMPLE-MOD-OATMILK"]}, str(uuid.uuid4()),
				order_name=order["name"], expected_revision=order["revision"])
		except frappe.ValidationError:
			pass
		else:
			raise AssertionError("A modifier from another group was accepted")
		try:
			api.order_command({"action": "add_line", "item": "TRT-SAMPLE-BURGER", "qty": 1,
				"modifiers": ["TRT-SAMPLE-MOD-CHEESE", "TRT-SAMPLE-MOD-CHEESE"]},
				str(uuid.uuid4()), order_name=order["name"], expected_revision=order["revision"])
		except frappe.ValidationError:
			pass
		else:
			raise AssertionError("Duplicate modifier was accepted")
		order = api.order_command({"action": "add_line", "item": "TRT-SAMPLE-BURGER", "qty": 2,
			"modifiers": ["TRT-SAMPLE-MOD-CHEESE", "TRT-SAMPLE-MOD-BACON",
				"TRT-SAMPLE-MOD-JALAPENOS", "TRT-SAMPLE-MOD-NOONIONS"],
			"note": "Cut in half"}, str(uuid.uuid4()),
			order_name=order["name"], expected_revision=order["revision"])
		assert len(order["lines"][0]["modifiers"]) == 4
		assert order["lines"][0]["rate"] == 12.0
		assert order["lines"][0]["amount"] == 24.0
		order = api.order_command({"action": "send"}, str(uuid.uuid4()),
			order_name=order["name"], expected_revision=order["revision"])
		tickets = [row for row in api.kitchen_tickets(outlet, "All") if row.order == order["name"]]
		assert len(tickets) == 1
		assert tickets[0].order_number == order["order_number"]
		assert "Extra cheese" in tickets[0].lines[0].note
		assert "Jalapeños" in tickets[0].lines[0].note
		assert "No onions" in tickets[0].lines[0].note
		assert "Cut in half" in tickets[0].lines[0].note
		return {"order_number": order["order_number"],
			"rate": order["lines"][0]["rate"], "amount": order["lines"][0]["amount"],
			"ticket_note": tickets[0].lines[0].note, "invalid_choices_rejected": True,
			"qr_table_title": table.title if table else None}
	finally:
		frappe.db.rollback()


def verify_table_add_on():
	"""Verify a second order stays on the same table and gets its own ticket."""
	if frappe.session.user != "Administrator":
		frappe.throw("Run table verification as Administrator", frappe.PermissionError)
	outlet = frappe.db.get_value("TRT Outlet", {"enabled": 1, "enable_tables": 1}, "name")
	table = frappe.db.get_value("TRT Table", {"outlet": outlet, "enabled": 1}, "name") if outlet else None
	item_a = "TRT-SAMPLE-BURGER"
	item_b = "TRT-SAMPLE-COLA"
	if not outlet or not table:
		frappe.throw("A table-enabled outlet with a table is required")
	created_orders = []
	try:
		first = api.order_command({"action": "create", "outlet": outlet, "channel": "Table",
			"table": table, "guest_count": 4}, str(uuid.uuid4()), expected_revision=0)
		created_orders.append(first["name"])
		first = api.order_command({"action": "add_line", "item": item_a, "qty": 1},
			str(uuid.uuid4()), order_name=first["name"], expected_revision=first["revision"])
		first = api.order_command({"action": "send"}, str(uuid.uuid4()),
			order_name=first["name"], expected_revision=first["revision"])
		second = api.order_command({"action": "create", "outlet": outlet, "channel": "Table",
			"table": table, "guest_count": 4, "parent_order": first["name"]},
			str(uuid.uuid4()), expected_revision=0)
		created_orders.append(second["name"])
		second = api.order_command({"action": "add_line", "item": item_b, "qty": 1},
			str(uuid.uuid4()), order_name=second["name"], expected_revision=second["revision"])
		second = api.order_command({"action": "send"}, str(uuid.uuid4()),
			order_name=second["name"], expected_revision=second["revision"])
		cards = api.register_tables(outlet)
		card = next(row for row in cards if row["name"] == table)
		tickets = [row for row in api.kitchen_tickets(outlet, "All")
			if row.order in (first["name"], second["name"])]
		assert first["table"] == second["table"] == table
		assert second["parent_order"] == first["name"]
		assert len(card["orders"]) == 2 and len(tickets) == 2
		return {"table": card["title"], "guests": card["guest_count"],
			"orders": [first["order_number"], second["order_number"]],
			"tickets": len(tickets), "add_on_to": second["parent_order"]}
	finally:
		# order_command commits its idempotency and ticket records, so a DB
		# rollback alone cannot clean this verification data up.
		if created_orders:
			tickets = frappe.get_all("TRT Kitchen Ticket",
				filters={"order": ["in", created_orders]}, pluck="name")
			events = frappe.get_all("TRT Sync Event",
				filters={"order": ["in", created_orders]}, pluck="name")
			for name in events:
				frappe.delete_doc("TRT Sync Event", name, ignore_permissions=True)
			for name in tickets:
				frappe.delete_doc("TRT Kitchen Ticket", name, ignore_permissions=True)
			for name in reversed(created_orders):
				if frappe.db.exists("TRT Order", name):
					frappe.delete_doc("TRT Order", name, ignore_permissions=True)
			frappe.db.commit()
		frappe.db.rollback()
