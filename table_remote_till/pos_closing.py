"""Keep a durable closing entry before ERPNext's consolidation commits/rollbacks."""

import frappe
from uuid import uuid4
from frappe.utils import strip_html


class DeferredTRTClosing:
	def on_submit(self):
		if (self.get("invoice_type") != "POS Invoice" or not frappe.db.exists("TRT Outlet", {
			"pos_profile": self.pos_profile, "company": self.company})):
			return super().on_submit()
		queue_closing(self)


def queue_closing(closing):
	closing.set_status(update=True, status="Queued")
	closing.db_set("error_message", "")
	frappe.enqueue("table_remote_till.pos_closing.process_closing", closing_name=closing.name,
		queue="long", timeout=10000, enqueue_after_commit=True,
		job_id=f"trt-pos-closing::{closing.name}::{uuid4().hex}")


def process_closing(closing_name):
	from erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log import (
		create_merge_logs, get_invoice_customer_map,
	)
	from table_remote_till.api import _as_admin

	frappe.db.sql("SELECT name FROM `tabPOS Closing Entry` WHERE name=%s FOR UPDATE", closing_name)
	closing = frappe.get_doc("POS Closing Entry", closing_name)
	if closing.docstatus != 1 or closing.status != "Queued":
		return
	try:
		with _as_admin():
			# Use ERPNext's accounting/consolidation unmodified, in a worker whose
			# parent closing already exists. Do not invoke native on_submit here:
			# it would queue a second merge for shifts with >=10 invoices.
			create_merge_logs(get_invoice_customer_map(closing.pos_invoices), closing)
			closing.update_sales_invoices_closing_entry()
		frappe.publish_realtime(f"poe_{closing.pos_opening_entry}",
			message={"operation": "Closed", "doc": closing},
			docname=f"POS Opening Entry/{closing.pos_opening_entry}", after_commit=True)
	except Exception as error:
		traceback = frappe.get_traceback()
		frappe.db.rollback()
		if frappe.db.get_value("POS Closing Entry", closing_name, "status") == "Submitted":
			# A notification can fail after ERPNext has committed the accounting.
			# Do not relabel an already successful close as Failed or replay it.
			frappe.log_error(title="TRT closing notification failed", message=traceback,
				reference_doctype="POS Closing Entry", reference_name=closing_name)
			return
		# ERPNext may already have saved Failed in its error handler. Save the
		# actual exception as well, rather than the last stock-cost warning.
		frappe.db.set_value("POS Closing Entry", closing_name, {"status": "Failed",
			"error_message": strip_html(str(error))[:1000]})
		frappe.db.commit()
		frappe.log_error(title="TRT shift consolidation failed", message=traceback,
			reference_doctype="POS Closing Entry", reference_name=closing_name)
		raise
