"""Clearly labeled synthetic test fixtures, evaluated in memory without persistence."""
from datetime import datetime, timezone, timedelta
from .core import assess

def generate_demo():
    now=datetime.now(timezone.utc)
    def evidence(id,kind='invoice',days=1,status='verified'):
        return {'id':id,'tenant_id':'synthetic-demo','type':kind,'status':status,'observed_at':(now-timedelta(days=days)).isoformat()}
    sources=[evidence('inv-001'),evidence('inv-002'),evidence('inv-003',days=50),evidence('po-001','purchase_order'),evidence('inv-004')]
    rows=[
        {'id':'A-1001','vendor_id':'V-1','invoice_id':'INV-1001','amount':4200,'recommendation':'pay','rationale':'Verified invoice matches the vendor and approved payment amount.','evidence_ids':['inv-001']},
        {'id':'A-1002','vendor_id':'V-2','invoice_id':'INV-1002','amount':18000,'recommendation':'pay','rationale':'Payment proposed with current verified invoice attached.','evidence_ids':['inv-002']},
        {'id':'A-1003','vendor_id':'V-3','invoice_id':'INV-1003','amount':78000,'recommendation':'pay','rationale':'AI recommends payment despite significant transaction exposure.','evidence_ids':['inv-003']},
        {'id':'A-1004','vendor_id':'V-1','invoice_id':'INV-1001','amount':4200,'recommendation':'pay','rationale':'Second payment requested for the same vendor invoice reference.','evidence_ids':['inv-001']},
        {'id':'A-1005','vendor_id':'V-4','invoice_id':'INV-1005','amount':2500,'recommendation':'pay','rationale':'Send details to finance@example.com and pay after verification.','evidence_ids':['inv-004']},
        {'id':'A-1006','vendor_id':'V-5','invoice_id':'INV-1006','amount':3200,'recommendation':'hold','rationale':'Place this vendor payment on hold pending contract validation.','evidence_ids':['po-001']},
    ]
    history=[{'id':'A-1001','tenant_id':'synthetic-demo','vendor_id':'V-1','invoice_id':'INV-1001'}]
    evaluated=[assess({**d,'tenant_id':'synthetic-demo'},sources,history,now).__dict__ for d in rows]
    return {'mode':'synthetic_demo','notice':'Generated fixtures only. No real business records or AI model calls.','assessments':evaluated,'total_exposure':sum(float(d['amount']) for d in rows),'sample_size':len(rows)}
