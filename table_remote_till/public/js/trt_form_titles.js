// Keep Frappe's hash `name` for links, while showing the document title in Desk.
if (!window.__trtReadableFormTitles) {
	window.__trtReadableFormTitles = true;
	for (const doctype of [
		"TRT Business Setup", "TRT Device", "TRT FX Rate", "TRT Import Job",
		"TRT Kitchen Station", "TRT Kitchen Ticket", "TRT Legacy Record",
		"TRT Menu", "TRT Modifier Group", "TRT Onboarding Run", "TRT Order",
		"TRT Outlet", "TRT Payment Attempt", "TRT Register", "TRT Reservation", "TRT Service Area",
		"TRT Staff Assignment", "TRT Sync Event", "TRT Table",
	]) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				const title = String(frm.doc[frm.meta.title_field] || "").trim();
				if (!title || frm.is_new()) return;
				requestAnimationFrame(() => {
					if (frappe.get_route()[1] !== frm.doctype || frappe.get_route()[2] !== frm.docname) return;
					frm.page.wrapper.find(".form-name-container").hide();
					frappe.utils.set_title(title);
				});
			},
		});
	}
}
