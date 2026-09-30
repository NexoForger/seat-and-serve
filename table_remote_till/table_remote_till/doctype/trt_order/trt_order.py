from frappe.model.document import Document
from frappe.model.naming import make_autoname


class TRTOrder(Document):
	def before_insert(self):
		if not self.order_number:
			self.order_number = make_autoname("TRT-.#####")
