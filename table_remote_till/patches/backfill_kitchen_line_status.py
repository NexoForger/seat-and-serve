"""Preserve existing kitchen progress when item statuses are introduced."""

import frappe


def execute():
	frappe.db.sql("""
		UPDATE `tabTRT Ticket Line` line
		JOIN `tabTRT Kitchen Ticket` ticket ON ticket.name = line.parent
		SET line.status = ticket.status
		WHERE ticket.status IN ('Preparing', 'Ready', 'Served')
			AND (line.status IS NULL OR line.status = '' OR line.status = 'Queued')
	""")
