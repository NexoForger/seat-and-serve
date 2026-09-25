"""Install only app-owned defaults; merchant finance settings stay tenant controlled."""

import frappe


ROLES = ("TRT Manager", "TRT Cashier", "TRT Kitchen")


def ensure_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def before_install():
	ensure_roles()


def after_install():
	ensure_roles()


def after_migrate():
	ensure_roles()
