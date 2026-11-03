# Read-only ERP integrations and provenance

Proofline v0.3 supports **read-only API extraction and normalization** for three accounting/ERP platforms. These connectors do not authorize payments, create bills, mutate purchase orders, or store ERP tokens in the browser. A provider must grant proper OAuth2 scopes and a server-side access token before a real connection can run.

| Connector | Source objects | Upstream API | Important caveat |
|---|---|---|---|
| Xero | `Invoices` filtered to `ACCPAY` bills; `PurchaseOrders` | `https://api.xero.com/api.xro/2.0/` | Xero does not consistently expose a reliable bill-to-PO number in its summary response. Missing linkage remains an exception unless explicitly mapped. |
| QuickBooks Online | `Bill`, **not customer Invoice**; `PurchaseOrder` | `https://quickbooks.api.intuit.com/v3/company/{realm}/query` | Bill purchase-order linkage cannot safely be inferred from coincidental document numbers. Explicit ID → PO number map is supported. |
| Microsoft Dynamics 365 Business Central | `purchaseInvoices`, `purchaseOrders` | `https://api.businesscentral.dynamics.com/v2.0/.../api/v2.0/companies({id})/` | Reads `orderNumber` when provided by the purchase invoice. Currency defaults to USD only if absent; validate against the company's books. |

## Configure connections

In your **server environment**, set `PROOFLINE_ERP_CONNECTIONS` to a JSON object indexed by the tenant configured under `PROOFLINE_TENANT_KEYS`:

```json
{
  "example-org": {
    "xero": {"tenant_id":"YOUR-XERO-TENANT-ID","access_token":"YOUR-SERVER-SIDE-ACCESS-TOKEN"},
    "quickbooks": {"realm_id":"YOUR-REALM-ID","access_token":"YOUR-SERVER-SIDE-ACCESS-TOKEN","sandbox":true},
    "business_central": {"directory_id":"YOUR-AZURE-DIRECTORY","environment":"sandbox","company_id":"YOUR-COMPANY-ID","access_token":"YOUR-SERVER-SIDE-ACCESS-TOKEN"}
  }
}
```

These are **placeholders**, not connected companies. Do not commit real secrets. The application assumes an external OAuth token acquisition/refresh process; the prototype does not implement OAuth consent screens or refresh-token rotation. Tokens can expire and must be replaced in the secret store. Enable only appropriate read permissions at the ERP provider. HTTPS origins are hardcoded, and Business Central continuation links are validated to prevent arbitrary-domain SSRF.

## Call a connector

```bash
curl -X POST http://localhost:8000/v1/erp/reconcile \
  -H 'Authorization: Bearer YOUR_PROOFLINE_TOKEN' \
  -H 'X-Tenant-ID: example-org' -H 'Content-Type: application/json' \
  -d '{"provider":"quickbooks","invoice_po_links":{"EXTERNAL_BILL_ID":"PO-100"},"tolerance":"0.00"}'
```

`invoice_po_links` is a **manual mapping supplied by the operator**. It helps reconcile documents but cannot independently verify that a link is true. If no verified PO link exists, the system emits `MISSING_PO` instead of guessing.

The connector normalizes provider-specific objects into Proofline's strict invoice/PO schema and runs the same deterministic reconciliation engine. Original provider IDs and tenant context are used to make boundaries explicit. Each batch caps invoices and purchase orders at 1,000 records; pagination stops at hard limits rather than silently claiming to represent all company transactions. No FX conversion is performed; exposure is grouped by currency.

## Verification level

Integration unit tests use **HTTPX mocked ERP responses** and assert correct auth headers, read-only GET requests, field mapping, missing PO links, tenant credential isolation and unsafe next-link rejection. They do **not** constitute a successful live provider connection. Live verification requires valid credentials, permitted scope, and an authorized sandbox/company.

Official documentation: [Xero Accounting API](https://developer.xero.com/documentation/api/accounting/overview/), [QuickBooks Online](https://developer.intuit.com/app/developer/qbo/docs/), [Business Central v2.0](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/).
