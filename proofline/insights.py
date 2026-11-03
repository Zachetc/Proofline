"""Explainable, descriptive operational insights; no invented causal claims."""
from collections import Counter
from decimal import Decimal

def summarize(items):
    counts=Counter(x['status'] for x in items)
    reasons=Counter(f['code'] for x in items for f in x.get('findings',[]))
    exposure={status:Decimal('0') for status in ('APPROVED','REVIEW','BLOCKED')}
    for x in items:
        try: exposure[x['status']]+=Decimal(str(x['financial_exposure']))
        except (ValueError,TypeError): pass
    total=len(items)
    actionable=[]
    if reasons.get('DUPLICATE_INVOICE'):
        actionable.append({'priority':'high','finding':'Potential duplicate payment attempts','count':reasons['DUPLICATE_INVOICE'],'action':'Reconcile vendor and invoice IDs against the AP ledger before payment.'})
    if reasons.get('STALE_EVIDENCE') or reasons.get('MISSING_EVIDENCE') or reasons.get('NO_EVIDENCE'):
        actionable.append({'priority':'high','finding':'Evidence gaps','count':sum(reasons[k] for k in ('STALE_EVIDENCE','MISSING_EVIDENCE','NO_EVIDENCE')),'action':'Request current, trusted source documents before release.'})
    if reasons.get('PII_IN_RATIONALE'):
        actionable.append({'priority':'high','finding':'Sensitive data in decision text','count':reasons['PII_IN_RATIONALE'],'action':'Investigate source handling and redact before sharing.'})
    if counts['REVIEW']:
        actionable.append({'priority':'medium','finding':'Human approval workload','count':counts['REVIEW'],'action':'Assign reviewers with separation of duties and record a reason for every disposition.'})
    return {'total':total,'counts':dict(counts),'approval_rate':round(counts['APPROVED']/total,4) if total else 0,
            'exposure_by_status_usd':{k:str(v.quantize(Decimal('.01'))) for k,v in exposure.items()},
            'top_findings':[{'code':k,'count':v} for k,v in reasons.most_common(10)],'recommendations':actionable,
            'limitations':'Descriptive counts of assessed decisions; not proof of actual fraud, realized savings, or model accuracy.'}
