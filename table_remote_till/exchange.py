"""Approved outlet FX for display and immutable receipt snapshots."""
import math
import frappe
from frappe.utils import flt, today


def approved_lbp_rate(outlet):
    rows = frappe.get_all('TRT FX Rate', filters={'outlet': outlet, 'enabled': 1,
        'effective_date': ['<=', today()]}, fields=['lbp_per_usd', 'effective_date', 'approved_by', 'approved_on'],
        order_by='effective_date desc, modified desc', limit=1)
    if not rows or not rows[0].approved_by or not rows[0].approved_on:
        return None
    rate = flt(rows[0].lbp_per_usd)
    return rate if math.isfinite(rate) and rate > 0 else None
