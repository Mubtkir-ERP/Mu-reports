import ast, copy, datetime, io, json, sys, types
from pathlib import Path
from openpyxl import load_workbook
class D(dict):
    __getattr__=dict.get
    __setattr__=dict.__setitem__
class E:
    def __init__(self,fn):self.fn=fn
    def __eq__(self,x):return E(lambda r:self.fn(r)==x)
    def __ge__(self,x):return E(lambda r:self.fn(r)>=x)
    def __le__(self,x):return E(lambda r:self.fn(r)<=x)
    def isin(self,x):return E(lambda r:self.fn(r) in x)
class T:
    def __getattr__(self,k):return E(lambda r:r.get(k))
class Q:
    def from_(self,*a):self.conditions=[];return self
    def select(self,*a):return self
    def where(self,x):self.conditions.append(x);return self
    def run(self,**kw):return [r for r in gl if all(e.fn(r) for e in self.conditions)]
gl=[]
def add(t,n,d,c,a='VAT',company='Co',cancelled=0):
    gl.append(D(voucher_type=t,voucher_no=n,debit=d,credit=c,account=a,company=company,
                is_cancelled=cancelled,posting_date='2026-10-08',party='',party_type=''))
add('Sales Invoice','SAME',0,100);add('Sales Invoice','SAME',0,50)
add('Sales Invoice','SR',15,0);add('Purchase Invoice','PI',75,0);add('Purchase Invoice','PR',0,7.5)
add('Payment Entry','SAME',0,12);add('Vouchers Entry','VE',9,0)
add('Journal Entry','JE',20,0);add('Journal Entry','JE',0,5)
add('Journal Entry','ZERO',30,0);add('Journal Entry','ZERO',0,30,'VAT2')
add('Stock Entry','OTHER',0,4)
add('Sales Invoice','CANCELLED',0,999,cancelled=1)
add('Sales Invoice','FOREIGN',0,999,company='Other')
add('Payment Entry','SETTLEMENT',0,1000,'Bank')
fixtures={
'Account':[D(name='VAT',company='Co',is_group=0),D(name='VAT2',company='Co',is_group=0)],
'Sales Invoice':[D(name='SAME',base_net_total=1000,customer='C',is_return=0,docstatus=1),
D(name='SR',base_net_total=-100,customer='C',is_return=1,docstatus=1),
D(name='ZERO-INVOICE',base_net_total=250,customer='C',is_return=0,docstatus=1,total_taxes_and_charges=0,company='Co',posting_date='2026-10-08')],
'Purchase Invoice':[D(name='PI',base_net_total=500,supplier='S',is_return=0,docstatus=1),D(name='PR',base_net_total=-50,supplier='S',is_return=1,docstatus=1)],
'Payment Entry':[D(name='SAME',payment_type='Pay',docstatus=1)],'Vouchers Entry':[D(name='VE',payment_type='Receive',docstatus=1)],
'Journal Entry':[D(name='JE',docstatus=1),D(name='ZERO',docstatus=1)],'Customer':[D(name='C',customer_name='Customer Display Name',tax_id='310123456700003')],
'Supplier':[D(name='S',supplier_name='Supplier Display Name',tax_id='310123456700003')],
'Sales Invoice Item':[D(parent='SAME',item_name='Item')], 'Purchase Invoice Item':[],'GL Entry':gl}
def match(r,filters):
    for k,v in filters.items():
        if isinstance(v,list):
            op,x=v
            if op=='in' and r.get(k) not in x:return False
            if op=='!=' and r.get(k)==x:return False
            if op=='between' and not x[0]<=r.get(k,'')<=x[1]:return False
        elif r.get(k)!=v:return False
    return True
def get_all(t,filters,fields=None,pluck=None,**kw):
    rows=[r for r in fixtures.get(t,[]) if match(r,filters)]
    return [r[pluck] for r in rows] if pluck else rows
f=types.ModuleType('frappe');f._dict=D;f._=lambda x:x;f.qb=Q();f.PermissionError=PermissionError
f.db=D(exists=lambda dt,t:t in fixtures,get_value=lambda *a:'SAR');f.has_permission=lambda *a:True
f.get_all=get_all;f.get_meta=lambda t:D(has_field=lambda k:True)
f.throw=lambda m,*a:(_ for _ in ()).throw(ValueError(m));f.whitelist=lambda:lambda x:x;f.local=D(response=D())
sys.modules['frappe']=f
u=types.ModuleType('frappe.utils');u.flt=lambda v:float(v or 0);u.cint=lambda v:int(v or 0)
u.getdate=lambda s:datetime.date.fromisoformat(s);u.now_datetime=lambda:datetime.datetime(2026,10,8,12,0)
sys.modules['frappe.utils']=u
q=types.ModuleType('frappe.query_builder');q.DocType=lambda x:T();sys.modules['frappe.query_builder']=q
qr=types.ModuleType('frappe.desk.query_report');qr.get_report_doc=lambda x:True;sys.modules['frappe.desk.query_report']=qr
root=Path(__file__).resolve().parents[1]
p=root/'mu_reports/mu_reports/report/all_tax_report/all_tax_report.py'
ns={};exec(compile(p.read_text(encoding='utf-8'),str(p),'exec'),ns)
base={'company':'Co','tax_accounts':['VAT','VAT2'],'from_date':'2026-10-01','to_date':'2026-10-31','include_zero_tax':1,'show_items':1,'show_tax_details':1,
      'account_classification':[{'account':'VAT','category':'Output'},{'account':'VAT2','category':'Adjustment'}]}
r=ns['get_review_data'](base)
docs={(r['voucher_type'],r['invoice_no']):r for r in r['documents']}
assert len(docs)==9 and ('Payment Entry','SETTLEMENT') not in docs
expected={('Sales Invoice','SAME'):150,('Sales Invoice','SR'):-15,('Purchase Invoice','PI'):-75,('Purchase Invoice','PR'):7.5,
('Payment Entry','SAME'):12,('Vouchers Entry','VE'):-9,('Journal Entry','JE'):-15,('Journal Entry','ZERO'):0,('Stock Entry','OTHER'):4}
for key,tax in expected.items():assert docs[key]['tax_amount']==tax
assert r['summary']['net']==59.5 and r['data'][-1]['tax_amount']==59.5
assert r['data'][-1]['net_amount']==450
assert all(a['difference']==0 for a in r['reconciliation'])
assert docs[('Payment Entry','SAME')]['net_amount'] is None
assert docs[('Purchase Invoice','PR')]['net_amount']==50
assert docs[('Stock Entry','OTHER')]['section_key']=='Other'
assert len([x for x in r['data'] if x['row_kind']=='item'])==1
assert len(docs[('Journal Entry','ZERO')]['account_details'])==2
r2=ns['get_review_data']({**base,'document_group':'Sales','include_zero_tax':0})
assert r2['summary']['net']==135 and len(r2['documents'])==2
assert all(a['difference']==0 for a in r2['reconciliation'])
assert sum(a['excluded_by_filters'] for a in r2['reconciliation'])==-75.5
assert len(r2['reconciliation_details'])>len(r2['documents'])
r3=ns['get_review_data']({**base,'include_non_taxed':1})
assert len(r3['documents'])==10 and r3['summary']['net']==59.5
assert ns['get_print_data'](base)['layout']=='summary'
assert ns['get_print_data'](base,'detailed')['layout']=='detailed'
assert len(ns['execute'](base))==6
for bad in ({**base,'company':''},{**base,'tax_accounts':['Bad']},{**base,'from_date':'2026-11-01'}):
    try:ns['get_review_data'](bad);raise AssertionError('expected rejection')
    except ValueError:pass
preview_docs=[{'voucher_type':'Sales Invoice','invoice_no':'SI','net_amount':120000,'tax_amount':18000},
              {'voucher_type':'Purchase Invoice','invoice_no':'PI','net_amount':-100000,'tax_amount':-15000}]
settings=D(declaration_mapping=[{'voucher_type':'Sales Invoice','invoice_no':'SI','box':1,'use_invoice_base':1},
                               {'voucher_type':'Purchase Invoice','invoice_no':'PI','box':7,'use_invoice_base':1}],
           declaration_manual=[{'box':n,'amount':0,'adjustment':0,'tax':0} for n in ns['RETURN_LABELS']],
           previous_correction=0,carried_credit=0)
d=ns['_declaration'](preview_docs,settings)
assert d['complete'] and d['payable']==3000 and len(d['rows'])==12
assert d['rows'][0]['amount']==120000 and d['rows'][6]['amount']==100000
assert not ns['_declaration'](preview_docs,D())['complete']
assert ns['_declaration'](preview_docs,D(declaration_mapping=settings.declaration_mapping))['payable']==3000
bad=copy.deepcopy(settings);bad.declaration_mapping.append(bad.declaration_mapping[0])
try:ns['_declaration'](preview_docs,bad);raise AssertionError()
except ValueError:pass
for invalid in ('NaN','Infinity','abc'):
    try:ns['_finite'](invalid);raise AssertionError()
    except ValueError:pass
# Return bases remain negative in their respective declaration category.
return_docs=[{'voucher_type':'Purchase Invoice','invoice_no':'PR','net_amount':50,'tax_amount':7.5}]
dret=ns['_declaration'](return_docs,D(declaration_mapping=[{'voucher_type':'Purchase Invoice','invoice_no':'PR','box':7,'use_invoice_base':1}]))
assert dret['rows'][6]['amount']==-50 and dret['rows'][6]['tax']==-7.5
ns['export_excel'](base)
wb=load_workbook(io.BytesIO(f.local.response.filecontent))
assert len(wb.sheetnames)==6 and 'VAT Return' in wb.sheetnames
assert not any(c.data_type=='f' for ws in wb for row in ws for c in row)
assert wb['Report'].cell(wb['Report'].max_row,9).value==59.5
# Preview uses the actual HTML generator, not a generated concept image.
preview=ns['get_print_data'](base,'declaration');preview['declaration']=d
preview['declaration']['restricted_scope']=False
preview['filters']['company']='شركة المثال'

for x in root.rglob('*.py'):ast.parse(x.read_text(encoding='utf-8-sig'),filename=str(x))
for x in root.rglob('*.json'):json.loads(x.read_text(encoding='utf-8-sig'))
print('PASS: full mocked report pipeline, GL signs, cancellation/company/date/account scope, duplicate voucher names across types, zero transfers, unknown GL types, returns, item/detail totals, classifications, filtered reconciliation, non-taxed invoices, declaration/manual bases, validation, XLSX sheets and numeric/formula safety, Python/JSON syntax.')

# Cards removed; native formats receive one non-circular metadata snapshot.
result=ns['execute'](base)
assert result[4]==[]
assert result[1][-1]['_tax_print']['currency']=='SAR'
assert result[1][-1]['_tax_print']['declaration']['restricted_scope']
assert result[0][1]['fieldname']=='voucher_type_label'
assert docs[('Sales Invoice','SAME')]['voucher_type']=='Sales Invoice'
# Language switches in the same process must not reuse module-import translations.
import csv
translation_path=root/'mu_reports/translations/ar.csv'
translations={row[0]:row[1] for row in csv.reader(translation_path.open(encoding='utf-8-sig')) if len(row)>1}
ns['_']=lambda text:translations.get(text,text)
ar_result=ns['execute'](base)
assert ar_result[4]==[]
ar_docs=[r for r in ar_result[1] if r['row_kind']=='document']
assert next(r for r in ar_docs if r['voucher_type']=='Sales Invoice')['voucher_type_label']=='فاتورة مبيعات'
assert next(r for r in ar_result[1] if r['row_kind']=='section')['invoice_no']=='فواتير المبيعات'
assert any(r.get('invoice_no')=='إجمالي فواتير المبيعات' for r in ar_result[1])
assert ar_result[1][-1]['invoice_no']=='المجموع الإجمالي'
assert ar_result[1][-1]['_tax_print']['declaration']['rows'][0]['label']=='المبيعات الخاضعة للنسبة الأساسية'
ns['_']=lambda text:text
assert next(r for r in ns['execute'](base)[1] if r['row_kind']=='section')['invoice_no']=='Sales Invoices'
# Native Letter Head content is rendered as Jinja server-side, never copied raw.
head=D(content='{% set title = doc.company %}<h1>{{ title }}</h1>',footer='<p>{{ filters.company }}</p>',check_permission=lambda p:None)
f.get_doc=lambda dt,name:head
render_calls=[]
def render_fixture(text,context):
    render_calls.append((text,context))
    assert context['doc'].company=='Co' and context['filters'].company=='Co'
    return '<h1>Co</h1>' if text==head.content else '<p>Co</p>'
f.render_template=render_fixture
rendered=ns['render_report_letter_head'](base,'Test Head')
assert len(render_calls)==2
assert rendered['header']=='<h1>Co</h1>' and rendered['footer']=='<p>Co</p>'
assert '{{' not in rendered['header'] and '{%' not in rendered['header']
assert ns['render_report_letter_head'](base,None)=={}
formats=json.loads((root/'mu_reports/fixtures/print_format.json').read_text(encoding='utf-8'))
assert len(formats)==3 and all(r['print_format_for']=='Report' and r['print_format_type']=='JS' and r['report']=='All Tax Report' for r in formats)
assert formats[0]['html']==(root/'mu_reports/mu_reports/report/all_tax_report/all_tax_report.html').read_text(encoding='utf-8')
print('PASS: no summary cards, raw/translated voucher types, per-request Arabic/English labels, native format registration/default, server letter-head renderer delegation (mocked).')

name_rows=[r for r in ns['execute'](base)[1] if r['row_kind']=='document']
assert next(r for r in name_rows if r['voucher_type']=='Sales Invoice')['party_name']=='Customer Display Name'
assert next(r for r in name_rows if r['voucher_type']=='Purchase Invoice')['party_name']=='Supplier Display Name'
print('PASS: customer/supplier display names resolved independently of party IDs.')
