import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class TRTReservation(Document):
	def before_insert(self):
		if not self.reservation_number:
			self.reservation_number = make_autoname("RSV-.#####")

	def validate(self):
		from table_remote_till.reservations import validate_reservation

		validate_reservation(self)
