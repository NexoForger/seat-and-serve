"""Publish the checked-in owner guides to private, published Wiki spaces.

Run with ``bench --site SITE execute table_remote_till.publish_docs.publish``.
Re-running updates these two pages and leaves the rest of each Wiki space alone.
"""

from pathlib import Path

import frappe


DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"

GUIDES = (
	{
		"space_name": "S&S English",
		"route": "trt-english",
		"title": "S&S (Seat & Serve) — Owner and Staff Guide",
		"page_route": "trt-english/owner-and-staff-guide",
		"file": "owner-and-staff-guide.en.md",
	},
	{
		"space_name": "S&S العربية",
		"route": "trt-arabic",
		"title": "S&S (Seat & Serve) — دليل المالك والموظفين",
		"page_route": "trt-arabic/دليل-المالك-والموظفين",
		"file": "owner-and-staff-guide.ar.md",
	},
)


def publish():
	"""Create/update the two S&S guide spaces and their single manual pages."""
	results = []
	for guide in GUIDES:
		space_name = frappe.db.get_value("Wiki Space", {"route": guide["route"]}, "name")
		if space_name:
			space = frappe.get_doc("Wiki Space", space_name)
			space.space_name = guide["space_name"]
			space.is_published = 1
			space.show_in_switcher = 1
			space.allow_contributions = 0
			space.save(ignore_permissions=True)
		else:
			space = frappe.get_doc({
				"doctype": "Wiki Space",
				"space_name": guide["space_name"],
				"route": guide["route"],
				"is_published": 1,
				"show_in_switcher": 1,
				"allow_contributions": 0,
				# Empty roles means signed-in Wiki users; Guest access is not enabled.
				"roles": [],
			})
			space.insert(ignore_permissions=True)

		page_name = frappe.db.get_value("Wiki Document",
			{"wiki_space": space.name, "route": guide["page_route"], "is_group": 0}, "name")
		if page_name:
			page = frappe.get_doc("Wiki Document", page_name)
			page.title = guide["title"]
		else:
			page = frappe.new_doc("Wiki Document")
			page.title = guide["title"]
			page.parent_wiki_document = space.root_group
		page.content = (DOCS_DIR / guide["file"]).read_text(encoding="utf-8")
		page.route = guide["page_route"]
		page.is_group = 0
		page.is_published = 1
		page.wiki_space = space.name
		page.save(ignore_permissions=True) if page_name else page.insert(ignore_permissions=True)
		results.append({"space": space.space_name, "route": space.route, "page": page.title, "page_route": page.route})

	frappe.db.commit()
	return results


def verify_published():
	"""Summarize the installed guides without exposing user or site data."""
	results = []
	for guide in GUIDES:
		space = frappe.get_doc("Wiki Space", {"route": guide["route"]})
		page = frappe.get_doc("Wiki Document", {"route": guide["page_route"]})
		content = (DOCS_DIR / guide["file"]).read_text(encoding="utf-8")
		if page.content != content:
			frappe.throw(f"Wiki content is out of date: {guide['file']}")
		if not space.is_published or not page.is_published:
			frappe.throw(f"Wiki guide is not published: {guide['space_name']}")
		if frappe.db.exists("Wiki Space Role", {"parent": space.name, "role": "Guest"}):
			frappe.throw(f"Wiki guide is unexpectedly public: {guide['space_name']}")
		results.append({
			"space": guide["space_name"],
			"page_route": page.route,
			"words": len(content.split()),
			"illustrations": content.count("!["),
			"public_guest_access": False,
		})
	return results
