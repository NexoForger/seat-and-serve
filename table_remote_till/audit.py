"""Inventory existing site customizations without exporting them as fixtures."""

import csv
from pathlib import Path

import frappe


def export():
	if frappe.session.user != "Administrator":
		frappe.throw("Administrator required", frappe.PermissionError)
	rows = []
	for row in frappe.get_all("Custom Field", fields=["name", "dt", "fieldname"],
		order_by="dt, fieldname", limit_page_length=10000):
		rows.append({"kind": "Custom Field", "name": row.name, "document": row.dt,
			"field": row.fieldname, "property": "", "decision": "Site-owned; do not export"})
	for row in frappe.get_all("Property Setter", fields=["name", "doc_type", "field_name", "property"],
		order_by="doc_type, field_name, property", limit_page_length=10000):
		rows.append({"kind": "Property Setter", "name": row.name, "document": row.doc_type,
			"field": row.field_name or "", "property": row.property,
			"decision": "Site-owned; do not export"})
	path = Path(__file__).resolve().parents[1] / "docs" / "development-site-customizations.csv"
	path.parent.mkdir(exist_ok=True)
	with path.open("w", encoding="utf-8", newline="") as handle:
		writer = csv.DictWriter(handle, fieldnames=("kind", "name", "document", "field", "property", "decision"),
			lineterminator="\n")
		writer.writeheader()
		writer.writerows(rows)
	return {"path": str(path), "custom_fields": sum(row["kind"] == "Custom Field" for row in rows),
		"property_setters": sum(row["kind"] == "Property Setter" for row in rows)}
