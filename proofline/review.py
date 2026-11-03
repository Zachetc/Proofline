"""Transactional reviewer queue; human dispositions never erase the original policy result."""
import sqlite3, hashlib, json
from datetime import datetime, timezone

REVIEW_SCHEMA='''
CREATE TABLE IF NOT EXISTS review_events (tenant_id TEXT NOT NULL, decision_id TEXT NOT NULL, event_json TEXT NOT NULL, previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (
 tenant_id TEXT NOT NULL, decision_id TEXT NOT NULL, disposition TEXT NOT NULL,
 reviewer TEXT NOT NULL, justification TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,decision_id)
);
'''

def ensure_review_schema(store):
    with store.connect() as db: db.executescript(REVIEW_SCHEMA)

def submit_review(store,tenant,decision_id,disposition,reviewer,justification):
    if disposition not in ('APPROVE','REJECT'):raise ValueError('Invalid disposition')
    if len(justification.strip())<15:raise ValueError('Review justification must be at least 15 characters')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        latest=db.execute('SELECT status FROM assessments WHERE tenant_id=? AND decision_id=? ORDER BY id DESC LIMIT 1',(tenant,decision_id)).fetchone()
        if not latest:raise LookupError('Decision not found')
        if latest['status']!='REVIEW':raise ValueError('Only REVIEW decisions may be dispositioned; blocked decisions cannot be overridden')
        timestamp=datetime.now(timezone.utc).isoformat()
        event={'decision_id':decision_id,'disposition':disposition,'reviewer':reviewer,'justification':justification,'created_at':timestamp}
        raw=json.dumps(event,sort_keys=True,separators=(',',':'))
        previous=db.execute('SELECT entry_hash FROM review_events WHERE tenant_id=? ORDER BY rowid DESC LIMIT 1',(tenant,)).fetchone()
        prev=previous['entry_hash'] if previous else 'GENESIS'
        digest=hashlib.sha256((prev+'|'+raw).encode()).hexdigest()
        try:
            db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)',(tenant,decision_id,disposition,reviewer,justification,timestamp))
            db.execute('INSERT INTO review_events VALUES(?,?,?,?,?,?)',(tenant,decision_id,raw,prev,digest,timestamp))
        except sqlite3.IntegrityError:raise ValueError('Decision already dispositioned')
    return {'decision_id':decision_id,'disposition':disposition,'reviewer':reviewer,'note':'Recorded human disposition; no payment executed'}

def list_reviews(store,tenant):
    with store.connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM reviews WHERE tenant_id=? ORDER BY created_at DESC LIMIT 200',(tenant,))]


def verify_review_chain(store,tenant):
    prev='GENESIS'; count=0
    with store.connect() as db:
        for row in db.execute('SELECT event_json,previous_hash,entry_hash FROM review_events WHERE tenant_id=? ORDER BY rowid',(tenant,)):
            if row['previous_hash']!=prev or hashlib.sha256((prev+'|'+row['event_json']).encode()).hexdigest()!=row['entry_hash']:
                return {'valid':False,'checked':count}
            prev=row['entry_hash'];count+=1
    return {'valid':True,'checked':count,'head':prev}
