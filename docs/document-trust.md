# Document verification: what can be proven

Proofline supports **cryptographic byte integrity and trusted detached Ed25519 signatures**, not a generic claim that every PDF or invoice is genuine. If a document has no independent trusted signing key, its authenticity remains **unverified**.

## Trust flow

1. A separate authorized administrator obtains a vendor's authentic Ed25519 **public** key through an approved channel, records the provenance, and pins it in the **server-side** `PROOFLINE_TRUSTED_DOCUMENT_KEYS` config for the correct tenant and `key_id`.
2. The issuer signs **the exact raw invoice bytes** using its own Ed25519 private key, outside Proofline. Proofline never receives private signing keys.
3. The client submits a file encoded as base64, the expected SHA-256, the key ID and the detached signature. The backend independently computes SHA-256 and verifies the signature over the original raw bytes.
4. A document is `VERIFIED_SIGNATURE` only when both the supplied hash and the trusted-key signature verify. Tampering, wrong keys, missing signatures and PDF extension/header mismatches fail or remain unverified.
5. `POST /v1/documents/attest` may register verified **structured JSON invoices only**. The signed JSON must validate against `Invoice` fields. Registration is tenant-scoped, atomic, and idempotent for the same content and key. The resulting evidence ID may be used in an AI/payment decision assessment.

Example trusted key configuration (public key is base64 of exactly 32 bytes):

```json
{"example-org":{"vendor-key-2026":"BASE64_PUBLIC_ED25519_KEY"}}
```

## Endpoints

`POST /v1/documents/verify` receives:

```json
{
  "filename":"invoice.json",
  "document_b64":"BASE64_OF_EXACT_DOCUMENT_BYTES",
  "expected_sha256":"64_HEX_DIGITS",
  "key_id":"vendor-key-2026",
  "signature_b64":"BASE64_OF_64_BYTE_ED25519_SIGNATURE"
}
```

`POST /v1/documents/attest` accepts `{"evidence_id":"signed-invoice-001","document":{...}}` with the same nested document body. Both require tenant-bound Proofline API authentication.

## Important limitations

- A valid signature attests that bytes were signed by the owner of the configured private key. It **does not** independently prove that the issuer is a legitimate company, that goods were delivered, that the invoice has not been canceled, or that a bank transfer should be made.
- The service **does not validate embedded PDF digital signatures**, PDF PKI trust chains, revocation, or timestamps. A PDF may be verified using an **external detached** Ed25519 signature. To register invoice evidence for payment policy checks, the signed content must instead be structured JSON under the strict invoice schema.
- SHA-256 alone is an integrity checksum, **not** independent authenticity: a malicious uploader can change the file and its reported hash together.
- The API does not perform OCR or visual document forensics. PDF header recognition does not mean a PDF is safe to parse or fully valid.
- Key onboarding, signer identity proofing, revocation, encrypted storage, and secure admin workflow remain integration responsibilities; no compliance certification is implied.
