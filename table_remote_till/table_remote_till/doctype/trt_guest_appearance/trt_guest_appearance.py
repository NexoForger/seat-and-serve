import re

import frappe
from frappe.model.document import Document


COLORS = (
	"primary_color", "accent_color", "page_color", "surface_color", "text_color", "muted_color",
)
FONTS = {"Manrope", "DM Sans", "Lato", "Nunito"}


class TRTGuestAppearance(Document):
	def validate(self):
		for field in COLORS:
			value = self.get(field)
			if value and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
				frappe.throw(f"{field.replace('_', ' ').title()} must be a six-digit hex color")
		for field in ("heading_font", "body_font"):
			if self.get(field) and self.get(field) not in FONTS:
				frappe.throw(f"{field.replace('_', ' ').title()} is not an approved font")
