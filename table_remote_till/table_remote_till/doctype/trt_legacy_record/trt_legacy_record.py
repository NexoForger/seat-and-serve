import frappe
from frappe.model.document import Document


class TRTLegacyRecord(Document):
	def before_save(self):
		previous = self.get_doc_before_save()
		if previous and previous.status == "Imported":
			frappe.throw("Imported historical records are immutable", frappe.PermissionError)

	def on_trash(self):
		if self.status == "Imported":
			frappe.throw("Imported historical records cannot be deleted", frappe.PermissionError)
