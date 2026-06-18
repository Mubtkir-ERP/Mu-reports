// Copyright (c) 2026, Mubtkir and contributors
// For license information, please see license.txt

frappe.query_reports["All Tax Report"] = {
	"filters": [
		{
			"fieldname": "from_date",
			"label": "From Date",
			"fieldtype": "Date",
			"default": "Today"
		},
		{
			"fieldname": "to_date",
			"label": "To Date",
			"fieldtype": "Date",
			"default": "Today"
		},
		{
			fieldname: "tax_accounts",
			label: __("Tax Accounts"),
			fieldtype: "MultiSelectList",
			options: "Account",
			get_data: function (txt) {
				return frappe.db.get_link_options("Account", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			"fieldname": "party",
			"label": "Party",
			"fieldtype": "Data"
		},
		{
			"fieldname": "invoice_no",
			"label": "Voucher No",
			"fieldtype": "Data"
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		}
	],

	formatter: function (value, row, column, data, default_formatter) {
		let formatted_value = default_formatter(value, row, column, data);

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
