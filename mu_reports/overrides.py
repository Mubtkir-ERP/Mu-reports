import frappe
from frappe.desk.query_report import run as original_run

@frappe.whitelist()
def query_report_run(*args, **kwargs):
	res = original_run(*args, **kwargs)
	report_name = kwargs.get("report_name") or (args[0] if args else None)
	if report_name == "General Ledger":
		columns = res.get("columns", [])
		
		# Translate dynamic column labels (e.g., "Debit (SAR)", "Credit (SAR)", "Balance (SAR)")
		for col in columns:
			label = col.get("label") or ""
			if label.startswith("Debit (") and label.endswith(")"):
				currency_code = label[7:-1]
				col["label"] = frappe._("Debit ({0})").format(currency_code)
			elif label.startswith("Credit (") and label.endswith(")"):
				currency_code = label[8:-1]
				col["label"] = frappe._("Credit ({0})").format(currency_code)
			elif label.startswith("Balance (") and label.endswith(")"):
				currency_code = label[9:-1]
				col["label"] = frappe._("Balance ({0})").format(currency_code)

		# Check if party_name already exists in columns
		has_party_name = any(col.get("fieldname") == "party_name" for col in columns)
		
		if not has_party_name:
			# Find the index of the "party" column so we can insert "party_name" right after it
			party_index = -1
			for idx, col in enumerate(columns):
				if col.get("fieldname") == "party":
					party_index = idx
					break
			
			party_name_column = {
				"label": frappe._("Party Name"),
				"fieldname": "party_name",
				"fieldtype": "Data",
				"width": 150
			}
			
			if party_index != -1:
				columns.insert(party_index + 1, party_name_column)
			else:
				columns.append(party_name_column)

		# Translate row contents dynamically (Voucher Type, Party Type, Opening/Total/Closing labels)
		result_rows = res.get("result", [])
		for row in result_rows:
			if isinstance(row, dict):
				if row.get("voucher_type"):
					row["voucher_type"] = frappe._(row["voucher_type"])
				if row.get("party_type"):
					row["party_type"] = frappe._(row["party_type"])
				
				acc_val = row.get("account")
				if acc_val:
					clean_acc = acc_val.strip("'\"")
					if clean_acc in ["Opening", "Total", "Closing (Opening + Total)"]:
						translated_label = frappe._(clean_acc)
						row["account"] = f"'{translated_label}'" if acc_val.startswith("'") else translated_label
		
	return res
