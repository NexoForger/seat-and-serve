"""Non-persistent local-site smoke check for the order command path."""

import json
import uuid
from datetime import timedelta

import frappe
from frappe.utils import now_datetime
from frappe.utils.file_manager import save_file

from table_remote_till import api
from table_remote_till import cleanup
from table_remote_till import migration
from table_remote_till import onboarding
from table_remote_till import reservations
from table_remote_till.promotions import discount_for_bill


def deals_run():
	"""Check the seeded register deals, server price, and kitchen contents without saving an order."""
	frappe.set_user("Administrator")
	try:
		outlet = frappe.db.get_value("TRT Menu Entry", {"item": "TRT-SAMPLE-BURGERFRIESDEAL"}, "parent")
		assert outlet, "Seed the sample deals first"
		outlet = frappe.db.get_value("TRT Menu", outlet, "outlet")
		items = {row["item"]: row for row in api.catalog(outlet, "Till")["items"]}
		deals = {code: items[f"TRT-SAMPLE-{code}"] for code in
			("BURGERFRIESDEAL", "CHICKENSALADDEAL", "SNACKDUO")}
		assert [deals[code]["rate"] for code in deals] == [10.5, 11.5, 6.5]
		assert all(row["deal_description"] for row in deals.values())
		order = api.order_command({"action": "create", "outlet": outlet, "channel": "Till"},
			str(uuid.uuid4()), expected_revision=0)
		for code, deal in deals.items():
			order = api.order_command({"action": "add_line", "item": f"TRT-SAMPLE-{code}"},
				str(uuid.uuid4()), order["name"], order["revision"])
			line = order["lines"][-1]
			assert line["rate"] == deal["rate"]
			assert deal["deal_description"] in line["note"]
		order = api.order_command({"action": "send"}, str(uuid.uuid4()),
			order["name"], order["revision"])
		tickets = frappe.get_all("TRT Kitchen Ticket", filters={"order": order["name"]}, pluck="name")
		assert len(tickets) == 1
		assert len(frappe.get_doc("TRT Kitchen Ticket", tickets[0]).lines) == 3
		kitchen_card = next(row for row in api.kitchen_tickets(outlet, "All") if row.name == tickets[0])
		assert kitchen_card["lines"][0]["item_name"] == "Burger & Fries Combo"
		assert deals["BURGERFRIESDEAL"]["deal_description"] in kitchen_card["lines"][0]["note"]
		return {"deals": list(deals), "total": order["grand_total"], "kitchen_ticket": True}
	finally:
		frappe.db.rollback()


def promotions_run():
	"""Exercise coupon, manager discount, and loyalty against real POS Invoices; roll back all data."""
	frappe.set_user("Administrator")
	profile = frappe.get_doc("POS Profile", "testing")
	item = frappe.db.get_value("Item Price", {"price_list": profile.selling_price_list}, "item_code")
	customer = frappe.db.get_value("Customer", {}, "name")
	assert item and customer
	try:
		frappe.db.set_value("POS Profile", profile.name, "update_stock", 0)
		frappe.db.set_value("Item", item, "is_stock_item", 0)
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		for old in frappe.get_all("POS Opening Entry", filters={"user": "Administrator",
			"status": "Open"}, pluck="name"):
			frappe.db.set_value("POS Opening Entry", old, "status", "Closed")
		opening = frappe.get_doc({"doctype": "POS Opening Entry", "pos_profile": profile.name,
			"company": profile.company, "user": "Administrator",
			"period_start_date": now_datetime()})
		for payment in profile.payments:
			opening.append("balance_details", {"mode_of_payment": payment.mode_of_payment})
		opening.insert(ignore_permissions=True)
		opening.submit()
		outlet = frappe.get_doc({"doctype": "TRT Outlet", "title": "Promotion Smoke",
			"company": profile.company, "warehouse": profile.warehouse,
			"pos_profile": profile.name, "price_list": profile.selling_price_list,
			"walk_in_customer": customer,
			"receivable_account": frappe.db.get_value("Company", profile.company, "default_receivable_account"),
			"base_currency": "USD", "cash_currency": "USD", "enabled": 1,
			"enable_tables": 1, "reservation_open_time": "00:00:00",
			"reservation_close_time": "23:59:00"}).insert(ignore_permissions=True)
		station = frappe.get_doc({"doctype": "TRT Kitchen Station", "title": "Promotion Smoke",
			"outlet": outlet.name, "enabled": 1}).insert(ignore_permissions=True)
		menu = frappe.get_doc({"doctype": "TRT Menu", "title": "Promotion Smoke",
			"outlet": outlet.name, "enabled": 1, "show_on_till": 1})
		menu.append("items", {"item": item, "available": 1, "station": station.name})
		menu.insert(ignore_permissions=True)
		area = frappe.get_doc({"doctype": "TRT Service Area", "title": "Promotion Smoke",
			"outlet": outlet.name, "enabled": 1}).insert(ignore_permissions=True)
		table = frappe.get_doc({"doctype": "TRT Table", "title": "P1", "outlet": outlet.name,
			"area": area.name, "seats": 2, "enabled": 1}).insert(ignore_permissions=True)
		tax_account = frappe.db.get_value("Account", {"company": profile.company,
			"account_type": "Tax", "is_group": 0}, "name")
		tax = frappe.get_doc({"doctype": "Sales Taxes and Charges Template",
			"title": f"Promotion VAT {uuid.uuid4().hex[:8]}", "company": profile.company,
			"taxes": [{"charge_type": "On Net Total", "account_head": tax_account,
				"description": "Promotion VAT", "rate": 11}]}).insert(ignore_permissions=True)
		frappe.db.set_value("TRT Outlet", outlet.name, "tax_template", tax.name)
		frappe.clear_cache()
		code = f"SMOKE{uuid.uuid4().hex[:12].upper()}"
		promotion = frappe.get_doc({"doctype": "TRT Promotion", "code": code.lower(),
			"title": "Ten percent", "outlet": outlet.name, "enabled": 1,
			"discount_type": "Percentage", "discount_value": 10, "max_uses": 1,
			"valid_from": frappe.utils.today(), "valid_until": frappe.utils.today()}).insert(ignore_permissions=True)
		assert promotion.name == code
		root = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Table",
			"table": table.name}, str(uuid.uuid4()), expected_revision=0)
		root = api.order_command({"action": "add_line", "item": item, "qty": 1},
			str(uuid.uuid4()), root["name"], root["revision"])
		addon = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Table",
			"table": table.name, "parent_order": root["name"]}, str(uuid.uuid4()), expected_revision=0)
		addon = api.order_command({"action": "add_line", "item": item, "qty": 2},
			str(uuid.uuid4()), addon["name"], addon["revision"])
		pre_total = addon["bill"]["grand_total"]
		configured = api.configure_bill(addon["name"], {"coupon_code": code},
			str(uuid.uuid4()), addon["bill"]["root_revision"])
		bill = configured["bill"]
		assert bill["ticket_count"] == 2 and bill["discount_amount"] > 0
		assert abs(bill["grand_total"] - (pre_total - bill["discount_amount"])) < 0.02
		frappe.db.set_value("TRT Promotion", code, "minimum_total", pre_total + 1)
		assert api.register_order(outlet.name, addon["name"])["bill"]["billing_errors"]
		frappe.db.set_value("TRT Promotion", code, "minimum_total", 0)
		cash = [{"mode_of_payment": "Cash", "currency": "USD", "amount": bill["amount_due"]}]
		event = str(uuid.uuid4())
		paid = api.cash_checkout(addon["name"], cash, event, configured["revision"])
		assert api.cash_checkout(addon["name"], cash, event, configured["revision"])["pos_invoice"] == paid["pos_invoice"]
		invoice = frappe.get_doc("POS Invoice", paid["pos_invoice"])
		assert invoice.docstatus == 1 and len(invoice.items) == 2
		assert all(row.included_in_print_rate for row in invoice.taxes)
		assert abs(float(invoice.rounded_total or invoice.grand_total) - bill["grand_total"]) < 0.01
		assert frappe.db.count("TRT Promotion Redemption", {"order": root["name"],
			"pos_invoice": invoice.name}) == 1
		try:
			discount_for_bill(frappe._dict({"promotion": code, "currency": "USD"}), outlet, 100)
		except frappe.ValidationError:
			pass
		else:
			raise AssertionError("Used-up coupon was accepted")
		assert frappe.db.count("TRT Payment Attempt", {"order": root["name"],
			"pos_invoice": invoice.name}) == 1
		assert frappe.db.get_value("TRT Order", root["name"], "pos_invoice") == invoice.name
		reservation_table = frappe.get_doc({"doctype": "TRT Table", "title": "P2",
			"outlet": outlet.name, "area": area.name, "seats": 2,
			"enabled": 1}).insert(ignore_permissions=True)
		day = str(now_datetime().date())
		slot = reservations.reservation_availability(outlet.name, day, 2,
			reservation_table.name)["slots"][0]
		booked = reservations.register_book_reservation({"outlet": outlet.name,
			"date": day, "time": slot, "party_size": 2,
			"table": reservation_table.name, "guest_name": "Paid Booking",
			"phone": "+961 71123456"}, str(uuid.uuid4()))
		booking_name = frappe.db.get_value("TRT Reservation",
			{"reservation_number": booked["reservation_number"]}, "name")
		seated = reservations.seat_reservation(booking_name, str(uuid.uuid4()))
		seated = api.order_command({"action": "add_line", "item": item},
			str(uuid.uuid4()), seated["name"], seated["revision"])
		booking_addon = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Table", "table": reservation_table.name,
			"parent_order": seated["name"]}, str(uuid.uuid4()), expected_revision=0)
		booking_addon = api.order_command({"action": "add_line", "item": item},
			str(uuid.uuid4()), booking_addon["name"], booking_addon["revision"])
		paid_booking = api.cash_checkout(booking_addon["name"], [{"mode_of_payment": "Cash",
			"currency": "USD", "amount": booking_addon["bill"]["amount_due"]}],
			str(uuid.uuid4()), booking_addon["revision"])
		assert frappe.db.get_value("TRT Reservation", booking_name, "status") == "Completed"
		assert frappe.db.get_value("TRT Order", seated["name"], "pos_invoice") == paid_booking["pos_invoice"]
		assert frappe.db.get_value("TRT Order", booking_addon["name"], "pos_invoice") == paid_booking["pos_invoice"]
		assert len(frappe.get_doc("POS Invoice", paid_booking["pos_invoice"]).items) == 2
		manual = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Till"},
			str(uuid.uuid4()), expected_revision=0)
		manual = api.order_command({"action": "add_line", "item": item},
			str(uuid.uuid4()), manual["name"], manual["revision"])
		manual = api.configure_bill(manual["name"], {"manual_discount_type": "Percentage",
			"manual_discount_value": 100, "manual_discount_reason": "Service recovery"},
			str(uuid.uuid4()), manual["bill"]["root_revision"])
		assert manual["bill"]["amount_due"] == 0
		free = api.cash_checkout(manual["name"], [], str(uuid.uuid4()), manual["revision"])
		assert free["status"] == "Settled" and frappe.get_doc("POS Invoice", free["pos_invoice"]).docstatus == 1
		expense = frappe.db.get_value("Account", {"company": profile.company,
			"root_type": "Expense", "is_group": 0}, "name")
		cost_center = frappe.db.get_value("Cost Center", {"company": profile.company,
			"is_group": 0}, "name")
		program = frappe.get_doc({"doctype": "Loyalty Program",
			"loyalty_program_name": f"Smoke Loyalty {uuid.uuid4().hex[:8]}",
			"company": profile.company, "from_date": frappe.utils.today(),
			"loyalty_program_type": "Single Tier Program", "expiry_duration": 365,
			"conversion_factor": 0.25, "expense_account": expense,
			"cost_center": cost_center,
			"collection_rules": [{"tier_name": "Member", "min_spent": 0,
				"collection_factor": 1}]}).insert(ignore_permissions=True)
		member = frappe.get_doc({"doctype": "Customer",
			"customer_name": f"Promotion Member {uuid.uuid4().hex[:8]}",
			"customer_type": "Individual",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			"loyalty_program": program.name}).insert(ignore_permissions=True)
		first = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Till",
			"customer": member.name}, str(uuid.uuid4()), expected_revision=0)
		first = api.order_command({"action": "add_line", "item": item, "qty": 2},
			str(uuid.uuid4()), first["name"], first["revision"])
		first_bill = first["bill"]
		first = api.cash_checkout(first["name"], [{"mode_of_payment": "Cash",
			"currency": "USD", "amount": first_bill["amount_due"]}],
			str(uuid.uuid4()), first["revision"])
		assert frappe.db.count("Loyalty Point Entry", {"customer": member.name,
			"invoice": first["pos_invoice"]}) == 1
		second = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Till", "customer": member.name}, str(uuid.uuid4()), expected_revision=0)
		second = api.order_command({"action": "add_line", "item": item, "qty": 1},
			str(uuid.uuid4()), second["name"], second["revision"])
		assert second["bill"]["loyalty"]["available_points"] >= 2
		second = api.configure_bill(second["name"], {"customer": member.name,
			"loyalty_points": 2}, str(uuid.uuid4()), second["bill"]["root_revision"])
		assert second["bill"]["loyalty"]["amount"] == 0.5
		second = api.cash_checkout(second["name"], [{"mode_of_payment": "Cash",
			"currency": "USD", "amount": second["bill"]["amount_due"]}],
			str(uuid.uuid4()), second["revision"])
		loyalty_invoice = frappe.get_doc("POS Invoice", second["pos_invoice"])
		assert loyalty_invoice.docstatus == 1 and loyalty_invoice.loyalty_points == 2
		assert loyalty_invoice.discount_amount == 0.5
		assert frappe.db.get_value("TRT Order", second["name"], "loyalty_amount_redeemed") == 0.5
		assert frappe.db.count("Loyalty Point Entry", {"customer": member.name,
			"invoice": loyalty_invoice.name, "loyalty_points": -2}) == 1
		assert second["bill"]["amount_due"] == float(loyalty_invoice.rounded_total or loyalty_invoice.grand_total)
		returned_loyalty = api.return_order(second["name"], str(uuid.uuid4()), second["revision"])
		assert frappe.db.get_value("POS Invoice", returned_loyalty["return_invoice"], "docstatus") == 1
		return json.dumps({"coupon_invoice": invoice.name, "coupon_discount": bill["discount_amount"],
			"manual_invoice": free["pos_invoice"], "loyalty_invoice": second["pos_invoice"],
			"one_redemption": True})
	finally:
		frappe.db.rollback()


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
			"enable_retail": 1, "enable_pickup": 1, "enable_tables": 1,
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
		for old in frappe.get_all("POS Opening Entry", filters={"user": "Administrator",
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
		area = frappe.get_doc({"doctype": "TRT Service Area", "title": "Smoke Dining Room",
			"outlet": outlet.name, "enabled": 1}).insert(ignore_permissions=True)
		tax_account = frappe.db.get_value("Account", {"company": profile.company,
			"account_type": "Tax", "is_group": 0}, "name")
		assert tax_account
		tax_template = frappe.get_doc({"doctype": "Sales Taxes and Charges Template",
			"title": f"Smoke VAT {uuid.uuid4().hex[:8]}", "company": profile.company,
			"taxes": [{"charge_type": "On Net Total", "account_head": tax_account,
				"description": "Smoke VAT", "rate": 11}]}).insert(ignore_permissions=True)
		frappe.db.set_value("TRT Outlet", outlet.name, "tax_template", tax_template.name)
		frappe.clear_cache()
		table = frappe.get_doc({"doctype": "TRT Table", "title": "Smoke Table",
			"outlet": outlet.name, "area": area.name, "seats": 4,
			"enabled": 1}).insert(ignore_permissions=True)
		root = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Table",
			"table": table.name, "guest_count": 2}, str(uuid.uuid4()), expected_revision=0)
		root = api.order_command({"action": "add_line", "item": item, "qty": 1},
			str(uuid.uuid4()), root["name"], root["revision"])
		root = api.order_command({"action": "send"}, str(uuid.uuid4()), root["name"], root["revision"])
		addon = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Table",
			"table": table.name, "guest_count": 2, "parent_order": root["name"]},
			str(uuid.uuid4()), expected_revision=0)
		addon = api.order_command({"action": "add_line", "item": item, "qty": 2},
			str(uuid.uuid4()), addon["name"], addon["revision"])
		addon = api.order_command({"action": "send"}, str(uuid.uuid4()), addon["name"], addon["revision"])
		draft_addon = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Table",
			"table": table.name, "guest_count": 2, "parent_order": addon["name"]},
			str(uuid.uuid4()), expected_revision=0)
		draft_addon = api.order_command({"action": "add_line", "item": item, "qty": 3},
			str(uuid.uuid4()), draft_addon["name"], draft_addon["revision"])
		other_table = frappe.get_doc({"doctype": "TRT Table", "title": "Smoke Other Table",
			"outlet": outlet.name, "area": area.name, "seats": 4,
			"enabled": 1}).insert(ignore_permissions=True)
		other = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Table",
			"table": other_table.name, "guest_count": 1}, str(uuid.uuid4()), expected_revision=0)
		other = api.order_command({"action": "add_line", "item": item, "qty": 4},
			str(uuid.uuid4()), other["name"], other["revision"])
		bill = api.register_order(outlet.name, draft_addon["name"])["bill"]
		assert bill["ticket_count"] == 3 and bill["item_count"] == 6
		assert bill["order_numbers"] == [root["order_number"], addon["order_number"], draft_addon["order_number"]]
		assert abs(bill["grand_total"] - sum(ticket["grand_total"] for ticket in (root, addon, draft_addon))) < 0.01
		cash = [{"mode_of_payment": "Cash", "currency": "USD", "amount": bill["grand_total"]}]
		bill_event = str(uuid.uuid4())
		paid = api.cash_checkout(draft_addon["name"], cash, bill_event, draft_addon["revision"])
		assert api.cash_checkout(draft_addon["name"], cash, bill_event, draft_addon["revision"])["pos_invoice"] == paid["pos_invoice"]
		assert api.cash_checkout(root["name"], cash, str(uuid.uuid4()), root["revision"])["pos_invoice"] == paid["pos_invoice"]
		members = [frappe.get_doc("TRT Order", name) for name in (root["name"], addon["name"], draft_addon["name"])]
		assert all(member.status == "Settled" and member.pos_invoice == paid["pos_invoice"] for member in members)
		invoice = frappe.get_doc("POS Invoice", paid["pos_invoice"])
		assert invoice.docstatus == 1 and [(row.item_code, row.qty) for row in invoice.items] == [
			(item, 1), (item, 2), (item, 3)]
		assert abs(float(invoice.rounded_total or invoice.grand_total) - bill["grand_total"]) < 0.01
		assert float(invoice.total_taxes_and_charges) > 0
		assert all(int(tax.included_in_print_rate) for tax in invoice.taxes)
		group_tickets = [ticket for ticket in api.kitchen_tickets(outlet.name, "All")
			if ticket.order in (root["name"], addon["name"], draft_addon["name"])]
		assert len(group_tickets) == 3 and len({ticket.order for ticket in group_tickets}) == 3
		assert frappe.db.count("TRT Payment Attempt", {"pos_invoice": invoice.name, "order": root["name"]}) == 1
		assert frappe.db.count("TRT Sync Event", {"event_id": bill_event}) == 1
		assert frappe.db.get_value("TRT Order", other["name"], "status") == "Draft"
		assert api.register_order(outlet.name, root["name"])["bill"]["pos_invoice"] == invoice.name
		assert api.register_order(outlet.name, draft_addon["name"])["bill"]["grand_total"] == float(invoice.rounded_total or invoice.grand_total)
		other_addon = api.order_command({"action": "create", "outlet": outlet.name, "channel": "Table",
			"table": other_table.name, "guest_count": 1, "parent_order": other["name"]},
			str(uuid.uuid4()), expected_revision=0)
		other_addon = api.order_command({"action": "add_line", "item": item, "qty": 1},
			str(uuid.uuid4()), other_addon["name"], other_addon["revision"])
		other_bill = api.register_order(outlet.name, other["name"])["bill"]
		other_paid = api.cash_checkout(other["name"], [{"mode_of_payment": "Cash",
			"currency": "USD", "amount": other_bill["grand_total"]}], str(uuid.uuid4()), other["revision"])
		assert other_paid["pos_invoice"] != invoice.name
		assert frappe.db.get_value("TRT Order", other_addon["name"], "pos_invoice") == other_paid["pos_invoice"]
		assert [(row.item_code, row.qty) for row in frappe.get_doc("POS Invoice", other_paid["pos_invoice"]).items] == [
			(item, 4), (item, 1)]
		frappe.db.set_value("TRT Outlet", outlet.name, "tax_template", None)
		frappe.clear_cache()
		assert api.register_order(outlet.name, root["name"])["bill"]["grand_total"] == bill["grand_total"]
		try:
			api.order_command({"action": "create", "outlet": outlet.name, "channel": "Table",
				"table": table.name, "guest_count": 2, "parent_order": root["name"]},
				str(uuid.uuid4()), expected_revision=0)
		except frappe.ValidationError:
			pass
		else:
			raise AssertionError("Add-on was accepted after the table bill settled")
		expiry_root = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Table", "table": table.name, "guest_count": 2},
			str(uuid.uuid4()), expected_revision=0)
		expired_event = str(uuid.uuid4())
		expired = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Table", "table": table.name, "guest_count": 2,
			"parent_order": expiry_root["name"]}, expired_event, expected_revision=0)
		fresh = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Table", "table": table.name, "guest_count": 2,
			"parent_order": expiry_root["name"]}, str(uuid.uuid4()), expected_revision=0)
		nonempty = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Table", "table": table.name, "guest_count": 2,
			"parent_order": expiry_root["name"]}, str(uuid.uuid4()), expected_revision=0)
		nonempty = api.order_command({"action": "add_line", "item": item, "qty": 1},
			str(uuid.uuid4()), nonempty["name"], nonempty["revision"])
		counter_draft = api.order_command({"action": "create", "outlet": outlet.name,
			"channel": "Till"}, str(uuid.uuid4()), expected_revision=0)
		old = now_datetime() - timedelta(minutes=6)
		for name in (expiry_root["name"], expired["name"], nonempty["name"], counter_draft["name"]):
			frappe.db.sql("UPDATE `tabTRT Order` SET modified=%s WHERE name=%s", (old, name))
		cards = api.register_tables(outlet.name)
		assert any(ticket.name == expired["name"] and ticket.expired_empty_addon
			for card in cards for ticket in card["orders"])
		assert cleanup.expire_empty_addon_drafts(outlet.name) == [expired["name"]]
		assert cleanup.expire_empty_addon_drafts(outlet.name) == []
		assert not frappe.db.exists("TRT Order", expired["name"])
		assert all(frappe.db.exists("TRT Order", name) for name in
			(expiry_root["name"], fresh["name"], nonempty["name"], counter_draft["name"]))
		assert frappe.db.get_value("TRT Sync Event", {"event_id": expired_event},
			["order", "status"]) == (None, "Expired")
		try:
			api.order_command({"action": "create", "outlet": outlet.name,
				"channel": "Table", "table": table.name, "guest_count": 2,
				"parent_order": expiry_root["name"]}, expired_event, expected_revision=0)
		except frappe.ValidationError:
			pass
		else:
			raise AssertionError("Expired draft replay created a second add-on")
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
			"table_bill_invoice": paid["pos_invoice"], "table_bill_tickets": bill["ticket_count"],
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


def bim_migration_run():
	"""Exercise a BIM-shaped, semicolon-delimited Arabic product export and price import."""
	frappe.set_user("Administrator")
	price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	assert price_list and group
	currency = frappe.db.get_value("Price List", price_list, "currency")
	code = f"BIM-SMOKE-{uuid.uuid4().hex[:10]}"
	file = None
	try:
		job = frappe.get_doc("TRT Import Job", migration.new_job(
			"BIM POS", "Item", target_price_list=price_list)["job"])
		content = f"prodnum;prodname;category;unit;saleprice;currency\n{code};قهوة;{group};Nos;12.50;{currency}\n".encode("cp1256")
		file = frappe.get_doc({"doctype": "File", "file_name": f"bim-smoke-{uuid.uuid4()}.csv",
			"content": content, "attached_to_doctype": "TRT Import Job",
			"attached_to_name": job.name, "is_private": 1}).insert(ignore_permissions=True)
		raw = frappe.get_doc("File", file.name).get_content(encodings=[])
		assert raw == content
		migration.attach_export(job.name, file.name)
		mapping = migration.suggest_mapping(job.name)["mapping"]
		assert all(mapping[field] == column for field, column in {
			"source_id": "prodnum", "name": "prodname", "item_group": "category",
			"stock_uom": "unit", "selling_rate": "saleprice", "currency": "currency",
		}.items())
		preview = migration.preview(job.name, json.dumps(mapping))
		assert preview["rows"] == 1 and not preview["errors"]
		assert preview["price_currency"] == currency
		result = migration.import_masters(job.name)
		assert result["counts"]["imported"] == 1
		assert frappe.db.get_value("Item", code, "item_name") == "قهوة"
		assert frappe.db.get_value("Item Price", {"item_code": code,
			"price_list": price_list, "selling": 1}, "price_list_rate") == 12.5
		retry = migration.import_masters(job.name)
		assert retry["counts"]["already_imported"] == 1
		return json.dumps({"source": "BIM POS", "preview_rows": preview["rows"],
			"imported": result["counts"]["imported"], "retry_imported": 0})
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
	assert workspace.label == "S&S (Seat & Serve)"
	parents = set(frappe.get_all("DocType", filters={"module": "Table Remote Till",
		"istable": 0}, pluck="name"))
	children = set(frappe.get_all("DocType", filters={"module": "Table Remote Till",
		"istable": 1}, pluck="name"))
	linked = {row.link_to for row in workspace.links if row.type == "Link" and row.link_type == "DocType"}
	assert parents == linked, {"missing": sorted(parents - linked), "extra": sorted(linked - parents)}
	assert all(row.label == row.link_to.removeprefix("TRT ") for row in workspace.links
		if row.type == "Link" and row.link_type == "DocType")
	embedded = {field.options for parent in parents for field in frappe.get_meta(parent).fields
		if field.fieldtype == "Table"}
	assert children <= embedded, sorted(children - embedded)
	assert any(row.type == "URL" and row.url == "/onboarding" for row in workspace.shortcuts)
	assert any(row.type == "URL" and row.url == "/reservations" for row in workspace.shortcuts)
	return json.dumps({"parent_doctypes": len(parents), "child_tables": len(children),
		"workspace": workspace.name})


def onboarding_retail_run():
	"""A retail-only site gets a saleable demo catalog without a floor plan."""
	frappe.set_user("Administrator")
	try:
		choices = onboarding.options()
		setup_name = frappe.db.get_value("TRT Business Setup", {"company": choices["company"]}, "name")
		if setup_name:
			# Exercise the retail path even on a development company already
			# configured for restaurants; the transaction is rolled back below.
			frappe.db.set_value("TRT Business Setup", setup_name, "business_type", "Retail")
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
