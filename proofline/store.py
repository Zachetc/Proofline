"""SQLite transactional audit ledger with tenant scoping and immutable decision results."""
import sqlite3, json, hashlib
from datetime import datetime, timezone
from pathlib import Path
from .core import assess, fingerprint, redact

SCHEMA='''
CREATE TABLE IF NOT EXISTS evidence (id TEXT, tenant_id TEXT, kind TEXT, status TEXT, observed_at TEXT, PRIMARY KEY(tenant_id,id));
CREATE TABLE IF NOT EXISTS decisions (id TEXT, tenant_id TEXT, vendor_id TEXT, invoice_id TEXT, payload TEXT, created_at TEXT, PRIMARY KEY(tenant_id,id));
CREATE INDEX IF NOT EXISTS decisions_vendor_invoice ON decisions(tenant_id,vendor_id,invoice_id);
CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, decision_id TEXT NOT NULL, status TEXT NOT NULL, score INTEGER NOT NULL, report TEXT NOT NULL, previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS assessments_tenant ON assessments(tenant_id,id);
'''
class Store:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as db: db.executescript(SCHEMA)
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        return db
    def ingest_evidence(self,tenant,e):
        with self.connect() as db:
            existing=db.execute('SELECT kind,status,observed_at FROM evidence WHERE tenant_id=? AND id=?',(tenant,e['id'])).fetchone()
            if existing:
                if (existing['kind'],existing['status'],existing['observed_at']) != (e['type'],e['status'],e['observed_at']):
                    raise ValueError('Evidence ID already exists with different content')
                return
            db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(e['id'],tenant,e['type'],e['status'],e['observed_at']))
    def evaluate(self,tenant,d):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT payload FROM decisions WHERE tenant_id=? AND id=?',(tenant,d['id'])).fetchone()
            if existing and fingerprint(json.loads(existing['payload']))!=fingerprint({**d,'rationale':redact(d.get('rationale',''))}): raise ValueError('Decision ID already exists with different content')
            if existing:
                previous_report=db.execute('SELECT report,entry_hash FROM assessments WHERE tenant_id=? AND decision_id=? ORDER BY id DESC LIMIT 1',(tenant,d['id'])).fetchone()
                if previous_report:return {**json.loads(previous_report['report']),'audit_hash':previous_report['entry_hash']}
            evidence=[dict(id=r['id'],tenant_id=tenant,type=r['kind'],status=r['status'],observed_at=r['observed_at']) for r in db.execute('SELECT * FROM evidence WHERE tenant_id=?',(tenant,))]
            history=[dict(r) for r in db.execute('SELECT id,tenant_id,vendor_id,invoice_id FROM decisions WHERE tenant_id=?',(tenant,))]
            report=assess({**d,'tenant_id':tenant},evidence,history)
            if not existing:
                safe={**d,'rationale':redact(d.get('rationale',''))}
                db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?)',(d['id'],tenant,d.get('vendor_id'),d.get('invoice_id'),json.dumps(safe),datetime.now(timezone.utc).isoformat()))
            previous=db.execute('SELECT entry_hash FROM assessments WHERE tenant_id=? ORDER BY id DESC LIMIT 1',(tenant,)).fetchone()
            prev=previous['entry_hash'] if previous else 'GENESIS'
            raw=json.dumps(report.__dict__,sort_keys=True,separators=(',',':'))
            entry=hashlib.sha256((prev+'|'+raw).encode()).hexdigest()
            db.execute('INSERT INTO assessments(tenant_id,decision_id,status,score,report,previous_hash,entry_hash,created_at) VALUES(?,?,?,?,?,?,?,?)',(tenant,d['id'],report.status,report.score,raw,prev,entry,report.evaluated_at))
            return {**report.__dict__,'audit_hash':entry}
    def list_assessments(self,tenant):
        with self.connect() as db:
            return [dict(json.loads(r['report']),audit_hash=r['entry_hash']) for r in db.execute('SELECT report,entry_hash FROM assessments WHERE tenant_id=? ORDER BY id DESC LIMIT 200',(tenant,))]
    def verify_chain(self,tenant):
        prev='GENESIS'; count=0
        with self.connect() as db:
            for r in db.execute('SELECT report,previous_hash,entry_hash FROM assessments WHERE tenant_id=? ORDER BY id',(tenant,)):
                if r['previous_hash']!=prev or hashlib.sha256((prev+'|'+r['report']).encode()).hexdigest()!=r['entry_hash']:
                    return {'valid':False,'checked':count}
                prev=r['entry_hash'];count+=1
        return {'valid':True,'checked':count,'head':prev}

    def attest_document(self, tenant, evidence_id, sha256, key_id, invoice_id, vendor_id, observed_at):
        """Atomically bind a trusted signature result to an immutable invoice evidence record."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS document_attestation (
                tenant_id TEXT NOT NULL,evidence_id TEXT NOT NULL,
                sha256 TEXT NOT NULL, key_id TEXT NOT NULL,
                invoice_id TEXT NOT NULL,vendor_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,PRIMARY KEY(tenant_id,evidence_id))''')
            row=db.execute('SELECT sha256,key_id,invoice_id,vendor_id FROM document_attestation WHERE tenant_id=? AND evidence_id=?',(tenant,evidence_id)).fetchone()
            if row:
                if tuple(row)!= (sha256,key_id,invoice_id,vendor_id):raise ValueError('Attestation evidence ID already bound to different signed content')
                return
            prior=db.execute('SELECT 1 FROM evidence WHERE tenant_id=? AND id=?',(tenant,evidence_id)).fetchone()
            if prior:raise ValueError('Evidence ID is already allocated')
            db.execute('INSERT INTO document_attestation VALUES(?,?,?,?,?,?,?)',(tenant,evidence_id,sha256,key_id,invoice_id,vendor_id,observed_at))
            db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(evidence_id,tenant,'invoice','verified',observed_at))
