"""Generate the initial, versioned Table Remote Till DocType metadata.

Run from the app root with ``python tools/generate_doctypes.py``. Controllers are
created only when missing so business logic can be edited independently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "table_remote_till" / "table_remote_till"


def f(name: str, kind: str = "Data", options: str | None = None, **extra):
    field = {"fieldname": name, "fieldtype": kind, "label": name.replace("_", " ").title()}
    if options:
        field["options"] = options
    field.update(extra)
    return field


SPECS = {
    "TRT Business Setup": [
        f("company", "Link", "Company", reqd=1, unique=1),
        f("business_type", "Select", "Restaurant/Pub\nRetail\nMixed", reqd=1),
        f("country", "Link", "Country", default="Lebanon"),
        f("base_currency", "Link", "Currency", default="USD"),
        f("cash_currency", "Link", "Currency", default="LBP"),
        f("tax_approved_by", "Link", "User"), f("tax_approved_on", "Datetime"),
        f("payroll_approved_by", "Link", "User"), f("payroll_approved_on", "Datetime"),
        f("notes", "Small Text"),
    ],
    "TRT Outlet": [
        f("title", reqd=1, in_list_view=1), f("company", "Link", "Company", reqd=1),
        f("branch", "Link", "Branch"), f("warehouse", "Link", "Warehouse"),
        f("pos_profile", "Link", "POS Profile"), f("price_list", "Link", "Price List"),
        f("walk_in_customer", "Link", "Customer"),
        f("receivable_account", "Link", "Account"),
        f("tax_template", "Link", "Sales Taxes and Charges Template"),
        f("base_currency", "Link", "Currency"), f("cash_currency", "Link", "Currency"),
        f("enable_tables", "Check"), f("enable_tabs", "Check"), f("enable_takeaway", "Check"),
        f("enable_retail", "Check"), f("enable_kiosk", "Check"), f("enable_qr", "Check"),
        f("enable_pickup", "Check"), f("enabled", "Check", default="1"),
        f("online_provider"), f("allow_sandbox_payments", "Check"),
    ],
    "TRT Register": [
        f("title", reqd=1, in_list_view=1), f("outlet", "Link", "TRT Outlet", reqd=1),
        f("pos_profile", "Link", "POS Profile", reqd=1),
        f("opening_entry", "Link", "POS Opening Entry"), f("gateway_url", options="URL"),
        f("enabled", "Check", default="1"),
    ],
    "TRT Staff Assignment": [
        f("user", "Link", "User", reqd=1, in_list_view=1),
        f("outlet", "Link", "TRT Outlet", reqd=1, in_list_view=1),
        f("allow_till", "Check"), f("allow_kitchen", "Check"),
        f("allow_manager", "Check"), f("enabled", "Check", default="1"),
    ],
    "TRT FX Rate": [
        f("outlet", "Link", "TRT Outlet", reqd=1, in_list_view=1),
        f("effective_date", "Date", reqd=1, in_list_view=1),
        f("lbp_per_usd", "Float", reqd=1),
        f("approved_by", "Link", "User", reqd=1),
        f("approved_on", "Datetime", reqd=1),
        f("enabled", "Check", default="1"),
    ],
    "TRT Service Area": [
        f("title", reqd=1, in_list_view=1), f("outlet", "Link", "TRT Outlet", reqd=1),
        f("sort_order", "Int"), f("enabled", "Check", default="1"),
    ],
    "TRT Table": [
        f("title", reqd=1, in_list_view=1), f("area", "Link", "TRT Service Area", reqd=1),
        f("outlet", "Link", "TRT Outlet", reqd=1), f("seats", "Int"),
        f("qr_secret"),
        f("enabled", "Check", default="1"),
    ],
    "TRT Menu": [
        f("title", reqd=1, in_list_view=1), f("outlet", "Link", "TRT Outlet", reqd=1),
        f("items", "Table", "TRT Menu Entry"), f("show_on_till", "Check", default="1"),
        f("show_on_kiosk", "Check"), f("show_on_menu", "Check"),
        f("enabled", "Check", default="1"),
    ],
    "TRT Menu Entry": [
        f("item", "Link", "Item", reqd=1, in_list_view=1), f("category", "Link", "Item Group"),
        f("name_en"), f("name_ar"), f("price_override", "Currency"),
        f("modifier_group", "Link", "TRT Modifier Group"),
        f("station", "Link", "TRT Kitchen Station"),
        f("available", "Check", default="1"), f("sort_order", "Int"),
    ],
    "TRT Modifier Group": [
        f("title", reqd=1, in_list_view=1), f("minimum", "Int"), f("maximum", "Int"),
        f("options", "Table", "TRT Modifier Option"),
    ],
    "TRT Modifier Option": [
        f("item", "Link", "Item", reqd=1, in_list_view=1),
        f("name_en"), f("name_ar"), f("price_delta", "Currency"),
        f("ingredient_item", "Link", "Item"), f("ingredient_qty", "Float"),
    ],
    "TRT Kitchen Station": [
        f("title", reqd=1, in_list_view=1), f("outlet", "Link", "TRT Outlet", reqd=1),
        f("printer", "Link", "TRT Device"), f("enabled", "Check", default="1"),
    ],
    "TRT Order": [
        f("outlet", "Link", "TRT Outlet", reqd=1, in_list_view=1),
        f("register", "Link", "TRT Register"),
        f("channel", "Select", "Till\nTable\nTab\nTakeaway\nRetail\nKiosk\nQR\nPickup", reqd=1),
        f("table", "Link", "TRT Table"), f("tab_label"),
        f("customer", "Link", "Customer"),
        f("status", "Select", "Draft\nSent\nPreparing\nReady\nServed\nSettled\nVoid", default="Draft", in_list_view=1),
        f("lines", "Table", "TRT Order Line"), f("currency", "Link", "Currency", reqd=1),
        f("exchange_rate", "Float", default="1"), f("net_total", "Currency", read_only=1),
        f("tax_total", "Currency", read_only=1), f("grand_total", "Currency", read_only=1),
        f("revision", "Int", default="0", read_only=1), f("external_id", unique=1),
        f("guest_session", read_only=1, hidden=1),
        f("pos_invoice", "Link", "POS Invoice", read_only=1),
        f("pickup_time", "Datetime"), f("notes", "Small Text"),
    ],
    "TRT Order Line": [
        f("item", "Link", "Item", reqd=1, in_list_view=1), f("item_name"),
        f("qty", "Float", reqd=1, default="1"), f("rate", "Currency", read_only=1),
        f("amount", "Currency", read_only=1), f("modifiers_json", "Code", "JSON"),
        f("station", "Link", "TRT Kitchen Station"), f("note", "Small Text"),
    ],
    "TRT Kitchen Ticket": [
        f("order", "Link", "TRT Order", reqd=1, in_list_view=1),
        f("station", "Link", "TRT Kitchen Station", reqd=1),
        f("status", "Select", "Queued\nPreparing\nReady\nServed\nCancelled", default="Queued"),
        f("revision", "Int", default="1", read_only=1),
        f("lines", "Table", "TRT Ticket Line"), f("sent_at", "Datetime"),
    ],
    "TRT Ticket Line": [
        f("order_line", "Data"), f("item", "Link", "Item", reqd=1),
        f("qty", "Float", reqd=1), f("note", "Small Text"),
    ],
    "TRT Device": [
        f("title", reqd=1, in_list_view=1), f("outlet", "Link", "TRT Outlet", reqd=1),
        f("register", "Link", "TRT Register"),
        f("kind", "Select", "Receipt Printer\nKitchen Printer\nBarcode Scanner\nCash Drawer\nCustomer Display\nScale\nCard Terminal\nKiosk", reqd=1),
        f("driver"), f("address"), f("settings_json", "Code", "JSON"),
        f("enabled", "Check", default="1"),
    ],
    "TRT Payment Attempt": [
        f("order", "Link", "TRT Order", reqd=1, in_list_view=1),
        f("mode", "Select", "Cash\nCard\nOnline", reqd=1),
        f("currency", "Link", "Currency", reqd=1), f("amount", "Currency", reqd=1),
        f("exchange_rate", "Float"),
        f("status", "Select", "Pending\nAuthorized\nCaptured\nFailed\nCancelled", default="Pending"),
        f("provider"), f("provider_reference"), f("idempotency_key", unique=1),
        f("order_revision", "Int", read_only=1),
        f("pos_invoice", "Link", "POS Invoice"),
    ],
    "TRT Sync Event": [
        f("event_id", unique=1, reqd=1, in_list_view=1),
        f("outlet", "Link", "TRT Outlet", reqd=1),
        f("register", "Link", "TRT Register"), f("order", "Link", "TRT Order"),
        f("event_type", reqd=1), f("payload_json", "Code", "JSON"),
        f("status", "Select", "Pending\nApplied\nConflict", default="Pending"),
        f("error", "Small Text"), f("received_at", "Datetime"),
    ],
    "TRT Import Job": [
        f("source", "Select", "Omega POS\nSquirrel Cloud\nSquirrel 11\nGeneric", reqd=1),
        f("record_type", "Select", "Item\nCustomer\nSupplier\nSale\nReturn\nPayment\nPurchase\nStock\nJournal\nEmployee", reqd=1),
        f("status", "Select", "Uploaded\nMapped\nValidated\nImporting\nComplete\nFailed", default="Uploaded"),
        f("source_file", "Attach"), f("mapping_json", "Code", "JSON"),
        f("preview_json", "Code", "JSON"), f("report_json", "Code", "JSON"),
        f("imported_count", "Int", read_only=1), f("error_count", "Int", read_only=1),
    ],
    "TRT Legacy Record": [
        f("source", reqd=1), f("record_type", reqd=1), f("source_id", reqd=1),
        f("source_key", unique=1, reqd=1), f("job", "Link", "TRT Import Job", reqd=1),
        f("frappe_doctype"), f("frappe_name"), f("source_date", "Date"),
        f("branch"), f("amount", "Currency"),
        f("status", "Select", "Staged\nImported\nUnavailable\nFailed", default="Staged"),
        f("error", "Small Text"),
    ],
}


def main():
    root = APP / "doctype"
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").touch()
    for title, fields in SPECS.items():
        slug = re.sub(r"\W+", "_", title.lower()).strip("_")
        folder = root / slug
        folder.mkdir(exist_ok=True)
        (folder / "__init__.py").touch()
        is_child = title in {"TRT Menu Entry", "TRT Modifier Option", "TRT Order Line", "TRT Ticket Line"}
        permissions = [] if is_child else [
            {"role": role, "read": 1, "write": 1, "create": 1, "delete": 1,
             "print": 1, "report": 1, "export": 1}
            for role in ("System Manager", "TRT Manager")
        ]
        doc = {
            "doctype": "DocType", "name": title, "module": "Table Remote Till",
            "engine": "InnoDB", "autoname": "hash", "istable": int(is_child),
            "field_order": [field["fieldname"] for field in fields],
            "fields": fields, "permissions": permissions,
            "sort_field": "modified", "sort_order": "DESC",
        }
        (folder / f"{slug}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        controller = folder / f"{slug}.py"
        if not controller.exists():
            controller.write_text("from frappe.model.document import Document\n\n\nclass " + title.replace(" ", "") + "(Document):\n\tpass\n")
    print(f"Generated {len(SPECS)} DocTypes in {root}")


if __name__ == "__main__":
    main()
