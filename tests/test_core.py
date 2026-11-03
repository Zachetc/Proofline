from datetime import datetime,timezone,timedelta
from proofline.core import assess,pii_signals,redact

def fixtures():
    now=datetime.now(timezone.utc)
    d={'id':'1','tenant_id':'a','vendor_id':'v','invoice_id':'i','amount':200,'recommendation':'pay','rationale':'Verified payment matched with current vendor documentation.','evidence_ids':['e']}
    e=[{'id':'e','tenant_id':'a','type':'invoice','status':'verified','observed_at':(now-timedelta(days=1)).isoformat()}]
    return d,e,now

def test_approval_and_missing_evidence():
    d,e,now=fixtures()
    assert assess(d,e,[],now).status=='APPROVED'
    assert assess(d,[],[],now).status=='BLOCKED'

def test_stale_and_tenant_isolation():
    d,e,now=fixtures()
    e[0]['observed_at']=(now-timedelta(days=35)).isoformat()
    assert assess(d,e,[],now).status=='BLOCKED'
    e[0]['tenant_id']='other'
    assert assess(d,e,[],now).status=='BLOCKED'

def test_duplicate_and_high_value():
    d,e,now=fixtures()
    assert assess(d,e,[{'id':'other','tenant_id':'a','vendor_id':'v','invoice_id':'i'}],now).status=='BLOCKED'
    d['amount']=10000
    assert assess(d,e,[],now).status=='REVIEW'
    d['amount']=50000
    assert assess(d,e,[],now).status=='BLOCKED'

def test_sensitive_data():
    d,e,now=fixtures();d['rationale']='Please contact admin@example.com about this payment now.'
    assert assess(d,e,[],now).status=='BLOCKED'
    assert pii_signals('123-45-6789')==['ssn']
    assert '[REDACTED_EMAIL]' in redact('admin@example.com')
    assert 'payment_card' in pii_signals('4111 1111 1111 1111')
