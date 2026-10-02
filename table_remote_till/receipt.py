"""Print submitted POS Invoices on an outlet's Ethernet receipt printer."""

from __future__ import annotations

import ipaddress
import json
import re
import socket

import frappe
from PIL import Image, ImageDraw, ImageFont, features
from frappe.utils import flt, strip_html


WIDTH = 576  # 80 mm paper at 203 dpi
MARGIN = 24
FONT_PATHS = (
	"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
	"/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)


def configured_printer(outlet: str, register: str | None = None):
	"""Prefer a register printer, then an outlet-wide printer."""
	devices = frappe.get_all("TRT Device", filters={"outlet": outlet,
		"kind": "Receipt Printer", "enabled": 1},
		fields=["name", "title", "register", "driver", "address", "settings_json"], order_by="modified desc")
	return next((row for row in devices if register and row.register == register), None) or next(
		(row for row in devices if not row.register), None)


def _printer_target(device):
	if (device.driver or "escpos_tcp").lower() != "escpos_tcp":
		frappe.throw("Receipt printer driver must be escpos_tcp")
	address = (device.address or "").strip()
	host, separator, port_text = address.partition(":")
	try:
		ipaddress.IPv4Address(host)
		port = int(port_text) if separator else 9100
		if not 1 <= port <= 65535:
			raise ValueError("port")
	except ValueError:
		frappe.throw("Receipt printer address must be an IPv4 address, optionally followed by :port")
	return host, port


def _font(size):
	for path in FONT_PATHS:
		try:
			return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC)
		except OSError:
			continue
	frappe.throw("Install DejaVu Sans in the Frappe container to print receipts")


def _clean(value):
	return re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "")).strip()


def _money(value, currency):
	precision = 0 if currency == "LBP" else 2
	return f"{flt(value):,.{precision}f} {currency}"


def _receipt_rows(invoice, order, outlet, company, copy=False, test=False):
	currency = invoice.currency
	rows = [("center", _clean(company.company_name or company.name), "title")]
	if test:
		rows.append(("center", "TEST PRINT - NO SALE", "body"))
	if copy:
		rows.append(("center", "REPRINT", "body"))
	if getattr(company, "receipt_header", None):
		rows.append(("center", _clean(strip_html(company.receipt_header)), "small"))
	if company.tax_id:
		rows.append(("center", f"Tax ID: {_clean(company.tax_id)}", "small"))
	rows += [("center", _clean(outlet.title), "body"), ("rule", "", ""),
		("pair", ("RECEIPT", invoice.name), "body"),
		("pair", ("Date", f"{invoice.posting_date} {invoice.posting_time or ''}".strip()), "small"),
		("pair", ("Order", order.order_number), "small")]
	if order.table:
		rows.append(("pair", ("Table", frappe.db.get_value("TRT Table", order.table, "title") or order.table), "small"))
	if invoice.customer_name:
		rows.append(("pair", ("Customer", invoice.customer_name), "small"))
	remarks = invoice.remarks or ""
	cashier = remarks.split("cashier ", 1)[-1].split(";", 1)[0] if "cashier " in remarks else invoice.owner
	rows.extend([("pair", ("Cashier", cashier), "small"), ("rule", "", "")])
	for item in invoice.items:
		rows.append(("text", _clean(item.item_name or item.item_code), "body"))
		rows.append(("pair", (f"{flt(item.qty):g} x {_money(item.rate, currency)}", _money(item.amount, currency)), "small"))
	rows.append(("rule", "", ""))
	rows.append(("pair", ("Items", _money(invoice.total, currency)), "body"))
	if flt(invoice.discount_amount):
		rows.append(("pair", ("Discount", "-" + _money(invoice.discount_amount, currency)), "body"))
	if flt(invoice.total_taxes_and_charges):
		included = any(flt(tax.included_in_print_rate) for tax in invoice.taxes)
		rows.append(("pair", ("Tax included" if included else "Tax",
			_money(invoice.total_taxes_and_charges, currency)), "small"))
	if flt(invoice.rounded_total) and abs(flt(invoice.rounded_total) - flt(invoice.grand_total)) > 0.001:
		rows.append(("pair", ("Rounding", _money(flt(invoice.rounded_total) - flt(invoice.grand_total), currency)), "small"))
	rows.extend([("rule", "", ""),
		("pair", ("TOTAL", _money(invoice.rounded_total or invoice.grand_total, currency)), "title")])
	for payment in invoice.payments:
		if flt(payment.amount):
			rows.append(("pair", (_clean(payment.mode_of_payment), _money(payment.amount, currency)), "body"))
	rows += [("rule", "", ""), ("center", "Thank you for your visit", "body")]
	if getattr(company, "receipt_footer", None):
		rows.append(("center", _clean(strip_html(company.receipt_footer)), "small"))
	return rows


def _wrap(draw, text, font, max_width):
	words = text.split()
	if not words:
		return [""]
	lines = []
	line = ""
	for word in words:
		candidate = f"{line} {word}".strip()
		if line and draw.textlength(candidate, font=font) > max_width:
			lines.append(line)
			line = word
		else:
			line = candidate
	if line:
		lines.append(line)
	return lines


def render_receipt(invoice, order, outlet, company, copy=False, test=False):
	"""Render text as a bitmap so Arabic and mixed-script item names survive ESC/POS."""
	fonts = {"title": _font(28), "body": _font(23), "small": _font(19)}
	measure = ImageDraw.Draw(Image.new("1", (WIDTH, 1), 1))
	operations = []
	y = 16
	for kind, value, style in _receipt_rows(invoice, order, outlet, company, copy, test):
		font = fonts.get(style, fonts["body"])
		line_height = int(font.size * 1.5)
		if kind == "rule":
			operations.append((kind, y, None, None, font))
			y += 17
		elif kind == "pair":
			left, right = map(_clean, value)
			right_width = measure.textlength(right, font=font)
			left_width = WIDTH - 2 * MARGIN - right_width - 12
			start = y
			for part in _wrap(measure, left, font, max(120, left_width)):
				operations.append(("left", y, part, None, font))
				y += line_height
			operations.append(("right", start, right, None, font))
		else:
			for part in _wrap(measure, _clean(value), font, WIDTH - 2 * MARGIN):
				operations.append((kind, y, part, None, font))
				y += line_height
		y += 4
	image = Image.new("1", (WIDTH, y + 40), 1)
	draw = ImageDraw.Draw(image)
	for kind, top, value, _, font in operations:
		if kind == "rule":
			draw.line((MARGIN, top + 4, WIDTH - MARGIN, top + 4), fill=0, width=2)
			continue
		width = draw.textlength(value, font=font)
		x = (WIDTH - width) / 2 if kind == "center" else WIDTH - MARGIN - width if kind == "right" else MARGIN
		draw.text((x, top), value, font=font, fill=0,
			direction="rtl" if re.search(r"[\u0600-\u06ff]", value) and features.check("raqm") else None)
	return image


def escpos_bytes(image, cut=True):
	"""ESC/POS raster blocks, bounded to avoid large single printer writes."""
	output = bytearray(b"\x1b@")
	for top in range(0, image.height, 256):
		strip = image.crop((0, top, image.width, min(top + 256, image.height)))
		data = strip.tobytes()
		bytes_per_row = (strip.width + 7) // 8
		# Pillow mode 1 uses 1 for white; ESC/POS uses 1 for a black dot.
		data = bytes(byte ^ 0xFF for byte in data)
		output += bytes((0x1D, 0x76, 0x30, 0, bytes_per_row & 255,
			bytes_per_row >> 8, strip.height & 255, strip.height >> 8))
		output += data
	output += b"\n\n\n"
	if cut:
		output += b"\x1dV\x00"
	return bytes(output)


def _send(device, image):
	host, port = _printer_target(device)
	settings = json.loads(device.settings_json or "{}")
	payload = escpos_bytes(image, cut=settings.get("auto_cut", True))
	with socket.create_connection((host, port), timeout=5) as connection:
		connection.settimeout(10)
		connection.sendall(payload)


def print_invoice(invoice_name, order_name, device, copy=False):
	order = frappe.get_doc("TRT Order", order_name)
	invoice = frappe.get_doc("POS Invoice", invoice_name)
	if invoice.docstatus != 1 or invoice.is_return or order.pos_invoice != invoice.name:
		frappe.throw("Only a submitted sale receipt can be printed")
	outlet = frappe.get_doc("TRT Outlet", order.outlet)
	company = frappe.get_doc("Company", outlet.company)
	try:
		_send(device, render_receipt(invoice, order, outlet, company, copy))
	except OSError:
		frappe.log_error("Receipt printer connection failed", "TRT receipt print")
		frappe.throw("Receipt printer is unreachable. Payment is saved; check the printer and use Reprint receipt.")
	return {"invoice": invoice.name, "printer": device.title or device.name}


def test_receipt(outlet_name, register):
	"""Print a marked setup slip with no order or accounting transaction."""
	device = configured_printer(outlet_name, register)
	if not device:
		frappe.throw("No enabled receipt printer is assigned to this register")
	outlet = frappe.get_doc("TRT Outlet", outlet_name)
	company = frappe.get_doc("Company", outlet.company)
	invoice = frappe._dict({"name": "TEST-NO-SALE", "currency": outlet.base_currency or "USD",
		"posting_date": frappe.utils.today(), "posting_time": frappe.utils.nowtime(),
		"owner": "Test", "remarks": "", "customer_name": None,
		"items": [frappe._dict({"item_name": "Printer setup check", "qty": 1,
			"rate": 0, "amount": 0})], "total": 0, "discount_amount": 0,
		"total_taxes_and_charges": 0, "taxes": [], "rounded_total": 0,
		"grand_total": 0, "payments": []})
	order = frappe._dict({"order_number": "TEST", "table": None})
	_send(device, render_receipt(invoice, order, outlet, company, test=True))
	return {"printer": device.title or device.name, "test": True}
