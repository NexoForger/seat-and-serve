"""Collect an invoiced tab without re-invoicing its items or recognizing cash twice."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import frappe
from frappe.utils import flt, get_datetime, now_datetime


def payment_amounts(tenders, base, fx, modes):
    quantum = Decimal('0.01') if base == 'USD' else Decimal('1')
    rows = []
    for tender in tenders:
        try:
            if not isinstance(tender, dict) or isinstance(tender.get('amount'), bool):
                raise ValueError
            currency, mode = tender.get('currency'), tender.get('mode_of_payment')
            amount = Decimal(str(tender.get('amount')))
            if not amount.is_finite() or amount <= 0 or mode not in modes or currency not in ('USD', 'LBP'):
                raise ValueError
            if currency != base and (base not in ('USD', 'LBP') or not fx or fx <= 0):
                raise ValueError
            converted = amount if currency == base else amount / Decimal(str(fx)) if base == 'USD' else amount * Decimal(str(fx))
            converted = converted.quantize(quantum, rounding=ROUND_HALF_UP)
            if converted <= 0:
                raise ValueError
        except (ValueError, InvalidOperation, TypeError, ZeroDivisionError):
            frappe.throw('Enter positive cash payments in enabled modes and USD/LBP with an approved rate')
        rows.append(dict(mode=mode, currency=currency, amount=float(amount), base_amount=float(converted)))
    if not rows:
        frappe.throw('Enter a payment amount')
    return rows


def validate_amount(amount, due, currency, allow_partial):
    quantum = Decimal('0.01') if currency == 'USD' else Decimal('1')
    try:
        amount = Decimal(str(amount)).quantize(quantum, rounding=ROUND_HALF_UP)
        due = Decimal(str(due)).quantize(quantum, rounding=ROUND_HALF_UP)
        if not amount.is_finite() or amount <= 0 or amount > due:
            raise ValueError
    except (ValueError, InvalidOperation):
        frappe.throw('Payment must be positive and cannot exceed the remaining balance')
    if amount < due and not allow_partial:
        frappe.throw('Enable Allow Partial Payment in this outlet\'s POS Profile before accepting a partial tab payment')
    return float(due - amount)


def balance(order, invoice):
    """POS cash is native paid_amount; post-consolidation receipts are native Payment Entries."""
    total = flt(invoice.rounded_total or invoice.grand_total)
    paid = flt(invoice.paid_amount)
    entries = frappe.get_all('TRT Payment Attempt', filters={'order': order.name,
        'status': 'Captured', 'payment_entry': ['is', 'set']}, fields=['payment_entry', 'base_amount'])
    for row in entries:
        if frappe.db.get_value('Payment Entry', row.payment_entry, 'docstatus') == 1:
            paid += flt(row.base_amount)
    return dict(paid_amount=paid, amount_due=max(0, total-paid))


def shift_receipts(opening):
    """These receipts are already in GL and must only be added to drawer reconciliation."""
    return frappe.db.sql('''SELECT p.provider AS mode_of_payment, SUM(p.base_amount) AS amount
        FROM `tabTRT Payment Attempt` p INNER JOIN `tabPayment Entry` e ON e.name=p.payment_entry
        WHERE p.pos_opening_entry=%s AND p.status='Captured' AND e.docstatus=1
        GROUP BY p.provider''', opening, as_dict=True)


def receive(order, outlet, tenders, event_id, expected_revision):
    from table_remote_till.api import _as_admin, _snapshot
    from table_remote_till.exchange import approved_lbp_rate
    from table_remote_till.shifts import active_opening
    from table_remote_till.printer_api import schedule_cash_drawer
    import json
    if order.channel != 'Tab' or order.status != 'Partially Paid' or int(expected_revision) != order.revision:
        frappe.throw('Tab changed; refresh before taking payment')
    frappe.db.sql('SELECT name FROM `tabPOS Profile` WHERE name=%s FOR UPDATE', outlet.pos_profile)
    profile = frappe.get_doc('POS Profile', outlet.pos_profile)
    opening = active_opening(profile.name)
    if profile.disabled or profile.company != outlet.company or not opening:
        frappe.throw('Open a valid POS shift before taking payment')
    if frappe.db.exists('POS Closing Entry', {'pos_opening_entry': opening, 'docstatus': 1}):
        frappe.throw('This shift is closing; wait for the next shift')
    frappe.db.sql('SELECT name FROM `tabPOS Invoice` WHERE name=%s FOR UPDATE', order.pos_invoice)
    invoice = frappe.get_doc('POS Invoice', order.pos_invoice)
    if (invoice.docstatus != 1 or invoice.is_return or invoice.company != outlet.company
        or invoice.pos_profile != profile.name or invoice.currency != order.currency):
        frappe.throw('This tab invoice cannot receive a payment')
    current = balance(order, invoice)
    modes = {row.mode_of_payment for row in profile.payments
        if frappe.db.get_value('Mode of Payment', row.mode_of_payment, 'type') == 'Cash'}
    fx = approved_lbp_rate(outlet.name)
    rows = payment_amounts(tenders, order.currency, fx, modes)
    total = sum(row['base_amount'] for row in rows)
    remaining = validate_amount(total, current['amount_due'], order.currency, profile.allow_partial_payment)
    amounts = {}
    for row in rows:
        amounts[row['mode']] = amounts.get(row['mode'], 0) + row['base_amount']
    entries = {}
    cashier = frappe.session.user
    with _as_admin():
        if invoice.consolidated_invoice:
            from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
            from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account
            frappe.db.sql('SELECT name FROM `tabSales Invoice` WHERE name=%s FOR UPDATE', invoice.consolidated_invoice)
            for mode, amount in amounts.items():
                account = get_bank_cash_account(mode, outlet.company).get('account')
                if not account or frappe.db.get_value('Account', account, 'account_currency') != order.currency:
                    frappe.throw('Configure a cash account in the outlet selling currency')
                entry = get_payment_entry('Sales Invoice', invoice.consolidated_invoice,
                    party_amount=amount, bank_account=account, bank_amount=amount)
                allocated = sum(flt(ref.allocated_amount) for ref in entry.references
                    if ref.reference_doctype == 'Sales Invoice' and ref.reference_name == invoice.consolidated_invoice)
                if (entry.payment_type != 'Receive' or entry.paid_from_account_currency != order.currency
                    or abs(flt(entry.paid_amount) - amount) > 0.001
                    or abs(flt(entry.received_amount) - amount) > 0.001 or abs(allocated - amount) > 0.001):
                    frappe.throw('Invoice payment terms or account currencies require an accountant to receive this payment')
                entry.mode_of_payment = mode
                entry.remarks = f'Tab {order.order_number}; cashier {cashier}; event {event_id}'
                entry.insert(ignore_permissions=True)
                entry.flags.ignore_permissions = True
                entry.submit()
                entries[mode] = entry.name
        else:
            opened = frappe.db.get_value('POS Opening Entry', opening, 'period_start_date')
            if opened and get_datetime(invoice.creation) < get_datetime(opened):
                frappe.throw('Wait for the previous shift to finish consolidating this tab')
            invoice.update_payments([dict(mode_of_payment=mode, amount=amount) for mode, amount in amounts.items()])
    for index, row in enumerate(rows):
        frappe.get_doc({'doctype': 'TRT Payment Attempt', 'order': order.name, 'mode': 'Cash',
            'currency': row['currency'], 'amount': row['amount'], 'exchange_rate': fx or 1,
            'base_amount': row['base_amount'], 'pos_opening_entry': opening,
            'payment_entry': entries.get(row['mode']), 'status': 'Captured', 'provider': row['mode'],
            'idempotency_key': f'{event_id}:{index}', 'pos_invoice': invoice.name,
            'order_revision': order.revision}).insert(ignore_permissions=True)
    order.status = 'Settled' if remaining == 0 else 'Partially Paid'
    order.revision += 1
    order.save(ignore_permissions=True)
    frappe.get_doc({'doctype': 'TRT Sync Event', 'event_id': event_id, 'outlet': order.outlet,
        'register': order.register, 'order': order.name, 'event_type': 'cash_checkout',
        'payload_json': json.dumps(tenders), 'status': 'Applied', 'received_at': now_datetime()}).insert(ignore_permissions=True)
    schedule_cash_drawer(order, invoice.name, tenders, payment_id=event_id)
    return _snapshot(order)
