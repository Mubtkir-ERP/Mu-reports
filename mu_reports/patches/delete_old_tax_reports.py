import frappe

def execute():
	for report_name in ["Tax Report", "Tax Statement Report"]:
		if frappe.db.exists("Report", report_name):
			frappe.delete_doc("Report", report_name, force=True, ignore_permissions=True)
