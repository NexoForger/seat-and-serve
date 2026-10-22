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

## Partial payments on tabs

Enable **Allow Partial Payment** on the outlet's ERPNext **POS Profile**. In Till, open a Tab, choose Cash payment, and enter the amount received. The total stays unchanged; **Paid** increases and **Remaining balance** decreases. The tab remains **Partially Paid** until the balance is cleared. The open-tab list and receipt show the remaining balance. Overpayments are rejected; mixed USD/LBP cash uses the approved exchange rate.

The first payment submits the sale invoice, so items, customer and discounts are fixed from that point. Create a separate order for additional sales. Further payments update the original POS Invoice while its shift remains open. After consolidation, they create native Payment Entries against the consolidated Sales Invoice and count in the cash reconciliation of the shift receiving them. They do not create another sale. A previous shift must finish consolidating before an old tab can receive cash in a new shift. Payment terms or foreign receivable accounts that change the allocation require an accountant to receive the payment.

Pull the update, run `bench --site YOUR_SITE migrate`, clear the site cache and restart the bench processes. The committed Till bundle contains the updated UI. Enable the POS Profile option before testing a partial payment. Remote acceptance check: pay $30 on a $100 tab, reopen it and verify $70 remaining; close the shift, receive the $70 in a new shift, and verify the Payment Entry, zero balance and new-shift cash reconciliation.
