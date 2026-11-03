"""Document byte-integrity and trusted detached Ed25519 origin verification.

A signed byte stream and an independently configured public key can establish
integrity/origin *relative to that trusted key*. Neither OCR nor an invoice's
financial legitimacy is implied. Unsigned PDFs cannot be authenticated here.
"""
from __future__ import annotations
import base64, binascii, hashlib, json, os, re
from pydantic import BaseModel, Field, ConfigDict
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

class DocumentRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    document_b64:str=Field(min_length=4,max_length=4_000_000)
    expected_sha256:str=Field(pattern=r'^[0-9a-fA-F]{64}$')
    signature_b64:str|None=None
    key_id:str|None=Field(default=None,max_length=100)
    filename:str|None=Field(default=None,max_length=255)


def trusted_keys(tenant:str):
    try:
        keys=json.loads(os.environ.get('PROOFLINE_TRUSTED_DOCUMENT_KEYS','{}'))
        record=keys.get(tenant,{}) if isinstance(keys,dict) else {}
        if not isinstance(record,dict):return {}
        return record
    except (TypeError,ValueError):return {}


def verify_document(tenant:str,request:DocumentRequest)->dict:
    try:
        raw=base64.b64decode(request.document_b64,validate=True)
    except (ValueError,binascii.Error):raise ValueError('Invalid document encoding')
    if len(raw)>2_000_000:raise ValueError('Document exceeds 2 MB limit')
    digest=hashlib.sha256(raw).hexdigest()
    digest_matches=digest==request.expected_sha256.lower()
    mime='application/pdf' if raw.startswith(b'%PDF-') else 'application/octet-stream'
    reasons=[]
    if not digest_matches:reasons.append('HASH_MISMATCH')
    if request.filename and request.filename.lower().endswith('.pdf') and mime!='application/pdf':reasons.append('PDF_HEADER_MISMATCH')
    signed=request.signature_b64 is not None or request.key_id is not None
    valid_signature=False
    if signed:
        if not request.signature_b64 or not request.key_id:
            reasons.append('INCOMPLETE_SIGNATURE')
        else:
            key=trusted_keys(tenant).get(request.key_id)
            if not isinstance(key,str):reasons.append('UNTRUSTED_SIGNER')
            else:
                try:
                    public=Ed25519PublicKey.from_public_bytes(base64.b64decode(key,validate=True))
                    signature=base64.b64decode(request.signature_b64,validate=True)
                    public.verify(signature,raw)
                    valid_signature=True
                except (ValueError,binascii.Error,InvalidSignature):reasons.append('INVALID_SIGNATURE')
    else:
        reasons.append('NO_SIGNATURE')
    # No success claim is based solely on matching an untrusted supplied hash.
    status='VERIFIED_SIGNATURE' if digest_matches and valid_signature and not reasons else ('FAILED' if any(r in reasons for r in ('HASH_MISMATCH','INVALID_SIGNATURE','PDF_HEADER_MISMATCH')) else 'UNVERIFIED')
    return {'status':status,'sha256':digest,'expected_hash_matches':digest_matches,'signature_valid':valid_signature,
            'trusted_key_id':request.key_id if valid_signature else None,'bytes':len(raw),'detected_mime':mime,'findings':reasons,
            'limits':'Verifies supplied bytes against a separately trusted Ed25519 public key; not embedded PDF signatures, identity/KYC, OCR correctness, invoice issuance, or payment entitlement.'}
