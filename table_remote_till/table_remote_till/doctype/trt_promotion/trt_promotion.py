import frappe
from frappe.model.document import Document
from frappe.utils import flt


class TRTPromotion(Document):
	def autoname(self):
		self.code = (self.code or "").strip().upper()
		self.name = self.code

	def before_validate(self):
		self.code = (self.code or "").strip().upper()

	def validate(self):
		if not self.code or len(self.code) > 32 or not all(char.isascii() and (char.isalnum() or char in "-_") for char in self.code):
			frappe.throw("Coupon code must use 1–32 letters, numbers, hyphens, or underscores")
		if self.code != self.name:
			frappe.throw("Coupon code cannot be changed; create a new promotion")
		if self.discount_type == "Percentage" and not 0 < flt(self.discount_value) <= 100:
			frappe.throw("Coupon percentage must be between 0 and 100")
		if self.discount_type == "Amount" and flt(self.discount_value) <= 0:
			frappe.throw("Coupon amount must be positive")
		if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
			frappe.throw("Coupon end date must be after its start date")
		if int(self.max_uses or 0) < 0:
			frappe.throw("Maximum uses cannot be negative")
