"""Non-persistent local-site smoke check for the order command path."""

import json
import uuid

import frappe
from frappe.utils.file_manager import save_file

from table_remote_till import api
from table_remote_till import migration
from table_remote_till import onboarding


def run():
	frappe.set_user("Administrator")
	profile = frappe.get_doc("POS Profile", "testing")
	item = frappe.db.get_value("Item Price", {"price_list": profile.selling_price_list}, "item_code")
	customer = frappe.db.get_value("Customer", {}, "name")
	assert item and customer
	try:
		outlet = frappe.get_doc({"doctype": "TRT Outlet", "title": "Smoke Outlet",
			"company": profile.company, "warehouse": profile.warehouse,
			"pos_profile": profile.name, "price_list": profile.selling_price_list,
			"walk_in_customer": customer,
			"receivable_account": frappe.db.get_value("Company", profile.company, "default_receivable_account"),
			"base_currency": "USD", "cash_currency": "LBP", "enabled": 1,
			"enable_retail": 1, "enable_pickup": 1,
			"online_provider": "Sandbox", "allow_sandbox_payments": 1}).insert(ignore_permissions=True)
		station = frappe.get_doc({"doctype": "TRT Kitchen Station", "title": "Smoke Station",
			"outlet": outlet.name, "enabled": 1}).insert(ignore_permissions=True)
		menu = frappe.get_doc({"doctype": "TRT Menu", "title": "Smoke Menu", "outlet": outlet.name,
			"enabled": 1, "show_on_till": 1, "show_on_menu": 1})
		menu.append("items", {"item": item, "available": 1, "station": station.name})
		menu.insert(ignore_permissions=True)
		created = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Till", "customer": customer}, str(uuid.uuid4()), expected_revision=0)
		event_id = str(uuid.uuid4())
		added = api.order_command({"action": "add_line", "item": item, "qty": 2}, event_id,
			created["name"], created["revision"])
		duplicate = api.order_command({"action": "add_line", "item": item, "qty": 2}, event_id,
			created["name"], created["revision"])
		assert len(duplicate["lines"]) == 1
		assert added["grand_total"] > 0
		try:
			api.order_command({"action": "set_qty", "line": added["lines"][0]["name"], "qty": 3},
				str(uuid.uuid4()), created["name"], created["revision"])
		except frappe.TimestampMismatchError:
			pass
		else:
			raise AssertionError("Expected revision conflict")
		frappe.db.set_value("POS Profile", profile.name, "update_stock", 0)
		frappe.db.set_value("Item", item, "is_stock_item", 0)
		frappe.clear_cache()
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		for old in frappe.get_all("POS Opening Entry", filters={"pos_profile": profile.name,
			"status": "Open"}, pluck="name"):
			frappe.db.set_value("POS Opening Entry", old, "status", "Closed")
		opening = frappe.get_doc({"doctype": "POS Opening Entry", "pos_profile": profile.name,
			"company": profile.company, "user": "Administrator",
			"period_start_date": frappe.utils.now_datetime()})
		for payment in profile.payments:
			opening.append("balance_details", {"mode_of_payment": payment.mode_of_payment})
		opening.insert(ignore_permissions=True)
		opening.submit()
		settled = api.cash_checkout(created["name"],
			[{"mode_of_payment": "Cash", "currency": "USD", "amount": added["grand_total"]}],
			str(uuid.uuid4()), added["revision"])
		assert settled["status"] == "Settled" and settled["pos_invoice"]
		return_event = str(uuid.uuid4())
		returned = api.return_order(created["name"], return_event, settled["revision"])
		assert returned["status"] == "Returned" and returned["return_invoice"]
		assert api.return_order(created["name"], return_event, settled["revision"])["return_invoice"] == returned["return_invoice"]
		frappe.db.set_value("Currency", "LBP", "enabled", 1)
		frappe.get_doc({"doctype": "TRT FX Rate", "outlet": outlet.name,
			"effective_date": frappe.utils.today(), "lbp_per_usd": 89500,
			"approved_by": "Administrator", "approved_on": frappe.utils.now_datetime(),
			"enabled": 1}).insert(ignore_permissions=True)
		mixed_order = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Till", "customer": customer}, str(uuid.uuid4()), expected_revision=0)
		mixed_added = api.order_command({"action": "add_line", "item": item, "qty": 2},
			str(uuid.uuid4()), mixed_order["name"], mixed_order["revision"])
		mixed_tenders = [{"mode_of_payment": "Cash", "currency": "USD",
			"amount": mixed_added["grand_total"] / 2},
			{"mode_of_payment": "Cash", "currency": "LBP",
			"amount": mixed_added["grand_total"] / 2 * 89500}]
		mixed_event = str(uuid.uuid4())
		mixed_settled = api.cash_checkout(mixed_order["name"], mixed_tenders,
			mixed_event, mixed_added["revision"])
		assert mixed_settled["status"] == "Settled" and mixed_settled["exchange_rate"] == 89500
		assert api.cash_checkout(mixed_order["name"], mixed_tenders,
			mixed_event, mixed_added["revision"])["name"] == mixed_order["name"]
		cashier_email = f"trt-smoke-{uuid.uuid4().hex[:8]}@example.invalid"
		cashier = frappe.get_doc({"doctype": "User", "email": cashier_email,
			"first_name": "Smoke Cashier", "send_welcome_email": 0,
			"roles": [{"role": "TRT Cashier"}]}).insert(ignore_permissions=True)
		frappe.set_user(cashier.name)
		try:
			api.order_command({"action": "create", "outlet": outlet.name,
				"channel": "Till"}, str(uuid.uuid4()), expected_revision=0)
		except frappe.PermissionError:
			pass
		else:
			raise AssertionError("Unassigned cashier accessed outlet")
		frappe.set_user("Administrator")
		frappe.get_doc({"doctype": "TRT Staff Assignment", "user": cashier.name,
			"outlet": outlet.name, "allow_till": 1, "enabled": 1}).insert(ignore_permissions=True)
		frappe.set_user(cashier.name)
		assert len(api.bootstrap()["outlets"]) == 1
		cashier_order = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Till"}, str(uuid.uuid4()), expected_revision=0)
		cashier_added = api.order_command({"action": "add_line", "item": item, "qty": 1},
			str(uuid.uuid4()), cashier_order["name"], cashier_order["revision"])
		cashier_settled = api.cash_checkout(cashier_order["name"],
			[{"mode_of_payment": "Cash", "currency": "USD",
				"amount": cashier_added["grand_total"]}], str(uuid.uuid4()), cashier_added["revision"])
		assert cashier_settled["pos_invoice"]
		frappe.set_user("Administrator")
		link = api.guest_link(outlet.name, "Pickup")
		frappe.set_user("Guest")
		guest = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Pickup"}, str(uuid.uuid4()), expected_revision=0,
			guest_token=link["token"])
		other_link = api.guest_link(outlet.name, "Pickup")
		try:
			api.order_command({"action": "add_line", "item": item, "qty": 1},
				str(uuid.uuid4()), guest["name"], guest["revision"], other_link["token"])
		except frappe.PermissionError:
			pass
		else:
			raise AssertionError("Another guest session modified an order")
		guest_item = api.order_command({"action": "add_line", "item": item, "qty": 1},
			str(uuid.uuid4()), guest["name"], guest["revision"], link["token"])
		assert guest_item["grand_total"] > 0
		if frappe.conf.developer_mode:
			attempt = api.payment_intent(guest["name"], str(uuid.uuid4()),
				guest_item["revision"], link["token"])
			captured = api.sandbox_capture(attempt["attempt"], guest_item["revision"], link["token"])
			assert captured["status"] == "Sent"
			frappe.set_user("Administrator")
			tickets = [ticket for ticket in api.kitchen_tickets(outlet.name)
				if ticket.order == guest["name"]]
			assert len(tickets) == 1
			updated = api.set_ticket_status(tickets[0]["name"], "Preparing",
				str(uuid.uuid4()), tickets[0]["revision"])
			assert updated["status"] == "Preparing"
		return json.dumps({"created": created["name"], "priced_total": added["grand_total"],
			"idempotent": True, "version_conflict": True, "guest_priced": guest_item["grand_total"],
			"cash_invoice": settled["pos_invoice"], "mixed_cash_invoice": mixed_settled["pos_invoice"],
			"cashier_invoice": cashier_settled["pos_invoice"],
			"return_invoice": returned["return_invoice"],
			"sandbox_tested": bool(frappe.conf.developer_mode)})
	finally:
		frappe.db.rollback()


def migration_run():
	frappe.set_user("Administrator")
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	assert group and territory
	file = None
	try:
		job = frappe.get_doc("TRT Import Job", migration.new_job("Omega POS", "Customer")["job"])
		content = f"id,name,group,territory\nC-100,Migration Smoke,{group},{territory}\n".encode()
		file = save_file(f"trt-smoke-{uuid.uuid4()}.csv", content, "TRT Import Job", job.name,
			is_private=1)
		migration.attach_export(job.name, file.name)
		assert migration.suggest_mapping(job.name)["mapping"]["source_id"] == "id"
		mapping = {"source_id": "id", "name": "name", "customer_group": "group",
			"territory": "territory"}
		preview = migration.preview(job.name, json.dumps(mapping))
		assert preview["rows"] == 1 and not preview["errors"]
		result = migration.import_masters(job.name)
		assert result["counts"]["imported"] == 1
		return json.dumps({"preview_rows": preview["rows"], "imported": result["counts"]["imported"]})
	finally:
		if file:
			file.delete(ignore_permissions=True)
		frappe.db.rollback()


def onboarding_run():
	"""Exercise a fresh outlet, generated ERP masters, and idempotent replay."""
	frappe.set_user("Administrator")
	try:
		choices = onboarding.options()
		assert choices["companies"]
		company = choices["company"]
		name = f"TRT Smoke {uuid.uuid4().hex[:8]}"
		config = {"company": company, "business_type": "Restaurant/Pub",
			"outlet_title": name, "branch": name, "register_title": "Main Register",
			"channels": ["Table", "Tab", "Takeaway", "Kiosk", "QR", "Pickup"],
			"seed_sample_data": True,
			"cash_mode": choices["defaults"]["cash_mode"],
			"write_off_account": choices["defaults"]["write_off_account"],
			"cost_center": choices["defaults"]["cost_center"]}
		frappe.set_user("Guest")
		try:
			onboarding.preview_setup(config)
		except frappe.PermissionError:
			pass
		else:
			raise AssertionError("Guest could preview onboarding")
		frappe.set_user("Administrator")
		plan = onboarding.preview_setup(config)
		assert any(row["label"] == "POS Profile" and row["action"] == "Create"
			for row in plan["actions"])
		request_id = str(uuid.uuid4())
		result = onboarding.apply_setup(config, request_id)
		assert frappe.db.exists("TRT Outlet", result["outlet"])
		assert frappe.db.exists("TRT Register", result["register"])
		assert frappe.db.exists("POS Profile", result["pos_profile"])
		assert frappe.db.get_value("TRT Outlet", result["outlet"], "enable_qr") == 1
		assert frappe.db.exists("TRT Table", {"outlet": result["outlet"], "title": "T1"})
		assert frappe.db.count("TRT Menu Entry", {"parent": frappe.db.get_value(
			"TRT Menu", {"outlet": result["outlet"]}, "name")}) == 3
		assert onboarding.apply_setup(config, request_id) == result
		assert frappe.db.count("TRT Onboarding Run", {"request_id": request_id}) == 1
		return json.dumps({"outlet": result["outlet"], "created": len(result["created"]),
			"replay_safe": True})
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()


def workspace_run():
	"""Confirm Desk exposes each parent record and embeds each child table."""
	frappe.set_user("Administrator")
	workspace = frappe.get_doc("Workspace", "Table Remote Till")
	parents = set(frappe.get_all("DocType", filters={"module": "Table Remote Till",
		"istable": 0}, pluck="name"))
	children = set(frappe.get_all("DocType", filters={"module": "Table Remote Till",
		"istable": 1}, pluck="name"))
	linked = {row.link_to for row in workspace.links if row.type == "Link" and row.link_type == "DocType"}
	assert parents == linked, {"missing": sorted(parents - linked), "extra": sorted(linked - parents)}
	embedded = {field.options for parent in parents for field in frappe.get_meta(parent).fields
		if field.fieldtype == "Table"}
	assert children <= embedded, sorted(children - embedded)
	assert any(row.type == "URL" and row.url == "/onboarding" for row in workspace.shortcuts)
	return json.dumps({"parent_doctypes": len(parents), "child_tables": len(children),
		"workspace": workspace.name})


def onboarding_retail_run():
	"""A retail-only site gets a saleable demo catalog without a floor plan."""
	frappe.set_user("Administrator")
	try:
		choices = onboarding.options()
		name = f"TRT Retail {uuid.uuid4().hex[:8]}"
		config = {"company": choices["company"], "business_type": "Retail",
			"outlet_title": name, "branch": name, "register_title": "Front Register",
			"channels": ["Retail"], "seed_sample_data": True,
			"cash_mode": choices["defaults"]["cash_mode"],
			"write_off_account": choices["defaults"]["write_off_account"],
			"cost_center": choices["defaults"]["cost_center"]}
		result = onboarding.apply_setup(config, str(uuid.uuid4()))
		outlet = frappe.get_doc("TRT Outlet", result["outlet"])
		assert outlet.enable_retail and not outlet.enable_tables
		assert not frappe.db.exists("TRT Service Area", {"outlet": outlet.name})
		menu = frappe.get_doc("TRT Menu", frappe.db.get_value("TRT Menu", {"outlet": outlet.name}, "name"))
		assert len(menu.items) == 3
		assert all(frappe.db.get_value("Item", row.item, "is_stock_item") == 0 for row in menu.items)
		return json.dumps({"outlet": outlet.name, "demo_items": len(menu.items)})
	finally:
		frappe.db.rollback()


def isolation_marker():
	"""Create a marker on a disposable site to verify database isolation."""
	frappe.set_user("Administrator")
	marker = frappe.get_doc({"doctype": "TRT Modifier Group",
		"title": "TRT fresh-site isolation marker"}).insert(ignore_permissions=True)
	frappe.db.commit()
	return marker.name
