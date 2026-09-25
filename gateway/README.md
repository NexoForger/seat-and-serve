# Store gateway prototype

Node 22+ and HTTPS are required. Set `TRT_GATEWAY_CERT`, `TRT_GATEWAY_KEY`, `TRT_GATEWAY_TOKEN`, `TRT_GATEWAY_DB`, `TRT_SITE_URL`, `TRT_SITE_API_TOKEN` (`key:secret` for a dedicated Frappe service user), and `TRT_OUTLET`. Start with `npm start`.

The gateway records staff order commands and accepted cash in SQLite before acknowledging them. `/refresh` copies the outlet catalog from Frappe; `/sync` replays pending order commands with the same event IDs. `/state` exposes local orders, shared kitchen tickets, and event conflicts. `/ticket` advances a local ticket with an event ID and expected revision. All routes require `Authorization: Bearer <TRT_GATEWAY_TOKEN>`. Device simulators respond at `/device/simulate`.

This is a development prototype. It does not settle offline cash into POS Invoices, sync local kitchen status, calculate authoritative offline tax, resolve price conflicts, coordinate multiple gateway processes, or certify real devices. Keep it off a live LAN until those controls are implemented and tested.
