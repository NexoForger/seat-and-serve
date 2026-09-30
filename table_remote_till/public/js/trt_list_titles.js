// Frappe's default list adds a raw `name` (ID) column even when a title_field exists.
for (const doctype of [
	"TRT Business Setup", "TRT Device", "TRT FX Rate", "TRT Import Job",
	"TRT Kitchen Station", "TRT Kitchen Ticket", "TRT Legacy Record",
	"TRT Menu", "TRT Modifier Group", "TRT Onboarding Run", "TRT Order",
	"TRT Outlet", "TRT Payment Attempt", "TRT Register", "TRT Reservation", "TRT Service Area",
	"TRT Staff Assignment", "TRT Sync Event", "TRT Table",
]) {
	frappe.listview_settings[doctype] = {
		...(frappe.listview_settings[doctype] || {}),
		hide_name_column: true,
	};
}
