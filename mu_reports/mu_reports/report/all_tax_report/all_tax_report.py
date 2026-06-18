# Copyright (c) 2025, Mubtkir and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType
from collections import defaultdict


def execute(filters=None):
	filters = filters or {}

	columns = [
		{
			"label": _("Voucher No"),
			"fieldname": "invoice_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 250,
		},
		{
			"label": _("Voucher Type"),
			"fieldname": "voucher_type",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Party"),
			"fieldname": "party",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("VAT Registration Number"),
			"fieldname": "custom_vat_registration_number",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"label": _("Tax Account"),
			"fieldname": "account",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Item"),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Net Amount"),
			"fieldname": "net_amount",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Tax Amount"),
			"fieldname": "tax_amount",
			"fieldtype": "Currency",
			"width": 150,
		},
	]

	data = []
	gl_rows = get_gl_tax_entries(filters)

	if not gl_rows:
		return columns, []

	# Group by voucher_type dynamically
	grouped = defaultdict(list)
	for row in gl_rows:
		grouped[row["voucher_type"]].append(row)

	total_net = 0
	total_tax = 0

	for voucher_type, rows in grouped.items():
		header_rows = [r for r in rows if r.get("_is_header")]

		sec_net = sum(r.get("net_amount") or 0 for r in header_rows)
		sec_tax = sum(r.get("tax_amount") or 0 for r in header_rows)

		# Section header label row
		data.append({
			"invoice_no": _(voucher_type),
			"net_amount": None,
			"tax_amount": None,
			"indent": 0,
		})

		# Data rows
		for row in rows:
			row.pop("_is_header", None)
			data.append(row)

		# Section total
		data.append({
			"invoice_no": f"{_(voucher_type)} {_('Total')}",
			"net_amount": sec_net,
			"tax_amount": sec_tax,
			"indent": 0,
		})

		# Spacer
		data.append({
			"invoice_no": "",
			"net_amount": None,
			"tax_amount": None,
			"indent": 0,
		})

		total_net += sec_net
		total_tax += sec_tax

	# Grand total
	data.append({
		"invoice_no": _("Grand Total"),
		"net_amount": total_net,
		"tax_amount": total_tax,
		"indent": 0,
	})

	return columns, data


def get_gl_tax_entries(filters):
	"""
	- net_amount: abs(invoice.net_total) — always positive
	- tax_amount: abs(GL debit or credit on tax lines) — always positive
	"""
	if not filters.get("tax_accounts"):
		frappe.throw(_("Please select at least one Tax Account to filter by."))

	tax_accounts = filters["tax_accounts"]
	if isinstance(tax_accounts, str):
		tax_accounts = [a.strip() for a in tax_accounts.split("\n") if a.strip()]

	gle = DocType("GL Entry")

	# ── Step 1: find voucher_nos that touch a tax account ──
	tax_query = (
		frappe.qb.from_(gle)
		.select(gle.voucher_no, gle.voucher_type)
		.distinct()
		.where(gle.is_cancelled == 0)
		.where(gle.account.isin(tax_accounts))
	)

	if filters.get("from_date"):
		tax_query = tax_query.where(gle.posting_date >= filters["from_date"])
	if filters.get("to_date"):
		tax_query = tax_query.where(gle.posting_date <= filters["to_date"])
	if filters.get("party"):
		tax_query = tax_query.where(gle.party == filters["party"])
	if filters.get("invoice_no"):
		tax_query = tax_query.where(gle.voucher_no == filters["invoice_no"])

	voucher_rows = tax_query.run(as_dict=True)

	if not voucher_rows:
		return []

	voucher_nos = [r.voucher_no for r in voucher_rows]

	# ── Step 2: fetch ONLY tax account GL lines ──
	gl_query = (
		frappe.qb.from_(gle)
		.select(
			gle.voucher_no,
			gle.voucher_type,
			gle.posting_date,
			gle.account,
			gle.party,
			gle.party_type,
			gle.debit,
			gle.credit,
		)
		.where(gle.is_cancelled == 0)
		.where(gle.voucher_no.isin(voucher_nos))
		.where(gle.account.isin(tax_accounts))
		.orderby(gle.voucher_no)
		.orderby(gle.posting_date)
	)

	all_rows = gl_query.run(as_dict=True)

	# ── Step 3: aggregate tax amount per voucher ──
	voucher_map = {}

	for row in all_rows:
		vno = row["voucher_no"]

		if vno not in voucher_map:
			voucher_map[vno] = {
				"voucher_no":        vno,
				"voucher_type":      row["voucher_type"],
				"posting_date":      row["posting_date"],
				"party":             "",
				"party_type":        "",
				"tax_amount_raw":    0.0,
				"tax_accounts_used": set(),
			}

		entry = voucher_map[vno]

		if row.get("party") and not entry["party"]:
			entry["party"]      = row["party"]
			entry["party_type"] = row.get("party_type", "")

		# Use whichever side has the value — debit for refunds, credit for collection
		entry["tax_amount_raw"] += row["debit"] + row["credit"]
		entry["tax_accounts_used"].add(row["account"])

	# ── Step 4: bulk-fetch net_total from source documents ──
	by_type = defaultdict(list)
	for vno, v in voucher_map.items():
		by_type[v["voucher_type"]].append(vno)

	net_total_map = {}

	for voucher_type, vnos in by_type.items():
		if voucher_type not in ("Sales Invoice", "Purchase Invoice","Vouchers Entry"):
			for vno in vnos:
				net_total_map[vno] = 0.0
			continue

		party_field = "customer" if voucher_type == "Sales Invoice" else "supplier"

		if voucher_type == "Vouchers Entry":
			fields=["name","total_allocated_amount"]
		else:
			fields=["name", "net_total",party_field]
			
		rows = frappe.get_all(
			voucher_type,
			filters={"name": ["in", vnos], "docstatus": 1},
			fields=fields,
		)

		for r in rows:
			# Always positive — abs handles both invoices and returns
			net_total_map[r["name"]] = abs(r.get("net_total") or r.get("total_allocated_amount") or 0)

			if not voucher_map[r["name"]]["party"]:
				voucher_map[r["name"]]["party"] = r.get(party_field) or ""

	# ── Step 5: bulk-fetch VAT registration numbers ──
	customer_vat_map = {}
	supplier_vat_map = {}

	sales_parties = list({
		v["party"] for v in voucher_map.values()
		if v["voucher_type"] == "Sales Invoice" and v["party"]
	})
	purchase_parties = list({
		v["party"] for v in voucher_map.values()
		if v["voucher_type"] == "Purchase Invoice" and v["party"]
	})

	if sales_parties:
		for r in frappe.get_all(
			"Customer",
			filters={"name": ["in", sales_parties]},
			fields=["name"],
		):
			customer_vat_map[r["name"]] = r.get("custom_vat_registration_number") or ""

	if purchase_parties:
		for r in frappe.get_all(
			"Supplier",
			filters={"name": ["in", purchase_parties]},
			fields=["name"],
		):
			supplier_vat_map[r["name"]] = r.get("custom_vat_registration_number") or ""

	# ── Step 6: bulk-fetch items ──
	items_map = defaultdict(list)

	si_vouchers = [vno for vno, v in voucher_map.items() if v["voucher_type"] == "Sales Invoice"]
	pi_vouchers = [vno for vno, v in voucher_map.items() if v["voucher_type"] == "Purchase Invoice"]

	if si_vouchers:
		for r in frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": ["in", si_vouchers], "docstatus": 1},
			fields=["parent", "item_name"],
		):
			items_map[r["parent"]].append(r["item_name"])

	if pi_vouchers:
		for r in frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": ["in", pi_vouchers], "docstatus": 1},
			fields=["parent", "item_name"],
		):
			items_map[r["parent"]].append(r["item_name"])

	# ── Step 7: build result rows ──
	results = []

	for vno, v in voucher_map.items():
		vat_number = ""
		if v["voucher_type"] == "Sales Invoice":
			vat_number = customer_vat_map.get(v["party"], "")
		elif v["voucher_type"] == "Purchase Invoice":
			vat_number = supplier_vat_map.get(v["party"], "")

		net_amount = net_total_map.get(vno, 0.0)          # always positive
		tax_amount = abs(v["tax_amount_raw"])              # always positive

		# Parent row (indent 1)
		results.append({
			"invoice_no":                     vno,
			"voucher_type":                   v["voucher_type"],
			"posting_date":                   v["posting_date"],
			"party":                          v["party"],
			"account":                        ", ".join(sorted(v["tax_accounts_used"])),
			"item_name":                      "",
			"net_amount":                     net_amount,
			"tax_amount":                     tax_amount,
			"custom_vat_registration_number": vat_number,
			"indent":                         1,
			"_is_header":                     True,
		})

		# Item child rows (indent 2)
		seen_items = set()
		for item_name in items_map.get(vno, []):
			if item_name and item_name not in seen_items:
				seen_items.add(item_name)
				results.append({
					"invoice_no":                     "",
					"voucher_type":                   "",
					"party":                          "",
					"custom_vat_registration_number": "",
					"posting_date":                   None,
					"account":                        "",
					"item_name":                      item_name,
					"net_amount":                     None,
					"tax_amount":                     None,
					"indent":                         2,
				})

	return results
