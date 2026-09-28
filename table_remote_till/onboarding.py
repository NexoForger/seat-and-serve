"""In-site ERP readiness checks and the managed outlet setup API."""

import frappe

from table_remote_till import onboarding_service


def _manager():
	if not set(frappe.get_roles()).intersection({"System Manager", "TRT Manager"}):
		frappe.throw("Manager role required", frappe.PermissionError)


@frappe.whitelist()
def options(company=None):
	"""Only the choices needed to build a valid POS setup for one company."""
	_manager()
	companies = frappe.get_all("Company", filters={"is_group": 0},
		fields=["name", "abbr", "country", "default_currency", "cost_center",
			"default_receivable_account"], order_by="name")
	if not companies:
		return {"companies": [], "company": None, "choices": {}}
	company = company or companies[0].name
	if company not in {row.name for row in companies}:
		frappe.throw("Unknown company")
	current = frappe.get_doc("Company", company)
	accounts = frappe.get_all("Account", filters={"company": company, "is_group": 0},
		fields=["name", "account_type"], order_by="name")
	write_off = next((row.name for row in accounts if "Stock Adjustment" in row.name),
		current.default_expense_account)
	return {"companies": companies, "company": company,
		"defaults": {"write_off_account": write_off, "cost_center": current.cost_center,
			"cash_mode": "Cash"},
		"choices": {
			"warehouses": frappe.get_all("Warehouse", filters={"company": company,
				"is_group": 0, "disabled": 0}, pluck="name", order_by="name"),
			"price_lists": frappe.get_all("Price List", filters={"currency": current.default_currency,
				"selling": 1, "enabled": 1}, pluck="name", order_by="name"),
			"customers": frappe.get_all("Customer", filters={"disabled": 0},
				pluck="name", order_by="name", limit=100),
			"profiles": frappe.get_all("POS Profile", filters={"company": company,
				"currency": current.default_currency, "disabled": 0},
				pluck="name", order_by="name"),
			"cash_modes": frappe.get_all("Mode of Payment", filters={"type": "Cash",
				"enabled": 1}, pluck="name", order_by="name"),
			"accounts": [row.name for row in accounts],
			"cost_centers": frappe.get_all("Cost Center", filters={"company": company,
				"is_group": 0}, pluck="name", order_by="name"),
			"tax_templates": frappe.get_all("Sales Taxes and Charges Template",
				filters={"company": company, "disabled": 0}, pluck="name", order_by="name"),
		}}


@frappe.whitelist()
def preview_setup(config):
	_manager()
	return onboarding_service.preview(config)


@frappe.whitelist(methods=["POST"])
def apply_setup(config, request_id):
	_manager()
	return onboarding_service.apply(config, request_id)


@frappe.whitelist()
def status(company=None):
	_manager()
	companies = frappe.get_all("Company", filters={"is_group": 0}, pluck="name")
	company = company or (companies[0] if companies else None)
	if company and company not in companies:
		frappe.throw("Unknown company")
	setup_name = frappe.db.get_value("TRT Business Setup", {"company": company}, "name") if company else None
	setup = frappe.get_doc("TRT Business Setup", setup_name) if setup_name else None

	def check(label, doctype, filters=None, route=None):
		return {"label": label, "ready": bool(frappe.db.exists(doctype, filters or {})),
			"route": route or f"/app/{frappe.scrub(doctype).replace('_', '-')}"}

	outlets = frappe.get_all("TRT Outlet", filters={"company": company}, pluck="name") if company else []
	steps = [
		{"label": "Business settings and owner approvals", "ready": bool(setup),
			"route": "/app/trt-business-setup"},
		{"label": "Branch", "ready": bool(outlets and frappe.db.get_value("TRT Outlet", outlets[0], "branch")),
			"route": "/app/branch"},
		check("Outlet and channels", "TRT Outlet", {"company": company, "enabled": 1} if company else {"name": "__missing__"}),
		check("Warehouse", "Warehouse", {"company": company, "is_group": 0} if company else {"name": "__missing__"}),
		check("Chart of accounts", "Account", {"company": company, "is_group": 0} if company else {"name": "__missing__"}),
		check("Selling price list", "Price List", {"selling": 1}),
		check("POS Profile", "POS Profile", {"company": company} if company else {"name": "__missing__"}),
		check("Staff outlet assignments", "TRT Staff Assignment",
			{"outlet": ["in", outlets]} if outlets else {"name": "__missing__"}),
		check("Approved USD/LBP rate", "TRT FX Rate",
			{"outlet": ["in", outlets], "enabled": 1} if outlets else {"name": "__missing__"}),
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
