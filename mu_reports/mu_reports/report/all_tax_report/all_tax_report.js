(() => {
// All Tax Report: signed company-currency GL movements and review tools.
const taxMethod = 'mu_reports.mu_reports.report.all_tax_report.all_tax_report.';
const taxEscape = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const taxNumber = value => value === null || value === undefined || value === '' ? '—' :
    Number(value).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const taxCategory = value => ({Output:'مخرجات', Input:'مدخلات', Adjustment:'تسويات',
    Excluded:'مستبعد من الإقرار', Unclassified:'غير مصنف'}[value] || 'غير مصنف');
const taxBoxes = {1:'المبيعات الخاضعة للنسبة الأساسية',2:'الخدمات الصحية والتعليم الأهلي للمواطنين',
    3:'المبيعات المحلية الصفرية',4:'الصادرات',5:'المبيعات المعفاة',7:'المشتريات بالنسبة الأساسية',
    8:'الاستيرادات المدفوعة عند الاستيراد',9:'الاستيرادات وفق الاحتساب العكسي',
    10:'المشتريات الصفرية',11:'المشتريات المعفاة'};
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
    get_print_html: makeTaxPrintHtml,
    filters: [
        {fieldname:'from_date',label:__('From Date'),fieldtype:'Date',default:frappe.datetime.month_start(),on_change:()=>taxSyncFilters()},
        {fieldname:'to_date',label:__('To Date'),fieldtype:'Date',default:frappe.datetime.get_today(),on_change:()=>taxSyncFilters()},
        {fieldname:'tax_accounts',label:__('Tax Accounts'),fieldtype:'MultiSelectList',options:'Account',reqd:1,
            get_data: txt => frappe.db.get_link_options('Account',txt,{company:frappe.query_report.get_filter_value('company'),is_group:0})},
        {fieldname:'party',label:__('Party'),fieldtype:'Data'},
        {fieldname:'invoice_no',label:__('Voucher No'),fieldtype:'Data'},
        {fieldname:'company',label:__('Company'),fieldtype:'Link',options:'Company',reqd:1,
            default:frappe.defaults.get_user_default('Company'),on_change:()=>taxSyncFilters()},
        {fieldname:'show_items',label:'إظهار المنتجات',fieldtype:'Check',default:0},
        {fieldname:'show_tax_details',label:'تفصيل حسابات الضريبة',fieldtype:'Check',default:0},
        {fieldname:'voucher_type',label:'نوع المستند',fieldtype:'Select',
            options:'\nSales Invoice\nPurchase Invoice\nPayment Entry\nVouchers Entry\nJournal Entry'},
        {fieldname:'document_group',label:'مجموعة المستندات',fieldtype:'Select',
            options:[{label:'الكل',value:'All'},{label:'المبيعات',value:'Sales'},{label:'المشتريات',value:'Purchases'},
                {label:'المرتجعات فقط',value:'Returns'},{label:'السندات والقيود فقط',value:'Settlements'}],default:'All'},
        {fieldname:'include_zero_tax',label:'إظهار صافي الضريبة الصفري',fieldtype:'Check',default:1},
        {fieldname:'include_non_taxed',label:'إضافة الفواتير ذات إجمالي الضرائب الصفري',fieldtype:'Check',default:0},
        ...['account_classification','declaration_mapping','declaration_manual','previous_correction','carried_credit']
            .map(fieldname => ({fieldname,fieldtype:'Small Text',hidden:1,hidden_due_to_dependency:1,on_change:()=>{}}))
    ],
    onload(report) {
        report.page.add_inner_button('طباعة مختصرة',()=>printTaxReport('summary'),__('Print'));
        report.page.add_inner_button('طباعة مفصلة',()=>printTaxReport('detailed'),__('Print'));
        report.page.add_inner_button('طباعة جدول الإقرار',()=>printTaxReport('declaration'),__('Print'));
        report.page.add_inner_button('تصنيف حسابات الضريبة',taxAccountSettings,'المراجعة');
        report.page.add_inner_button('إعداد جدول الإقرار',taxDeclarationSettings,'المراجعة');
        report.page.add_inner_button('مطابقة الأستاذ',taxReconcile,'المراجعة');
        report.page.add_inner_button('تنبيهات البيانات',taxWarnings,'المراجعة');
        report.page.add_inner_button('تصدير Excel',taxExportExcel);
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
        if (kind === 'tax_detail') {
            if (!['account','tax_amount','item_name'].includes(column.fieldname)) return '';
            if (column.fieldname === 'item_name') formatted = taxCategory(value);
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
        if (!response.ok || !(response.headers.get('content-type') || '').includes('application/')) throw new Error('تعذر تصدير التقرير؛ راجع المدخلات والصلاحيات');
        const blob = await response.blob();
        if ((response.headers.get('content-type') || '').includes('json')) throw new Error('لم يُرجع الخادم ملف Excel');
        const url=URL.createObjectURL(blob);const link=document.createElement('a');
        link.href=url;link.download='All-Tax-Report.xlsx';document.body.appendChild(link);link.click();link.remove();
        setTimeout(()=>URL.revokeObjectURL(url),10000);
    } catch(e){frappe.msgprint(taxEscape(e.message || e));}
}
async function taxAccountSettings() {
    const saved = taxLoad(); const accounts = taxFilters().tax_accounts || [];
    const old = new Map((saved.account_classification || []).map(r=>[r.account,r]));
    const d = new frappe.ui.Dialog({title:'تصنيف حسابات الضريبة',size:'large',fields:[
        {fieldtype:'HTML',options:'التصنيف يحدد ملخص المخرجات والمدخلات والتسويات. الاستبعاد لا يحذف الحركة من مطابقة الأستاذ. الإعدادات محفوظة لهذا المستخدم والشركة في هذا المتصفح.'},
        {fieldname:'rows',fieldtype:'Table',label:'الحسابات',cannot_add_rows:1,cannot_delete_rows:1,
            data:accounts.map(account=>({account,category:old.get(account)?.category || 'Unclassified'})),fields:[
                {fieldname:'account',fieldtype:'Data',label:'الحساب',read_only:1,in_list_view:1},
                {fieldname:'category',fieldtype:'Select',label:'التصنيف',in_list_view:1,
                    options:[{label:'غير مصنف',value:'Unclassified'},{label:'مخرجات',value:'Output'},
                        {label:'مدخلات',value:'Input'},{label:'تسويات',value:'Adjustment'},{label:'مستبعد من الإقرار',value:'Excluded'}]}]}],
        primary_action_label:'حفظ',primary_action:async values=>{
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
    const d = new frappe.ui.Dialog({title:'إعداد جدول الإقرار',size:'extra-large',fields:[
        {fieldtype:'HTML',options:'صنّف كل مستند مرة واحدة. اعتمد كامل صافي الفاتورة فقط إذا كان الوعاء يخص بندًا واحدًا بالكامل ويطابق نطاق الحسابات المختارة؛ وإلا أدخل الوعاء الصحيح يدويًا. لا يُستنتج الوعاء من السداد. المستند متعدد بنود الإقرار يبقى للمراجعة؛ استخدم الإضافات اليدوية بعد مراجعة توزيعه.'},
        {fieldname:'mapping',label:'تصنيف المستندات الظاهرة',fieldtype:'Table',cannot_add_rows:1,cannot_delete_rows:1,
            data:result.documents.map(r=>({...old.get(r.voucher_type+'|'+r.invoice_no),voucher_type:r.voucher_type,invoice_no:r.invoice_no})),fields:[
                {fieldname:'voucher_type',fieldtype:'Data',label:'النوع',read_only:1,in_list_view:1},
                {fieldname:'invoice_no',fieldtype:'Data',label:'المستند',read_only:1,in_list_view:1},
                {fieldname:'box',fieldtype:'Select',label:'بند الإقرار',in_list_view:1,
                    options:[{label:'غير مصنف',value:''},...Object.entries(taxBoxes).map(([value,label])=>({value,label:value+' — '+label}))]},
                {fieldname:'use_invoice_base',fieldtype:'Check',label:'اعتماد كامل صافي الفاتورة',in_list_view:1},
                {fieldname:'base_amount',fieldtype:'Data',label:'وعاء يدوي (المرتجع بالسالب)',in_list_view:1}]},
        {fieldtype:'Section Break',label:'إضافات يدوية مستقلة — لا تكرر مبالغ المستندات أعلاه'},
        {fieldtype:'HTML',options:'الخانات هنا مبالغ إضافية وليست بديلًا عن الإجماليات المحسوبة. أدخل صفرًا صراحةً للبند غير المستخدم بعد التحقق. مبالغ الاستيراد والخصم والتصحيحات تحتاج مراجعة؛ لا يحسبها التقرير من نسبة مفترضة.'},
        {fieldname:'manual',label:'الإضافات والتعديلات (ريال / عملة الشركة)',fieldtype:'Table',cannot_add_rows:1,cannot_delete_rows:1,
            data:Object.entries(taxBoxes).map(([box,label])=>({box:Number(box),label,...manual.get(Number(box))})),fields:[
                {fieldname:'box',fieldtype:'Int',label:'البند',read_only:1,in_list_view:1},
                {fieldname:'label',fieldtype:'Data',label:'البيان',read_only:1,in_list_view:1},
                ...['amount','adjustment','tax'].map((fieldname,i)=>({fieldname,fieldtype:'Data',
                    label:['إضافة للوعاء','مبلغ تعديل الوعاء','إضافة للضريبة'][i],in_list_view:1}))]},
        {fieldname:'previous_correction',fieldtype:'Data',label:'تصحيح ضريبة فترات سابقة (+ / −)',default:saved.previous_correction},
        {fieldname:'carried_credit',fieldtype:'Data',label:'رصيد ضريبي دائن مرحّل (موجب)',default:saved.carried_credit}
    ],primary_action_label:'حفظ',primary_action:async values=>{
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
    return `<div style="overflow:auto"><table class="table table-bordered" dir="rtl"><thead><tr>${headers.map(h=>`<th>${taxEscape(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
async function taxReconcile() {
    const result = await taxCall('get_review_data');
    const headers=['الحساب','مدين','دائن','صافي الأستاذ','صافي المستندات','المعروض','مخفي بالفلاتر','فرق المطابقة'];
    const rows=result.reconciliation.map(r=>[taxEscape(r.account),...['debit','credit','ledger_tax','document_tax','visible_tax','excluded_by_filters','difference'].map(k=>taxNumber(r[k]))]);
    const details=result.reconciliation_details.map(a=>[taxEscape(a.voucher_type),taxEscape(a.invoice_no),taxEscape(a.account),taxNumber(a.debit),taxNumber(a.credit),taxNumber(a.tax_amount)]);
    taxReviewDialog('مطابقة الأستاذ', '<p>المطابقة تشمل حسابات الشركة والفترة والمستند المختارة قبل فلتر الطرف والمجموعة والصافي الصفري. إخفاء الصفوف ليس فرقًا محاسبيًا. راجع التفاصيل عند وجود فرق.</p>'+taxHtmlTable(headers,rows)+
        '<h5>تفاصيل المستندات ضمن نطاق المطابقة</h5>'+taxHtmlTable(['النوع','المستند','الحساب','مدين','دائن','صافي'],details));
}
async function taxWarnings() {
    const result=await taxCall('get_print_data',{layout:'declaration'});
    const rows=result.warnings.map(r=>[taxEscape(r.voucher_type),taxEscape(r.invoice_no),taxEscape(r.message)]);
    result.declaration.pending.forEach(r=>rows.push([taxEscape(r.voucher_type),taxEscape(r.invoice_no),taxEscape(r.reason)]));
    taxReviewDialog('تنبيهات البيانات',`<p>بنود الإقرار غير المكتملة: ${taxEscape(result.declaration.missing_boxes.join('، ') || 'لا يوجد')}. التنبيهات للمراجعة ولا تغيّر الحساب تلقائيًا.</p>`+
        taxHtmlTable(['النوع','المستند','الملاحظة'],rows));
}
function printTaxReport(layout='summary') {
    const d=new frappe.ui.Dialog({title:layout==='declaration'?'طباعة جدول الإقرار':layout==='detailed'?'طباعة مفصلة':'طباعة مختصرة',
        fields:[{fieldname:'letter_head',fieldtype:'Link',options:'Letter Head',label:__('Letter Head'),
            description:'اختيارية؛ اتركها فارغة للطباعة دون ترويسة'}],primary_action_label:__('Print'),
        primary_action:async values=>{
            const win=window.open('','_blank');
            if(!win){frappe.msgprint('اسمح بالنوافذ المنبثقة للطباعة');return;}
            const filters=taxFilters();d.hide();
            try {
                const response=await frappe.call({method:taxMethod+'get_print_data',args:{filters:JSON.stringify(filters),layout}});
                const result=response.message;
                let head='';
                if(values.letter_head){const r=await frappe.db.get_value('Letter Head',values.letter_head,'content');head=r.message?.content || '';}
                win.document.open();win.document.write(makeTaxPrintHtml(result,head));win.document.close();win.focus();
                await win.document.fonts?.ready;
                await Promise.all([...win.document.images].map(img=>img.complete?Promise.resolve():new Promise(resolve=>{img.onload=resolve;img.onerror=resolve;setTimeout(resolve,5000);}))); 
                win.print();
            } catch(e){win.close();frappe.msgprint({title:'خطأ الطباعة',message:taxEscape(e.message || e),indicator:'red'});}
        }});d.show();
}
function makeTaxPrintHtml(result,letterHeadHtml='') {
    const declaration=result.layout==='declaration';const summary=result.layout==='summary';
    let content='';
    if(declaration){
        const d=result.declaration;
        const body=d.rows.map(r=>`${r.number===1 || r.number===7 ? `<tr class="section"><td colspan="4">${r.number===1?'المبيعات':'المشتريات'}</td></tr>`:''}
            <tr class="${r.is_total?'subtotal':''}"><td>${r.number}. ${taxEscape(r.label)}</td><td class="numeric">${taxNumber(r.amount)}</td><td class="numeric">${taxNumber(r.adjustment)}</td><td class="numeric">${taxNumber(r.tax)}</td></tr>`).join('');
        const foot=[['صافي الضريبة للفترة (مبدئي)',d.current_tax],['تصحيحات الفترات السابقة',d.previous_correction],
            ['الرصيد الدائن المرحّل',d.carried_credit],['صافي الضريبة المستحقة (مبدئي)',d.payable]];
        content=`<table class="declaration"><thead><tr><th>البيان</th><th>المبلغ</th><th>مبلغ التعديل</th><th>مبلغ الضريبة</th></tr></thead><tbody>${body}
            ${foot.map(([label,value],i)=>`<tr class="${i===3?'grand_total':''}"><td>${label}</td><td colspan="3" class="numeric">${taxNumber(value)}</td></tr>`).join('')}</tbody></table>
            <p class="notice">${d.complete?'مكتمل التصنيف حسب المدخلات؛ يحتاج مراجعة قبل التقديم.':'مسودة غير مكتملة: '+d.pending.length+' مستندات تحتاج مراجعة، وبنود غير مكتملة: '+taxEscape(d.missing_boxes.join('، '))}
            ${d.restricted_scope?' — توجد فلاتر تقيد نطاق الإقرار؛ أزل فلاتر الطرف والنوع والمستند، وأظهر الصافي الصفري والفواتير ذات إجمالي الضرائب الصفري لإعداد نطاق أوسع.':''}
            ${result.currency!=='SAR'?' — العملة ليست الريال السعودي؛ لا تعتمد الأرقام للإقرار.':''}</p>`;
    } else {
        const cols=summary?[{fieldname:'invoice_no',label:'نوع المستند'},{fieldname:'net_amount',label:'صافي المبلغ المعروف'},{fieldname:'tax_amount',label:'صافي الضريبة'}]:result.columns;
        const rows=result.data.filter(r=>!summary || ['subtotal','grand_total'].includes(r.row_kind));
        content=`<table><thead><tr>${cols.map(c=>`<th>${taxEscape(c.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr class="${taxEscape(r.row_kind)}">${cols.map(c=>{
            const numeric=['net_amount','tax_amount'].includes(c.fieldname);
            return `<td class="${numeric?'numeric':''}">${numeric?taxNumber(r[c.fieldname]):taxEscape(r.row_kind==='tax_detail'&&c.fieldname==='item_name'?taxCategory(r[c.fieldname]):r[c.fieldname])}</td>`;
        }).join('')}</tr>`).join('')}</tbody></table>`;
    }
    const f=result.filters;const title=declaration?'إقرار ضريبة القيمة المضافة':summary?'ملخص التقرير الضريبي':'التقرير الضريبي المفصل';
    return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>${title}</title><style>
    @page{size:A4 ${declaration||summary?'portrait':'landscape'};margin:12mm}
    body{font-family:Arial,Tahoma,sans-serif;font-size:${declaration||summary?'11':'9'}px;color:#222;direction:rtl}
    h2{text-align:center;font-size:17px;margin:8px}.filters{text-align:center;font-size:10px;margin-bottom:10px}
    table{width:100%;border-collapse:collapse;table-layout:fixed}.declaration th:first-child{width:56%}th,td{border:1px solid #a6b5b5;padding:6px 5px;overflow-wrap:anywhere}
    th{background:#e8f1f1}thead{display:table-header-group}tr{break-inside:avoid}.numeric{text-align:left;direction:ltr;white-space:nowrap}
    .section td{background:${declaration?'#087f7b':'#eee'};color:${declaration?'white':'#222'};font-weight:bold}
    .subtotal td{background:#eef4f7;font-weight:bold;color:#1f77b4}.grand_total td{background:#dff1e9;font-weight:bold}
    .item td,.tax_detail td{color:#666;font-size:9px}.notice{font-size:10px;padding:8px;border:1px solid #d2b16a}
    @media screen{body{font-size:14px;max-width:${declaration?'850':'1200'}px;margin:24px auto}}</style></head><body>
    ${letterHeadHtml?`<div class="letter-head">${letterHeadHtml}</div>`:''}<h2>${title}</h2>
    <div class="filters">${taxEscape(f.company)} | ${taxEscape(f.from_date)} — ${taxEscape(f.to_date)} | العملة: ${taxEscape(result.currency)}<br>
    الحسابات: ${taxEscape((f.tax_accounts||[]).join('، '))}<br>وقت الاستخراج: ${taxEscape(result.generated_at)}<br>
    نطاق العرض: ${taxEscape(f.document_group||'All')} | نوع المستند: ${taxEscape(f.voucher_type||'الكل')} | الطرف: ${taxEscape(f.party||'الكل')} | المستند: ${taxEscape(f.invoice_no||'الكل')}</div>
    ${content}${declaration?'':'<p>صافي الفاتورة كامل وليس موزعًا على الحسابات المختارة. الخانة الفارغة وعاء غير متاح؛ المجاميع تشمل المعروف فقط. تفاصيل الحسابات للشرح ولا تُجمع مرة ثانية.</p>'}
    </body></html>`;
}

})();
