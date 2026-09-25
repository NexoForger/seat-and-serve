import frappe
from frappe.utils import get_url


no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest" or not set(frappe.get_roles()).intersection({"System Manager", "TRT Manager"}):
		frappe.local.flags.redirect_location = "/login?redirect-to=/onboarding"
		raise frappe.Redirect
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.site_url = get_url()
