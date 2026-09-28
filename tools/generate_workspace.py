"""Write the versioned Desk workspace that exposes every parent TRT DocType."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "table_remote_till" / "table_remote_till"
GROUPS = {
    "Business setup": ["TRT Business Setup", "TRT Onboarding Run", "TRT Outlet",
                       "TRT Register", "TRT Staff Assignment", "TRT FX Rate"],
    "Floor and devices": ["TRT Service Area", "TRT Table", "TRT Kitchen Station", "TRT Device"],
    "Catalog": ["TRT Menu", "TRT Modifier Group"],
    "Operations": ["TRT Order", "TRT Kitchen Ticket", "TRT Payment Attempt", "TRT Sync Event"],
    "Migration": ["TRT Import Job", "TRT Legacy Record"],
}
SHORTCUTS = {
    "Guided onboarding": "/onboarding",
    "Staff till": "/till",
    "Kitchen": "/kitchen",
    "Kiosk": "/kiosk",
    "Public menu": "/menu",
}


def main():
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
    for index, (heading, doctypes) in enumerate(GROUPS.items()):
        content.append({"id": f"trt-card-{index}", "type": "card",
                        "data": {"card_name": heading, "col": 4}})
        links.append({"type": "Card Break", "label": heading, "hidden": 0})
        links.extend({"type": "Link", "label": doctype, "link_type": "DocType",
                      "link_to": doctype, "hidden": 0, "onboard": 0}
                     for doctype in doctypes)
    workspace = {
        "doctype": "Workspace", "name": "Table Remote Till", "label": "Table Remote Till",
        "title": "Table Remote Till", "module": "Table Remote Till", "app": "table_remote_till",
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
    print(f"Wrote {target} with {sum(map(len, GROUPS.values()))} parent DocTypes")


if __name__ == "__main__":
    main()
