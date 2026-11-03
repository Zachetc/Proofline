# Changelog

## 0.2 — End-to-end structured assurance

- Added authenticated, stateless invoice/PO reconciliation, CSV upload UI and CSV exception export.
- Added actionable descriptive metrics and policy rule-frequency insights.
- Added human approval/rejection workflow for `REVIEW` decisions with justifications.
- Added separate hash-chain verification for review events.
- Bound Bearer credentials to explicitly configured tenant IDs.
- Made evidence metadata immutable by ID and repeated decision assessment idempotent.
- Added complete API workflow regression tests and sample analytical results.
- Documented evidence authenticity, storage and identity limitations explicitly.

## 0.1 — Initial policy assurance prototype

- Deterministic policy engine, SQLite assessment ledger, synthetic dashboard and tests.

## v0.3 — ERP ingestion and independently signed invoice evidence

- Added three read-only, tenant-bound ERP adapters: Xero accounts payable, QuickBooks Online Bills and Business Central purchase invoices; all normalized to the existing deterministic reconciliation workflow.
- Missing ERP purchase order links are not guessed; explicitly map invoice IDs to PO numbers when trusted operators have confirmed those relationships.
- Added strict tenant-configured Ed25519 detached signature and SHA-256 checks for files and an atomic registration path for signed, structured invoice JSON evidence.
- Added a deterministic 500-invoice synthetic dataset, 500 purchase orders, exception breakdowns by rule/vendor, and flagged face value grouped by currency without invalid FX summation.
- Added ERP and document-verification panels to the browser interface and mock-provider/integrity tests.
- Updated API, trust, and deployment documentation with the actual remaining limitations.
