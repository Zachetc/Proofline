"""Strict, deterministic invoice/PO reconciliation. No self-attested evidence verification."""
from decimal import Decimal, InvalidOperation
from datetime import date
from pydantic import BaseModel, Field, ConfigDict

class Invoice(BaseModel):
    model_config=ConfigDict(extra='forbid')
    invoice_id:str=Field(min_length=1,max_length=100)
    vendor_id:str=Field(min_length=1,max_length=100)
    po_id:str=Field(min_length=1,max_length=100)
    amount:Decimal=Field(gt=0,max_digits=14,decimal_places=2)
    currency:str=Field(pattern=r'^[A-Z]{3}$')
    invoice_date:date

class PurchaseOrder(BaseModel):
    model_config=ConfigDict(extra='forbid')
    po_id:str=Field(min_length=1,max_length=100)
    vendor_id:str=Field(min_length=1,max_length=100)
    amount:Decimal=Field(gt=0,max_digits=14,decimal_places=2)
    currency:str=Field(pattern=r'^[A-Z]{3}$')

class ReconcileRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    invoices:list[Invoice]=Field(max_length=1000)
    purchase_orders:list[PurchaseOrder]=Field(max_length=1000)
    paid_invoice_keys:list[str]=Field(default_factory=list,max_length=10000)
    tolerance:Decimal=Field(default=Decimal('0.00'),ge=0,le=1000)

def reconcile(req:ReconcileRequest):
    po_by_id={}
    for po in req.purchase_orders:
        if po.po_id in po_by_id: raise ValueError('Duplicate purchase order IDs in input')
        po_by_id[po.po_id]=po
    paid=set(req.paid_invoice_keys)
    seen=set(); rows=[]
    for inv in req.invoices:
        key=inv.vendor_id+'|'+inv.invoice_id
        flags=[]
        if key in seen:flags.append('DUPLICATE_IN_BATCH')
        if key in paid:flags.append('ALREADY_PAID')
        seen.add(key)
        po=po_by_id.get(inv.po_id)
        if po is None:flags.append('MISSING_PO')
        else:
            if po.vendor_id!=inv.vendor_id:flags.append('VENDOR_MISMATCH')
            if po.currency!=inv.currency:flags.append('CURRENCY_MISMATCH')
            if abs(po.amount-inv.amount)>req.tolerance:flags.append('AMOUNT_MISMATCH')
        rows.append({'key':key,'invoice_id':inv.invoice_id,'vendor_id':inv.vendor_id,'po_id':inv.po_id,
                     'amount':str(inv.amount),'currency':inv.currency,'status':'EXCEPTION' if flags else 'MATCHED','flags':flags})
    from collections import Counter
    c=Counter(x['status'] for x in rows)
    by_currency={}
    for row in rows:
        if row['status']=='EXCEPTION':
            currency=row['currency'];by_currency[currency]=by_currency.get(currency,Decimal('0'))+Decimal(row['amount'])
    reasons=Counter(reason for row in rows for reason in row['flags'])
    vendors=Counter(row['vendor_id'] for row in rows if row['status']=='EXCEPTION')
    return {'summary':{'total':len(rows),'matched':c['MATCHED'],'exceptions':c['EXCEPTION'],
                       'exception_rate':round(c['EXCEPTION']/len(rows),4) if rows else 0,
                       'at_risk_amount':str(next(iter(by_currency.values()))) if len(by_currency)==1 else ('0' if not by_currency else None),
                       'at_risk_by_currency':{k:str(v) for k,v in sorted(by_currency.items())},
                       'top_reasons':[{'code':k,'count':v} for k,v in reasons.most_common(8)],
                       'top_vendors':[{'vendor_id':k,'exceptions':v} for k,v in vendors.most_common(8)]},
            'items':rows,'note':'At-risk amounts are invoice face values grouped by original currency, never FX-converted. They are neither proven fraud nor verified recoverable savings.'}
