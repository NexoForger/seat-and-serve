import frappe
from frappe.model.document import Document


class TRTMenu(Document):
	def validate(self):
		if not self.items:
			return
		company = frappe.db.get_value("TRT Outlet", self.outlet, "company")
		for row in self.items:
			label = frappe.db.get_value("Item", row.item, "item_name") or row.item
			bom_names = frappe.get_all("BOM", filters={"item": row.item,
				"company": company, "docstatus": 1, "is_active": 1}, pluck="name")
			# Most menu items are sold without recipe-level stock depletion. Validate
			# an attached recipe when present, but do not make recipes mandatory.
			for bom_name in bom_names:
				materials = frappe.get_all("BOM Item", filters={"parent": bom_name},
					pluck="item_code")
				if not materials:
					frappe.throw(f"{label}'s BOM needs raw materials")
				for item_code in materials:
					flags = frappe.db.get_value("Item", item_code,
						["is_stock_item", "is_purchase_item", "is_sales_item",
							"include_item_in_manufacturing"], as_dict=True)
					if not flags or not (flags.is_stock_item and flags.is_purchase_item and
							flags.include_item_in_manufacturing and not flags.is_sales_item):
						frappe.throw(f"{item_code} in {label}'s BOM must be a purchasable stock raw material")
