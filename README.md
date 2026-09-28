# Table Remote Till

Frappe v16 app for ERPNext and HRMS, with Doppio-generated Vue 3/TypeScript staff till, kitchen, kiosk, and public menu frontends. Each business must have its own Frappe site and database. Outlets, registers, and branches live inside that site.

## Current development status

The app installs and migrates on the existing local bench. The four routes `/till`, `/kitchen`, `/kiosk`, and `/menu` build and serve. The ERPNext Desk workspace at `/desk/table-remote-till` exposes every parent app DocType; the four child DocTypes are edited inside their parent forms. Versioned DocTypes cover business setup, onboarding runs, outlets, registers, tables, menus, orders, kitchen tickets, payments, devices, FX rates, sync events, and import jobs. Staff and guest order commands are server priced, idempotent, and revision checked. A development sandbox can simulate guest checkout. Exact cash and mixed USD/LBP tender can create an ERPNext POS Invoice when the site has an open POS session, approved FX rate, stock, and payment modes. The SQLite gateway prototype accepts local staff commands and records cash for later manager reconciliation.

This is **not ready for live sales**. Card/online provider capture, real device drivers, partial refunds, split bills, weighed items, modifier accounting, full historical transaction migration, offline cash settlement, multi-device gateway recovery certification, complete offline PWA behavior, Windows/macOS packaging, and branch-scoped Desk permissions remain to be implemented. A settled order can now receive one full ERPNext POS Invoice return through the idempotent `return_order` command; partial line returns still need their own quantity and stock policy. The web manifests provide an installable shell, while offline commands currently require the separate gateway prototype. Sandbox capture charges no money and is available only when `developer_mode` and `allow_sandbox_payments` are both enabled. Do not enable sandbox payments on a live site.

## Install and build

Install ERPNext and HRMS in a Frappe v16 bench, then add this repository as `apps/table_remote_till` and run:

```sh
bench --site BUSINESS_SITE install-app table_remote_till
cd apps/table_remote_till
yarn install
yarn build
```

`tools/provision_site.py BUSINESS_SITE` creates a separate site and installs all three apps. It reads `TRT_DB_ROOT_PASSWORD` and `TRT_SITE_ADMIN_PASSWORD` from the environment. Run `--dry-run` to inspect the command. Complete ERPNext Company/chart of accounts setup, then open the app workspace or `/onboarding`.

The guided onboarding page selects a company, outlet, branch, register, channels, cash mode, and accounting references. It previews every operation and applies them together: business setup, branch, warehouse, selling list, walk-in customer, POS Profile, outlet, register, manager assignment, starter menu, and restaurant floor/station. Optional explicit choices enable LBP, record an approved FX rate, and switch site-wide POS Settings to POS Invoice mode. Each run has a UUID idempotency key and a `TRT Onboarding Run` audit record. The **Seed sample data** checkbox adds clearly labeled non-stock items, item prices, menu entries, and a sample table; remove them before live use. Tax/payroll approvals, real items, shift opening, live payments, device certification, and historical reconciliation remain separate steps.

The existing development site has POS Settings set to Sales Invoice mode, an outdated open POS session, and LBP disabled. Those must be configured before cash checkout there. The smoke check changes them only inside a rolled-back transaction; it does not change the lasting site configuration.

## Development checks

```sh
bench --site SITE execute table_remote_till.smoke.run
bench --site SITE execute table_remote_till.smoke.migration_run
bench --site SITE execute table_remote_till.smoke.onboarding_run
bench --site SITE execute table_remote_till.smoke.onboarding_retail_run
bench --site SITE execute table_remote_till.smoke.workspace_run
cd apps/table_remote_till/gateway && npm test
```

The smoke checks insert temporary test records and roll back. Frontend type checks run with `vue-tsc --noEmit` inside each of `till`, `kitchen`, `kiosk`, and `menu`.

## Import flow

The onboarding page can create an Import Job, upload a **private** CSV/XLSX export, suggest column mappings, preview totals, and import supported master records. The same flow is available in the `TRT Import Job` Desk form. Choose Omega POS, Squirrel Cloud, Squirrel 11, or Generic and map semantic fields to column headers in `mapping_json`, for example:

```json
{"source_id":"id","name":"customer_name","customer_group":"group","territory":"territory"}
```

Preview reports missing fields, duplicate source IDs, counts, and source totals by branch and period. Current import execution supports Item, Customer, and Supplier masters and stores a source-ID ledger. Historical Sale, Return, Payment, Purchase, Stock, Journal, and Employee exports can be inventoried and previewed, but their transaction import and reconciliation are not implemented. No data is synthesized when source exports are unavailable.

## Store gateway

See [gateway/README.md](gateway/README.md). It uses HTTPS, a bearer token, and a durable SQLite event queue. It needs a dedicated Frappe API token, outlet ID, and certificates. It is a prototype: offline prices are provisional, cash is flagged for manager settlement, and real LAN/device certification is outstanding.

## Repository boundaries

This app is its own Git repository inside the local bench. The outer Docker repository ignores `development/`; commit and publish the app repository separately. The preexisting Kotlin starter is outside this Frappe implementation.
