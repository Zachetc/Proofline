"""Multi-tenant API with role-specific bearer keys and no third-party AI dependency."""
from __future__ import annotations
import os, secrets, json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ConfigDict
from .store import Store
from .insights import summarize
from .reconcile import ReconcileRequest, reconcile
from .review import ensure_review_schema, submit_review, list_reviews, verify_review_chain
from .core import redact
from .erp import ERPRequest, fetch_erp, ERPError
from .documents import DocumentRequest, verify_document

DB=os.getenv('PROOFLINE_DB','proofline.db')
app=FastAPI(title='Proofline AI Decision Assurance',version='0.3.0')
store=Store(DB)
ensure_review_schema(store)

class Evidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=100)
    type:str=Field(pattern='^(invoice|purchase_order|vendor_record|contract)$')
    status:str=Field(pattern='^(verified|unverified)$')
    observed_at:str

class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=100)
    vendor_id:str=Field(max_length=100)
    invoice_id:str=Field(max_length=100)
    amount:float=Field(ge=0,le=1e12,allow_inf_nan=False)
    recommendation:str=Field(pattern='^(pay|hold)$')
    rationale:str=Field(max_length=5000)
    evidence_ids:list[str]=Field(max_length=100)

class Credentials(BaseModel):
    tenant:str
    role:str

def identity(authorization:str|None=Header(None),x_tenant_id:str|None=Header(None)):
    if not x_tenant_id or not x_tenant_id.replace('-','').replace('_','').isalnum() or len(x_tenant_id)>80:
        raise HTTPException(400,'Valid X-Tenant-ID header required')
    # Bind every credential to its configured tenant; a caller cannot choose a different tenant.
    try: mapping=json.loads(os.getenv('PROOFLINE_TENANT_KEYS','{}'))
    except json.JSONDecodeError: raise HTTPException(503,'Invalid tenant key configuration')
    if not isinstance(mapping,dict):raise HTTPException(503,'Invalid tenant key configuration')
    legacy=os.getenv('PROOFLINE_API_KEY')
    if legacy:mapping[os.getenv('PROOFLINE_TENANT','default')]=legacy
    if not mapping:raise HTTPException(503,'Configure PROOFLINE_API_KEY or PROOFLINE_TENANT_KEYS')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'Valid Bearer token required')
    candidate=authorization[7:]
    authorized=any(secrets.compare_digest(candidate,key) and secrets.compare_digest(x_tenant_id,tenant)
                   for tenant,key in mapping.items() if isinstance(key,str) and isinstance(tenant,str))
    if not authorized:raise HTTPException(401,'Invalid token or tenant')
    return x_tenant_id

@app.get('/',response_class=HTMLResponse)
def home(): return HTMLResponse(Path(__file__).with_name('dashboard.html').read_text())

@app.get('/health')
def health(): return {'status':'ok','version':'0.3.0','demo_mode':os.getenv('PROOFLINE_DEMO','0')=='1'}

@app.post('/v1/evidence',status_code=201)
def ingest(body:Evidence,tenant:str=Depends(identity)):
    try:store.ingest_evidence(tenant,body.model_dump())
    except ValueError as exc:raise HTTPException(409,str(exc))
    return {'stored':True,'id':body.id,'tenant':tenant}

@app.post('/v1/assess')
def evaluate(body:Decision,tenant:str=Depends(identity)):
    try:return store.evaluate(tenant,body.model_dump())
    except ValueError as e:raise HTTPException(409,str(e))

@app.get('/v1/assessments')
def assessments(tenant:str=Depends(identity)):
    return {'items':store.list_assessments(tenant)}

@app.get('/v1/audit/verify')
def verify(tenant:str=Depends(identity)):
    return store.verify_chain(tenant)

@app.get('/demo')
def demo():
    if os.getenv('PROOFLINE_DEMO','0')!='1':raise HTTPException(404,'Demo disabled')
    from .demo import generate_demo
    return generate_demo()

@app.get('/v1/insights')
def insights(tenant:str=Depends(identity)):
    return summarize(store.list_assessments(tenant))

@app.post('/v1/reconcile')
def reconcile_batch(body:ReconcileRequest,tenant:str=Depends(identity)):
    try:return reconcile(body)
    except ValueError as exc:raise HTTPException(422,str(exc))

class ReviewBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    decision_id:str=Field(min_length=1,max_length=100)
    disposition:str=Field(pattern='^(APPROVE|REJECT)$')
    reviewer:str=Field(min_length=2,max_length=100)
    justification:str=Field(min_length=15,max_length=2000)

@app.post('/v1/reviews',status_code=201)
def review(body:ReviewBody,tenant:str=Depends(identity)):
    try:return submit_review(store,tenant,body.decision_id,body.disposition,body.reviewer,redact(body.justification))
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))

@app.get('/v1/reviews')
def reviews(tenant:str=Depends(identity)):
    return {'items':list_reviews(store,tenant)}

@app.get('/demo/insights')
def demo_insights():
    if os.getenv('PROOFLINE_DEMO','0')!='1':raise HTTPException(404,'Demo disabled')
    from .demo import generate_demo
    return summarize(generate_demo()['assessments'])

@app.get('/v1/reviews/audit/verify')
def verify_reviews(tenant:str=Depends(identity)):
    return verify_review_chain(store,tenant)

@app.post('/demo/reconcile')
def demo_reconcile(body:ReconcileRequest):
    if os.getenv('PROOFLINE_DEMO','0')!='1':raise HTTPException(404,'Demo disabled')
    try:return reconcile(body)
    except ValueError as exc:raise HTTPException(422,str(exc))


@app.post('/v1/erp/reconcile')
async def erp_reconcile(body:ERPRequest,tenant:str=Depends(identity)):
    try:return await fetch_erp(tenant,body)
    except ERPError as exc:raise HTTPException(422,str(exc))

@app.post('/v1/documents/verify')
def document_verify(body:DocumentRequest,tenant:str=Depends(identity)):
    try:return verify_document(tenant,body)
    except ValueError as exc:raise HTTPException(422,str(exc))


@app.get('/demo/dataset')
def demo_dataset():
    if os.getenv('PROOFLINE_DEMO','0')!='1':raise HTTPException(404,'Demo disabled')
    import csv
    path=Path(__file__).resolve().parents[1]/'examples'
    with (path/'invoices_large.csv').open(newline='',encoding='utf8') as f:invoices=list(csv.DictReader(f))
    with (path/'purchase_orders_large.csv').open(newline='',encoding='utf8') as f:orders=list(csv.DictReader(f))
    return {'invoices':invoices,'purchase_orders':orders,'source':'deterministic synthetic fixtures; 500 invoices, 500 purchase orders'}


class AttestationBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    evidence_id:str=Field(min_length=1,max_length=100)
    document:DocumentRequest

@app.post('/v1/documents/attest',status_code=201)
def attest(body:AttestationBody,tenant:str=Depends(identity)):
    from datetime import datetime,timezone
    import base64,json
    from .reconcile import Invoice
    result=verify_document(tenant,body.document)
    if result['status']!='VERIFIED_SIGNATURE':
        raise HTTPException(422,'Document has no valid trusted signature and matching hash')
    try:
        signed=json.loads(base64.b64decode(body.document.document_b64,validate=True))
        if not isinstance(signed,dict):raise ValueError()
        invoice=Invoice.model_validate(signed)
    except Exception:
        raise HTTPException(422,'Only signed structured invoice JSON can become verified invoice evidence')
    observed=datetime.now(timezone.utc).isoformat()
    try:store.attest_document(tenant,body.evidence_id,result['sha256'],body.document.key_id,invoice.invoice_id,invoice.vendor_id,observed)
    except ValueError as exc:raise HTTPException(409,str(exc))
    return {'evidence_id':body.evidence_id,'status':'VERIFIED_SIGNATURE','sha256':result['sha256'],
            'invoice_id':invoice.invoice_id,'vendor_id':invoice.vendor_id,'registered_at':observed,
            'limitations':'Signature proves origin relative to the configured key; the invoice can still be commercially false or disputed.'}
