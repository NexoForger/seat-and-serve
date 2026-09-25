# Development bench audit, 25 September 2026

The existing site `fuckomegaproject.localhost` was backed up before app installation. Its `xpos` app registration had no corresponding source app and prevented a clean bench migrate; the stale registrations were removed. ERPNext and HRMS remain installed. The new app uses its own repository inside the bench because the outer Docker repository ignores `development/`.

The site currently has **69 Custom Fields** and **193 Property Setters**. [The inventory](development-site-customizations.csv) lists every record and its disposition. None was created by Table Remote Till, so none is exported as an app fixture. Existing HRMS/ERPNext and prior POS fields remain site owned. This avoids replacing site settings through bulk customization export.

Fields needing particular attention during pilot setup include the prior POS Profile purchase/sale and print fields, `POS Profile User.pos_role`, Company receipt header/footer, and item/local name fields. The Property Setters hide barcode controls in Item, POS Invoice, and other stock and sales forms; they also change field order and naming series. The new till reads Item Price and Item data through its own API and does not rely on those form changes. Before adopting any prior field in a new site, verify its behavior and owner with that business.

The current site is not a pilot: its POS Settings use Sales Invoice mode, its open POS Opening Entry is dated 22 September 2026, LBP is disabled, and no TRT outlet, staff assignment, or approved FX rate exists. The `/onboarding` checklist reports these gaps. Smoke checks alter test settings only within a rolled-back transaction.
