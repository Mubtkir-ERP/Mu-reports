// Template compiler follows Frappe version-15 microtemplate.js (MIT, John Resig / Frappe).
const fs=require('fs');const vm=require('vm');const assert=require('assert');
const trans={}; // Localization is supplied by Frappe at runtime.
trans['Export Excel']='تصدير Excel'; trans['Total Sales Invoices']='إجمالي فواتير المبيعات'; trans['Sales Invoice']='فاتورة مبيعات';
let lang='en';global.__=(text,args=[])=>{let s=lang==='ar'?(trans[text]||text):text;return s.replace(/\{(\d+)\}/g,(_,n)=>args[n]??'');};
const escape=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
global.frappe={utils:{is_rtl:()=>lang==='ar',escape_html:escape},format:v=>v===''?'':Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})};
function compile(str){
 str=str.replace(/{{/g,'{%=').replace(/}}/g,'%}');
 const code="var _p=[],print=function(){_p.push.apply(_p,arguments)};with(obj){\n_p.push('"+str.replace(/[\r\t\n]/g,' ').split('{%').join('\t').replace(/((^|%})[^\t]*)'/g,'$1\r').replace(/\t=(.*?)%}/g,"',$1,'").split('\t').join("');\n").split('%}').join("\n_p.push('").split('\r').join("\\'")+"');}return _p.join('');";
 return new Function('obj',code);
}
const root=require('path').resolve(__dirname,'..');
const formats=JSON.parse(fs.readFileSync(root+'/mu_reports/fixtures/print_format.json','utf8'));
for(lang of ['en','ar']){
 const rows=[{row_kind:'document',invoice_no:'SI-TEST',voucher_type:'Sales Invoice',voucher_type_label:__('Sales Invoice'),party:'CUST-TEST',party_name:'Customer Display Name',net_amount:20000,tax_amount:3000},{row_kind:'subtotal',invoice_no:__('Total Sales Invoices'),net_amount:20000,tax_amount:3000},{row_kind:'grand_total',invoice_no:'Grand Total',net_amount:20000,tax_amount:3000,_tax_print:{filters:{company:'Test',tax_accounts:['VAT']},currency:'SAR',declaration:{rows:[{number:1,label:'Test',amount:20000,adjustment:0,tax:3000}],current_tax:3000,previous_correction:0,carried_credit:0,payable:3000,complete:true,pending:[],missing_boxes:[]}}}]; const data={original_data:rows,data:rows,filters:{}};
 for(const pf of formats){
  const html=compile(pf.html)(data);const suffix=pf.name.endsWith('Summary')?'summary':pf.name.endsWith('Detailed')?'detailed':'declaration';
  assert(!html.includes('{%=')&&!html.includes('{%')&&!html.includes('{{'));
  assert(html.includes('dir="'+(lang==='ar'?'rtl':'ltr')+'"'));
  assert(html.includes('3,000.00'));
  if(lang==='ar')assert(!html.includes('Total Sales Invoices')&&!html.includes('Sales Invoices'));
  if(suffix==='summary')assert(html.includes(lang==='ar'?'إجمالي فواتير المبيعات':'Total Sales Invoices'));
  if(suffix==='detailed'){assert(html.includes('Customer Display Name'));assert(!html.includes('CUST-TEST'));assert.strictEqual((html.match(/<th>/g)||[]).length,7);} 
  if(suffix==='detailed')assert(html.includes(lang==='ar'?'فاتورة مبيعات':'Sales Invoice'));
  const escaped=structuredClone(data);escaped.original_data.at(-1)._tax_print.filters.company='<script>bad()</script>';
  assert(!compile(pf.html)(escaped).includes('<script>bad()</script>'));

 }
}
// Test client integration without a Frappe site. No custom print buttons may be installed.
const script=fs.readFileSync(root+'/mu_reports/mu_reports/report/all_tax_report/all_tax_report.js','utf8');
const buttons=[];const filters={company:'Co',from_date:'2026-10-01',to_date:'2026-10-31',tax_accounts:['VAT']};
const settings={};const events=[];
let toolbarButtons=[];
const toolbar={find:()=>({length:toolbarButtons.filter(b=>b.marker==='1').length,
 text(label){toolbarButtons.filter(b=>b.marker==='1').forEach(b=>b.label=label);return this;},attr(){return this;}}),removeClass(){return this;}};
const report={report_name:'All Tax Report',_no_refresh:true,page:{inner_toolbar:toolbar,add_inner_button:(...a)=>{
 buttons.push(a);const b={label:a[0],marker:null};toolbarButtons.push(b);return {attr(k,v){if(k==='data-tax-export')b.marker=v;return this;}};
}},
 get_filter_values:()=>filters,get_filter:field=>({set_value:async val=>{filters[field]=val}}),refresh:async()=>{toolbarButtons=[];},
 print_report:async s=>events.push(['print',s]),pdf_report:async s=>events.push(['pdf',s])};
const context={console,__:global.__,localStorage:{getItem:()=>null},frappe:{...global.frappe,boot:{lang:'en'},query_reports:{},query_report:report,session:{user:'test'},
 datetime:{month_start:()=>'',get_today:()=>''},defaults:{get_user_default:()=>''},call:async args=>{events.push(args);return {message:{header:'<h1>Rendered</h1>'}};}}};
vm.createContext(context);vm.runInContext(script,context);vm.runInContext(script,context);
(async()=>{
 await context.frappe.query_reports['All Tax Report'].onload(report);
 assert(!buttons.some(b=>/Print|طباعة/.test(b[0])));
 assert(events.length===0);
 await report.print_report({with_letter_head:1,letter_head_name:'Test Head'});
 assert(events[0].method.endsWith('render_report_letter_head'));
 assert(events[1][1].letter_head.header==='<h1>Rendered</h1>');
 const count=events.length;await report.pdf_report({with_letter_head:0});assert(events.length===count+1);
 for(lang of ['ar','en','ar']) {
  await report.refresh();
  assert.strictEqual(toolbarButtons.filter(b=>b.marker==='1').length,1);
  assert.strictEqual(toolbarButtons.find(b=>b.marker==='1').label,global.__('Export Excel'));
  await report.refresh();assert.strictEqual(toolbarButtons.filter(b=>b.marker==='1').length,1);
 }
 report.report_name='Other Report';await report.print_report({with_letter_head:1,letter_head_name:'Other Head'});assert(events.at(-1)[0]==='print');
 await report.refresh();assert.strictEqual(toolbarButtons.length,0);
 console.log('PASS: all native JS templates compile/render in Arabic and English, language directions, translated types/totals, numeric totals, escaping, repeated script loading, no custom print buttons, native Print/PDF letter-head delegation and other-report isolation.');
})().catch(e=>{console.error(e);process.exitCode=1;});
