# API examples

Set `PROOFLINE_API_KEY` and `PROOFLINE_TENANT=default` in the server environment. These commands use a placeholder; substitute your own secret in your terminal. Never commit it.

## Reconcile invoices with purchase orders

```bash
curl -X POST http://127.0.0.1:8000/v1/reconcile \
  -H 'Authorization: Bearer YOUR_KEY' \
  -H 'X-Tenant-ID: default' -H 'Content-Type: application/json' \
  -d '{"invoices":[{"invoice_id":"INV-1","vendor_id":"V1","po_id":"PO-1","amount":"100.00","currency":"USD","invoice_date":"2026-11-03"}],"purchase_orders":[{"po_id":"PO-1","vendor_id":"V1","amount":"100.00","currency":"USD"}],"paid_invoice_keys":[],"tolerance":"0.00"}'
```

Expected summary: `total=1`, `matched=1`, `exceptions=0`, `at_risk_amount=0`. This checks field consistency only.

## Register evidence and evaluate a recommendation

```bash
curl -X POST http://127.0.0.1:8000/v1/evidence \
  -H 'Authorization: Bearer YOUR_KEY' -H 'X-Tenant-ID: default' -H 'Content-Type: application/json' \
  -d '{"id":"e-1","type":"invoice","status":"verified","observed_at":"2026-11-03T00:00:00Z"}'

curl -X POST http://127.0.0.1:8000/v1/assess \
  -H 'Authorization: Bearer YOUR_KEY' -H 'X-Tenant-ID: default' -H 'Content-Type: application/json' \
  -d '{"id":"D-1","vendor_id":"V1","invoice_id":"INV-1","amount":12000,"recommendation":"pay","rationale":"Invoice and vendor details were checked against current records.","evidence_ids":["e-1"]}'
```

This recommendation is routed to `REVIEW` because it exceeds the $10,000 manual-approval threshold. A human reviewer can submit `{"decision_id":"D-1","disposition":"APPROVE","reviewer":"analyst-1","justification":"Verified payment request with AP manager."}` to `/v1/reviews`. A `BLOCKED` assessment cannot be overridden using this endpoint.

## Insights and audit

`GET /v1/insights` returns total decisions, outcome counts, exposure by status, top findings, and next-step recommendations. `GET /v1/audit/verify` and `GET /v1/reviews/audit/verify` check their respective SHA-256 chains.

All protected endpoints require the same two headers. No endpoint initiates a bank transfer.
