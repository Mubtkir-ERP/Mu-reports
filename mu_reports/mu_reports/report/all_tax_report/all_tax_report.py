# Copyright (c) 2026, Mubtkir and contributors
from collections import defaultdict
import json
import math
import frappe
from frappe import _
from frappe.utils import flt, cint, getdate, now_datetime
from frappe.query_builder import DocType

SECTION_NAMES = {
    'Sales Invoice': 'Sales Invoices', 'Sales Return': 'Sales Returns',
    'Purchase Invoice': 'Purchase Invoices', 'Purchase Return': 'Purchase Returns',
    'Payment Entry': 'ERPNext Payment Entries', 'Vouchers Entry': 'Voucher Entries',
    'Journal Entry': 'Journal Entries', 'Other': 'Other GL Vouchers',
}
SECTION_ORDER = tuple(SECTION_NAMES)
RETURN_LABELS = {
    1: 'Sales subject to the standard rate',
    2: 'Sales to citizens: private healthcare and education',
    3: 'Domestic zero-rated sales', 4: 'Exports', 5: 'Exempt sales',
    7: 'Purchases subject to the standard rate',
    8: 'Standard-rated imports with VAT paid at import',
    9: 'Standard-rated imports under reverse charge',
    10: 'Zero-rated purchases', 11: 'Exempt purchases',
}


def _json(value, default):
    if not value:
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        frappe.throw(_('Invalid classification settings.'))


def normalize_tax_accounts(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = value.replace(',', '\n').splitlines()
    if isinstance(value, str):
        value = [value]
    return list(dict.fromkeys(str(v.get('value') if isinstance(v, dict) else v).strip()
                              for v in (value or []) if v and (not isinstance(v, dict) or v.get('value'))))


def _settings(value):
    rows = _json(value, [])
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        frappe.throw(_('Classification settings must contain rows.'))
    return rows


def _validate(filters):
    from frappe.desk.query_report import get_report_doc
    get_report_doc('All Tax Report')
    if not filters.get('company'):
        frappe.throw(_('Please select a Company.'))
    if not frappe.has_permission('Company', 'read', filters.company):
        frappe.throw(_('Not permitted to read this Company.'), frappe.PermissionError)
    if not filters.get('from_date') or not filters.get('to_date'):
        frappe.throw(_('Please select both dates.'))
    if getdate(filters.from_date) > getdate(filters.to_date):
        frappe.throw(_('From Date must not be after To Date.'))
    accounts = normalize_tax_accounts(filters.get('tax_accounts'))
    if not accounts:
        frappe.throw(_('Please select at least one Tax Account to filter by.'))
    valid = frappe.get_all('Account', filters={'name': ['in', accounts], 'company': filters.company,
                                              'is_group': 0}, pluck='name')
    if set(valid) != set(accounts):
        frappe.throw(_('Selected accounts must be ledger accounts of the selected Company.'))
    filters.tax_accounts = accounts
    return filters


def _field_exists(doctype, field):
    return frappe.get_meta(doctype).has_field(field)


def _master_fields(doctype, names, fields):
    if not names or not frappe.db.exists('DocType', doctype):
        return {}
    fields = ['name'] + [f for f in fields if _field_exists(doctype, f)]
    return {r.name: r for r in frappe.get_all(doctype, filters={'name': ['in', list(names)]}, fields=fields)}


def _section(vtype, doc):
    if vtype in ('Sales Invoice', 'Purchase Invoice') and doc and doc.get('is_return'):
        return 'Sales Return' if vtype == 'Sales Invoice' else 'Purchase Return'
    return vtype if vtype in SECTION_NAMES else 'Other'


def _invoice_net(vtype, doc):
    if vtype not in ('Sales Invoice', 'Purchase Invoice') or not doc or doc.get('base_net_total') is None:
        return None
    return flt(doc.base_net_total) * (-1 if vtype == 'Purchase Invoice' else 1)


def _read_ledger(filters):
    gle = DocType('GL Entry')
    query = (frappe.qb.from_(gle).select(gle.voucher_no, gle.voucher_type, gle.posting_date,
             gle.account, gle.party, gle.party_type, gle.debit, gle.credit)
             .where(gle.is_cancelled == 0).where(gle.company == filters.company)
             .where(gle.account.isin(filters.tax_accounts))
             .where(gle.posting_date >= filters.from_date).where(gle.posting_date <= filters.to_date))
    if filters.get('invoice_no'):
        query = query.where(gle.voucher_no == filters.invoice_no)
    return query.run(as_dict=True)


def _visible(row, filters):
    if filters.get('party') and row['party'] != filters.party:
        return False
    if filters.get('voucher_type') and row['voucher_type'] != filters.voucher_type:
        return False
    mode = filters.get('document_group') or 'All'
    section = row['section_key']
    if mode == 'Sales' and section not in ('Sales Invoice', 'Sales Return'):
        return False
    if mode == 'Purchases' and section not in ('Purchase Invoice', 'Purchase Return'):
        return False
    if mode == 'Returns' and section not in ('Sales Return', 'Purchase Return'):
        return False
    if mode == 'Settlements' and row['voucher_type'] in ('Sales Invoice', 'Purchase Invoice'):
        return False
    return cint(filters.get('include_zero_tax')) or abs(row['tax_amount']) > 0.0000001


def _load_documents(filters, ledger):
    vouchers = {}
    for r in ledger:
        key = (r.voucher_type, r.voucher_no)
        v = vouchers.setdefault(key, {'posting_date': r.posting_date, 'party': '', 'party_type': '',
                                      'accounts': {}, 'has_tax_gl': True})
        a = v['accounts'].setdefault(r.account, {'debit': 0.0, 'credit': 0.0})
        a['debit'] += flt(r.debit)
        a['credit'] += flt(r.credit)
        if r.party and not v['party']:
            v['party'], v['party_type'] = r.party, r.party_type or ''
    by_type = defaultdict(set)
    for vtype, name in vouchers:
        by_type[vtype].add(name)
    docs = {}
    for vtype, names in by_type.items():
        docs[vtype] = _master_fields(vtype, names, ['base_net_total', 'customer', 'supplier', 'party',
                                                  'party_type', 'customer_name', 'supplier_name', 'party_name', 'is_return', 'payment_type', 'docstatus'])
        # Tax GL lines often have no party; recover it from the same voucher's GL.
        for r in frappe.get_all('GL Entry', filters={'company': filters.company, 'is_cancelled': 0,
                   'voucher_type': vtype, 'voucher_no': ['in', list(names)], 'party': ['!=', '']},
                   fields=['voucher_no', 'party', 'party_type'], order_by='name asc'):
            v = vouchers[(vtype, r.voucher_no)]
            if not v['party']:
                v['party'], v['party_type'] = r.party, r.party_type or ''
    if cint(filters.get('include_non_taxed')):
        for vtype in ('Sales Invoice', 'Purchase Invoice'):
            query_filters = {'company': filters.company, 'docstatus': 1,
                             'posting_date': ['between', [filters.from_date, filters.to_date]],
                             'total_taxes_and_charges': 0}
            if filters.get('invoice_no'):
                query_filters['name'] = filters.invoice_no
            fields = ['name', 'posting_date', 'base_net_total', 'is_return', 'docstatus',
                      'customer' if vtype == 'Sales Invoice' else 'supplier']
            for doc in frappe.get_all(vtype, filters=query_filters, fields=fields):
                key = (vtype, doc.name)
                if key not in vouchers:
                    vouchers[key] = {'posting_date': doc.posting_date, 'party': '', 'party_type': '',
                                     'accounts': {}, 'has_tax_gl': False}
                docs.setdefault(vtype, {})[doc.name] = doc
    customers, suppliers = set(), set()
    for (vtype, name), v in vouchers.items():
        doc = docs.get(vtype, {}).get(name) or {}
        if vtype == 'Sales Invoice':
            v['party'], v['party_type'] = doc.get('customer') or v['party'], 'Customer'
        elif vtype == 'Purchase Invoice':
            v['party'], v['party_type'] = doc.get('supplier') or v['party'], 'Supplier'
        else:
            v['party'] = v['party'] or doc.get('party') or ''
            v['party_type'] = v['party_type'] or doc.get('party_type') or ''
        if v['party_type'] == 'Customer':
            customers.add(v['party'])
        if v['party_type'] == 'Supplier':
            suppliers.add(v['party'])
    customer_map = _master_fields('Customer', customers - {''}, ['customer_name', 'custom_vat_registration_number', 'tax_id'])
    supplier_map = _master_fields('Supplier', suppliers - {''}, ['supplier_name', 'custom_vat_registration_number', 'tax_id'])
    settings = _settings(filters.get('account_classification'))
    account_map = {r.get('account'): r.get('category') if r.get('category') in
                   ('Output', 'Input', 'Adjustment', 'Excluded') else 'Unclassified' for r in settings}
    results = []
    for (vtype, name), v in sorted(vouchers.items(), key=lambda x: (str(x[1]['posting_date']), x[0])):
        doc = docs.get(vtype, {}).get(name)
        section = _section(vtype, doc)
        master = (customer_map if v['party_type'] == 'Customer' else supplier_map).get(v['party'], {})
        vat = master.get('custom_vat_registration_number') or master.get('tax_id') or ''
        details = []
        for account, a in sorted(v['accounts'].items()):
            details.append({'account': account, 'debit': a['debit'], 'credit': a['credit'],
                            'tax_amount': a['credit'] - a['debit'],
                            'category': account_map.get(account) or 'Unclassified'})
        tax = sum(a['tax_amount'] for a in details)
        net = _invoice_net(vtype, doc)
        warnings = []
        if v['party_type'] in ('Customer', 'Supplier') and not vat:
            warnings.append(_('VAT registration number is missing'))
        if net is None:
            warnings.append(_('Tax base is unavailable; a payment amount is not a tax base'))
        if any(a['category'] not in ('Output', 'Input', 'Adjustment', 'Excluded') for a in details):
            warnings.append(_('Tax account is unclassified'))
        if v['has_tax_gl'] and not doc:
            warnings.append(_('Source document is unavailable; the amount comes from GL'))
        if doc and doc.get('docstatus') is not None and doc.get('docstatus') != 1:
            warnings.append(_('Document status conflicts with uncancelled GL movement'))
        if sum(a['debit'] for a in details) and sum(a['credit'] for a in details):
            warnings.append(_('Both debit and credit movements exist; review account details'))
        if net is not None and net * tax < 0:
            warnings.append(_('Tax sign differs from the invoice net direction'))
        row = {'invoice_no': name, 'voucher_type': vtype, 'voucher_type_label': _(vtype), 'posting_date': v['posting_date'],
               'party': v['party'], 'party_name': (doc or {}).get('customer_name') or (doc or {}).get('supplier_name') or (doc or {}).get('party_name') or master.get('customer_name') or master.get('supplier_name') or v['party'], 'account': ', '.join(a['account'] for a in details),
               'custom_vat_registration_number': vat, 'item_name': '', 'net_amount': net,
               'tax_amount': tax, 'section_key': section, 'indent': 1, 'row_kind': 'document',
               'account_details': details, 'warnings': warnings, 'has_tax_gl': v['has_tax_gl']}
        results.append(row)
    return results


def _reconciliation(ledger, documents, visible):
    # Independently total raw GL rows and document aggregates by account.
    result = {}
    for r in ledger:
        a = result.setdefault(r.account, {'account': r.account, 'debit': 0.0, 'credit': 0.0,
                                         'document_tax': 0.0, 'visible_tax': 0.0})
        a['debit'] += flt(r.debit)
        a['credit'] += flt(r.credit)
    for rows, field in ((documents, 'document_tax'), (visible, 'visible_tax')):
        for row in rows:
            for detail in row['account_details']:
                result[detail['account']][field] += detail['tax_amount']
    for a in result.values():
        a['ledger_tax'] = a['credit'] - a['debit']
        a['excluded_by_filters'] = a['document_tax'] - a['visible_tax']
        a['difference'] = a['ledger_tax'] - a['document_tax']
    return sorted(result.values(), key=lambda a: a['account'])


def _summary(documents):
    totals = defaultdict(float)
    for row in documents:
        for detail in row['account_details']:
            totals[detail['category']] += detail['tax_amount']
    return {'output': totals['Output'], 'input': -totals['Input'], 'adjustment': totals['Adjustment'],
            'unclassified': totals['Unclassified'], 'excluded': totals['Excluded'],
            'net': sum(row['tax_amount'] for row in documents)}


def _table_data(documents, filters):
    items = defaultdict(list)
    if cint(filters.get('show_items')):
        for vtype in ('Sales Invoice', 'Purchase Invoice'):
            names = [r['invoice_no'] for r in documents if r['voucher_type'] == vtype]
            if names:
                for item in frappe.get_all(vtype + ' Item', filters={'parent': ['in', names]},
                        fields=['parent', 'item_name'], order_by='idx asc'):
                    items[(vtype, item.parent)].append(item.item_name)
    grouped = defaultdict(list)
    for row in documents:
        grouped[row['section_key']].append(row)
    data = []
    for section in SECTION_ORDER:
        rows = grouped[section]
        if not rows:
            continue
        data.append({'invoice_no': _(SECTION_NAMES[section]), 'row_kind': 'section', 'indent': 0})
        for row in rows:
            data.append(row)
            if cint(filters.get('show_tax_details')):
                for a in row['account_details']:
                    data.append({'voucher_type': row['voucher_type'], 'account': a['account'],
                                 'tax_amount': a['tax_amount'], 'net_amount': None,
                                 'item_name': _(a['category']), 'row_kind': 'tax_detail', 'indent': 2})
            for name in items[(row['voucher_type'], row['invoice_no'])]:
                data.append({'voucher_type': row['voucher_type'], 'item_name': name,
                             'row_kind': 'item', 'indent': 2, 'net_amount': None, 'tax_amount': None})
        known = [r['net_amount'] for r in rows if r['net_amount'] is not None]
        data.append({'invoice_no': _('Total {0}').format(_(SECTION_NAMES[section])), 'row_kind': 'subtotal',
                     'indent': 0, 'section_key': section, 'net_amount': sum(known) if known else None,
                     'tax_amount': sum(r['tax_amount'] for r in rows)})
    if documents:
        known = [r['net_amount'] for r in documents if r['net_amount'] is not None]
        data.append({'invoice_no': _('Grand Total'), 'row_kind': 'grand_total', 'indent': 0,
                     'net_amount': sum(known) if known else None,
                     'tax_amount': sum(r['tax_amount'] for r in documents)})
    return data


def _finite(value):
    if value is None or value == '':
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        frappe.throw(_('Invalid manual amount.'))
    if not math.isfinite(value):
        frappe.throw(_('Manual amounts must be finite.'))
    return value


def _declaration(documents, filters):
    mappings = _settings(filters.get('declaration_mapping'))
    mapping = {}
    for m in mappings:
        key = (m.get('voucher_type'), m.get('invoice_no'))
        if key in mapping:
            frappe.throw(_('A voucher must be mapped only once in the declaration.'))
        mapping[key] = m
    boxes = {n: {'number': n, 'label': _(label), 'amount': None, 'adjustment': None, 'tax': None}
             for n, label in RETURN_LABELS.items()}
    pending = []
    for row in documents:
        m = mapping.get((row['voucher_type'], row['invoice_no']))
        number = cint(m.get('box')) if m else 0
        if number not in boxes:
            pending.append({'voucher_type': row['voucher_type'], 'invoice_no': row['invoice_no'],
                            'tax_amount': row['tax_amount'], 'reason': _('Document is not mapped to a return box')})
            continue
        box = boxes[number]
        # One explicit voucher mapping prevents repeating an invoice base per account.
        base = _finite(m.get('base_amount'))
        if base is None and cint(m.get('use_invoice_base')) and row['net_amount'] is not None:
            base = row['net_amount'] * (-1 if row['voucher_type'] == 'Purchase Invoice' else 1)
        if base is None:
            pending.append({'voucher_type': row['voucher_type'], 'invoice_no': row['invoice_no'],
                            'tax_amount': row['tax_amount'], 'reason': _('Tax base has not been entered or confirmed')})
        else:
            box['amount'] = flt(box['amount']) + base
        box['tax'] = flt(box['tax']) + row['tax_amount'] * (1 if number < 6 else -1)
        if number in (3, 4, 5, 10, 11) and abs(row['tax_amount']) > 0.0000001:
            pending.append({'voucher_type': row['voucher_type'], 'invoice_no': row['invoice_no'],
                            'tax_amount': row['tax_amount'], 'reason': _('Nonzero tax in a zero-rated or exempt box')})
    manual_rows = _settings(filters.get('declaration_manual'))
    seen = set()
    for manual in manual_rows:
        n = cint(manual.get('box'))
        if n not in boxes or n in seen:
            frappe.throw(_('Manual declaration rows must have unique valid box numbers.'))
        seen.add(n)
        for field in ('amount', 'adjustment', 'tax'):
            value = _finite(manual.get(field))
            if value is not None:
                boxes[n][field] = flt(boxes[n][field]) + value
    result = []
    for start, end, total_number, label in ((1, 5, 6, _('Total Sales')), (7, 11, 12, _('Total Purchases'))):
        group = [boxes[n] for n in range(start, end + 1)]
        result.extend(group)
        # Missing categories stay blank in rows and make the declaration incomplete.
        result.append({'number': total_number, 'label': label, 'is_total': True,
                       **{field: sum(flt(r[field]) for r in group) for field in ('amount', 'adjustment', 'tax')}})
    missing = [n for n, r in boxes.items() if any(r[f] is None for f in ('amount', 'adjustment', 'tax'))]
    current = result[5]['tax'] - result[-1]['tax']
    previous = _finite(filters.get('previous_correction'))
    carried = _finite(filters.get('carried_credit'))
    if carried is not None and carried < 0:
        frappe.throw(_('Carried credit must be entered as a positive amount.'))
    return {'rows': result, 'pending': pending, 'missing_boxes': missing, 'current_tax': current,
            'previous_correction': previous, 'carried_credit': carried,
            'payable': current + (previous or 0) - (carried or 0),
            'complete': not pending and not missing and previous is not None and carried is not None,
            'manual_entries': manual_rows}


def _build(filters):
    filters = _validate(frappe._dict(_json(filters, {})))
    ledger = _read_ledger(filters)
    documents = _load_documents(filters, ledger)
    visible = [r for r in documents if _visible(r, filters)]
    warnings = [{'voucher_type': r['voucher_type'], 'invoice_no': r['invoice_no'], 'message': w}
                for r in visible for w in r['warnings']]
    return {'filters': dict(filters), 'generated_at': str(now_datetime()),
            'currency': frappe.db.get_value('Company', filters.company, 'default_currency'),
            'documents': visible, 'data': _table_data(visible, filters),
            'reconciliation': _reconciliation(ledger, documents, visible),
            'summary': _summary(visible), 'warnings': warnings,
            'reconciliation_details': [{'voucher_type': r['voucher_type'], 'invoice_no': r['invoice_no'],
                                       **a} for r in documents for a in r['account_details']]}


def get_columns():
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
            "fieldname": "voucher_type_label",
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


    return columns


def execute(filters=None):
    result = _attach_declaration(_build(filters or {}))
    if result['data']:
        result['data'][-1]['_tax_print'] = {k: result[k] for k in
            ('filters', 'generated_at', 'currency', 'declaration')}
    message = _('Amounts are in company currency. The full invoice net amount is not allocated to selected tax accounts. ')
    message += _('A blank base is unavailable; totals include known net amounts only. ')
    if cint(result['filters'].get('show_tax_details')):
        message += _('Account details are explanatory; each document contributes to totals only once. ')
    message += _('Review warnings: ') + str(len(result['warnings']))
    return get_columns(), result['data'], message, None, [], 1


def _attach_declaration(result):
    result['declaration'] = _declaration(result['documents'], frappe._dict(result['filters']))
    restricted = any(result['filters'].get(k) for k in ('party', 'invoice_no', 'voucher_type'))
    restricted = restricted or result['filters'].get('document_group', 'All') != 'All'
    restricted = restricted or not cint(result['filters'].get('include_zero_tax'))
    restricted = restricted or not cint(result['filters'].get('include_non_taxed'))
    result['declaration']['restricted_scope'] = bool(restricted)
    if restricted or result['currency'] != 'SAR':
        result['declaration']['complete'] = False
    return result


@frappe.whitelist()
def get_print_data(filters=None, layout='summary'):
    result = _build(filters or {})
    result['columns'] = get_columns()
    result['layout'] = layout if layout in ('summary', 'detailed', 'declaration') else 'summary'
    _attach_declaration(result)
    return result


@frappe.whitelist()
def get_review_data(filters=None):
    return _build(filters or {})


@frappe.whitelist()
def export_excel(filters=None):
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    report = get_print_data(filters, 'declaration')
    wb = Workbook()
    wb.remove(wb.active)
    def sheet(name, headers, rows):
        ws = wb.create_sheet(name)
        ws.sheet_view.rightToLeft = str(getattr(frappe.local, 'lang', 'en')).split('-')[0] in ('ar', 'he', 'fa', 'ur')
        ws.append(headers)
        for row in rows:
            ws.append(row)
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.fill = PatternFill('solid', fgColor='087F7B')
            cell.font = Font(color='FFFFFF', bold=True)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                # Names and notes must never become Excel formulas.
                if isinstance(cell.value, str):
                    cell.data_type = 's'
                elif isinstance(cell.value, (int, float)):
                    cell.number_format = '#,##0.00;[Red](#,##0.00)'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        for i in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 24
        return ws
    columns = report['columns']
    sheet(_('Report'), [c['label'] for c in columns] + [_('Row Type'), _('Warnings')],
          [[r.get(c['fieldname']) for c in columns] + [r.get('row_kind'), '; '.join(r.get('warnings', []))]
           for r in report['data']])
    sheet(_('Account Details'), [_('Voucher Type'), _('Voucher'), _('Account'), _('Debit'), _('Credit'), _('Net Tax'), _('Classification')],
          [[_(r['voucher_type']), r['invoice_no'], a['account'], a['debit'], a['credit'], a['tax_amount'], _(a['category'])]
           for r in report['documents'] for a in r['account_details']])
    fields = ['account', 'debit', 'credit', 'ledger_tax', 'document_tax', 'visible_tax', 'excluded_by_filters', 'difference']
    sheet(_('Reconciliation'), [_('Account'), _('Debit'), _('Credit'), _('Ledger Net'), _('Document Net'), _('Visible Net'), _('Hidden by Filters'), _('Difference')],
          [[r[f] for f in fields] for r in report['reconciliation']])
    d = report['declaration']
    sheet(_('VAT Return'), [_('Box'), _('Description'), _('Amount'), _('Adjustment'), _('Tax')],
          [[r['number'], r['label'], r['amount'], r['adjustment'], r['tax']] for r in d['rows']] +
          [[None, _('Net VAT for the Period'), None, None, d['current_tax']],
           [None, _('Previous Period Corrections'), None, None, d['previous_correction']],
           [None, _('Carried Credit'), None, None, d['carried_credit']],
           [None, _('Provisional VAT Payable'), None, None, d['payable']]])
    sheet(_('Review'), [_('Voucher Type'), _('Voucher'), _('Note')],
          [[_(r['voucher_type']), r['invoice_no'], r['message']] for r in report['warnings']] +
          [[_(r['voucher_type']), r['invoice_no'], r['reason']] for r in d['pending']])
    meta = [[_('Company'), report['filters']['company']], [_('Currency'), report['currency']],
            [_('Generated At'), report['generated_at']], [_('Return Status'), _('Classification Complete') if d['complete'] else _('Incomplete Draft')],
            [_('Note'), _('Invoice net amounts are complete; totals include known bases only. Do not sum account details again.')],
            [_('Return Layout Source'), 'https://zatca.gov.sa/ar/HelpCenter/guidelines/Documents/إرشادات.pdf']]
    meta += [[k, json.dumps(v, ensure_ascii=False, default=str)] for k, v in report['filters'].items()]
    sheet(_('Settings'), [_('Description'), _('Value')], meta)
    stream = BytesIO()
    wb.save(stream)
    frappe.local.response.filename = 'All-Tax-Report.xlsx'
    frappe.local.response.filecontent = stream.getvalue()
    frappe.local.response.type = 'binary'


@frappe.whitelist()
def render_report_letter_head(filters=None, letter_head=None):
    # Native report Print Formats use JS templates. Render letter-head Jinja
    # on the server with the company context before the native print wrapper.
    filters = _validate(frappe._dict(_json(filters, {})))
    if not letter_head:
        return {}
    head = frappe.get_doc('Letter Head', letter_head)
    head.check_permission('read')
    context = {'doc': filters, 'filters': filters}
    result = {}
    for source, target in (('content', 'header'), ('footer', 'footer')):
        if head.get(source):
            result[target] = frappe.render_template(head.get(source), context)
    return result
