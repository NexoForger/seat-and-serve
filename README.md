# S&S (Seat & Serve)

S&S connects the waiter register, kitchen display, self-service kiosk, public menu, reservations, and ERPNext sales records. It is a Frappe v16 app with ERPNext and HRMS dependencies and Vue 3/TypeScript frontends. Each business uses its own Frappe site and database; outlets, registers, and branches live inside that site.

The installed package stays `table_remote_till`. Existing DocTypes, roles, API routes, and assets retain their `TRT` or `table_remote_till` identifiers so a rebrand does not break data on installed sites. **S&S (Seat & Serve)** is the product name displayed to staff and guests.

| Surface | Route | What it does |
| --- | --- | --- |
| Waiter register | `/till` | Table service, counter and takeaway sales, tabs, modifiers, savings, and supported checkout |
| Kitchen display (KDS) | `/kitchen` | Separate order cards, item statuses, and runner actions |
| Kiosk | `/kiosk` | Self-service ordering where enabled |
| Public menu / QR | `/menu` | Guest browsing and ordering for enabled channels |
| Reservation portal | `/reservations` | Public bookings for outlets with enabled tables |
| Business onboarding | `/onboarding` | Preview and create the initial outlet and register setup |
| Manager Desk | `/desk/table-remote-till` | Configure and inspect the app's versioned Frappe records |

## Current development status

The app installs and migrates on the existing local bench. The Desk workspace exposes parent app DocTypes; child DocTypes are edited inside their parent forms. Versioned records cover business setup, onboarding, outlets, registers, tables, reservations, menus, orders, kitchen tickets, payments, devices, FX rates, sync events, promotions, and import jobs. Staff and guest order commands are server priced, idempotent, and revision checked. Exact cash and mixed USD/LBP tender can create an ERPNext POS Invoice when the site has an open POS session, approved FX rate, stock, and payment modes. The SQLite gateway prototype accepts local staff commands and records cash for later manager reconciliation.

This is **not ready for live sales**. Card/online provider capture, real device drivers, partial refunds, split bills, weighed items, modifier accounting, full historical transaction migration, offline cash settlement, multi-device gateway recovery certification, complete offline PWA behavior, Windows/macOS packaging, and branch-scoped Desk permissions remain to be implemented. A settled order can receive one full ERPNext POS Invoice return through the idempotent `return_order` command; partial line returns still need their own quantity and stock policy. The web manifests provide an installable shell, while offline commands currently require the separate gateway prototype. Sandbox capture charges no money and is available only when `developer_mode` and `allow_sandbox_payments` are both enabled. Do not enable sandbox payments on a live site.

## Install and build

Prerequisites are Frappe v16, ERPNext, HRMS, MariaDB, Redis, an ERPNext Company/chart of accounts, and Node.js/Yarn for the browser builds. The local Docker environment supplies the runtime tools inside the Frappe container. For the local Docker bench in this workspace, run the interactive setup script from this app directory:

```sh
./setup.sh                 # macOS/Linux
./setup.sh --dry-run       # preview choices without changing anything
```

On Windows PowerShell, use `.\setup.ps1` or `.\setup.ps1 -DryRun`. The scripts ask for the Docker project and site name, whether to install frontend dependencies and build assets, and (for a new site) the MariaDB root and site Administrator passwords. They start the local Compose stack, create a new site or install missing apps on an existing site, build the four frontends, and migrate. Docker Desktop/Engine with Compose and a bench containing Frappe, ERPNext and HRMS are prerequisites. The scripts do not overwrite an existing site or reset its data. They do not install Docker or bootstrap a Frappe bench.

For a bench outside this workspace's Docker layout, use the manual commands below.

Install ERPNext and HRMS in a Frappe v16 bench, then add this repository as `apps/table_remote_till` and run:

```sh
bench --site BUSINESS_SITE install-app table_remote_till
cd apps/table_remote_till
for frontend in till kitchen kiosk menu; do (cd "$frontend" && yarn install --force --frozen-lockfile); done
yarn build
cd ../..
bench build --app table_remote_till
bench --site BUSINESS_SITE migrate
```

`tools/provision_site.py BUSINESS_SITE` creates a separate site and installs all three apps. It reads `TRT_DB_ROOT_PASSWORD` and `TRT_SITE_ADMIN_PASSWORD` from the environment. Run `--dry-run` to inspect the command. Complete ERPNext Company/chart of accounts setup, then open the app workspace or `/onboarding`.

If an existing Docker site's MariaDB login starts failing after a Frappe container is recreated, run `env/bin/python apps/table_remote_till/tools/repair_mariadb_site_user.py SITE` from the bench directory inside the Frappe container to inspect its database user. Rerun with `--apply` to grant that site's existing user access across the Docker network. The script prompts for the MariaDB root password and verifies the site login; it does not replace or drop the database.

The guided onboarding page selects a company, outlet, branch, register, channels, cash mode, and accounting references. It previews every operation and applies them together: business setup, branch, warehouse, selling list, walk-in customer, POS Profile, outlet, register, manager assignment, starter menu, and restaurant floor/station. Optional explicit choices enable LBP, record an approved FX rate, and switch site-wide POS Settings to POS Invoice mode. Each run has a UUID idempotency key and a `TRT Onboarding Run` audit record. The **Seed sample data** checkbox adds clearly labeled items, item prices, menu entries, and a sample table; remove them before live use. Tax/payroll approvals, real items, shift opening, live payments, device certification, and historical reconciliation remain separate steps.

### Configure the business after installation

1. Complete the ERPNext Company, chart of accounts, tax template, warehouse, selling Price List, POS Profile, payment modes, and walk-in Customer. A current POS Opening Entry and POS Invoice mode are required for cash checkout.
2. Use `/onboarding` to preview the outlet, register, staff assignment, channels, menu, service areas, and kitchen stations before applying them.
3. Create real sale Items and Item Prices. Approve each sale Item's BOM/recipe; ingredients in a BOM should be raw-material Items. Then add sale Items to the enabled `TRT Menu` and assign their kitchen station.
4. Create enabled tables for dine-in and reservations. Assign staff to the relevant outlet, then test an order through the register, KDS, and POS Invoice on a nonproduction site.
5. Configure a valid, approved `TRT FX Rate` and payment modes before accepting mixed USD/LBP tender. Have the accountant verify the tax-inclusive invoice and close procedure.

The existing development site has POS Settings set to Sales Invoice mode, an outdated open POS session, and LBP disabled. Those must be configured before cash checkout there. The smoke check changes them only inside a rolled-back transaction; it does not change the lasting site configuration.

## Register, kitchen, and one table bill

The waiter chooses an order type before opening the catalog. For dine-in, the register shows the table map and lets staff resume any open ticket for a table. Later drinks or dessert go into a new add-on ticket. Each sent ticket has its own kitchen release and KDS card, so the kitchen does not receive the original items again. Empty add-on drafts are removed after five minutes.

The KDS displays one card per order with its order type and age. Kitchen staff can set each item to **Queued**, **Preparing**, **Ready**, or **Served**, or use **Start all**, **Ready all**, **Dispatch runner**, and **Mark served** on the order. The card and line state remain specific to that ticket. On each kitchen screen, tap **Enable & test sound** once. The choice is saved in local storage; after a reload, the first tap on the screen reactivates audio because browsers require a fresh interaction. A continuous alarm sounds for new orders until **Start all** succeeds for each one.

All linked dine-in tickets for one table session are billed on **one POS Invoice**. Checkout can start from the root ticket or any add-on. The server locks and validates the group, includes every line once, releases any remaining draft add-on to the kitchen, and marks each ticket Settled with the same invoice. Retrying checkout cannot create a second invoice or payment attempt. Unrelated tables cannot be combined. Other order types retain one-order checkout. Split bills and partial ticket settlement are not implemented.

Prices shown in the register are **tax inclusive**. The tax amount is allocated inside the final price; no tax is added to the displayed price when the order or invoice is created. Discounts reallocate included tax within the discounted total. The server recalculates prices, modifiers, tax, and the amount due at checkout. Guest sandbox checkout is a developer-only simulation and collects no money.

## Development checks

```sh
bench --site SITE execute table_remote_till.smoke.run
bench --site SITE execute table_remote_till.smoke.promotions_run
bench --site SITE execute table_remote_till.smoke.deals_run
bench --site SITE execute table_remote_till.reservation_smoke.run
bench --site SITE execute table_remote_till.smoke.migration_run
bench --site SITE execute table_remote_till.smoke.bim_migration_run
bench --site SITE execute table_remote_till.smoke.onboarding_run
bench --site SITE execute table_remote_till.smoke.onboarding_retail_run
bench --site SITE execute table_remote_till.smoke.workspace_run
cd apps/table_remote_till/gateway && npm test
```

The smoke checks insert temporary test records and roll back. Frontend type checks run with `vue-tsc --noEmit` inside each of `till`, `kitchen`, `kiosk`, and `menu`.

## Table reservations

An enabled outlet with table service and at least one enabled table appears on the public `/reservations` page. Guests select the location, party size, date, and an available time, then provide a name and phone or email. The server assigns the smallest suitable free table and returns an `RSV-` booking reference. The guest portal does not expose the internal table ID or other guests' details. The public booking endpoint is rate limited.

Staff can open **Reservations** from the register to create a booking, optionally choose a specific table, review that day's arrivals, seat a guest, or mark a confirmed booking cancelled or no-show. The table map shows the next reservation. Seating creates the table's root order, and paying its bill marks the reservation completed. Add-on kitchen tickets remain separate while the table still receives one final invoice. Overlapping reservations and walk-in orders that would take a reserved table are rejected by the server.

Set the reservation opening and closing times, slot interval, sitting duration, and advance booking window on each `TRT Outlet`. Defaults are 09:00–23:00, 30-minute slots, a 90-minute sitting, and 30 days ahead. Times use the Frappe site's timezone. This first version books one table per party and provides no automated SMS or email confirmations.

## Register deals, coupons, discounts, and loyalty

- **Menu modifiers:** Menu entries can reference a `TRT Modifier Group`. Guests and staff may select any number of its options, subject to the configured minimum and server checks; selected modifiers and item notes appear on the kitchen ticket.
- **Combos and offers:** Create an ERPNext sale Item with its tax-inclusive Item Price and BOM of raw materials, then add it to `TRT Menu` with `Register Deal Type` set to Combo or Offer. Its menu price override, if set, is the complete deal price. The register puts these items in **Combo deals / Offers**. `Deal Contents` describes the bundle on the register and kitchen ticket. Each deal is one order line at its fixed price; it does not automatically replace separately added components.
- **Coupons:** Managers create an outlet-scoped `TRT Promotion` in Desk with a code, percentage or fixed amount, optional minimum bill, dates, and maximum uses. The cashier enters the code under **Cash payment → Customer & savings**, then selects **Apply to bill**. The server calculates the discount on the complete bill, including all linked table add-on tickets. One submitted POS Invoice creates one `TRT Promotion Redemption`; payment retries reuse the same invoice. A coupon code is available to staff; there is no guest or online coupon entry yet.
- **Manual discounts:** A `TRT Manager` or System Manager can set a percentage or fixed amount and must record a reason. Cashiers cannot change manager discounts. One bill uses either a coupon or a manual discount. Fixed deal prices may still receive a whole-bill discount.
- **Loyalty:** Configure an ERPNext `Loyalty Program`, enroll a named Customer, and set its conversion factor, earning tiers, expense account, and cost center. At checkout, select that Customer, enter a whole number of available points, and apply the bill settings. Points earned and redeemed use ERPNext `Loyalty Point Entry` records. This ERPNext version's POS Invoice payment validator excludes native loyalty credit from its full-payment check, so the app records redemption as an additional tax-aware invoice discount and writes the corresponding negative point ledger entries. Cash due and the submitted invoice total therefore match. Returns and loyalty liability accounting should be reviewed against the business's accounting policy before live use.

All register prices remain tax inclusive; applying a discount reallocates the included tax inside the final price. The same customer and savings settings live on the root order of a table session, regardless of which ticket is open at checkout. The register shows the final amount due before tender. ERPNext Pricing Rules and web-store Coupon Codes are bypassed in this register path; use the controls above for register checkout.

## Import flow

The onboarding page can create an Import Job, upload a **private** CSV/XLSX export, suggest column mappings, preview totals, and import supported master records. The same flow is available in the `TRT Import Job` Desk form. Choose Omega POS, BIM POS, Squirrel Cloud, Squirrel 11, or Generic and map semantic fields to column headers in `mapping_json`, for example:

```json
{"source_id":"id","name":"customer_name","customer_group":"group","territory":"territory"}
```

For BIM POS, use a separate export for each record type. BIM POS product lines and installations can have different columns, so the suggested mappings (including `prodnum` for products) must be checked against the actual file. CSV imports accept comma, semicolon, tab, or pipe delimiters and UTF-8 or Windows-1256 text; XLSX is also supported. For Item imports, select an enabled selling Price List and map `selling_rate` to create ERPNext Item Prices. Preview reports missing fields, invalid rates, duplicate source IDs, counts, and source totals by branch and period. Current import execution supports Item, Customer, and Supplier masters and stores a source-ID ledger. Imported Items are not automatically added to a till menu: each menu item still needs its approved BOM and raw-material recipe. Historical Sale, Return, Payment, Purchase, Stock, Journal, and Employee exports can be inventoried and previewed, but their transaction import and reconciliation are not implemented. No data is synthesized when source exports are unavailable.

## Store gateway

See [gateway/README.md](gateway/README.md). It uses HTTPS, a bearer token, and a durable SQLite event queue. It needs a dedicated Frappe API token, outlet ID, and certificates. It is a prototype: offline prices are provisional, cash is flagged for manager settlement, and real LAN/device certification is outstanding.

## Owner and staff documentation

The complete bilingual operating and role-training manuals live in the Wiki app as the **S&S English** and **S&S العربية** spaces. The checked-in Markdown sources and SVG illustrations are in [`docs/`](docs/). After installing Wiki on a site, publish or refresh the pages with:

```sh
bench --site SITE execute table_remote_till.publish_docs.publish
```

The spaces are readable by signed-in Wiki users and are not open to anonymous guests. Verify the installed page content with `bench --site SITE execute table_remote_till.publish_docs.verify_published`.

## Records, security, and upgrades

S&S operational records include orders, order lines, kitchen tickets, reservations, payment attempts, promotions and redemptions, FX rates, staff assignments, devices, sync events, import jobs, and onboarding runs. ERPNext owns the customer, stock, POS Invoice, and accounting ledgers. Use ERPNext reports and the business's approved end-of-day process to reconcile them.

Staff APIs validate their outlet access on the server. Public booking responses omit other guests and internal table IDs, and the public booking endpoint is rate limited. Keep import files private, assign only the required roles, and back up each site before migrating. After upgrading source, rebuild the four frontends, run `bench build --app table_remote_till`, and migrate every affected site. The S&S rebrand deliberately preserves existing `TRT` identifiers and the Desk workspace route.

## Repository boundaries

This app is its own Git repository inside the local bench. The outer Docker repository ignores `development/`; commit and publish the app repository separately. The preexisting Kotlin starter is outside this Frappe implementation.
