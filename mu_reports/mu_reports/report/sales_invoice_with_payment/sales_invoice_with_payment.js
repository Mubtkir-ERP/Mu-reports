// Copyright (c) 2025, Youssef Restom and contributors
// For license information, please see license.txt

frappe.query_reports["Sales Invoice with Payment"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 0,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 0,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 0,
		},
		{
			fieldname: "from_time",
			label: __("From Time"),
			fieldtype: "Time",
			default: "00:00:00",
			reqd: 0,
		},
		{
			fieldname: "to_time",
			label: __("To Time"),
			fieldtype: "Time",
			default: "23:59:59",
			reqd: 0,
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			// فلتر بروفايل نقاط البيع — غير إجباري
			fieldname: "pos_profile",
			label: __("POS Profile"),
			fieldtype: "Link",
			options: "POS Profile",
			reqd: 0,
			get_query: function () {
				const company = frappe.query_report.get_filter_value("company");
				if (company) {
					return { filters: { company: company } };
				}
			},
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				"",
				"Draft",
				"Return",
				"Credit Note Issued",
				"Submitted",
				"Paid",
				"Partly Paid",
				"Unpaid",
				"Overdue",
				"Cancelled",
				"Internal Transfer",
			],
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// تمييز عمود التكلفة باللون الأحمر إذا كانت صفر (لا توجد تكلفة معروفة)
		if (column.fieldname === "product_cost" && data && data.has_zero_cost) {
			value = `<span style="color: var(--red-500, #e24c4c); font-weight: 600;">${value}</span>`;
		}

		// تلوين صافي الربح: أخضر للموجب، أحمر للسالب
		if (column.fieldname === "net_profit" && data) {
			const color =
				flt(data.net_profit) < 0
					? "var(--red-500, #e24c4c)"
					: "var(--green-600, #28a745)";
			value = `<span style="color: ${color};">${value}</span>`;
		}

		return value;
	},
};
