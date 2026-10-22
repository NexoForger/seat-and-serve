# Shift closing

S&S saves a submitted POS Closing Entry with the counted cash, then runs ERPNext invoice consolidation on the `long` worker queue after that entry commits. This is required because ERPNext's consolidation performs its own rollback and commit. Running consolidation inside submission could roll back the closing entry itself and replace the original error with `Could not find Reference Name: POS-CLO-...`.

The cashier sees **Queued** while processing. Reopen **Close shift** and select **Refresh status** to see the result. If consolidation fails, the original failure message is displayed with the saved cash counts and the existing closing-entry link. After correcting the reported configuration or stock-data issue, select **Retry closing with saved counts**. Retry uses the same closing entry and invoices; it does not submit another cash count or record another payment. Completed or queued entries are not queued again.

The existing ERPNext stock valuation, invoice, and accounting rules still determine whether consolidation can succeed. A zero valuation rate is the item's stock cost, not its selling price. The fix preserves the actual consolidation exception instead of displaying the last warning and a missing-reference error; inventory data may still need correction on the site.

After pulling this update, clear the site cache and restart the Frappe processes so the new `POS Closing Entry` controller extension loads. The updated Till bundle is included. Ensure a worker is listening on the `long` queue; otherwise the closing remains **Queued**. `bench --site YOUR_SITE doctor` helps inspect worker and scheduler state.

```sh
bench --site YOUR_SITE migrate
bench --site YOUR_SITE clear-cache
bench restart
```

Regression checks:

```sh
python3 -m unittest discover -s tests -p 'test_shifts.py' -v
python3 -m unittest discover -s tests -p 'test_pos_closing.py' -v
```
