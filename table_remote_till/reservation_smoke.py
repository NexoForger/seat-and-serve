"""Rolled-back integration check for public and staff table reservations."""

import json
import uuid

import frappe
from frappe.utils import now_datetime

from table_remote_till import api, reservations


def run():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name")
	try:
		outlet = frappe.get_doc({"doctype": "TRT Outlet", "title": "Reservation Smoke",
			"company": company, "enabled": 1, "enable_tables": 1,
			"reservation_open_time": "00:00:00", "reservation_close_time": "23:59:00",
			"reservation_slot_minutes": 30, "reservation_duration_minutes": 90,
			"reservation_advance_days": 30, "base_currency": "USD"}).insert(ignore_permissions=True)
		area = frappe.get_doc({"doctype": "TRT Service Area", "title": "Reservation Smoke",
			"outlet": outlet.name, "enabled": 1}).insert(ignore_permissions=True)
		small = frappe.get_doc({"doctype": "TRT Table", "title": "R1", "outlet": outlet.name,
			"area": area.name, "seats": 2, "enabled": 1}).insert(ignore_permissions=True)
		large = frappe.get_doc({"doctype": "TRT Table", "title": "R2", "outlet": outlet.name,
			"area": area.name, "seats": 4, "enabled": 1}).insert(ignore_permissions=True)
		day = str(now_datetime().date())
		frappe.set_user("Guest")
		assert any(row.name == outlet.name for row in reservations.reservation_outlets())
		available = reservations.reservation_availability(outlet.name, day, 2)
		assert available["slots"]
		time = available["slots"][0]
		payload = {"outlet": outlet.name, "date": day, "time": time, "party_size": 2,
			"guest_name": "Booking One", "phone": "+961 71123456"}
		request_id = str(uuid.uuid4())
		first = reservations.book_reservation(payload, request_id)
		assert first["reservation_number"].startswith("RSV-") and "table" not in first
		assert reservations.book_reservation(payload, request_id) == first
		first_doc = frappe.get_doc("TRT Reservation", {"request_id": request_id})
		assert first_doc.table == small.name and first_doc.source == "Portal"
		second_payload = {**payload, "guest_name": "Booking Two", "phone": "+961 71123457"}
		second = reservations.book_reservation(second_payload, str(uuid.uuid4()))
		second_doc = frappe.get_doc("TRT Reservation", {"reservation_number": second["reservation_number"]})
		assert second_doc.table == large.name
		assert time not in reservations.reservation_availability(outlet.name, day, 2)["slots"]
		try:
			reservations.book_reservation({**payload, "guest_name": "Booking Three"}, str(uuid.uuid4()))
		except frappe.ValidationError:
			pass
		else:
			raise AssertionError("Overbooked a full time slot")
		try:
			reservations.register_reservations(outlet.name, day)
		except frappe.PermissionError:
			pass
		else:
			raise AssertionError("Guest accessed staff reservation list")
		frappe.set_user("Administrator")
		assert len(reservations.register_reservations(outlet.name, day)) == 2
		assert api.register_tables(outlet.name)[0]["next_reservation"]["reservation_number"] == first["reservation_number"]
		seated = reservations.seat_reservation(first_doc.name, str(uuid.uuid4()))
		assert seated["reservation"] == first_doc.name and seated["table"] == small.name
		assert frappe.db.get_value("TRT Reservation", first_doc.name, "status") == "Seated"
		assert reservations.seat_reservation(first_doc.name, str(uuid.uuid4()))["name"] == seated["name"]
		try:
			api.order_command({"action": "create", "outlet": outlet.name,
				"channel": "Table", "table": small.name}, str(uuid.uuid4()), expected_revision=0)
		except frappe.ValidationError:
			pass
		else:
			raise AssertionError("Walk-in took an occupied reserved table")
		assert reservations.update_reservation(second_doc.name, "Cancelled")["status"] == "Cancelled"
		assert time in reservations.reservation_availability(outlet.name, day, 2)["slots"]
		staff_slot = reservations.reservation_availability(outlet.name, day, 3)["slots"][-1]
		staff = reservations.register_book_reservation({"outlet": outlet.name,
			"date": day, "time": staff_slot, "party_size": 3, "table": large.name,
			"guest_name": "Staff Guest", "email": "staff@example.invalid"}, str(uuid.uuid4()))
		assert staff["reservation_number"].startswith("RSV-")
		assert frappe.db.get_value("TRT Reservation", {"reservation_number": staff["reservation_number"]}, "source") == "Register"
		return json.dumps({"portal_booking": first["reservation_number"],
			"staff_booking": staff["reservation_number"], "seated_order": seated["order_number"],
			"double_booking_blocked": True})
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
