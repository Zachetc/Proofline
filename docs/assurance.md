# Assurance, threat model and measurement

## What is independently checked?

**Structured reconciliation:** PO and invoice IDs, vendors, amounts, currencies, paid-reference keys and duplicates are compared by deterministic code. This is a real control on the supplied structured records, but **not** an independent verification of their authenticity.

**Decision gate:** The model checks referenced evidence metadata, 30-day freshness, invoice presence, decision value, duplicate vendor/invoice combinations, sensitive information and rationale length. It never calls a remote model or initiates payment.

**Review workflow:** Only `REVIEW` decisions can be dispositioned, once, with a named reviewer and justification. `BLOCKED` is not overridable through this workflow. A reviewer name is user-provided, not an authenticated identity assertion.

**Audit:** Assessment and review events are chained separately with SHA-256. The app detects modification of an individual stored event, but a privileged actor can rewrite the full ledger. External hash anchoring, immutable storage, signed user identity and independent verification are not implemented.

## Threats and mitigations

| Threat | Current mitigation | Remaining risk |
| --- | --- | --- |
| Cross-tenant reads | Server-side key-to-tenant binding and scoped SQL | Shared key compromise; no SSO or RBAC |
| Duplicate payment reference | Vendor/invoice matching and already-paid keys | Reference normalization and authoritative AP ledger not integrated |
| False verified document | Evidence freshness/status checks | Verification flag is caller-submitted; trusted connectors required |
| Sensitive rationale | Email, SSN and Luhn-card redaction | Detection is heuristic and not comprehensive |
| Audit modification | Application-level hash chains | Privileged full-chain rewrite possible |
| Unbounded input | Pydantic list/field limits, browser file size limits | No global request-body cap, rate limiter or WAF configured |
| Replay of assessment | Idempotent decision ID with payload conflict detection | External business events require reconciliation |
| Incorrect business conclusions | Explicit face-value/exposure language and synthetic labels | No independently measured savings or fraud precision |

## Metrics worth measuring with real permissioned data

- **Exception rate:** flagged invoices / invoices evaluated. Multiple flags on one invoice count once.
- **Flagged face value:** sum of amounts of flagged rows, including repeated invoices; *not* realized savings.
- **Approval rate:** approved assessments / assessments evaluated.
- **Rule frequency:** counts of specific rule failures.
- **Review turnaround:** would require authenticated reviewer identities and timestamps for queue entry and disposition.
- **Precision/recall:** cannot be calculated without a labeled truth set from independent review.

## Validation status

The automated test suite covers core decision rules, tenant isolation, API auth, reconciliation, duplicate detection, review restrictions, audit tampering and idempotence. Passing tests does not demonstrate regulatory compliance, deployment uptime or production-grade security.
