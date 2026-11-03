import pytest
from datetime import datetime,timezone
from proofline.insights import summarize
from proofline.reconcile import ReconcileRequest,reconcile
from proofline.review import ensure_review_schema,submit_review,list_reviews,verify_review_chain
from proofline.store import Store

def test_reconcile_flags_mismatches_and_duplicate():
    body=ReconcileRequest.model_validate({'invoices':[
      {'invoice_id':'I1','vendor_id':'V1','po_id':'P1','amount':'100.00','currency':'USD','invoice_date':'2026-11-03'},
      {'invoice_id':'I1','vendor_id':'V1','po_id':'P1','amount':'100.00','currency':'USD','invoice_date':'2026-11-03'},
      {'invoice_id':'I2','vendor_id':'V2','po_id':'P1','amount':'120.00','currency':'USD','invoice_date':'2026-11-03'}],
      'purchase_orders':[{'po_id':'P1','vendor_id':'V1','amount':'100.00','currency':'USD'}]})
    result=reconcile(body)
    assert result['summary']['matched']==1
    assert result['summary']['exceptions']==2
    assert 'DUPLICATE_IN_BATCH' in result['items'][1]['flags']
    assert 'VENDOR_MISMATCH' in result['items'][2]['flags']
    assert 'AMOUNT_MISMATCH' in result['items'][2]['flags']
    assert result['summary']['at_risk_amount']=='220.00'

def test_human_review_and_tamper_detection(tmp_path):
    store=Store(tmp_path/'test.db');ensure_review_schema(store)
    store.ingest_evidence('t',{'id':'e','type':'invoice','status':'verified','observed_at':datetime.now(timezone.utc).isoformat()})
    result=store.evaluate('t',{'id':'D','vendor_id':'V','invoice_id':'I','amount':12000,'recommendation':'pay','rationale':'Invoice matches authorized amount and vendor','evidence_ids':['e']})
    assert result['status']=='REVIEW'
    submit_review(store,'t','D','APPROVE','reviewer-1','Reviewed with the AP manager.')
    assert len(list_reviews(store,'t'))==1
    assert verify_review_chain(store,'t')['valid']
    with pytest.raises(ValueError):submit_review(store,'t','D','REJECT','reviewer-2','Another justification here')
    with store.connect() as db:db.execute("UPDATE review_events SET event_json='{}' WHERE tenant_id='t'")
    assert not verify_review_chain(store,'t')['valid']

def test_insights_no_claimed_savings():
    result=summarize([{'status':'BLOCKED','financial_exposure':'500.00','findings':[{'code':'DUPLICATE_INVOICE'}]}])
    assert result['exposure_by_status_usd']['BLOCKED']=='500.00'
    assert result['recommendations'][0]['count']==1
    assert 'not proof' in result['limitations']

def test_private_reconcile_requires_tenant_bound_key(monkeypatch,tmp_path):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv('PROOFLINE_DB',str(tmp_path/'auth.db'))
    monkeypatch.setenv('PROOFLINE_TENANT_KEYS','{"tenant-a":"secret-a","tenant-b":"secret-b"}')
    monkeypatch.delenv('PROOFLINE_API_KEY',raising=False)
    import proofline.api as api
    importlib.reload(api)
    client=TestClient(api.app)
    body={'invoices':[],'purchase_orders':[]}
    assert client.post('/v1/reconcile',json=body).status_code==400
    assert client.post('/v1/reconcile',json=body,headers={'X-Tenant-ID':'tenant-b','Authorization':'Bearer secret-a'}).status_code==401
    assert client.post('/v1/reconcile',json=body,headers={'X-Tenant-ID':'tenant-a','Authorization':'Bearer secret-a'}).status_code==200
    assert client.post('/demo/reconcile',json=body).status_code==404

def test_assessment_idempotent_and_evidence_immutable(tmp_path):
    store=Store(tmp_path/'immutable.db')
    e={'id':'e1','type':'invoice','status':'verified','observed_at':datetime.now(timezone.utc).isoformat()}
    store.ingest_evidence('t',e)
    with pytest.raises(ValueError):store.ingest_evidence('t',{**e,'status':'unverified'})
    d={'id':'d1','vendor_id':'v','invoice_id':'i','amount':100,'recommendation':'pay','rationale':'Payment amount and invoice reference checked','evidence_ids':['e1']}
    a=store.evaluate('t',d);b=store.evaluate('t',d)
    assert a['audit_hash']==b['audit_hash']
    assert store.verify_chain('t')['checked']==1
