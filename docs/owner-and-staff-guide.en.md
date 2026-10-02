# S&S (Seat & Serve): owner and staff guide

**Plain-language operating manual · English · reviewed against the local app source on 30 September 2026**

> This guide describes the features present in this S&S build. A label or setup screen does not mean that a payment provider, printer, tax rule, or workflow is ready for live use. Complete the pilot checklist and reconcile one real-world test with your accountant before accepting real sales.

![S&S service flow from guest order to ERPNext invoice](/assets/table_remote_till/images/service-flow.svg)

## Start here

S&S is a restaurant and retail service layer on Frappe/ERPNext. Staff use the **Till** to start and edit orders, the **Kitchen** screen to prepare them, and ERPNext to hold accounting, item, price, customer, stock, and POS records. Guests can use the public **Menu**, QR order page, **Kiosk**, or reservation portal when configured. The `TRT` prefix on records and roles is a stable internal identifier from the app's earlier name.

### Choose your task

- **Owner or opening manager:** read sections 1–4, complete the go-live checklist, then train each role below.
- **Shift manager:** read sections 3–6 and the manager training card.
- **Cashier / counter staff:** read sections 5–6 and the cashier card.
- **Server / host / runner:** read section 5 and the service card.
- **Kitchen team:** use the kitchen card and section 5.
- **Bookkeeper / accountant:** read sections 2, 3, 6, and 7 before approving tax, payment, discount, and return handling.
- **Administrator / support:** read section 8 and the limitations before changing users, devices, or the gateway.

## 1. What S&S does

The app provides staff and guest web pages plus a set of Frappe records:

| Screen | Route | Used for |
|---|---|---|
| Till | `/till` | Staff counter sales, dine-in tables, tabs, takeaway/pickup, modifiers, discounts, coupons, loyalty, and cash checkout |
| Kitchen | `/kitchen` | See tickets, start preparation, mark ticket lines ready, and manage kitchen work |
| Kiosk | `/kiosk` | Guest self-service ordering where enabled |
| Public menu / QR ordering | `/menu` | Browse a menu and submit a guest order from a configured outlet/table link |
| Reservations | `/reservations` | Book a table at an enabled outlet; staff can also book and seat guests from the Till |
| Guided setup | `/onboarding` | Preview and create initial business/outlet/register records |
| Frappe Desk workspace | `/desk/table-remote-till` | Managers configure TRT records and review operational data |

Typical flow: a guest or staff member creates an order; the server rechecks outlet, menu, price, modifiers, and order revision; kitchen tickets are generated; staff deliver the food; an eligible order is checked out to ERPNext as a POS Invoice. A table bill can include several linked tickets/add-ons. Payment is still manual cash tender entry in this build.

## 2. Before configuring the business

Assign one accountable owner for each item before the opening manager starts:

1. **Company and accounting:** legal company, fiscal year, chart of accounts, taxes, cost centers, warehouses, and tax-inclusive menu-price policy. Have the bookkeeper approve these.
2. **Currency and tender:** company currency must be USD or LBP for the guided flow. Enable the intended currencies, cash payment modes, and POS invoice setup in ERPNext. For mixed USD/LBP, management must publish the approved exchange rate and decide rounding/change policy.
3. **Products and stock:** create real ERPNext Items, UOMs, groups, selling Item Prices, tax templates, stock settings, and approved recipes/BOMs. Sample items are training data, not live inventory.
4. **Service design:** list outlets, branches, service areas, tables and seat counts, kitchen stations, sales channels, menu categories, modifiers, and who can approve discounts/returns.
5. **People and access:** create named Frappe Users; assign the least access needed, outlet staff assignments, and a manager who can resolve exceptions. Never share Administrator credentials.
6. **Equipment and network:** identify each register and tablet, test local Wi-Fi coverage, power, and browser screen size. Ethernet receipt printers require a reachable `escpos_tcp` TRT Device and a real test print; other device records do not mean a hardware driver is implemented.
7. **Opening data:** decide which master records to migrate. Keep original exports and an import/reconciliation log. Historical sales/payments are previewable but not imported as transactions by this version.

## 3. First setup: guided onboarding

Use a manager or System Manager account. Open `/onboarding`; the page checks that a business setup, branch, menu, outlet, staff assignment, open POS session, required currency settings, and—when selected—an approved FX rate exist.

![Six stages for setting up TRT](/assets/table_remote_till/images/setup-roadmap.svg)

### Recommended order

1. Finish Company and accounting setup in ERPNext first. The wizard does not configure or approve tax/payroll policy.
2. In `/onboarding`, choose the Company, base currency, branch, warehouse, selling price list, cash payment mode, outlet name, and enabled channels. Confirm the branch and warehouse belong to the intended company.
3. Choose which channels the outlet will actually use: table service, tab, takeaway/pickup, counter/retail, kiosk, and QR. Set table areas and kitchen stations as appropriate.
4. Preview the proposed records. Read every warning and confirm names, currency, payment mode, and accounting links. The wizard creates/reuses operational masters in one idempotent run and records a `TRT Onboarding Run` audit entry.
5. Enable LBP only if the company has approved its accounting and settlement policy. Add an approved `TRT FX Rate` with the effective time and approver before mixed tender. Never invent a rate at the till.
6. Review POS Settings. Live checkout requires **POS Invoice** mode and an open POS Opening Entry for today. The existing development site was specifically found in Sales Invoice mode with an old open session and LBP disabled; it is not ready for live sales.
7. Add real stock Items and selling Item Prices. Then prepare each sale item’s BOM/recipe, tax setup, and stock policy. Add approved Items to `TRT Menu`; imports alone do not make an Item appear on the Till.
8. Create `TRT Modifier Group` records and options only where the kitchen can fulfill them. Set minimum/maximum choices deliberately and price add-ons correctly.
9. Create and enable `TRT Tables`, `TRT Service Areas`, and `TRT Kitchen Stations`; confirm every table and menu entry belongs to the correct outlet/station.
10. Assign named users to the outlet. Do not issue public QR links until you test them from a guest phone and confirm they expose only the intended menu and table.
11. With sample data disabled for production, walk one order through each channel, kitchen, payment, and ERPNext invoice. Verify the inventory, tax, tender, and accounting entries with the bookkeeper before opening.

**Sample data:** the wizard can add clearly labeled non-stock sample items, prices, menu rows, recipes, and a sample table for demonstration. Do not treat them as approved products. Remove or disable sample content before go-live; do not seed sample orders into a live service.

## 4. Build and maintain the menu

- **ERPNext Item:** the stock/accounting identity. Set item name, group, stock behavior, UOM, barcode if used, taxes, price, and recipe/BOM under the business’s accounting rules.
- **Item Price:** the selling price in a selling Price List. TRT expects configured menu prices to be tax-inclusive. Confirm displayed price and tax allocation with the accountant.
- **TRT Menu:** an outlet’s enabled menu plus its entries. An entry can choose category, English and Arabic names, station, availability, photo, modifier group, deal type, deal description, and optional complete deal price.
- **Modifier Group / options:** guest choices such as size or add-on. Keep option Items and prices aligned with inventory and kitchen practice. A modifier’s allowed options are validated on the server; do not promise a choice that the station cannot prepare.
- **Combos and offers:** create a sale Item and approved BOM, then mark the menu entry Combo or Offer. Any menu override is the complete deal price. The deal remains one order line; it does not automatically add its components as separate sale lines. Put clear contents in Deal Contents so the guest and kitchen see what is included.
- **Availability:** check menu enabled state, outlet, channel switches, and entry availability before service. Removing something from one menu does not change the underlying ERPNext Item or past orders.
- **Images:** use approved product photography with clear rights and sensible file size. Check guest menu on a real phone, in both languages.

## 5. Daily service workflow

### Open the shift

1. Log in with your own account and check you are assigned to the correct outlet/register.
2. Manager confirms the outlet, menu availability, kitchen stations, connectivity, POS Settings, approved current FX rate if needed, and today's POS Opening Entry.
3. Till opens only when the register and outlet are configured. If there is no open POS session, do not take checkout through a workaround—call the manager.
4. Confirm drawer float according to company cash policy outside TRT. The application does not count the physical drawer automatically.

### Take an order

1. Choose the service type and, for dine-in, select the right table. An occupied table reopens its saved order; available tables start a new one.
2. Add items from the current outlet menu. Ask about modifiers and guest notes, then repeat them back. Do not put allergy claims in free text as a substitute for the restaurant’s allergen protocol.
3. Save/send the order. The server validates price and modifier choices. Do not use browser refresh to resolve a pending action; first check the order list/table and ask a manager if status is unclear.
4. For more items later, attach a new add-on ticket to the same table/root bill. Five-minute idle empty add-on drafts are cleaned automatically. Open tickets show separately in the kitchen; checkout covers the linked table bill.
5. Tell the guest the displayed total and any expected wait. Guest QR/Kiosk requests may still need staff confirmation and food handoff.

### Prepare and hand off

1. Kitchen opens `/kitchen` on its assigned screen and checks outlet and connection status.
2. Read order number, table/tab/channel, time, modifiers, notes, and add-on relationship. Ask the manager to correct unclear or unsafe orders before preparation.
3. Start the ticket/order if the controls show it as new. Update each ticket line to **Preparing**, then **Ready** when that item is actually complete.
4. Tell the runner/server when the ticket is ready. The runner matches ticket and table/order number before pickup, confirms the complete handoff, and marks/communicates served according to the screen flow.
5. If the connection fails, stop relying on the screen as a live queue. Use the venue’s manager-approved paper contingency, prevent duplicate preparation, and reconcile every paper order into TRT after recovery. The separate gateway is a development prototype, not an approved offline fallback.

### Close and reconcile

1. Stop taking new orders at the published closing time. Resolve open tickets and open table bills with the manager.
2. Cashier and manager compare submitted POS Invoices/payment entries with physical drawer and any external terminal reports. TRT does not itself count cash, reconcile a card provider, or settle offline cash.
3. Investigate unpaid/pending orders, duplicate attempts, voids, returns, and invoice mismatches before closing the POS Opening Entry using ERPNext’s approved procedure.
4. Manager records exceptions and actions in the business’s shift log. Never delete or rewrite a posted invoice to hide a discrepancy.

## 6. Money, savings, returns, and customers

### Checkout today

The Till checkout currently creates an ERPNext **POS Invoice** for supported exact cash or mixed USD/LBP tender when the POS session, approved FX rate, payment modes, stock, and configuration are valid. It is not connected to a card processor or online gateway. The current hardware/device records do not capture payments.

- Choose the enabled payment mode and currency; for a split tender add each amount and verify the due is fully covered before confirming.
- Mixed USD/LBP uses the currently approved outlet FX rate. Verify rate, tender, change, rounding, and invoice total aloud with the guest.
- A server or network response may be delayed. Before retrying, inspect the bill and payment attempt; the backend uses an idempotency key so a retry should reuse one invoice. If uncertain, stop and ask the manager.
- A full return for a settled order is supported through the app’s idempotent `return_order` command. Partial line returns still need their own quantity/stock policy; do not promise or manually improvise a partial refund through TRT.
- Card/online payments, automatic refund to a card, split bills, weighed items, and full offline cash settlement are not implemented.

### Coupons and manager discounts

- Manager creates an outlet-scoped `TRT Promotion` with a unique code, percentage/fixed value, optional minimum bill, date range, and maximum uses. Check dates and outlet before announcing it.
- Cashier applies one coupon in **Cash payment → Customer & savings** and selects **Apply to bill**. It covers the complete bill including linked table add-on tickets. A submitted invoice writes a redemption record; payment retries reuse the invoice.
- One bill can use a coupon or a manual discount, not both. A `TRT Manager`/System Manager can enter a percentage or amount plus a reason. Cashiers cannot alter manager discounts.
- Deal prices can still receive a whole-bill discount. Prices are tax-inclusive and included tax is recalculated after a discount. ERPNext Pricing Rules and web-store Coupon Codes are bypassed on this register path.
- Do not promise stacking or additional exclusions that are not configured; read the promotion terms to the guest.

### Loyalty and customers

ERPNext Loyalty Program must be configured by the bookkeeper: conversion factor, earning tiers, expense account, cost center, and named Customer enrollment. At checkout select that customer and whole available points. Verify point balance and final tender. TRT records points in ERPNext Loyalty Point Entry and records redemption as an invoice discount in this build. Accountant must approve the loyalty liability and return accounting before production.

Guest menu ordering currently does not provide guest coupon entry or online payment. Ask for a named customer only when necessary, explain how the business uses the data, and follow its privacy/retention rules.

## 7. Migration, reports, and audit

The import tool accepts private CSV/XLSX exports, supports UTF-8 or Windows-1256 CSV, and can detect comma, semicolon, tab, or pipe delimiters. It has source profiles for Omega POS, BIM POS, Squirrel Cloud, Squirrel 11, or Generic, with a mapping preview. Current executed imports cover **Item, Customer, and Supplier master records** and source-ID tracking. Item imports can create Item Prices when the selling Price List/rate mapping is configured.

1. Preserve the original export and restrict its access; it may contain personal or business-sensitive data.
2. Choose the source and record type; use separate BIM POS exports per record type.
3. Check suggested mappings against actual column headings. Preview missing fields, invalid rates, duplicates, counts, and source totals.
4. Fix the source file/mapping, then import a small controlled batch. Verify created master records and prices before continuing.
5. Reconcile totals and document who approved the migration. Imported products need recipes/BOMs and TRT menu entries separately.

Historical Sale, Return, Payment, Purchase, Stock, Journal, and Employee exports can be inventoried and previewed only. Their transaction import and historical reconciliation are not implemented. Never claim the old sales ledger has been migrated because a preview succeeded.

Useful operational records include TRT Order, Order Line, Kitchen Ticket and Ticket Line, Payment Attempt, Promotion/Redemption, FX Rate, Staff Assignment, Device, Sync Event, Import Job, and Onboarding Run, plus ERPNext POS Invoice and stock/accounting ledgers. Access depends on Frappe permissions. Reconcile through ERPNext reports and the business’s approved close process.

## 8. Roles, access, and staff training

Use named user accounts and only grant a role after the person passes a supervised practice order. Role names in Desk may be combined with ERPNext roles; test access with a sample user because this build does not provide branch-scoped Desk permissions.

### Owner / business administrator

**Can own:** approved company, tax and currency policy; outlet and channel choices; manager assignment; policy for cash, promotions, returns, stock and privacy; go-live decision.

**Training:** complete sections 2–3; review one test per channel; confirm full invoice to tender to stock/accounting trail; approve contingency and close procedure; schedule menu/FX/access reviews. Do not ask the owner to personally share an admin login.

**Ready when:** they can explain what TRT currently cannot process (card, online, partial refund, approved offline settlement); identify the escalation manager; and sign off the pilot reconciliation.

### TRT Manager / shift manager

**Can own:** day-to-day outlet setup and operational review; onboarding (TRT Manager/System Manager); promotion setup; manager discount with reason; exception escalation; the permitted full return command.

**Training practice:** preview a safe onboarding configuration; apply a test coupon; record a manual discount reason; resolve a duplicate/pending payment without retrying blindly; use the open-session checklist; reconcile an intentionally mismatched test invoice.

**Ready when:** they can find the owning order, kitchen tickets, payment attempt, POS Invoice, and redemption; know who can approve FX/tax changes; and can explain no split bill/partial return.

### Cashier / counter staff

**Can own:** accurate order capture, customer selection when needed, tender entry, coupon entry, receipt handoff, and rapid exception escalation. Cannot set manual manager discounts.

**Training practice:** counter sale; table add-on; modifier; one supported cash checkout; test mixed tender under manager supervision; coupon application; delayed response investigation by looking up order before retry. Practice switching language English/Arabic.

**Ready when:** they can match amount/currency to the guest and screen, protect credentials, never invent FX, and call the manager for no session, no connection, mismatch, uncertain payment, void/return, or discount request.

### Server / host / runner

**Can own:** correct guest count, table, service type, item choices, notes, table add-on, kitchen-ready handoff, and guest updates.

**Training practice:** start a new table, reopen an occupied table, add a later ticket, communicate a modifier/allergen concern through venue policy, find a ready ticket, and match the runner handoff to the right table. Guest QR is not proof that food is paid or handed over.

**Ready when:** they can repeat the table and order number, confirm changes before send, avoid creating duplicate orders on refresh, and know the paper contingency lead.

### Kitchen team

**Can own:** station preparation and actual line status updates in Kitchen. Do not mark ready before it is ready; do not change price or payment.

**Training practice:** identify new/preparing/ready/served states; interpret table/add-on/modifier and notes; update one line at a time; refresh after a recovered connection; report a duplicate, missing, or unsafe order before preparing it.

**Ready when:** they can track each item’s status, preserve ticket/order identity, and use manager-approved fallback when the screen loses connection.

### Bookkeeper / accountant

**Can own:** Company/accounting setup, tax, POS Profile/Opening Entry, payment modes, price lists, loyalty accounts, stock and return accounting, migration reconciliation.

**Training practice:** confirm a test invoice’s item, tax-inclusive price, discounts/tax allocation, payment entries, stock ledger, FX conversion, and return trace. Confirm chart-of-accounts mappings and loyalty return policy.

**Ready when:** they approve one fully reconciled pilot and document local accounting choices. The guide does not determine local tax law.

### System administrator / support

**Can own:** Frappe apps, named accounts/roles, device/network/browser support, backups, upgrades, API tokens, and incident response.

**Training practice:** use a least-privilege test user; verify the four routes; issue dedicated API credentials only to a service user; rotate secrets; confirm backups/restores; monitor logs and release changes. Do not expose private import files or QR secrets in screenshots/support tickets.

**Gateway note:** the local SQLite gateway is experimental. It accepts local commands and queues events, but does not settle offline cash into POS invoices, synchronize kitchen status, authoritatively calculate offline tax, resolve price conflicts, coordinate multiple processes, or certify hardware. Do not enable on a live LAN as a fallback.

## 9. Known boundaries and incident playbook

This build is **not ready for live sales without a business-specific pilot**. Besides the gaps called out above, it still lacks certified real device drivers, complete offline PWA behavior, Windows/macOS packaging, branch-scoped Desk permissions, and full historical transaction migration. Partial line returns need a defined quantity/stock policy. Sandbox payment is for development only and requires both developer mode and `allow_sandbox_payments`; never enable on a live site.

| What you see | Safe next step |
|---|---|
| Till says open a POS shift | Manager/accountant verifies today's POS Opening Entry and POS Invoice mode in ERPNext. |
| Order/connection state is unclear | Do not submit again immediately. Search table/order and Payment Attempt; manager resolves one authoritative state. |
| No menu item | Check outlet menu, entry availability, channel, item price list, and enabled Item. Imported Item alone is not a menu item. |
| Wrong/expired currency rate | Stop mixed-currency checkout; manager/bookkeeper approves a new rate and effective time. Never edit the amount to compensate. |
| Duplicate/missing kitchen ticket | Stop preparation if safe; manager matches order, table, ticket, and revision. Prevent duplicate cooking. |
| Guest reports wrong charge | Preserve invoice/order/payment references and escalate to manager/bookkeeper. Use approved ERPNext return procedure; don't delete submitted records. |
| Network down | Follow the venue's paper contingency. Do not call the gateway prototype a supported offline settlement. Reconcile manually before re-entering orders. |
| QR link exposed or device lost | Disable/reissue through a manager/admin; revoke any associated account/token; report incident. |

## 10. Owner’s go-live sign-off

- [ ] Company, fiscal year, chart, tax, stock, payment, currency, and item-price setup approved by the accountable bookkeeper.
- [ ] Outlet, channel, tables, stations, real menu, modifiers, recipes/BOMs, language names, and staff assignments reviewed by the operating manager.
- [ ] Today's POS Opening Entry and POS Invoice mode confirmed; cash drawer procedure is documented.
- [ ] Mixed currency disabled unless approved rate, rounding, settlement, and change rules are written and tested.
- [ ] One full dine-in, takeaway/counter, and any enabled guest/kiosk flow practiced; a real device/hardware certification is completed outside the app where needed.
- [ ] Each pilot POS Invoice reconciled to tender, tax, stock, and accounting records; return and discount rules reviewed.
- [ ] Each staff member passed role practice; escalation names and paper fallback are posted.
- [ ] Sample content removed/disabled; imported data checked and sensitive exports stored privately.
- [ ] Limits (no card/online provider, partial returns, or supported offline settlement) are understood by the owner and frontline staff.

## Glossary

**Outlet:** service location with its own channels and menu. **Register:** configured staff point of sale. **Order:** guest sale container. **Ticket:** a kitchen work grouping; add-on tickets may link to a root table order. **Root order:** the bill record that owns shared table customer/savings settings. **POS Opening Entry:** ERPNext record opening a cashier's POS session. **POS Invoice:** ERPNext sales/accounting document generated by supported TRT checkout. **FX:** approved exchange rate for USD/LBP tender. **BOM/recipe:** stock ingredients consumed for a sale item. **Idempotency:** safe retry behavior intended to prevent duplicate order/payment records.

## Source and change control

This manual is based on the TRT app README and code present in the local bench on 30 September 2026. A named business owner should review it after each app upgrade and after any change to accounting policy, payment provider, tax, access, or menu workflows. Local tax and labor policy must be provided by the business’s qualified advisers.
