# Copyright (c) 2025, Mubtkir and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType


def execute(filters=None):
	filters = filters or {}

	columns = [
		{
			"label": _("Voucher Type"),
			"fieldname": "voucher_type",
			"fieldtype": "Data",
			"width": 0,
			"hidden": 1,
		},
		{
			"label": _("Invoice No"),
			"fieldname": "invoice_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 250,
		},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 150},
		{
			"label": _("VAT Registration Number"),
			"fieldname": "custom_vat_registration_number",
			"fieldtype": "Data",
			"width": 180,
		},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 150},
		{"label": _("Item"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Description"), "fieldname": "description", "fieldtype": "Data", "width": 250},
		{"label": _("Net Amount"), "fieldname": "net_amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Tax Amount"), "fieldname": "tax_amount", "fieldtype": "Currency", "width": 130},
	]

	data = []

	sections = {
		_("Sales Invoices"): {"doctype": "Sales Invoice", "is_return": 0},
		_("Sales Returns"): {"doctype": "Sales Invoice", "is_return": 1},
		_("Purchase Invoices"): {"doctype": "Purchase Invoice", "is_return": 0},
		_("Purchase Returns"): {"doctype": "Purchase Invoice", "is_return": 1},
	}

	total_net = 0
	total_tax = 0

	for section_name, params in sections.items():
		invoices = get_invoices(params["doctype"], filters, params["is_return"])
		section_net = sum(row.get("net_amount", 0) for row in invoices if row.get("indent") == 1)
		section_tax = sum(row.get("tax_amount", 0) for row in invoices if row.get("indent") == 1)
		if (params["doctype"] == "Purchase Invoice" and not params["is_return"]) or (
			params["doctype"] == "Sales Invoice" and params["is_return"]
		):
			section_net = -section_net
			section_tax = -section_tax

		data.append({"invoice_no": section_name, "net_amount": None, "tax_amount": None, "indent": 0})
		data.extend(invoices)
		data.append(
			{
				"invoice_no": f"{section_name} Total",
				"net_amount": abs(section_net),
				"tax_amount": abs(section_tax),
				"indent": 0,
			}
		)
		data.append(_empty_row())

		total_net += section_net
		total_tax += section_tax

	# ── Voucher Entries section ──────────────────────────────────────────────
	voucher_section_name = _("Voucher Entries")
	voucher_rows = get_voucher_entries(filters)
	voucher_net = sum(row.get("net_amount", 0) for row in voucher_rows if row.get("indent") == 1)
	voucher_tax = sum(row.get("tax_amount", 0) for row in voucher_rows if row.get("indent") == 1)

	data.append({"invoice_no": voucher_section_name, "net_amount": None, "tax_amount": None, "indent": 0})
	data.extend(voucher_rows)
	data.append(
		{
			"invoice_no": f"{voucher_section_name} Total",
			"net_amount": voucher_net,
			"tax_amount": voucher_tax,
			"indent": 0,
		}
	)
	data.append(_empty_row())

	total_net += voucher_net
	total_tax += voucher_tax

	# ── Journal Entries section ──────────────────────────────────────────────
	journal_section_name = _("Journal Entries")
	journal_rows = get_journal_entries(filters)
	journal_net = sum(row.get("net_amount", 0) for row in journal_rows if row.get("indent") == 1)
	journal_tax = sum(row.get("tax_amount", 0) for row in journal_rows if row.get("indent") == 1)

	if journal_rows:
		data.append({"invoice_no": journal_section_name, "net_amount": None, "tax_amount": None, "indent": 0})
		data.extend(journal_rows)
		data.append(
			{
				"invoice_no": f"{journal_section_name} Total",
				"net_amount": journal_net,
				"tax_amount": journal_tax,
				"indent": 0,
			}
		)
		data.append(_empty_row())

		total_net += journal_net
		total_tax += journal_tax
	# ────────────────────────────────────────────────────────────────────────

	data.append(
		{"invoice_no": _("Grand Total"), "net_amount": total_net, "tax_amount": total_tax, "indent": 0}
	)

	return columns, data


# ── helpers ──────────────────────────────────────────────────────────────────

def _empty_row():
	return {
		"invoice_no": "",
		"party": "",
		"custom_vat_registration_number": "",
		"posting_date": None,
		"item_name": "",
		"description": "",
		"net_amount": None,
		"tax_amount": None,
		"indent": 0,
	}


def get_tax_accounts(filters):
	tax_accounts = filters.get("tax_account")
	if not tax_accounts:
		return []
	if isinstance(tax_accounts, str):
		try:
			import json
			tax_accounts = json.loads(tax_accounts)
		except Exception:
			tax_accounts = [tax_accounts]
	return tax_accounts


def get_voucher_entries(filters):
	"""
	Pull vouchers from GL Entry (excluding Sales/Purchase Invoice).

	Each child row from `Voucher Entry Account` is returned individually.
	When a tax_account filter is applied, rows whose `account` matches
	the filter contribute their `amount` as tax_amount (net_amount = 0).

	Party VAT number:
	  - party_type == "Customer"  → Customer.custom_vat_registration_number
	  - party_type == "Supplier"  → Supplier.tax_id
	"""
	gl  = DocType("GL Entry")
	ve  = DocType("Vouchers Entry")
	vea = DocType("Voucher Entry Account")

	EXCLUDED_VOUCHER_TYPES = ("Sales Invoice", "Purchase Invoice")

	tax_accounts = get_tax_accounts(filters)

	# ── child rows sub-query: individual rows, no aggregation ────────────
	from pypika import Case

	if tax_accounts:
		amounts_sub = (
			frappe.qb.from_(vea)
			.select(
				vea.parent,
				vea.name.as_("vea_name"),
				Case()
					.when(vea.taxes.isnotnull() & (vea.taxes != ""), vea.amount)
					.else_(0)
					.as_("net_total"),
				Case()
					.when(vea.account.isin(tax_accounts), vea.amount)
					.when(vea.taxes.isnotnull() & (vea.taxes != ""), vea.tax_amount)
					.else_(0)
					.as_("tax_total"),
			)
			.where(
				(vea.taxes.isnotnull() & (vea.taxes != "")) | 
				vea.account.isin(tax_accounts)
			)
		)
	else:
		amounts_sub = (
			frappe.qb.from_(vea)
			.select(
				vea.parent,
				vea.name.as_("vea_name"),
				vea.amount.as_("net_total"),
				vea.tax_amount.as_("tax_total"),
			)
			.where(vea.taxes.isnotnull())
			.where(vea.taxes != "")
		)

	# ── customer VAT sub-query ────────────────────────────────────────────
	customer = DocType("Customer")
	cust_sub = (
		frappe.qb.from_(customer)
		.select(
			customer.name.as_("cust_name"),
			customer.customer_name,
			customer.custom_vat_registration_number.as_("cust_vat"),
		)
	)

	# ── supplier tax_id sub-query ─────────────────────────────────────────
	supplier = DocType("Supplier")
	supp_sub = (
		frappe.qb.from_(supplier)
		.select(
			supplier.name.as_("supp_name"),
			supplier.supplier_name,
			supplier.tax_id.as_("supp_tax_id"),
		)
	)

	query = (
		frappe.qb.from_(gl)
		.inner_join(ve).on(ve.name == gl.voucher_no)
		.inner_join(amounts_sub).on(amounts_sub.parent == ve.name)
		.left_join(cust_sub).on(
			(gl.party_type == "Customer") & (cust_sub.cust_name == gl.party)
		)
		.left_join(supp_sub).on(
			(gl.party_type == "Supplier") & (supp_sub.supp_name == gl.party)
		)
		.select(
			gl.voucher_no.as_("invoice_no"),
			gl.posting_date,
			gl.party.as_("party"),
			gl.party_type,
			gl.remarks.as_("remarks"),
			amounts_sub.vea_name,
			amounts_sub.net_total.as_("net_amount"),
			amounts_sub.tax_total.as_("tax_amount"),
			cust_sub.cust_vat.as_("cust_vat"),
			cust_sub.customer_name,
			supp_sub.supp_tax_id.as_("supp_tax_id"),
			supp_sub.supplier_name,
			ve.payment_type,
		)
		.where(gl.is_cancelled == 0)
		.where(gl.voucher_type.notin(EXCLUDED_VOUCHER_TYPES))
		.groupby(gl.voucher_no, amounts_sub.vea_name)
	)

	if filters.get("company"):
		query = query.where(gl.company == filters["company"])
	if filters.get("from_date"):
		query = query.where(gl.posting_date >= filters["from_date"])
	if filters.get("to_date"):
		query = query.where(gl.posting_date <= filters["to_date"])
	if filters.get("invoice_no"):
		query = query.where(gl.voucher_no == filters["invoice_no"])

	if tax_accounts:
		gl_tax = DocType("GL Entry")
		tax_doc_query = (
			frappe.qb.from_(gl_tax)
			.select(gl_tax.voucher_no)
			.where(gl_tax.account.isin(tax_accounts))
			.where(gl_tax.is_cancelled == 0)
			.distinct()
		)
		query = query.where(gl.voucher_no.isin(tax_doc_query))

	rows = query.run(as_dict=True)
	results = []

	for row in rows:
		if row.get("party_type") == "Customer":
			vat_number = row.get("cust_vat") or ""
			party_name = row.get("customer_name") or row.get("party")
		elif row.get("party_type") == "Supplier":
			vat_number = row.get("supp_tax_id") or ""
			party_name = row.get("supplier_name") or row.get("party")
		else:
			vat_number = ""
			party_name = row.get("party")

		net_amount = abs(row.get("net_amount") or 0)
		tax_amount = abs(row.get("tax_amount") or 0)

		if row.get("payment_type") == "Pay":
			net_amount = -net_amount
			tax_amount = -tax_amount

		results.append(
			{
				"invoice_no": row["invoice_no"],
				"voucher_type": "Vouchers Entry",
				"posting_date": row["posting_date"],
				"party": party_name or "",
				"custom_vat_registration_number": vat_number,
				"item_name": "",
				"description": "",
				"net_amount": net_amount,
				"tax_amount": tax_amount,
				"indent": 1,
			}
		)

	return results


def get_invoices(doctype, filters, is_return):
	invoice = DocType(doctype)
	invoice_item = DocType(f"{doctype} Item")

	# Determine party id / name fields
	if doctype == "Sales Invoice":
		party_id_field = invoice.customer
		party_name_field = invoice.customer_name
	else:
		party_id_field = invoice.supplier
		party_name_field = invoice.supplier_name

	query = (
		frappe.qb.from_(invoice)
		.left_join(invoice_item)
		.on(invoice_item.parent == invoice.name)
		.select(
			invoice.name.as_("invoice_no"),
			invoice.posting_date,
			party_id_field.as_("party_id"),
			party_name_field.as_("party"),
			invoice.net_total.as_("net_amount"),
			invoice.total_taxes_and_charges.as_("tax_amount"),
			invoice_item.item_name,
			invoice_item.description,
		)
		.where(invoice.docstatus == 1)
		.where(invoice.is_return == is_return)
	)

	if filters.get("company"):
		query = query.where(invoice.company == filters["company"])
	if filters.get("from_date"):
		query = query.where(invoice.posting_date >= filters["from_date"])
	if filters.get("to_date"):
		query = query.where(invoice.posting_date <= filters["to_date"])
	if filters.get("party"):
		query = query.where(party_id_field == filters["party"])
	if filters.get("invoice_no"):
		query = query.where(invoice.name == filters["invoice_no"])
	if not filters.get("include_non_taxed"):
		query = query.where(invoice.total_taxes_and_charges != 0)

	tax_accounts = get_tax_accounts(filters)
	if tax_accounts:
		gl_tax = DocType("GL Entry")
		tax_doc_query = (
			frappe.qb.from_(gl_tax)
			.select(gl_tax.voucher_no)
			.where(gl_tax.account.isin(tax_accounts))
			.where(gl_tax.is_cancelled == 0)
			.distinct()
		)
		query = query.where(invoice.name.isin(tax_doc_query))

	# ── VAT number: Customer → custom_vat_registration_number
	#               Supplier → tax_id  ──────────────────────────────────────
	if doctype == "Sales Invoice":
		party_master = DocType("Customer")
		query = (
			query
			.left_join(party_master).on(party_master.name == invoice.customer)
			.select(party_master.custom_vat_registration_number)
		)
	else:
		party_master = DocType("Supplier")
		query = (
			query
			.left_join(party_master).on(party_master.name == invoice.supplier)
			.select(party_master.tax_id.as_("custom_vat_registration_number"))
		)

	rows = query.run(as_dict=True)
	results = []
	last_invoice_no = None

	for row in rows:
		if row["invoice_no"] != last_invoice_no:
			inv_row = {
				"invoice_no": row["invoice_no"],
				"voucher_type": doctype,
				"posting_date": row["posting_date"],
				"party": row.get("party") or "",
				"custom_vat_registration_number": row.get("custom_vat_registration_number") or "",
				"item_name": "",
				"description": "",
				"net_amount": abs(row.get("net_amount") or 0),
				"tax_amount": abs(row.get("tax_amount") or 0),
				"indent": 1,
			}
			results.append(inv_row)
			last_invoice_no = row["invoice_no"]

		if row.get("item_name"):
			results.append(
				{
					"item_name": row["item_name"],
					"description": row.get("description") or "",
					"indent": 2,
					"net_amount": None,
					"tax_amount": None,
				}
			)

	return results


def get_journal_entries(filters):
	gl  = DocType("GL Entry")
	customer = DocType("Customer")
	supplier = DocType("Supplier")
	account = DocType("Account")

	cust_sub = (
		frappe.qb.from_(customer)
		.select(
			customer.name.as_("cust_name"),
			customer.customer_name,
			customer.custom_vat_registration_number.as_("cust_vat"),
		)
	)

	supp_sub = (
		frappe.qb.from_(supplier)
		.select(
			supplier.name.as_("supp_name"),
			supplier.supplier_name,
			supplier.tax_id.as_("supp_tax_id"),
		)
	)

	tax_accounts = get_tax_accounts(filters)

	# Subquery to aggregate tax amounts per voucher
	gl_tax = DocType("GL Entry")
	tax_subquery = (
		frappe.qb.from_(gl_tax)
		.inner_join(account).on(gl_tax.account == account.name)
		.select(
			gl_tax.voucher_no,
			frappe.qb.functions("SUM", gl_tax.credit - gl_tax.debit).as_("tax_total")
		)
		.where(gl_tax.is_cancelled == 0)
		.where(gl_tax.voucher_type == "Journal Entry")
		.groupby(gl_tax.voucher_no)
	)

	if tax_accounts:
		tax_subquery = tax_subquery.where(gl_tax.account.isin(tax_accounts))
	else:
		tax_subquery = tax_subquery.where(account.account_type.isin(["Tax", "Charge", "Duties and Taxes", "Tax / Duty"]))

	query = (
		frappe.qb.from_(gl)
		.left_join(cust_sub).on((gl.party_type == "Customer") & (cust_sub.cust_name == gl.party))
		.left_join(supp_sub).on((gl.party_type == "Supplier") & (supp_sub.supp_name == gl.party))
		.inner_join(tax_subquery).on(tax_subquery.voucher_no == gl.voucher_no)
		.select(
			gl.voucher_no.as_("invoice_no"),
			gl.posting_date,
			gl.party.as_("party"),
			gl.party_type,
			gl.remarks,
			frappe.qb.functions("SUM", gl.debit - gl.credit).as_("party_amount"),
			tax_subquery.tax_total.as_("tax_amount"),
			cust_sub.cust_vat.as_("cust_vat"),
			cust_sub.customer_name,
			supp_sub.supp_tax_id.as_("supp_tax_id"),
			supp_sub.supplier_name,
		)
		.where(gl.is_cancelled == 0)
		.where(gl.voucher_type == "Journal Entry")
		.groupby(gl.voucher_no, gl.party, gl.posting_date, gl.party_type, gl.remarks, cust_sub.cust_vat, cust_sub.customer_name, supp_sub.supp_tax_id, supp_sub.supplier_name, tax_subquery.tax_total)
	)

	if filters.get("company"):
		query = query.where(gl.company == filters["company"])
	if filters.get("from_date"):
		query = query.where(gl.posting_date >= filters["from_date"])
	if filters.get("to_date"):
		query = query.where(gl.posting_date <= filters["to_date"])
	if filters.get("invoice_no"):
		query = query.where(gl.voucher_no == filters["invoice_no"])

	if tax_accounts:
		gl_tax_filter = DocType("GL Entry")
		tax_doc_query = (
			frappe.qb.from_(gl_tax_filter)
			.select(gl_tax_filter.voucher_no)
			.where(gl_tax_filter.account.isin(tax_accounts))
			.where(gl_tax_filter.is_cancelled == 0)
			.distinct()
		)
		query = query.where(gl.voucher_no.isin(tax_doc_query))

	rows = query.run(as_dict=True)
	
	# Deduplicate: if a voucher has some lines with a party and some without, only keep the ones with a party
	voucher_has_party = set()
	for row in rows:
		if row.get("party"):
			voucher_has_party.add(row["invoice_no"])
			
	filtered_rows = []
	seen_no_party = set()
	for row in rows:
		v_no = row["invoice_no"]
		if row.get("party"):
			filtered_rows.append(row)
		elif v_no not in voucher_has_party and v_no not in seen_no_party:
			filtered_rows.append(row)
			seen_no_party.add(v_no)

	results = []

	for row in filtered_rows:
		if row.get("party_type") == "Customer":
			vat_number = row.get("cust_vat") or ""
			party_name = row.get("customer_name") or row.get("party")
		elif row.get("party_type") == "Supplier":
			vat_number = row.get("supp_tax_id") or ""
			party_name = row.get("supplier_name") or row.get("party")
		else:
			vat_number = ""
			party_name = row.get("party")

		party_amount = abs(row.get("party_amount") or 0)
		tax_amount = abs(row.get("tax_amount") or 0)
		
		if party_name:
			net_amount = abs(party_amount - tax_amount)
		else:
			net_amount = 0

		results.append(
			{
				"invoice_no": row["invoice_no"],
				"voucher_type": "Journal Entry",
				"posting_date": row["posting_date"],
				"party": party_name or "",
				"custom_vat_registration_number": vat_number,
				"item_name": "",
				"description": "",
				"net_amount": net_amount,
				"tax_amount": tax_amount,
				"indent": 1,
			}
		)

	return results