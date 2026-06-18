# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _


# الأعمدة الثابتة التي يجب ألا تتعارض مع أسماء طرق الدفع الديناميكية
RESERVED_FIELDNAMES = {
    "sales_invoice",
    "posting_date",
	"posting_time",
    "customer",
    "customer_name",
    "net_total",
    "total_taxes_and_charges",
    "grand_total",
    "outstanding_amount",
    "product_cost",
    "net_profit",
    "status",
    "pos_profile",
    "is_return",
    "has_zero_cost",
}


def execute(filters=None):
    filters = filters or {}
    payment_modes = get_payment_modes(filters)
    columns = get_columns(filters, payment_modes)
    data = get_data(filters, payment_modes)
    return columns, data


def get_payment_mode_fieldname(mode_of_payment, used_keys):
    """توليد fieldname آمن لا يتعارض مع الأعمدة الثابتة أو مع بعضه."""
    base_key = "mop_" + frappe.scrub(mode_of_payment)
    key = base_key
    counter = 1
    while key in RESERVED_FIELDNAMES or key in used_keys:
        key = f"{base_key}_{counter}"
        counter += 1
    used_keys[key] = mode_of_payment
    return key


def get_payment_modes(filters):
    """
    إرجاع قائمة طرق الدفع كـ list of dicts: {mode, fieldname}.
    إذا تم اختيار بروفايل نقاط بيع، تُعرض فقط طرق الدفع الخاصة به.
    """
    used_keys = {}
    modes = []

    pos_profile = filters.get("pos_profile")

    if pos_profile:
        # طرق الدفع المعرّفة داخل بروفايل نقاط البيع نفسه
        rows = frappe.db.sql(
            """
            SELECT DISTINCT mode_of_payment
            FROM `tabPOS Payment Method`
            WHERE parent = %(pos_profile)s
              AND parenttype = 'POS Profile'
              AND mode_of_payment IS NOT NULL
            ORDER BY mode_of_payment
            """,
            {"pos_profile": pos_profile},
            as_list=1,
        )
    else:
        rows = frappe.db.sql(
            """
            SELECT DISTINCT sip.mode_of_payment
            FROM `tabSales Invoice Payment` sip
            WHERE sip.mode_of_payment IS NOT NULL
            ORDER BY sip.mode_of_payment
            """,
            as_list=1,
        )

    for row in rows:
        mode = row[0]
        if not mode:
            continue
        fieldname = get_payment_mode_fieldname(mode, used_keys)
        modes.append({"mode": mode, "fieldname": fieldname})

    return modes


def get_columns(filters, payment_modes):
    columns = [
        {
            "label": _("Sales Invoice"),
            "fieldname": "sales_invoice",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 150,
        },
        {
            "label": _("Posting Date"),
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "label": _("Customer Name"),
            "fieldname": "customer_name",
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "label": _("POS Profile"),
            "fieldname": "pos_profile",
            "fieldtype": "Link",
            "options": "POS Profile",
            "width": 130,
        },
        {
            "label": _("Amount Before VAT"),
            "fieldname": "net_total",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("VAT Amount"),
            "fieldname": "total_taxes_and_charges",
            "fieldtype": "Currency",
            "width": 120,
        },
        {
            "label": _("Grand Total"),
            "fieldname": "grand_total",
            "fieldtype": "Currency",
            "width": 120,
        },
        {
            "label": _("Outstanding Amount"),
            "fieldname": "outstanding_amount",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("Product Cost"),
            "fieldname": "product_cost",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": _("Net Profit"),
            "fieldname": "net_profit",
            "fieldtype": "Currency",
            "width": 130,
        },
    ]

    for mode in payment_modes:
        columns.append(
            {
                "label": _(mode["mode"]),
                "fieldname": mode["fieldname"],
                "fieldtype": "Currency",
                "width": 120,
            }
        )

    columns.append(
        {
            "label": _("Status"),
            "fieldname": "status",
            "fieldtype": "Data",
            "width": 100,
        }
    )

    return columns


def get_data(filters, payment_modes):
    conditions = get_conditions(filters)

    # 1. بيانات الفواتير
    invoice_data = frappe.db.sql(
        """
        SELECT
            si.name AS sales_invoice,
            si.posting_date,
			si.posting_time,
            si.customer,
            si.customer_name,
            si.pos_profile,
            si.net_total,
            si.total_taxes_and_charges,
            si.grand_total,
            si.outstanding_amount,
            si.is_return,
            si.status
        FROM
            `tabSales Invoice` si
        WHERE
            si.docstatus = 1
            {conditions}
        ORDER BY
            si.posting_date DESC, si.name
        """.format(conditions=conditions),
        filters,
        as_dict=1,
    )

    if not invoice_data:
        return []

    invoice_names = [row.sales_invoice for row in invoice_data]
    valid_fieldnames = {m["fieldname"] for m in payment_modes}
    mode_to_field = {m["mode"]: m["fieldname"] for m in payment_modes}

    # 2. تفاصيل المدفوعات
    payment_data = frappe.db.sql(
        """
        SELECT
            sip.parent AS invoice,
            sip.mode_of_payment,
            sip.amount
        FROM
            `tabSales Invoice Payment` sip
        WHERE
            sip.parent IN %(invoices)s
        """,
        {"invoices": invoice_names},
        as_dict=1,
    )

    payment_map = {}
    for payment in payment_data:
        if not payment.mode_of_payment:
            continue
        # نعرض فقط طرق الدفع المطابقة للأعمدة الحالية (مهم عند فلترة البروفايل)
        field = mode_to_field.get(payment.mode_of_payment)
        if not field or field not in valid_fieldnames:
            continue
        payment_map.setdefault(payment.invoice, {})
        payment_map[payment.invoice][field] = (
            payment_map[payment.invoice].get(field, 0) + payment.amount
        )

    # 3. تكلفة المنتج — الحالة الأولى: Update Stock مفعّل في الفاتورة
    product_cost_data = frappe.db.sql(
        """
        SELECT
            sle.voucher_no AS sales_invoice,
            SUM(ABS(sle.actual_qty) * sle.valuation_rate) AS product_cost
        FROM
            `tabStock Ledger Entry` sle
        WHERE
            sle.voucher_type = 'Sales Invoice'
            AND sle.is_cancelled = 0
            AND sle.voucher_no IN %(invoices)s
        GROUP BY
            sle.voucher_no
        """,
        {"invoices": invoice_names},
        as_dict=1,
    )

    product_cost_map = {
        row.sales_invoice: (row.product_cost or 0) for row in product_cost_data
    }

    # الحالة الثانية: Update Stock مطفأ - نجلب التكلفة من Delivery Note
    missing_invoices = [inv for inv in invoice_names if inv not in product_cost_map]

    if missing_invoices:
        dn_cost_data = frappe.db.sql(
            """
            SELECT
                dni.against_sales_invoice AS sales_invoice,
                SUM(ABS(sle.actual_qty) * sle.valuation_rate) AS product_cost
            FROM
                `tabStock Ledger Entry` sle
            INNER JOIN
                `tabDelivery Note Item` dni ON dni.name = sle.voucher_detail_no
            WHERE
                sle.voucher_type = 'Delivery Note'
                AND sle.is_cancelled = 0
                AND dni.against_sales_invoice IN %(invoices)s
            GROUP BY
                dni.against_sales_invoice
            """,
            {"invoices": missing_invoices},
            as_dict=1,
        )

        for row in dn_cost_data:
            product_cost_map[row.sales_invoice] = row.product_cost or 0

    # الحالة الثالثة (fallback): الفواتير التي ما زالت بلا تكلفة (= 0)
    # نحسب التكلفة التقديرية من سعر التقييم / آخر سعر شراء في بطاقة الصنف
    still_missing = [
        inv
        for inv in invoice_names
        if not product_cost_map.get(inv)
    ]

    if still_missing:
        fallback_cost = get_fallback_cost_from_items(still_missing)
        for inv, cost in fallback_cost.items():
            if cost:
                product_cost_map[inv] = cost

    # 4. دمج كل البيانات داخل صفوف الفواتير
    for row in invoice_data:
        if row.sales_invoice in payment_map:
            row.update(payment_map[row.sales_invoice])

        product_cost = product_cost_map.get(row.sales_invoice, 0) or 0
        row.product_cost = -product_cost if row.is_return else product_cost

        # تمييز الصفوف التي تكلفتها صفر (لا valuation ولا سعر شراء)
        row.has_zero_cost = 1 if not product_cost else 0

        # صافي الربح = الإجمالي قبل الضريبة − التكلفة
        net_total = row.net_total or 0
        row.net_profit = net_total - row.product_cost

    return invoice_data


def get_fallback_cost_from_items(invoice_names):
    """
    حساب التكلفة التقديرية للفواتير التي ليس لها تكلفة من حركة المخزون.
    الأولوية: valuation_rate من بطاقة الصنف، ثم last_purchase_rate.
    تُحسب على مستوى بند الفاتورة (qty * تكلفة الوحدة التقديرية).
    """
    item_rows = frappe.db.sql(
        """
        SELECT
            sii.parent AS sales_invoice,
            sii.item_code,
            sii.stock_qty,
            COALESCE(NULLIF(it.valuation_rate, 0), it.last_purchase_rate, 0) AS unit_cost
        FROM
            `tabSales Invoice Item` sii
        INNER JOIN
            `tabItem` it ON it.name = sii.item_code
        WHERE
            sii.parent IN %(invoices)s
            AND it.is_stock_item = 1
        """,
        {"invoices": invoice_names},
        as_dict=1,
    )

    cost_map = {}
    for row in item_rows:
        qty = abs(row.stock_qty or 0)
        cost = qty * (row.unit_cost or 0)
        cost_map[row.sales_invoice] = cost_map.get(row.sales_invoice, 0) + cost

    return cost_map


def get_conditions(filters):
    conditions = []

    from_time = filters.get("from_time")
    to_time = filters.get("to_time")

    if filters.get("from_date"):
        if from_time:
            conditions.append(
                "TIMESTAMP(si.posting_date, si.posting_time) >= TIMESTAMP(%(from_date)s, %(from_time)s)"
            )
        else:
            conditions.append("si.posting_date >= %(from_date)s")

    if filters.get("to_date"):
        if to_time:
            conditions.append(
                "TIMESTAMP(si.posting_date, si.posting_time) <= TIMESTAMP(%(to_date)s, %(to_time)s)"
            )
        else:
            conditions.append("si.posting_date <= %(to_date)s")

    if filters.get("customer"):
        conditions.append("si.customer = %(customer)s")
    if filters.get("company"):
        conditions.append("si.company = %(company)s")
    if filters.get("pos_profile"):
        conditions.append("si.pos_profile = %(pos_profile)s")
    if filters.get("status"):
        conditions.append("si.status = %(status)s")

    return " AND " + " AND ".join(conditions) if conditions else ""
