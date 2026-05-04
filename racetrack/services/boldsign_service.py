import hashlib
import hmac
import json
import logging
import os

import requests


logger = logging.getLogger(__name__)

BOLDSIGN_API_KEY = os.getenv("BOLDSIGN_API_KEY", "")
BOLDSIGN_WEBHOOK_SECRET = os.getenv("BOLDSIGN_WEBHOOK_SECRET", "")
BOLDSIGN_API_BASE = os.getenv("BOLDSIGN_API_BASE", "https://api.boldsign.com/v1")


def _headers():
    return {
        "X-API-KEY": BOLDSIGN_API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def send_waiver_from_template(template_id, signer_name, signer_email, redirect_url, metadata):
    endpoint = f"{BOLDSIGN_API_BASE}/template/send"
    payload = {
        "templateId": template_id,
        "signerDetails": [{"name": signer_name, "emailAddress": signer_email, "signerType": "Signer"}],
        "redirectUrl": redirect_url,
        "metadata": metadata or {},
    }
    response = requests.post(endpoint, headers=_headers(), data=json.dumps(payload), timeout=30)
    if not response.ok:
        logger.error("BoldSign send failed: %s %s", response.status_code, response.text)
        response.raise_for_status()
    return response.json()


def get_embedded_signing_link(document_id, signer_email):
    endpoint = f"{BOLDSIGN_API_BASE}/document/getEmbeddedSignLink"
    payload = {"documentId": document_id, "signerEmail": signer_email}
    response = requests.post(endpoint, headers=_headers(), data=json.dumps(payload), timeout=30)
    if not response.ok:
        logger.error("BoldSign embedded link failed: %s %s", response.status_code, response.text)
        response.raise_for_status()
    return response.json()


def download_signed_document(document_id):
    endpoint = f"{BOLDSIGN_API_BASE}/document/download?documentId={document_id}"
    response = requests.get(endpoint, headers=_headers(), timeout=30)
    if not response.ok:
        logger.error("BoldSign download failed: %s %s", response.status_code, response.text)
        response.raise_for_status()
    return response.content


def verify_webhook_signature(raw_body, signature_header):
    if not BOLDSIGN_WEBHOOK_SECRET or not signature_header:
        return False
    expected = hmac.new(
        BOLDSIGN_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    sent = signature_header.strip()
    if sent.startswith("sha256="):
        sent = sent.split("=", 1)[1]
    return hmac.compare_digest(expected, sent)
