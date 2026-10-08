(() => {
// All Tax Report: signed company-currency GL movements and review tools.
const taxMethod = 'mu_reports.mu_reports.report.all_tax_report.all_tax_report.';
const taxEscape = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const taxNumber = value => value === null || value === undefined || value === '' ? '—' :
    Number(value).toLocaleString(frappe.boot.lang || 'en', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const taxCategory = value => ({Output:__("Output"), Input:__("Input"), Adjustment:__("Adjustment"),
    Excluded:__("Excluded"), Unclassified:__("Unclassified")}[value] || __("Unclassified"));
const taxBoxes = {1:__("Sales subject to the standard rate"),2:__("Private healthcare and education for citizens"),
    3:__("Domestic zero-rated sales"),4:__("Exports"),5:__("Exempt sales"),7:__("Standard-rated purchases"),
    8:__("Imports with VAT paid at import"),9:__("Reverse-charge imports"),
    10:__("Zero-rated purchases"),11:__("Exempt purchases")};
function taxStorageKey(period = false) {
    const f = frappe.query_report.get_filter_values() || {};
    return ['all-tax-v2', frappe.session.user, f.company || '', ...(period ? [f.from_date, f.to_date] : [])].join('|');
}
function taxLoad(period = false) {
    try { return JSON.parse(localStorage.getItem(taxStorageKey(period)) || '{}'); }
    catch (_) { return {}; }
}
function taxFilters() {
    const f = frappe.query_report.get_filter_values() || {};
    const company = taxLoad(); const period = taxLoad(true);
    return {...f, account_classification: JSON.stringify(company.account_classification || []),
        declaration_mapping: JSON.stringify(period.declaration_mapping || []),
        declaration_manual: JSON.stringify(period.declaration_manual || []),
        previous_correction: period.previous_correction ?? null, carried_credit: period.carried_credit ?? null};
}
async function taxSyncFilters(refresh = true) {
    const f = taxFilters();
    for (const key of ['account_classification','declaration_mapping','declaration_manual','previous_correction','carried_credit']) {
        await frappe.query_report.get_filter(key).set_value(f[key]);
    }
    if (refresh && !frappe.query_report._no_refresh) frappe.query_report.refresh();
}
async function taxCall(method, args = {}) {
    const response = await frappe.call({method: taxMethod + method,
        args: {filters: JSON.stringify(taxFilters()), ...args}});
    return response.message;
}
frappe.query_reports['All Tax Report'] = {
    filters: [
        {fieldname:'from_date',label:__('From Date'),fieldtype:'Date',default:frappe.datetime.month_start(),on_change:()=>taxSyncFilters()},
        {fieldname:'to_date',label:__('To Date'),fieldtype:'Date',default:frappe.datetime.get_today(),on_change:()=>taxSyncFilters()},
        {fieldname:'tax_accounts',label:__('Tax Accounts'),fieldtype:'MultiSelectList',options:'Account',reqd:1,
            get_data: txt => frappe.db.get_link_options('Account',txt,{company:frappe.query_report.get_filter_value('company'),is_group:0})},
        {fieldname:'party',label:__('Party'),fieldtype:'Data'},
        {fieldname:'invoice_no',label:__('Voucher No'),fieldtype:'Data'},
        {fieldname:'company',label:__('Company'),fieldtype:'Link',options:'Company',reqd:1,
            default:frappe.defaults.get_user_default('Company'),on_change:()=>taxSyncFilters()},
        {fieldname:'show_items',label:__("Show Items"),fieldtype:'Check',default:0},
        {fieldname:'show_tax_details',label:__("Show Tax Account Details"),fieldtype:'Check',default:0},
        {fieldname:'voucher_type',label:__("Voucher Type"),fieldtype:'Select',
            options:[{label:'',value:''},...['Sales Invoice','Purchase Invoice','Payment Entry','Vouchers Entry','Journal Entry'].map(value=>({value,label:__(value)}))]},
        {fieldname:'document_group',label:__("Document Group"),fieldtype:'Select',
            options:[{label:__("All"),value:'All'},{label:__("Sales"),value:'Sales'},{label:__("Purchases"),value:'Purchases'},
                {label:__("Returns Only"),value:'Returns'},{label:__("Payments and Journals Only"),value:'Settlements'}],default:'All'},
        {fieldname:'include_zero_tax',label:__("Include Zero Net Tax"),fieldtype:'Check',default:1},
        {fieldname:'include_non_taxed',label:__("Include Invoices with Zero Total Taxes"),fieldtype:'Check',default:0},
        ...['account_classification','declaration_mapping','declaration_manual','previous_correction','carried_credit']
            .map(fieldname => ({fieldname,fieldtype:'Small Text',hidden:1,hidden_due_to_dependency:1,on_change:()=>{}}))
    ],
    onload(report) {
        taxNativePrinting(report);
        taxHideSummary(report);
        report.page.add_inner_button(__("Classify Tax Accounts"),taxAccountSettings,__("Review"));
        report.page.add_inner_button(__("Configure VAT Return"),taxDeclarationSettings,__("Review"));
        report.page.add_inner_button(__("Reconcile GL"),taxReconcile,__("Review"));
        report.page.add_inner_button(__("Data Warnings"),taxWarnings,__("Review"));
        report.page.add_inner_button(__("Export Excel"),taxExportExcel);
        // Restore classifications before subsequent report runs; keys are company/period scoped.
        return taxSyncFilters(false);
    },
    formatter(value,row,column,data,default_formatter) {
        let formatted = default_formatter(value,row,column,data);
        if (!data) return formatted;
        const kind = data.row_kind;
        if (kind === 'section') return column.fieldname === 'invoice_no' ? `<strong>${formatted}</strong>` : '';
        if (kind === 'subtotal' || kind === 'grand_total') return `<strong style="color:#1f77b4">${formatted}</strong>`;
        if (kind === 'item' && column.fieldname !== 'item_name') return '';
        if (column.fieldname === 'voucher_type_label') formatted = taxEscape(data.voucher_type_label || __(data.voucher_type || ''));
        if (kind === 'tax_detail') {
            if (!['account','tax_amount','item_name'].includes(column.fieldname)) return '';
            if (column.fieldname === 'item_name') formatted = taxEscape(value);
            return `<span style="color:#666;padding-inline-start:14px">${formatted}</span>`;
        }
        if (kind === 'document' && column.fieldname === 'invoice_no') {
            const note = data.warnings?.length ? ` <span title="${taxEscape(data.warnings.join('؛ '))}" style="color:#b7791f">⚠</span>` : '';
            return `<span style="padding-inline-start:10px">${formatted}${note}</span>`;
        }
        return formatted;
    }
};
async function taxExportExcel() {
    try {
        const response = await fetch('/api/method/' + taxMethod + 'export_excel', {method:'POST',
            headers:{'Content-Type':'application/json','X-Frappe-CSRF-Token':frappe.csrf_token},
            body:JSON.stringify({filters:JSON.stringify(taxFilters())})});
        if (!response.ok || !(response.headers.get('content-type') || '').includes('application/')) throw new Error(__("Export failed; check the inputs and permissions"));
        const blob = await response.blob();
        if ((response.headers.get('content-type') || '').includes('json')) throw new Error(__("The server did not return an Excel file"));
        const url=URL.createObjectURL(blob);const link=document.createElement('a');
        link.href=url;link.download='All-Tax-Report.xlsx';document.body.appendChild(link);link.click();link.remove();
        setTimeout(()=>URL.revokeObjectURL(url),10000);
    } catch(e){frappe.msgprint(taxEscape(e.message || e));}
}
async function taxAccountSettings() {
    const saved = taxLoad(); const accounts = taxFilters().tax_accounts || [];
    const old = new Map((saved.account_classification || []).map(r=>[r.account,r]));
    const d = new frappe.ui.Dialog({title:__("Classify Tax Accounts"),size:'large',fields:[
        {fieldtype:'HTML',options:__("Classification is used for tax review. Excluded movements remain in GL reconciliation. Settings are stored in this browser for this user and company.")},
        {fieldname:'rows',fieldtype:'Table',label:__("Accounts"),cannot_add_rows:1,cannot_delete_rows:1,
            data:accounts.map(account=>({account,category:old.get(account)?.category || 'Unclassified'})),fields:[
                {fieldname:'account',fieldtype:'Data',label:__("Account"),read_only:1,in_list_view:1},
                {fieldname:'category',fieldtype:'Select',label:__("Classification"),in_list_view:1,
                    options:[{label:__("Unclassified"),value:'Unclassified'},{label:__("Output"),value:'Output'},
                        {label:__("Input"),value:'Input'},{label:__("Adjustment"),value:'Adjustment'},{label:__("Excluded"),value:'Excluded'}]}]}],
        primary_action_label:__("Save"),primary_action:async values=>{
            const updated = new Map((saved.account_classification || []).map(r=>[r.account,r]));
            values.rows.forEach(r=>updated.set(r.account,{account:r.account,category:r.category}));
            localStorage.setItem(taxStorageKey(),JSON.stringify({...saved,account_classification:[...updated.values()]}));
            d.hide(); await taxSyncFilters();
        }});d.show();
}
async function taxDeclarationSettings() {
    const result = await taxCall('get_review_data'); const saved = taxLoad(true);
    const old = new Map((saved.declaration_mapping || []).map(r=>[r.voucher_type+'|'+r.invoice_no,r]));
    const manual = new Map((saved.declaration_manual || []).map(r=>[Number(r.box),r]));
    const d = new frappe.ui.Dialog({title:__("Configure VAT Return"),size:'extra-large',fields:[
        {fieldtype:'HTML',options:__("Map each voucher once. Confirm the full invoice base only when it belongs entirely to one box and matches the selected account scope; otherwise enter the correct base manually. Payment amounts are not tax bases. Multi-box vouchers need manual allocation and review.")},
        {fieldname:'mapping',label:__("Map Visible Vouchers"),fieldtype:'Table',cannot_add_rows:1,cannot_delete_rows:1,
            data:result.documents.map(r=>({...old.get(r.voucher_type+'|'+r.invoice_no),voucher_type:r.voucher_type,voucher_type_label:__(r.voucher_type),invoice_no:r.invoice_no})),fields:[
                {fieldname:'voucher_type',fieldtype:'Data',label:__("Type"),read_only:1,in_list_view:1},
                {fieldname:'invoice_no',fieldtype:'Data',label:__("Voucher"),read_only:1,in_list_view:1},
                {fieldname:'box',fieldtype:'Select',label:__("Return Box"),in_list_view:1,
                    options:[{label:__("Unclassified"),value:''},...Object.entries(taxBoxes).map(([value,label])=>({value,label:value+' — '+label}))]},
                {fieldname:'use_invoice_base',fieldtype:'Check',label:__("Confirm Full Invoice Base"),in_list_view:1},
                {fieldname:'base_amount',fieldtype:'Data',label:__("Manual Base (Returns Negative)"),in_list_view:1}]},
        {fieldtype:'Section Break',label:__("Separate Manual Additions \u2014 Do Not Duplicate Voucher Amounts")},
        {fieldtype:'HTML',options:__("These are additions, not replacement totals. Explicitly enter zero for unused boxes after checking. Imports, deductions and corrections require review; no assumed tax rate is used.")},
        {fieldname:'manual',label:__("Manual Additions and Adjustments (Company Currency)"),fieldtype:'Table',cannot_add_rows:1,cannot_delete_rows:1,
            data:Object.entries(taxBoxes).map(([box,label])=>({box:Number(box),label,...manual.get(Number(box))})),fields:[
                {fieldname:'box',fieldtype:'Int',label:__("Box"),read_only:1,in_list_view:1},
                {fieldname:'label',fieldtype:'Data',label:__("Description"),read_only:1,in_list_view:1},
                ...['amount','adjustment','tax'].map((fieldname,i)=>({fieldname,fieldtype:'Data',
                    label:[__("Base Addition"),__("Base Adjustment"),__("Tax Addition")][i],in_list_view:1}))]},
        {fieldname:'previous_correction',fieldtype:'Data',label:__("Previous Period VAT Correction (+ / -)"),default:saved.previous_correction},
        {fieldname:'carried_credit',fieldtype:'Data',label:__("Carried VAT Credit (Positive)"),default:saved.carried_credit}
    ],primary_action_label:__("Save"),primary_action:async values=>{
        const merged = new Map((saved.declaration_mapping || []).map(r=>[r.voucher_type+'|'+r.invoice_no,r]));
        values.mapping.forEach(r=>merged.set(r.voucher_type+'|'+r.invoice_no,r));
        const settings = {...saved,declaration_mapping:[...merged.values()],declaration_manual:values.manual,
            previous_correction:values.previous_correction ?? null,carried_credit:values.carried_credit ?? null};
        // Validate on the server before storing invalid amounts or duplicate mappings.
        const filters = {...taxFilters(),...settings};
        await frappe.call({method:taxMethod+'get_print_data',args:{filters:JSON.stringify(filters),layout:'declaration'}});
        localStorage.setItem(taxStorageKey(true),JSON.stringify(settings));d.hide();await taxSyncFilters();
    }});d.show();
}
function taxReviewDialog(title,html) {
    const d = new frappe.ui.Dialog({title,size:'extra-large',fields:[{fieldtype:'HTML',fieldname:'content'}]});
    d.fields_dict.content.$wrapper.html(html);d.show();return d;
}
function taxHtmlTable(headers, rows) {
    return `<div style="overflow:auto"><table class="table table-bordered" dir="${frappe.utils.is_rtl() ? 'rtl' : 'ltr'}"><thead><tr>${headers.map(h=>`<th>${taxEscape(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
async function taxReconcile() {
    const result = await taxCall('get_review_data');
    const headers=['Account','Debit','Credit','Ledger Net','Document Net','Visible Net','Hidden by Filters','Difference'].map(label=>__(label));
    const rows=result.reconciliation.map(r=>[taxEscape(r.account),...['debit','credit','ledger_tax','document_tax','visible_tax','excluded_by_filters','difference'].map(k=>taxNumber(r[k]))]);
    const details=result.reconciliation_details.map(a=>[taxEscape(__(a.voucher_type)),taxEscape(a.invoice_no),taxEscape(a.account),taxNumber(a.debit),taxNumber(a.credit),taxNumber(a.tax_amount)]);
    taxReviewDialog(__('Reconcile GL'), '<p>'+taxEscape(__('Reconciliation includes selected company, period, accounts and voucher before party, group and zero-net filters. Hidden rows are not accounting differences.'))+'</p>'+taxHtmlTable(headers,rows)+
        '<h5>'+taxEscape(__('Voucher Details in Reconciliation Scope'))+'</h5>'+taxHtmlTable(['Type','Voucher','Account','Debit','Credit','Net Tax'].map(label=>__(label)),details));
}
async function taxWarnings() {
    const result=await taxCall('get_print_data',{layout:'declaration'});
    const rows=result.warnings.map(r=>[taxEscape(__(r.voucher_type)),taxEscape(r.invoice_no),taxEscape(r.message)]);
    result.declaration.pending.forEach(r=>rows.push([taxEscape(__(r.voucher_type)),taxEscape(r.invoice_no),taxEscape(r.reason)]));
    const boxes=result.declaration.missing_boxes.join(', ') || __('None');
    taxReviewDialog(__('Data Warnings'),'<p>'+taxEscape(__('Incomplete return boxes: {0}. Warnings do not change amounts automatically.',[boxes]))+'</p>'+taxHtmlTable(['Type','Voucher','Note'].map(label=>__(label)),rows));
}
function taxHideSummary(report) {
    if (report.$summary) report.$summary.empty().hide();
    if (report._tax_summary_hidden || typeof report.render_summary !== 'function') return;
    report._tax_summary_hidden = true;
    const original = report.render_summary.bind(report);
    report.render_summary = function(summary) {
        if (report.report_name === 'All Tax Report') {
            if (report.$summary) report.$summary.empty().hide();
            return;
        }
        return original(summary);
    };
}
function taxNativePrinting(report) {
    if (report._tax_native_printing) return;
    report._tax_native_printing = true;
    // Use the existing Print/PDF actions and dialog. No additional print button.
    for (const method of ['print_report', 'pdf_report']) {
        if (typeof report[method] !== 'function') continue;
        const original = report[method].bind(report);
        report[method] = async function(settings) {
            if (report.report_name !== 'All Tax Report') return original(settings);
            settings = settings || {};
            const name = settings.letter_head_name || (typeof settings.letter_head === 'string' ? settings.letter_head : null);
            if (settings.with_letter_head && name) {
                const head = await taxCall('render_report_letter_head',{letter_head:name});
                settings.letter_head = head;
            }
            return original(settings);
        };
    }
}

})();
