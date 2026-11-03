from datetime import datetime,timezone
from proofline.store import Store
import pytest

def test_ledger_idempotence_and_tenant_scope(tmp_path):
    s=Store(tmp_path/'test.db')
    s.ingest_evidence('a',{'id':'e','type':'invoice','status':'verified','observed_at':datetime.now(timezone.utc).isoformat()})
    d={'id':'d1','vendor_id':'v','invoice_id':'i','amount':100,'recommendation':'pay','rationale':'The invoice has been verified with current vendor records.','evidence_ids':['e']}
    assert s.evaluate('a',d)['status']=='APPROVED'
    assert s.evaluate('a',d)['status']=='APPROVED'
    assert s.verify_chain('a')['valid']
    assert s.verify_chain('a')['checked']==1
    assert s.list_assessments('b')==[]
    with pytest.raises(ValueError):s.evaluate('a',{**d,'amount':200})
    with s.connect() as db: db.execute("UPDATE assessments SET report='{}' WHERE id=1")
    assert not s.verify_chain('a')['valid']
