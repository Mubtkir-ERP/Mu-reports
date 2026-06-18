// Copyright (c) 2025, Mubtkir and contributors
// For license information, please see license.txt

frappe.query_reports["Tax Report"] = {
	filters: [
		{
			"fieldname": "company",
			"label": "Company",
			"fieldtype": "Link",
			"options": "Company",
			"default": "",
			"reqd": 0
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "invoice_type",
			label: __("Invoice Type"),
			fieldtype: "Select",
			options: "Sales Invoice\nPurchase Invoice",
			default: "Sales Invoice",
			reqd: 1,
			on_change: function () {
				let type = frappe.query_report.get_filter_value("invoice_type");

				frappe.query_report.set_filter_value("party", "");
				frappe.query_report.get_filter("party").df.options =
					type === "Sales Invoice" ? "Customer" : "Supplier";
				frappe.query_report.refresh();

				frappe.query_report.set_filter_value("invoice_no", "");
				frappe.query_report.get_filter("invoice_no").df.options = type;
				frappe.query_report.refresh();
			},
		},
		{
			fieldname: "party",
			label: __("Party"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "item",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "invoice_no",
			label: __("Invoice No"),
			fieldtype: "Link",
			options: "Sales Invoice",
			get_query: function () {
				let invoice_type = frappe.query_report.get_filter_value("invoice_type");
				return {
					filters: {
						docstatus: 1,
					},
				};
			},
		},
		{
			fieldname: "tax_account",
			label: __("Tax Accounts"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Account", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "include_non_taxed",
			label: __("Include Non-Taxed Invoices"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		let formatted_value = default_formatter(value, row, column, data);

		// Hide the negative sign for Voucher Entry data rows
		if (
			data &&
			data.indent === 1 &&
			data.voucher_type === "Vouchers Entry" &&
			(column.fieldname === "net_amount" || column.fieldname === "tax_amount") &&
			value < 0
		) {
			// Re-format with absolute value to hide the minus sign
			formatted_value = default_formatter(Math.abs(value), row, column, data);
		}

		if (data && data.indent !== undefined) {
			formatted_value = `<div style="padding-left:${data.indent * 20
				}px;">${formatted_value}</div>`;
		}

		if (data && data.invoice_no && !data.invoice_no.includes("Total") && data.indent === 0) {
			formatted_value = `<div style="font-weight:bold; color:#000;">${formatted_value}</div>`;
		}

		if (data && data.invoice_no && data.invoice_no.includes("Total")) {
			formatted_value = `<div style="font-weight:bold; color:#1f77b4; text-align:right;">${formatted_value}</div>`;
		}

		if (data && !data.invoice_no && !data.party && !data.item_name) {
			return "";
		}

		return formatted_value;
	},
};
