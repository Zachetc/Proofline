"""Complete authenticated journey from evidence to review and insights."""
import importlib
from datetime import datetime, timezone
from fastapi.testclient import TestClient

def test_complete_business_workflow(monkeypatch,tmp_path):
    monkeypatch.setenv('PROOFLINE_DB',str(tmp_path/'e2e.db'))
    monkeypatch.setenv('PROOFLINE_API_KEY','strong-local-key')
    monkeypatch.setenv('PROOFLINE_TENANT','finance')
    monkeypatch.setenv('PROOFLINE_DEMO','1')
    import proofline.api as api
    importlib.reload(api)
    c=TestClient(api.app)
    headers={'Authorization':'Bearer strong-local-key','X-Tenant-ID':'finance'}
    rec={'invoices':[{'invoice_id':'I-1','vendor_id':'V-1','po_id':'PO-1','amount':'12000.00','currency':'USD','invoice_date':'2026-11-03'}],
         'purchase_orders':[{'po_id':'PO-1','vendor_id':'V-1','amount':'12000.00','currency':'USD'}]}
    assert c.post('/v1/reconcile',json=rec,headers=headers).json()['summary']['matched']==1
    ev={'id':'doc-1','type':'invoice','status':'verified','observed_at':datetime.now(timezone.utc).isoformat()}
    assert c.post('/v1/evidence',json=ev,headers=headers).status_code==201
    assert c.post('/v1/evidence',json={**ev,'status':'unverified'},headers=headers).status_code==409
    d={'id':'D-1','vendor_id':'V-1','invoice_id':'I-1','amount':12000,'recommendation':'pay',
       'rationale':'The payment is recommended after checking the invoice against purchase order fields.',
       'evidence_ids':['doc-1']}
    r=c.post('/v1/assess',json=d,headers=headers)
    assert r.status_code==200 and r.json()['status']=='REVIEW'
    assert c.post('/v1/assess',json=d,headers=headers).json()['audit_hash']==r.json()['audit_hash']
    insights=c.get('/v1/insights',headers=headers).json()
    assert insights['counts']['REVIEW']==1
    assert insights['exposure_by_status_usd']['REVIEW']=='12000.00'
    rev={'decision_id':'D-1','disposition':'APPROVE','reviewer':'analyst-1',
         'justification':'Reviewed invoice fields with the AP supervisor.'}
    assert c.post('/v1/reviews',json=rev,headers=headers).status_code==201
    assert c.post('/v1/reviews',json=rev,headers=headers).status_code==409
    assert c.get('/v1/audit/verify',headers=headers).json()['valid']
    assert c.get('/v1/reviews/audit/verify',headers=headers).json()['valid']
    assert c.get('/v1/assessments',headers={**headers,'X-Tenant-ID':'other'}).status_code==401
