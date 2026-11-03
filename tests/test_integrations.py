from __future__ import annotations
import asyncio, base64, hashlib, json
import httpx, pytest
from datetime import date
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from proofline.documents import DocumentRequest,verify_document
from proofline.erp import ERPError, ERPRequest,fetch_erp, normalize_xero,normalize_quickbooks,normalize_business_central
from proofline.reconcile import ReconcileRequest,reconcile
from proofline.store import Store


def signed_doc():
    key=Ed25519PrivateKey.generate()
    raw=b'{"invoice_id":"INV-1","vendor_id":"V1","po_id":"PO-1","amount":"100.00","currency":"USD","invoice_date":"2026-11-03"}'
    public=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
    body=DocumentRequest(document_b64=base64.b64encode(raw).decode(),expected_sha256=hashlib.sha256(raw).hexdigest(),key_id='vendor-key-1',signature_b64=base64.b64encode(key.sign(raw)).decode(),filename='invoice.json')
    return raw,body,public

def test_crypto_signature_positive_and_fail_closed(monkeypatch):
    raw,body,public=signed_doc()
    monkeypatch.setenv('PROOFLINE_TRUSTED_DOCUMENT_KEYS',json.dumps({'t':{'vendor-key-1':public}}))
    result=verify_document('t',body)
    assert result['status']=='VERIFIED_SIGNATURE' and result['signature_valid']
    assert verify_document('other',body)['status']=='UNVERIFIED'
    assert verify_document('t',body.model_copy(update={'expected_sha256':'a'*64}))['status']=='FAILED'
    altered=body.model_copy(update={'document_b64':base64.b64encode(raw+b' ').decode(),'expected_sha256':hashlib.sha256(raw+b' ').hexdigest()})
    assert verify_document('t',altered)['status']=='FAILED'
    assert verify_document('t',body.model_copy(update={'signature_b64':None,'key_id':None}))['status']=='UNVERIFIED'
    assert verify_document('t',body.model_copy(update={'filename':'invoice.pdf'}))['status']=='FAILED'


def test_attestation_is_transactionally_tenant_scoped(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import proofline.api as api
    raw,doc,public=signed_doc()
    monkeypatch.setenv('PROOFLINE_TRUSTED_DOCUMENT_KEYS',json.dumps({'org-a':{'vendor-key-1':public}}))
    monkeypatch.setenv('PROOFLINE_TENANT_KEYS',json.dumps({'org-a':'secret-a','org-b':'secret-b'}))
    monkeypatch.delenv('PROOFLINE_API_KEY',raising=False)
    monkeypatch.setenv('PROOFLINE_DB',str(tmp_path/'db.sqlite'))
    import importlib;importlib.reload(api)
    c=TestClient(api.app)
    payload={'evidence_id':'signed-1','document':doc.model_dump()}
    assert c.post('/v1/documents/attest',json=payload,headers={'X-Tenant-ID':'org-b','Authorization':'Bearer secret-a'}).status_code==401
    h={'X-Tenant-ID':'org-a','Authorization':'Bearer secret-a'}
    a=c.post('/v1/documents/attest',json=payload,headers=h)
    assert a.status_code==201,a.text
    assert a.json()['invoice_id']=='INV-1'
    assert c.post('/v1/documents/attest',json=payload,headers=h).status_code==201
    changed={'evidence_id':'signed-1','document':doc.model_copy(update={'expected_sha256':'b'*64}).model_dump()}
    assert c.post('/v1/documents/attest',json=changed,headers=h).status_code==422


def test_live_connector_xero_mock_and_no_token_echo(monkeypatch):
    monkeypatch.setenv('PROOFLINE_ERP_CONNECTIONS',json.dumps({'org':{'xero':{'tenant_id':'xero-tenant','access_token':'xero-test-token'}}}))
    paths=[]
    def handler(request):
        assert request.headers['authorization']=='Bearer xero-test-token'
        assert request.headers['xero-tenant-id']=='xero-tenant'
        paths.append(request.url.path)
        if request.url.path.endswith('/Invoices'):
            return httpx.Response(200,json={'Invoices':[{'Type':'ACCPAY','Status':'AUTHORISED','InvoiceID':'x-id','InvoiceNumber':'INV-1','Contact':{'ContactID':'vendor-1'},'Total':100,'CurrencyCode':'USD','DateString':'2026-11-03'}]})
        return httpx.Response(200,json={'PurchaseOrders':[{'PurchaseOrderNumber':'PO-1','Contact':{'ContactID':'vendor-1'},'Total':100,'CurrencyCode':'USD'}]})
    async def run():
        return await fetch_erp('org',ERPRequest(provider='xero',invoice_po_links={'x-id':'PO-1'}),transport=httpx.MockTransport(handler))
    result=asyncio.run(run())
    assert result['summary']['matched']==1 and result['source']['provider']=='xero'
    assert len(paths)==2 and 'xero-test-token' not in repr(result)


def test_quickbooks_uses_bills_not_sales_invoices(monkeypatch):
    monkeypatch.setenv('PROOFLINE_ERP_CONNECTIONS',json.dumps({'org':{'quickbooks':{'realm_id':'12345','access_token':'quickbooks-test-token','sandbox':True}}}))
    def handler(request):
        assert request.url.host=='sandbox-quickbooks.api.intuit.com'
        q=request.url.params['query']
        if 'FROM Bill ' in q:
            return httpx.Response(200,json={'QueryResponse':{'Bill':[{'Id':'1','DocNumber':'B-1','VendorRef':{'value':'V1'},'TotalAmt':100,'Balance':100,'TxnDate':'2026-10-01'}]}})
        return httpx.Response(200,json={'QueryResponse':{'PurchaseOrder':[{'Id':'2','DocNumber':'P1','VendorRef':{'value':'V1'},'TotalAmt':100}]}})
    async def run():return await fetch_erp('org',ERPRequest(provider='quickbooks',invoice_po_links={'1':'P1'}),httpx.MockTransport(handler))
    r=asyncio.run(run())
    assert r['summary']['matched']==1
    assert r['source']['read_only']


def test_bc_odata_and_malicious_next_link_blocked(monkeypatch):
    monkeypatch.setenv('PROOFLINE_ERP_CONNECTIONS',json.dumps({'org':{'business_central':{'directory_id':'my-directory','company_id':'company-1','environment':'production','access_token':'abc123456789'}}}))
    def handler(req):
        if 'purchaseInvoices' in req.url.path:
            return httpx.Response(200,json={'value':[{'id':'id','number':'IN-1','vendorInvoiceNumber':'V-INV-1','vendorNumber':'V1','orderNumber':'PO-1','totalAmountIncludingTax':150,'currencyCode':'USD','invoiceDate':'2026-10-31','status':'Open'}]})
        return httpx.Response(200,json={'value':[{'number':'PO-1','vendorNumber':'V1','totalAmountIncludingTax':150,'currencyCode':'USD'}]})
    async def run():return await fetch_erp('org',ERPRequest(provider='business_central'),httpx.MockTransport(handler))
    assert asyncio.run(run())['summary']['matched']==1
    def bad(req):return httpx.Response(200,json={'value':[],'@odata.nextLink':'https://evil.example/steal'})
    with pytest.raises(ERPError,match='Unsafe ERP pagination'):
        asyncio.run(fetch_erp('org',ERPRequest(provider='business_central'),httpx.MockTransport(bad)))


def test_missing_erp_link_not_invented_and_multicurrency_exposure_not_summed():
    inv,orders,paid=normalize_quickbooks([{'Id':'i','DocNumber':'B-1','VendorRef':{'value':'v1'},'TotalAmt':100,'TxnDate':'2026-10-01'}],[],{})
    assert inv[0]['po_id'].startswith('UNLINKED:')
    assert reconcile(ReconcileRequest.model_validate({'invoices':inv,'purchase_orders':[]}))['summary']['exceptions']==1
    request=ReconcileRequest.model_validate({'invoices':[{'invoice_id':'1','vendor_id':'a','po_id':'missing','amount':100,'currency':'USD','invoice_date':'2026-11-03'}, {'invoice_id':'2','vendor_id':'a','po_id':'missing','amount':100,'currency':'EUR','invoice_date':'2026-11-03'}],'purchase_orders':[]})
    result=reconcile(request)
    assert result['summary']['at_risk_amount'] is None
    assert result['summary']['at_risk_by_currency']=={'EUR':'100.00','USD':'100.00'} or result['summary']['at_risk_by_currency']=={'EUR':'100','USD':'100'}


def test_large_synthetic_dataset_is_reproducible():
    import sys
    sys.path.insert(0,'examples')
    from generate_large_dataset import generate
    a,b=generate()
    assert len(a)==len(b)==500
    assert generate()==(a,b)
    result=reconcile(ReconcileRequest.model_validate({'invoices':a,'purchase_orders':b}))
    assert result['summary']['exceptions']>100
    assert result['summary']['matched']>200
    assert result['summary']['top_reasons']
