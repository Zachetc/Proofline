"""Deterministic decision assurance: no remote LLM calls, no fabricated approvals."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib, json, re

EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)
SSN = re.compile(r'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)')
CARD = re.compile(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)')

def fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()

def money(value):
    try:
        d=Decimal(str(value))
        if not d.is_finite() or d < 0: return None
        return d.quantize(Decimal('.01'))
    except (InvalidOperation, ValueError, TypeError): return None

def pii_signals(text: str) -> list[str]:
    found=[]
    if EMAIL.search(text): found.append('email')
    if SSN.search(text): found.append('ssn')
    # Luhn validation avoids treating most numeric identifiers as payment cards.
    for match in CARD.finditer(text):
        digits=re.sub(r'\D','',match.group())
        if 13 <= len(digits) <= 19 and sum((int(c)*2-9 if int(c)*2>9 else int(c)*2) if i%2 else int(c) for i,c in enumerate(digits[::-1]))%10==0:
            found.append('payment_card'); break
    return found

def redact(text: str) -> str:
    text=EMAIL.sub('[REDACTED_EMAIL]',text)
    text=SSN.sub('[REDACTED_SSN]',text)
    return CARD.sub(lambda m: '[REDACTED_CARD]' if 'payment_card' in pii_signals(m.group()) else m.group(), text)

@dataclass
class Finding:
    code: str
    severity: str
    detail: str

@dataclass
class Assessment:
    decision_id: str
    status: str
    score: int
    findings: list[dict]
    evidence_coverage: float
    financial_exposure: str
    evaluated_at: str
    policy_version: str = '2026.11'


def assess(decision: dict, evidence: list[dict], history: list[dict], now: datetime | None=None) -> Assessment:
    """Fail closed for critical evidence/policy errors. Evidence must be tenant-bound."""
    now=now or datetime.now(timezone.utc)
    findings=[]
    def add(code,severity,detail): findings.append(Finding(code,severity,detail))
    amount=money(decision.get('amount'))
    if amount is None: add('INVALID_AMOUNT','critical','Amount must be a finite, nonnegative currency value.')
    tenant=decision.get('tenant_id','')
    refs=decision.get('evidence_ids') or []
    records={e['id']:e for e in evidence if e.get('tenant_id')==tenant}
    valid=[]
    for ref in refs:
        e=records.get(ref)
        if not e:
            add('MISSING_EVIDENCE','high',f'Evidence {ref} is missing or outside the authorized tenant.')
            continue
        if e.get('status')!='verified':
            add('UNVERIFIED_EVIDENCE','high',f'Evidence {ref} has not been verified.')
            continue
        try:
            ts=datetime.fromisoformat(e['observed_at'].replace('Z','+00:00'))
            if ts.tzinfo is None: raise ValueError()
            age=(now-ts).total_seconds()
            if age<0 or age>30*86400:
                add('STALE_EVIDENCE','high',f'Evidence {ref} is outside the 30-day freshness window.')
                continue
        except (KeyError,ValueError,TypeError):
            add('INVALID_EVIDENCE_TIME','high',f'Evidence {ref} lacks a valid timezone-aware timestamp.')
            continue
        valid.append(e)
    coverage=len(valid)/len(refs) if refs else 0
    if not refs: add('NO_EVIDENCE','critical','Decision has no supporting evidence references.')
    if coverage<1: add('INCOMPLETE_COVERAGE','high','Not all cited evidence is verified and current.')
    if amount is not None and amount>=Decimal('10000'):
        add('HIGH_VALUE','high','Transactions of $10,000 or more require manual approval.')
    if amount is not None and amount>=Decimal('50000'):
        add('VERY_HIGH_VALUE','critical','Transactions of $50,000 or more cannot auto-approve.')
    if decision.get('vendor_id'):
        for old in history:
            if old.get('tenant_id')!=tenant: continue
            if old.get('vendor_id')==decision['vendor_id'] and old.get('invoice_id')==decision.get('invoice_id') and old.get('id')!=decision.get('id'):
                add('DUPLICATE_INVOICE','critical','Same vendor and invoice ID already exist in this tenant.')
                break
    if not decision.get('vendor_id') or not decision.get('invoice_id'):
        add('MISSING_IDENTITY','high','Vendor and invoice IDs are required.')
    if decision.get('recommendation') not in ('pay','hold'):
        add('INVALID_RECOMMENDATION','critical','Recommendation must be pay or hold.')
    text=decision.get('rationale','')
    pii=pii_signals(text)
    if pii: add('PII_IN_RATIONALE','critical','Rationale contains sensitive data: '+', '.join(pii)+'.')
    if len(text.strip())<20: add('WEAK_RATIONALE','medium','Rationale lacks sufficient explanation.')
    if decision.get('recommendation')=='pay' and not any(e.get('type')=='invoice' for e in valid):
        add('NO_VERIFIED_INVOICE','critical','Payment requires a verified, recent invoice document.')
    weights={'critical':35,'high':18,'medium':7,'low':2}
    score=max(0,100-sum(weights[f.severity] for f in findings))
    critical=any(f.severity=='critical' for f in findings)
    high=any(f.severity=='high' for f in findings)
    status='BLOCKED' if critical else ('REVIEW' if high or score<85 else 'APPROVED')
    return Assessment(str(decision['id']),status,score,[asdict(f) for f in findings],round(coverage,3),str(amount) if amount is not None else 'invalid',now.isoformat())
