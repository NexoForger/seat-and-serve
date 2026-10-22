# Receipt printers and cash drawers

The ERP can be hosted remotely. Run the included outbound print agent on the PC/Pi near the printer. It polls the ERP over HTTPS, then sends raw ESC/POS bytes to a USB printer or a LAN printer reachable from that PC/Pi. The ERP never needs an inbound connection to that PC/Pi, and it does not need to share its LAN. No browser plugin is needed.

The cash drawer stays plugged into the printer's RJ11/RJ12 drawer port. The printer must support the ESC/POS drawer pulse; the connector alone does not guarantee compatibility.

## Update the remote ERP

From the bench's `apps/table_remote_till` repository, pull the change. Then, from the bench directory:

```sh
bench --site YOUR_SITE migrate
bench --site YOUR_SITE clear-cache
bench restart
```

This adds **TRT Print Job** and loads the printer configuration form. Updated Till assets are included in Git. To rebuild them yourself, run `cd apps/table_remote_till/till && yarn install && yarn build`.

## Configure the remote print agent

1. Create a dedicated Frappe service user with **TRT Cashier** role, API key/secret, and an enabled **TRT Staff Assignment** granting Till access only to the required outlet.
2. Bind an agent name to that user in the ERP's private site configuration:

```json
{"trt_print_agents": {"register-1": "printer-agent@example.com"}}
```

3. On the printer PC/Pi, pull the same repository. The agent needs Python 3.9+ and no extra Python packages. For USB on Mac/Linux/Pi, install CUPS and configure a raw ESC/POS queue (`lpstat -v` lists queues). On Windows, install the printer and use its Windows queue name; the agent uses the Windows RAW spooler.
4. Keep the dedicated user's `api_key:api_secret` in the `TRT_PRINT_AGENT_TOKEN` environment variable on that host. Start the agent using either a USB queue or a LAN destination accessible from that host:

```sh
export TRT_PRINT_AGENT_TOKEN='YOUR_API_KEY:YOUR_API_SECRET'
python3 tools/print_agent.py --site https://YOUR_ERP_SITE --outlet OUTLET_ID --agent register-1 --allow-usb Xprinter_USB
```

For a LAN printer near that PC/Pi:

```sh
python3 tools/print_agent.py --site https://YOUR_ERP_SITE --outlet OUTLET_ID --agent register-1 --allow-lan 192.168.0.46:9100
```

On PowerShell, set the environment variable with `$env:TRT_PRINT_AGENT_TOKEN = 'YOUR_API_KEY:YOUR_API_SECRET'`, then use `python tools/print_agent.py ...`. Quote queue names containing spaces. Multiple `--allow-usb` and `--allow-lan` flags are supported. Only those destinations may receive jobs. Run one agent per agent name, and keep its SQLite journal persistent. The default journal is `~/.local/share/seat-and-serve/print-agent.sqlite`; change it with `--journal`. Use your host's service manager to keep the agent running.

## Configure and test the device

1. In ERP Desk, create or open **TRT Device** with Kind **Receipt Printer**. Choose its outlet and optional register, and enable it.
2. Select **Configure printer**. Set Printer host to **Local PC / Pi agent**, enter `register-1`, and choose **LAN / Ethernet** or **USB**. Enter either the printer IP and port, or the OS USB queue name matching the agent's allowlist. Save.
3. **Print test page** queues a marked `TEST PRINT - NO SALE` receipt. It creates no invoice/payment and sends no drawer pulse. View the result in **TRT Print Job**.
4. Enable the cash drawer in **Configure printer**. Default output 1 uses connector pin 2 with a 100 ms pulse; output 2 uses pin 5. Pulse duration must be an even number from 20 to 250 ms. Save and select **Test cash drawer**. It sends only the pulse, so the drawer opens without a receipt. Hardware tests require manager write access to the device and manager access to its outlet. Manual drawer tests are logged to `table_remote_till_devices`.

Equivalent device Settings JSON:

```json
{"print_agent":"register-1", "auto_cut":true, "drawer_enabled":true, "drawer_pin":0, "drawer_pulse_ms":100}
```

The Driver is `escpos_tcp` for LAN, `escpos_usb` for USB; Address is the IP/port or local OS queue name respectively. Leave Register blank for an outlet-wide printer; a matching register takes priority. Disable any printer-driver setting that opens the drawer automatically on every print.

If the ERP itself can directly reach the printer, select **ERP server**. An empty/missing `print_agent` preserves the existing direct printing behavior. Direct USB needs the queue and `lp` on the ERP host (or an installed Windows queue), so use the agent when ERP is in Docker or remote from the printer host.

## Payment and delivery rules

A confirmed cash checkout submits the POS Invoice and records one drawer job for that invoice in the same database transaction. The agent cannot see it until the payment commits. Duplicate checkout requests, multiple table tickets on one invoice, kitchen orders, online payments, receipt reprints, and bills covered entirely by loyalty points do not create another drawer action. Print failure never undoes payment.

For agent jobs, `Pending` means waiting for the PC/Pi; `Claimed` means reserved for one delivery attempt; `Sent` means LAN bytes were written; `Queued` means the OS spooler accepted the USB job. Neither state proves physical paper output or drawer opening. `Unknown` means an error, an expired drawer action, or uncertain delivery. Drawer jobs expire after 30 seconds while waiting for the agent. A claimed job is never reassigned or automatically sent again. The agent durably records dispatch before touching hardware and retries only its acknowledgement if the ERP connection fails.

USB spoolers may delay jobs while a printer is offline, including a drawer pulse already accepted by the spooler. Check the physical drawer and OS queue before issuing another test. Reprints are explicit new receipt jobs marked REPRINT. There is no automatic retry for an unknown drawer result. Direct ERP-server drawer actions are tracked in **TRT Sync Event**, with the same one-action-per-invoice rule.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_print*.py' -v
python3 -m unittest discover -s tests -p 'test_cash_drawer.py' -v
python3 -m unittest discover -s tests -p 'test_receipt_printing.py' -v
```

These tests use loopback sockets, fake spoolers, simulated payment commits, and an agent journal. They do not contact physical printers. Verify paper and drawer behavior separately on each deployed model.
