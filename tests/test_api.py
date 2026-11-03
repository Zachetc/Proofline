import os,importlib
from fastapi.testclient import TestClient

def test_auth_and_demo(monkeypatch,tmp_path):
    monkeypatch.setenv('PROOFLINE_DB',str(tmp_path/'api.db'))
    monkeypatch.setenv('PROOFLINE_API_KEY','test-secret')
    monkeypatch.setenv('PROOFLINE_DEMO','1')
    monkeypatch.setenv('PROOFLINE_TENANT','a')
    import proofline.api as api
    importlib.reload(api)
    c=TestClient(api.app)
    assert c.get('/health').status_code==200
    assert c.get('/demo').json()['sample_size']==6
    assert c.get('/v1/assessments',headers={'X-Tenant-ID':'a'}).status_code==401
    assert c.get('/v1/assessments',headers={'X-Tenant-ID':'a','Authorization':'Bearer test-secret'}).status_code==200
