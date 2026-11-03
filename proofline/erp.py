"""Read-only AP extraction from ERP APIs. No payment initiation or guessed PO relationships.

OAuth2 access tokens are supplied by a separately authorized credential manager via
PROOFLINE_ERP_CONNECTIONS. No OAuth secret/token is ever returned by the API.
"""
from __future__ import annotations
import json, os, re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from typing import Literal
import httpx
from pydantic import BaseModel, ConfigDict, Field
from .reconcile import ReconcileRequest, reconcile

class ERPError(ValueError): pass

class ERPRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    provider:Literal['xero','quickbooks','business_central']
    # Explicit invoice ID -> PO number mapping supplied by a trusted operator;
    # this is not a verified linkage and should be reviewed before payment.
    invoice_po_links:dict[str,str]=Field(default_factory=dict,max_length=1000)
    tolerance:Decimal=Field(default=Decimal('0'),ge=0,le=1000)


def connection_for(tenant:str,provider:str)->dict:
    try: data=json.loads(os.environ.get('PROOFLINE_ERP_CONNECTIONS','{}'))
    except ValueError:raise ERPError('Invalid ERP connection configuration')
    config=data.get(tenant,{}).get(provider) if isinstance(data,dict) else None
    if not isinstance(config,dict): raise ERPError('ERP connection not configured for this tenant and provider')
    if not isinstance(config.get('access_token'),str) or len(config['access_token'])<8:
        raise ERPError('Missing ERP access token')
    return config


def clean_id(v,field):
    value=str(v or '').strip()
    if not value or len(value)>100:raise ERPError(f'ERP record missing valid {field}')
    return value


def amount(v):
    try:
        d=Decimal(str(v));
        if not d.is_finite() or d<=0 or d.as_tuple().exponent < -2 or d>Decimal('999999999999.99'):
            raise ERPError('ERP record contains invalid monetary amount')
        return str(d)
    except (InvalidOperation,ValueError,TypeError):raise ERPError('ERP record contains invalid monetary amount')


def iso_date(v):
    if not v:raise ERPError('ERP invoice missing date')
    s=str(v)
    if s.startswith('/Date('):
        m=re.match(r'/Date\((-?\d+)',s)
        if not m:raise ERPError('Invalid ERP date')
        from datetime import datetime,timezone
        return datetime.fromtimestamp(int(m[1])/1000,timezone.utc).date().isoformat()
    try:return date.fromisoformat(s[:10]).isoformat()
    except ValueError:raise ERPError('Invalid ERP date')


def currency(code):
    v=str(code or 'USD').strip().upper()
    if not re.fullmatch(r'[A-Z]{3}',v):raise ERPError('Invalid currency code')
    return v


def unlinked(invoice_id):return 'UNLINKED:'+invoice_id


def normalize_xero(bills,orders,links):
    inv=[];po=[];paid=[]
    for row in orders:
        if not isinstance(row,dict):raise ERPError('Malformed purchase order')
        if str(row.get('Status','')).upper() in {'DELETED','VOIDED'}:continue
        po.append(dict(po_id=clean_id(row.get('PurchaseOrderNumber') or row.get('PurchaseOrderID'),'PO number'),vendor_id=clean_id((row.get('Contact') or {}).get('ContactID'),'vendor'),amount=amount(row.get('Total')),currency=currency(row.get('CurrencyCode'))))
    for row in bills:
        if not isinstance(row,dict):raise ERPError('Malformed bill')
        if str(row.get('Type','')).upper()!='ACCPAY':continue # not sales invoices
        if str(row.get('Status','')).upper() in {'VOIDED','DELETED'}:continue
        record_id=clean_id(row.get('InvoiceID'),'invoice key')
        invoice_id=clean_id(row.get('InvoiceNumber') or record_id,'invoice number')
        vendor=clean_id((row.get('Contact') or {}).get('ContactID'),'vendor')
        po_ref=links.get(record_id) or links.get(invoice_id)
        inv.append(dict(invoice_id=invoice_id,vendor_id=vendor,po_id=po_ref or unlinked(invoice_id),amount=amount(row.get('Total')),currency=currency(row.get('CurrencyCode')),invoice_date=iso_date(row.get('DateString') or row.get('Date'))))
        if str(row.get('Status','')).upper()=='PAID':paid.append(vendor+'|'+invoice_id)
    return inv,po,paid


def normalize_quickbooks(bills,orders,links):
    inv=[];po=[];paid=[]
    for row in orders:
        if not isinstance(row,dict):raise ERPError('Malformed purchase order')
        po.append(dict(po_id=clean_id(row.get('DocNumber') or row.get('Id'),'PO number'),vendor_id=clean_id((row.get('VendorRef') or {}).get('value'),'vendor'),amount=amount(row.get('TotalAmt')),currency=currency((row.get('CurrencyRef') or {}).get('value') or 'USD')))
    for row in bills:
        if not isinstance(row,dict):raise ERPError('Malformed bill')
        rid=clean_id(row.get('Id'),'bill ID')
        invoice_id=clean_id(row.get('DocNumber') or rid,'bill number')
        vendor=clean_id((row.get('VendorRef') or {}).get('value'),'vendor')
        # LinkedTxn is a transaction ID, not always the displayed PO number.
        po_ref=links.get(rid) or links.get(invoice_id)
        inv.append(dict(invoice_id=invoice_id,vendor_id=vendor,po_id=po_ref or unlinked(invoice_id),amount=amount(row.get('TotalAmt')),currency=currency((row.get('CurrencyRef') or {}).get('value') or 'USD'),invoice_date=iso_date(row.get('TxnDate'))))
        if Decimal(str(row.get('Balance',row.get('TotalAmt'))))==0:paid.append(vendor+'|'+invoice_id)
    return inv,po,paid


def normalize_business_central(bills,orders,links):
    inv=[];po=[];paid=[]
    for row in orders:
        if not isinstance(row,dict):raise ERPError('Malformed PO')
        po.append(dict(po_id=clean_id(row.get('number'),'PO number'),vendor_id=clean_id(row.get('vendorNumber') or row.get('vendorId'),'vendor'),amount=amount(row.get('totalAmountIncludingTax')),currency=currency(row.get('currencyCode') or 'USD')))
    for row in bills:
        if not isinstance(row,dict):raise ERPError('Malformed purchase invoice')
        rid=clean_id(row.get('id'),'invoice record ID')
        invoice_id=clean_id(row.get('vendorInvoiceNumber') or row.get('number') or rid,'vendor invoice number')
        vendor=clean_id(row.get('vendorNumber') or row.get('vendorId'),'vendor')
        po_ref=links.get(rid) or links.get(invoice_id) or row.get('orderNumber')
        inv.append(dict(invoice_id=invoice_id,vendor_id=vendor,po_id=po_ref or unlinked(invoice_id),amount=amount(row.get('totalAmountIncludingTax')),currency=currency(row.get('currencyCode') or 'USD'),invoice_date=iso_date(row.get('invoiceDate'))))
        if str(row.get('status','')).upper()=='PAID':paid.append(vendor+'|'+invoice_id)
    return inv,po,paid


async def fetch_erp(tenant:str,req:ERPRequest,transport=None):
    cfg=connection_for(tenant,req.provider)
    token=cfg['access_token']
    headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
    invoice_rows=[];order_rows=[]
    async with httpx.AsyncClient(timeout=20,transport=transport,follow_redirects=False) as client:
        async def get(url,params=None,extra=None):
            try:
                res=await client.get(url,params=params,headers={**headers,**(extra or {})})
                if res.status_code in (401,403):raise ERPError('ERP authorization failed; refresh the server-side connection')
                if res.status_code==429:raise ERPError('ERP rate limit reached; retry after provider reset')
                if res.status_code>=300:raise ERPError('ERP read failed (HTTP '+str(res.status_code)+')')
                body=res.json()
                if not isinstance(body,dict):raise ERPError('Invalid ERP JSON response')
                return body
            except (httpx.TransportError,ValueError) as exc:
                if isinstance(exc,ERPError):raise
                raise ERPError('ERP network or payload error') from None
        if req.provider=='xero':
            xid=clean_id(cfg.get('tenant_id'),'Xero tenant ID')
            h={'xero-tenant-id':xid}
            base='https://api.xero.com/api.xro/2.0/'
            # Xero uses separate paged calls for Accounts Payable bills and purchase orders.
            for path,key,dest in [('Invoices','Invoices',invoice_rows),('PurchaseOrders','PurchaseOrders',order_rows)]:
                for page in range(1,21):
                    payload=await get(base+path,{'page':page},h)
                    data=payload.get(key,[])
                    if not isinstance(data,list):raise ERPError('Malformed ERP records')
                    dest.extend(data)
                    if len(dest)>1000:raise ERPError('ERP batch exceeds 1000 record safety cap')
                    if len(data)<100:break
                else:raise ERPError('ERP pagination safety cap reached')
            invoices,orders,paid=normalize_xero(invoice_rows,order_rows,req.invoice_po_links)
        elif req.provider=='quickbooks':
            realm=clean_id(cfg.get('realm_id'),'QuickBooks realm')
            if not re.fullmatch(r'\d+',realm):raise ERPError('Invalid QuickBooks realm')
            base='https://sandbox-quickbooks.api.intuit.com' if cfg.get('sandbox') is True else 'https://quickbooks.api.intuit.com'
            endpoint=f'{base}/v3/company/{realm}/query'
            for entity,dest in [('Bill',invoice_rows),('PurchaseOrder',order_rows)]:
                for start in range(1,1002,100):
                    statement=f'SELECT * FROM {entity} STARTPOSITION {start} MAXRESULTS 100'
                    body=await get(endpoint,{'query':statement,'minorversion':'75'})
                    data=(body.get('QueryResponse') or {}).get(entity,[])
                    if not isinstance(data,list):raise ERPError('Malformed ERP records')
                    dest.extend(data)
                    if len(dest)>1000:raise ERPError('ERP batch exceeds 1000 record safety cap')
                    if len(data)<100:break
                else:raise ERPError('ERP pagination safety cap reached')
            invoices,orders,paid=normalize_quickbooks(invoice_rows,order_rows,req.invoice_po_links)
        else:
            directory=clean_id(cfg.get('directory_id'),'Azure directory')
            company=clean_id(cfg.get('company_id'),'Business Central company')
            environment=clean_id(cfg.get('environment'),'Business Central environment')
            for v in (directory,company,environment):
                if not re.fullmatch(r'[A-Za-z0-9_-]+',v):raise ERPError('Invalid Business Central identifier')
            base=f'https://api.businesscentral.dynamics.com/v2.0/{directory}/{environment}/api/v2.0/companies({company})/'
            for path,dest in [('purchaseInvoices',invoice_rows),('purchaseOrders',order_rows)]:
                url=base+path+'?$top=100'
                for _ in range(11):
                    body=await get(url)
                    data=body.get('value',[])
                    if not isinstance(data,list):raise ERPError('Malformed ERP records')
                    dest.extend(data)
                    if len(dest)>1000:raise ERPError('ERP batch exceeds 1000 record safety cap')
                    url=body.get('@odata.nextLink')
                    if not url:break
                    parsed=urlparse(url)
                    if parsed.scheme!='https' or parsed.netloc!='api.businesscentral.dynamics.com' or not url.startswith(base+path):
                        raise ERPError('Unsafe ERP pagination URL')
                else:raise ERPError('ERP pagination safety cap reached')
            invoices,orders,paid=normalize_business_central(invoice_rows,order_rows,req.invoice_po_links)
    if len(invoices)>1000 or len(orders)>1000:raise ERPError('ERP batch exceeds 1000 record safety cap')
    payload=ReconcileRequest.model_validate(dict(invoices=invoices,purchase_orders=orders,paid_invoice_keys=paid,tolerance=req.tolerance))
    result=reconcile(payload)
    # Distinguish absence of upstream linkage from confirmed fraud or mismatch.
    result['source']={'provider':req.provider,'tenant':tenant,'read_only':True,'upstream_invoices':len(invoice_rows),'upstream_purchase_orders':len(order_rows),'manual_links':len(req.invoice_po_links),'credential_scope':'server_side'}
    result['interpretation']='ERP live read when configured; unmatched purchase order references may reflect absent source links, not missing commercial documents.'
    return result
