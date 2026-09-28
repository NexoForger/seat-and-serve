app_name = "table_remote_till"
app_title = "Table Remote Till"
app_publisher = "Table Remote Till"
app_description = "Multichannel POS and ERP operations"
app_email = "dev@example.invalid"
app_license = "mit"

# Apps
# ------------------

required_apps = ["frappe/erpnext", "frappe/hrms"]

add_to_apps_screen = [{
	"name": "table_remote_till",
	"logo": "/assets/table_remote_till/images/table-remote-till.svg",
	"title": "Table Remote Till",
	"route": "/desk/table-remote-till",
	"has_permission": "table_remote_till.install.has_app_permission",
}]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/table_remote_till/css/table_remote_till.css"
# app_include_js = "/assets/table_remote_till/js/table_remote_till.js"

# include js, css files in header of web template
# web_include_css = "/assets/table_remote_till/css/table_remote_till.css"
# web_include_js = "/assets/table_remote_till/js/table_remote_till.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "table_remote_till/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {"TRT Import Job": "public/js/trt_import_job.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "table_remote_till/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "table_remote_till.utils.jinja_methods",
# 	"filters": "table_remote_till.utils.jinja_filters"
# }

# Installation
# ------------

before_install = "table_remote_till.install.before_install"
after_install = "table_remote_till.install.after_install"
after_migrate = "table_remote_till.install.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "table_remote_till.uninstall.before_uninstall"
# after_uninstall = "table_remote_till.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "table_remote_till.utils.before_app_install"
# after_app_install = "table_remote_till.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "table_remote_till.utils.before_app_uninstall"
# after_app_uninstall = "table_remote_till.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "table_remote_till.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "table_remote_till.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["table_remote_till.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"table_remote_till.tasks.all"
# 	],
# 	"daily": [
# 		"table_remote_till.tasks.daily"
# 	],
# 	"hourly": [
# 		"table_remote_till.tasks.hourly"
# 	],
# 	"weekly": [
# 		"table_remote_till.tasks.weekly"
# 	],
# 	"monthly": [
# 		"table_remote_till.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "table_remote_till.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "table_remote_till.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "table_remote_till.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "table_remote_till.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["table_remote_till.utils.before_request"]
# after_request = ["table_remote_till.utils.after_request"]

# Job Events
# ----------
# before_job = ["table_remote_till.utils.before_job"]
# after_job = ["table_remote_till.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"table_remote_till.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

website_route_rules = [{'from_route': '/menu/<path:app_path>', 'to_route': 'menu'}, {'from_route': '/kiosk/<path:app_path>', 'to_route': 'kiosk'}, {'from_route': '/kitchen/<path:app_path>', 'to_route': 'kitchen'}, {'from_route': '/till/<path:app_path>', 'to_route': 'till'},]
