"""Read-only ERP readiness checks for the in-site onboarding guide."""

import frappe


def _manager():
	if not set(frappe.get_roles()).intersection({"System Manager", "TRT Manager"}):
		frappe.throw("Manager role required", frappe.PermissionError)


@frappe.whitelist()
def status(company=None):
	_manager()
	companies = frappe.get_all("Company", pluck="name")
	company = company or (companies[0] if companies else None)
	if company and company not in companies:
		frappe.throw("Unknown company")
	setup_name = frappe.db.get_value("TRT Business Setup", {"company": company}, "name") if company else None
	setup = frappe.get_doc("TRT Business Setup", setup_name) if setup_name else None

	def check(label, doctype, filters=None, route=None):
		return {"label": label, "ready": bool(frappe.db.exists(doctype, filters or {})),
			"route": route or f"/app/{frappe.scrub(doctype).replace('_', '-')}"}

	steps = [
		{"label": "Business settings and owner approvals", "ready": bool(setup),
			"route": "/app/trt-business-setup"},
		check("Branch", "Branch", {"company": company} if company else {"name": "__missing__"}),
		check("Outlet and channels", "TRT Outlet", {"company": company, "enabled": 1} if company else {"name": "__missing__"}),
		check("Warehouse", "Warehouse", {"company": company, "is_group": 0} if company else {"name": "__missing__"}),
		check("Chart of accounts", "Account", {"company": company, "is_group": 0} if company else {"name": "__missing__"}),
		check("Selling price list", "Price List", {"selling": 1}),
		check("POS Profile", "POS Profile", {"company": company} if company else {"name": "__missing__"}),
		check("Staff outlet assignments", "TRT Staff Assignment"),
		check("Approved USD/LBP rate", "TRT FX Rate", {"enabled": 1}),
		{"label": "POS Invoice mode", "ready": frappe.db.get_single_value("POS Settings", "invoice_type") == "POS Invoice",
			"route": "/app/pos-settings"},
		check("Payment mode", "Mode of Payment"),
		check("Sales tax template", "Sales Taxes and Charges Template", {"company": company} if company else {"name": "__missing__"}),
		check("Items and stock", "Item", {"disabled": 0}),
		check("Suppliers and purchasing", "Supplier"),
		check("Customers and CRM", "Customer"),
		check("Employee records", "Employee", {"company": company} if company else {"name": "__missing__"}),
		check("Salary structure", "Salary Structure", {"company": company} if company else {"name": "__missing__"}),
		{"label": "Tax rules approved by business", "ready": bool(setup and setup.tax_approved_by and setup.tax_approved_on),
			"route": "/app/trt-business-setup"},
		{"label": "Payroll rules approved by business", "ready": bool(setup and setup.payroll_approved_by and setup.payroll_approved_on),
			"route": "/app/trt-business-setup"},
	]
	for currency in ("USD", "LBP"):
		steps.append(check(f"{currency} currency", "Currency", {"name": currency, "enabled": 1}))
	return {"company": company, "companies": companies, "steps": steps,
		"ready_count": sum(step["ready"] for step in steps), "total_count": len(steps)}
