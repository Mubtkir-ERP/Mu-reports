# Copyright (c) 2025, Mubtkir and contributors
# For license information, please see license.txt


import frappe
from frappe import _


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Data", "width": 250},
		{"fieldname": "total_amount", "label": _("Total Amount"), "fieldtype": "Currency", "width": 250},
		{"fieldname": "total_tax", "label": _("Total Tax"), "fieldtype": "Currency", "width": 250},
	]


def get_data(filters):
	conditions = []
	if filters.get("company"):
		conditions.append("gl.company = %(company)s")
	if filters.get("from_date") and filters.get("to_date"):
		conditions.append("gl.posting_date BETWEEN %(from_date)s AND %(to_date)s")
	if filters.get("account"):
		conditions.append("gl.account = %(account)s")
	else:
		conditions.append("acc.account_type = 'Tax'")

	where_clause = " AND ".join(conditions)

	query = f"""
        SELECT
            gl.voucher_type AS document_type,
            gl.voucher_no,
            gl.voucher_subtype,
            gl.posting_date,
            gl.account,
            gl.credit,
            gl.debit,
            gl.remarks
        FROM `tabGL Entry` gl
        INNER JOIN `tabAccount` acc ON gl.account = acc.name
        WHERE gl.is_cancelled != 1
        {f"AND {where_clause}" if where_clause else ""}
        ORDER BY gl.posting_date DESC, gl.voucher_type, gl.voucher_no
    """

	tax_gl_entries = frappe.db.sql(query, filters, as_dict=True)

	categorized = {
		"Sales Invoice": [],
		"Credit Note": [],
		"Purchase Invoice": [],
		"Debit Note": [],
		"Journal Entry": [],
	}

	for row in tax_gl_entries:
		subtype = row.get("voucher_subtype") or row.get("document_type")
		if subtype in categorized:
			categorized[subtype].append(row)

	data = []

	# Sales Invoice
	sales_invoice_nos = [entry["voucher_no"] for entry in categorized["Sales Invoice"]]
	grand_total = 0.0
	if sales_invoice_nos:
		result = frappe.db.sql(
			"""
            SELECT SUM(grand_total)
            FROM `tabSales Invoice`
            WHERE name IN %(names)s AND is_return = 0
        """,
			{"names": tuple(sales_invoice_nos)},
			as_dict=False,
		)
		grand_total = result[0][0] if result and result[0][0] else 0.0

	sales_tax = sum(e.get("credit", 0) or 0 for e in categorized["Sales Invoice"])
	data.append(
		{"document_type": _("Sales Invoice"), "total_amount": (grand_total / 1.15), "total_tax": sales_tax}
	)

	# Credit Note
	credit_note_nos = [entry["voucher_no"] for entry in categorized["Credit Note"]]
	credit_total = 0.0
	if credit_note_nos:
		result = frappe.db.sql(
			"""
            SELECT SUM(grand_total)
            FROM `tabSales Invoice`
            WHERE name IN %(names)s AND is_return = 1
        """,
			{"names": tuple(credit_note_nos)},
			as_dict=False,
		)
		credit_total = result[0][0] if result and result[0][0] else 0.0

	credit_tax = sum(e.get("debit", 0) or 0 for e in categorized["Credit Note"])
	data.append(
		{"document_type": _("Credit Note"), "total_amount": (credit_total / 1.15), "total_tax": credit_tax}
	)

	# Purchase Invoice
	purchase_invoice_nos = [entry["voucher_no"] for entry in categorized["Purchase Invoice"]]
	purchase_total = 0.0
	if purchase_invoice_nos:
		result = frappe.db.sql(
			"""
            SELECT SUM(grand_total)
            FROM `tabPurchase Invoice`
            WHERE name IN %(names)s AND is_return = 0
        """,
			{"names": tuple(purchase_invoice_nos)},
			as_dict=False,
		)
		purchase_total = result[0][0] if result and result[0][0] else 0.0

	purchase_tax = sum(e.get("debit", 0) or 0 for e in categorized["Purchase Invoice"])
	data.append(
		{
			"document_type": _("Purchase Invoice"),
			"total_amount": (purchase_total / 1.15),
			"total_tax": purchase_tax,
		}
	)

	# Debit Note
	debit_note_nos = [entry["voucher_no"] for entry in categorized["Debit Note"]]
	debit_total = 0.0
	if debit_note_nos:
		result = frappe.db.sql(
			"""
            SELECT SUM(grand_total)
            FROM `tabPurchase Invoice`
            WHERE name IN %(names)s AND is_return = 1
        """,
			{"names": tuple(debit_note_nos)},
			as_dict=False,
		)
		debit_total = result[0][0] if result and result[0][0] else 0.0

	debit_tax = sum(e.get("credit", 0) or 0 for e in categorized["Debit Note"])
	data.append(
		{"document_type": _("Debit Note"), "total_amount": (debit_total / 1.15), "total_tax": debit_tax}
	)

	# Journal Entry
	journal_tax = sum(e.get("debit", 0) or 0 for e in categorized["Journal Entry"])
	data.append({"document_type": _("Journal Entry"), "total_amount": "", "total_tax": (journal_tax / 0.15)})

	# Final Total Calculation
	net_sales_tax = sales_tax - credit_tax
	adjusted_purchase_tax = purchase_tax - debit_tax + journal_tax
	adjusted_diff = net_sales_tax - adjusted_purchase_tax

	# Append final summary row
	data.append({"document_type": _("Outstanding Tax"), "total_amount": "", "total_tax": adjusted_diff})

	return data
