"""Table reservations shared by the public portal and waiter register."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import getdate, get_datetime, now_datetime


ACTIVE_STATUSES = ("Confirmed", "Seated")
OPEN_ORDER_STATUSES = ("Draft", "Sent", "Preparing", "Ready", "Served")


def _settings(outlet):
	settings = frappe.get_cached_doc("TRT Outlet", outlet)
	if not settings.enabled or not settings.enable_tables or not frappe.db.exists(
		"TRT Table", {"outlet": outlet, "enabled": 1}
	):
		frappe.throw("Reservations are unavailable for this outlet")
	return settings


def _minutes(value, default, low, high):
	result = int(value or default)
	if not low <= result <= high:
		frappe.throw("Invalid reservation schedule configuration")
	return result


def _schedule(settings, day):
	date = getdate(day)
	open_time = str(settings.reservation_open_time or "09:00:00")
	close_time = str(settings.reservation_close_time or "23:00:00")
	opening = get_datetime(f"{date} {open_time}")
	closing = get_datetime(f"{date} {close_time}")
	if closing <= opening:
		frappe.throw("Reservation closing time must be after opening time")
	interval = _minutes(settings.reservation_slot_minutes, 30, 15, 120)
	duration = _minutes(settings.reservation_duration_minutes, 90, 30, 240)
	advance = _minutes(settings.reservation_advance_days, 30, 1, 365)
	return opening, closing, interval, duration, advance


def _slot_times(settings, day):
	opening, closing, interval, duration, advance = _schedule(settings, day)
	if getdate(day) < getdate(now_datetime()) or getdate(day) > getdate(now_datetime()) + timedelta(days=advance):
		frappe.throw("Reservation date is outside the booking window")
	result = []
	start = opening
	while start + timedelta(minutes=duration) <= closing:
		if start >= now_datetime() + timedelta(minutes=15):
			result.append(start)
		start += timedelta(minutes=interval)
	return result, duration


def _tables(outlet, party_size, requested_table=None):
	try:
		party_size = int(party_size)
	except (TypeError, ValueError):
		frappe.throw("Enter a valid guest count")
	if not 1 <= party_size <= 30:
		frappe.throw("Reservations need 1 to 30 guests")
	rows = frappe.get_all("TRT Table", filters={"outlet": outlet, "enabled": 1,
		"seats": [">=", party_size]}, fields=["name", "title", "seats", "area"],
		order_by="seats asc, title asc")
	if requested_table:
		rows = [row for row in rows if row.name == requested_table]
	if not rows:
		frappe.throw("No table fits this party size")
	return rows


def _is_free(table, starts_at, ends_at, exclude=None, ignore_order=None):
	conflict = frappe.db.sql("""SELECT name FROM `tabTRT Reservation`
		WHERE `table`=%s AND status IN ('Confirmed', 'Seated')
		AND starts_at < %s AND ends_at > %s AND name != %s LIMIT 1""",
		(table, ends_at, starts_at, exclude or ""))
	if conflict:
		return False
	# An open table order blocks near-term bookings. Future bookings can use the
	# table after the configured sitting duration; staff still see live occupancy.
	if starts_at <= now_datetime() + (ends_at - starts_at) and frappe.db.exists(
		"TRT Order", {"table": table, "status": ["in", OPEN_ORDER_STATUSES],
			**({"name": ["!=", ignore_order]} if ignore_order else {})}
	):
		return False
	return True


def validate_reservation(doc):
	settings = _settings(doc.outlet)
	doc.guest_name = (doc.guest_name or "").strip()
	doc.phone = (doc.phone or "").strip()
	doc.email = (doc.email or "").strip().lower()
	doc.special_requests = (doc.special_requests or "").strip()
	if not 2 <= len(doc.guest_name) <= 100:
		frappe.throw("Guest name must be 2–100 characters")
	if not doc.phone and not doc.email:
		frappe.throw("Add a phone number or email address")
	if doc.phone and (len(doc.phone) > 25 or not re.fullmatch(r"[+0-9() .-]{6,25}", doc.phone)):
		frappe.throw("Enter a valid phone number")
	if doc.email and (len(doc.email) > 140 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", doc.email)):
		frappe.throw("Enter a valid email address")
	if len(doc.special_requests) > 500:
		frappe.throw("Special requests are too long")
	_tables(doc.outlet, doc.party_size, doc.table)
	start = get_datetime(doc.starts_at)
	end = get_datetime(doc.ends_at)
	opening, closing, _, _, _ = _schedule(settings, start.date())
	if start < opening or end > closing or end <= start or end - start > timedelta(hours=4):
		frappe.throw("Reservation is outside the outlet's booking hours")
	if (doc.is_new() or doc.has_value_changed("starts_at")) and start not in _slot_times(settings, start.date())[0]:
		frappe.throw("Choose an available reservation time")
	if doc.status in ACTIVE_STATUSES:
		frappe.db.sql("SELECT name FROM `tabTRT Table` WHERE name=%s FOR UPDATE", doc.table)
		if not _is_free(doc.table, start, end, doc.name, doc.order):
			frappe.throw("This table is already booked for that time")
	if doc.order:
		order = frappe.db.get_value("TRT Order", doc.order, ["outlet", "table", "channel"], as_dict=True)
		if not order or (order.outlet, order.table, order.channel) != (doc.outlet, doc.table, "Table"):
			frappe.throw("Seated order does not belong to this reservation")


def _booking_payload(payload):
	if isinstance(payload, str):
		payload = frappe.parse_json(payload)
	if not isinstance(payload, dict):
		frappe.throw("Reservation details are required")
	return {key: payload.get(key) for key in
		("outlet", "date", "time", "party_size", "guest_name", "phone", "email", "special_requests", "table")}


def _create(payload, request_id, source):
	data = _booking_payload(payload)
	if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{12,80}", request_id):
		frappe.throw("A booking request ID is required")
	request_hash = hashlib.sha256(json.dumps({**data, "source": source},
		sort_keys=True, default=str).encode()).hexdigest()
	prior = frappe.db.get_value("TRT Reservation", {"request_id": request_id},
		["name", "request_hash"], as_dict=True)
	if prior:
		if prior.request_hash != request_hash:
			frappe.throw("Booking request ID was used for different details")
		return _confirmation(frappe.get_doc("TRT Reservation", prior.name))
	settings = _settings(data["outlet"])
	try:
		start = get_datetime(f'{getdate(data["date"])} {data["time"]}')
	except (ValueError, TypeError):
		frappe.throw("Choose a valid date and time")
	slots, duration = _slot_times(settings, start.date())
	if start not in slots:
		frappe.throw("Choose an available reservation time")
	end = start + timedelta(minutes=duration)
	rows = _tables(settings.name, data["party_size"], data["table"] if source == "Register" else None)
	for table in rows:
		frappe.db.sql("SELECT name FROM `tabTRT Table` WHERE name=%s FOR UPDATE", table.name)
		prior = frappe.db.get_value("TRT Reservation", {"request_id": request_id},
			["name", "request_hash"], as_dict=True)
		if prior:
			if prior.request_hash != request_hash:
				frappe.throw("Booking request ID was used for different details")
			return _confirmation(frappe.get_doc("TRT Reservation", prior.name))
		if not _is_free(table.name, start, end):
			continue
		reservation = frappe.get_doc({"doctype": "TRT Reservation", "outlet": settings.name,
			"table": table.name, "party_size": int(data["party_size"]),
			"starts_at": start, "ends_at": end, "guest_name": data["guest_name"],
			"phone": data["phone"], "email": data["email"],
			"special_requests": data["special_requests"], "source": source,
			"status": "Confirmed", "request_id": request_id,
			"request_hash": request_hash}).insert(ignore_permissions=True)
		return _confirmation(reservation)
	frappe.throw("That time just filled up. Choose another available time")


def _confirmation(doc):
	return {"reservation_number": doc.reservation_number, "outlet": doc.outlet,
		"outlet_title": frappe.db.get_value("TRT Outlet", doc.outlet, "title"),
		"date": str(get_datetime(doc.starts_at).date()),
		"time": get_datetime(doc.starts_at).strftime("%H:%M"),
		"party_size": doc.party_size, "status": doc.status}


@frappe.whitelist(allow_guest=True)
def reservation_outlets():
	"""Only public names of enabled locations that actually have tables."""
	return frappe.db.sql("""SELECT o.name, o.title, o.reservation_advance_days FROM `tabTRT Outlet` o
		WHERE o.enabled=1 AND o.enable_tables=1 AND EXISTS
		(SELECT 1 FROM `tabTRT Table` t WHERE t.outlet=o.name AND t.enabled=1)
		ORDER BY o.title""", as_dict=True)


@frappe.whitelist(allow_guest=True)
def reservation_availability(outlet, date, party_size, table=None):
	settings = _settings(outlet)
	if table:
		from table_remote_till.api import _staff_outlet

		_staff_outlet(outlet)
	tables = _tables(outlet, party_size, table)
	slots, duration = _slot_times(settings, date)
	return {"outlet": outlet, "date": str(getdate(date)), "party_size": int(party_size),
		"duration_minutes": duration,
		"slots": [start.strftime("%H:%M") for start in slots
			if any(_is_free(table.name, start, start + timedelta(minutes=duration)) for table in tables)]}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=3600, methods=["POST"])
def book_reservation(payload, request_id):
	if frappe.request and frappe.request.method != "POST":
		frappe.throw("POST required", frappe.PermissionError)
	return _create(payload, request_id, "Portal")


@frappe.whitelist(methods=["POST"])
def register_book_reservation(payload, request_id):
	from table_remote_till.api import _staff_outlet

	data = _booking_payload(payload)
	_staff_outlet(data["outlet"])
	return _create(data, request_id, "Register")


@frappe.whitelist()
def register_reservations(outlet, date):
	from table_remote_till.api import _staff_outlet

	_staff_outlet(outlet)
	_settings(outlet)
	day = getdate(date)
	if day < getdate(now_datetime()) - timedelta(days=7) or day > getdate(now_datetime()) + timedelta(days=365):
		frappe.throw("Date is outside the reservation list range")
	rows = frappe.db.sql("""SELECT r.name, r.reservation_number, r.guest_name, r.phone,
		r.email, r.party_size, r.starts_at, r.ends_at, r.status, r.source,
		r.special_requests, r.`table`, r.`order`, t.title AS table_title
		FROM `tabTRT Reservation` r JOIN `tabTRT Table` t ON t.name=r.`table`
		WHERE r.outlet=%s AND r.starts_at >= %s AND r.starts_at < %s
		ORDER BY r.starts_at, r.creation""",
		(outlet, datetime.combine(day, datetime.min.time()),
			datetime.combine(day + timedelta(days=1), datetime.min.time())), as_dict=True)
	for row in rows:
		row["time"] = get_datetime(row.starts_at).strftime("%H:%M")
		row["order_number"] = frappe.db.get_value("TRT Order", row.order, "order_number") if row.order else None
	return rows


@frappe.whitelist(methods=["POST"])
def update_reservation(reservation_name, action):
	from table_remote_till.api import _staff_outlet

	reservation = frappe.get_doc("TRT Reservation", reservation_name)
	_staff_outlet(reservation.outlet)
	if action not in ("Cancelled", "No Show"):
		frappe.throw("Invalid reservation action")
	frappe.db.sql("SELECT name FROM `tabTRT Table` WHERE name=%s FOR UPDATE", reservation.table)
	frappe.db.sql("SELECT name FROM `tabTRT Reservation` WHERE name=%s FOR UPDATE", reservation_name)
	reservation.reload()
	if reservation.status == action:
		return _confirmation(reservation)
	if reservation.status != "Confirmed":
		frappe.throw("Only confirmed reservations can be cancelled or marked no-show")
	reservation.status = action
	reservation.save(ignore_permissions=True)
	return _confirmation(reservation)


@frappe.whitelist(methods=["POST"])
def seat_reservation(reservation_name, request_id):
	from table_remote_till import api

	reservation = frappe.get_doc("TRT Reservation", reservation_name)
	api._staff_outlet(reservation.outlet)
	frappe.db.sql("SELECT name FROM `tabTRT Table` WHERE name=%s FOR UPDATE", reservation.table)
	frappe.db.sql("SELECT name FROM `tabTRT Reservation` WHERE name=%s FOR UPDATE", reservation_name)
	reservation.reload()
	if reservation.status == "Seated" and reservation.order:
		return api._snapshot(frappe.get_doc("TRT Order", reservation.order))
	if reservation.status != "Confirmed":
		frappe.throw("Only confirmed reservations can be seated")
	if get_datetime(reservation.starts_at) > now_datetime() + timedelta(hours=2):
		frappe.throw("This reservation is more than two hours away")
	if get_datetime(reservation.ends_at) < now_datetime():
		frappe.throw("This reservation has expired")
	return api.order_command({"action": "create", "outlet": reservation.outlet,
		"channel": "Table", "table": reservation.table,
		"guest_count": reservation.party_size, "reservation": reservation.name},
		request_id, expected_revision=0)


def block_walk_in(table, reservation_name=None):
	"""Require a booking's check-in flow when it currently owns a table."""
	now = now_datetime()
	rows = frappe.db.sql("""SELECT name, starts_at, ends_at, status, `order`
		FROM `tabTRT Reservation` WHERE `table`=%s
		AND status IN ('Confirmed', 'Seated') AND starts_at <= %s AND ends_at > %s
		ORDER BY starts_at LIMIT 1""", (table, now + timedelta(minutes=45), now), as_dict=True)
	if reservation_name:
		reservation = frappe.db.get_value("TRT Reservation", reservation_name,
			["name", "table", "status", "order", "starts_at", "ends_at"], as_dict=True)
		if (not reservation or reservation.table != table or reservation.status != "Confirmed"
			or reservation.order or get_datetime(reservation.starts_at) > now + timedelta(hours=2)
			or get_datetime(reservation.ends_at) < now):
			frappe.throw("Reservation cannot be seated at this table")
		return reservation
	if rows:
		frappe.throw("Table is reserved now. Seat the reservation from the register")
	return None
