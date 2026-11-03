"""Reproducible, 100% synthetic AP fixtures. No external or personal company data."""
from __future__ import annotations
import csv,random
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path

HERE=Path(__file__).resolve().parent

def generate(count=500,seed=20261103):
    rng=random.Random(seed);invoices=[];orders=[]
    for n in range(1,count+1):
        vendor=f'VEND-{n%36+1:03d}'
        po=f'PO-{n:06d}'
        amount=Decimal(rng.randrange(35000,2850000))/100
        orders.append({'po_id':po,'vendor_id':vendor,'amount':str(amount),'currency':'USD'})
        inv={'invoice_id':f'INV-{n:06d}','vendor_id':vendor,'po_id':po,'amount':str(amount),'currency':'USD','invoice_date':(date(2026,9,1)+timedelta(days=n%61)).isoformat()}
        # Independent reason codes can overlap. Duplicates intentionally repeat prior invoice IDs.
        if n%17==0:inv['invoice_id']=invoices[-1]['invoice_id'];inv['vendor_id']=invoices[-1]['vendor_id']
        if n%19==0:inv['amount']=str(amount+Decimal('175.00'))
        if n%23==0:inv['vendor_id']='VENDOR-UNRECOGNIZED'
        if n%29==0:inv['po_id']='PO-NOT-IN-SYSTEM'
        if n%31==0:inv['currency']='EUR'
        invoices.append(inv)
    return invoices,orders

if __name__=='__main__':
    inv,pos=generate()
    for name,rows in [('invoices_large.csv',inv),('purchase_orders_large.csv',pos)]:
        with (HERE/name).open('w',newline='',encoding='utf8') as f:
            w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    print('Wrote',len(inv),'synthetic invoices and',len(pos),'synthetic purchase orders')
