"""Write the versioned Desk workspace with grouped links to parent TRT DocTypes."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "table_remote_till" / "table_remote_till"
GROUPS = {
    "Business setup": ["TRT Business Setup", "TRT Guest Appearance", "TRT Onboarding Run",
                       "TRT Outlet", "TRT Staff Assignment"],
    "Floor and equipment": ["TRT Service Area", "TRT Table", "TRT Reservation",
                            "TRT Register", "TRT Device", "TRT Kitchen Station"],
    "Menus and modifiers": ["TRT Menu", "TRT Modifier Group"],
    "Promotions": ["TRT Promotion", "TRT Promotion Redemption"],
    "Orders and kitchen": ["TRT Order", "TRT Kitchen Ticket"],
    "Payments and rates": ["TRT Payment Attempt", "TRT FX Rate"],
    "Integrations and history": ["TRT Sync Event", "TRT Import Job", "TRT Legacy Record"],
}
SHORTCUTS = {
    "Guided onboarding": "/onboarding",
    "Staff till": "/till",
    "Kitchen": "/kitchen",
    "Kiosk": "/kiosk",
    "Public menu": "/menu",
    "Reservation portal": "/reservations",
}


def main():
    doctype_root = ROOT / "doctype"
    parent_doctypes = {
        doctype.get("name")
        for path in doctype_root.glob("*/*.json")
        for doctype in [json.loads(path.read_text())]
        if doctype.get("doctype") == "DocType" and not doctype.get("istable")
    }
    grouped_doctypes = [doctype for doctypes in GROUPS.values() for doctype in doctypes]
    unknown = sorted(set(grouped_doctypes) - parent_doctypes)
    duplicates = sorted({doctype for doctype in grouped_doctypes if grouped_doctypes.count(doctype) > 1})
    if unknown or duplicates:
        raise ValueError(f"Invalid workspace groups; unknown={unknown}, duplicates={duplicates}")

    ungrouped = sorted(parent_doctypes - set(grouped_doctypes))
    groups = dict(GROUPS)
    if ungrouped:
        groups["Other records"] = ungrouped

    links = []
    content = [{"id": "trt-shortcuts", "type": "header",
                "data": {"text": "<span class=\"h4\"><b>Start here</b></span>", "col": 12}}]
    shortcuts = []
    for index, (label, url) in enumerate(SHORTCUTS.items()):
        content.append({"id": f"trt-shortcut-{index}", "type": "shortcut",
                        "data": {"shortcut_name": label, "col": 3}})
        shortcuts.append({"type": "URL", "label": label, "url": url, "color": "Blue"})
    content.append({"id": "trt-records", "type": "header",
                    "data": {"text": "<span class=\"h4\"><b>App records</b></span>", "col": 12}})
    for index, (heading, doctypes) in enumerate(groups.items()):
        content.append({"id": f"trt-card-{index}", "type": "card",
                        "data": {"card_name": heading, "col": 4}})
        links.append({"type": "Card Break", "label": heading, "hidden": 0})
        links.extend({"type": "Link", "label": doctype.removeprefix("TRT "), "link_type": "DocType",
                      "link_to": doctype, "hidden": 0, "onboard": 0}
                     for doctype in doctypes)
    workspace = {
        "doctype": "Workspace", "name": "Table Remote Till", "label": "S&S (Seat & Serve)",
        "title": "S&S (Seat & Serve)", "module": "Table Remote Till", "app": "table_remote_till",
        "type": "Workspace", "icon": "selling", "public": 1,
        "is_hidden": 0, "parent_page": "", "sequence_id": 18.0,
        "content": json.dumps(content, separators=(",", ":")),
        "links": links, "shortcuts": shortcuts, "charts": [], "number_cards": [],
        "quick_lists": [], "custom_blocks": [],
        "roles": [{"role": "System Manager"}, {"role": "TRT Manager"}],
    }
    target = ROOT / "workspace" / "table_remote_till" / "table_remote_till.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(workspace, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote {target} with {sum(map(len, groups.values()))} parent DocTypes in {len(groups)} folders")


if __name__ == "__main__":
    main()
