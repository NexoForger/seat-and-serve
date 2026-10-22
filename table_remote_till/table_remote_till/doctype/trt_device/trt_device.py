from frappe.model.document import Document
import frappe

from table_remote_till.printing import PrintError, settings, target


class TRTDevice(Document):
	def validate(self):
		if self.kind == "Receipt Printer" and self.enabled:
			try:
				settings(self)
				target(self)
			except PrintError as error:
				frappe.throw(str(error))
