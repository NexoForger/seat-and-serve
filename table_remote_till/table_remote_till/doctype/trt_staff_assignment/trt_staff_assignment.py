import frappe
from frappe.model.document import Document


class TRTStaffAssignment(Document):
	def validate(self):
		duplicate = frappe.db.get_value("TRT Staff Assignment",
			{"user": self.user, "outlet": self.outlet}, "name")
		if duplicate and duplicate != self.name:
			frappe.throw("User already has an assignment for this outlet")
		if not set(frappe.get_roles(self.user)).intersection(
			{"TRT Cashier", "TRT Kitchen", "TRT Manager", "System Manager"}
		):
			frappe.throw("Assigned user needs a S&S (Seat & Serve) role")
