import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Tuple
from urllib.parse import urlencode

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


def send_waiver_from_template(
    template_id,
    signer_name,
    signer_email,
    redirect_url,
    metadata,
    signer_role="User",
):
    query = urlencode({"templateId": template_id})
    endpoint = f"{BOLDSIGN_API_BASE}/template/send?{query}"
    payload = {
        "Roles": [
            {
                "RoleIndex": 1,
                "SignerName": signer_name,
                "SignerEmail": signer_email,
                "SignerType": "Signer",
                "SignerRole": signer_role,
            }
        ],
        "RedirectUrl": redirect_url,
        "Metadata": metadata or {},
        "DisableEmails": True,
    }

    response = requests.post(endpoint, headers=_headers(), data=json.dumps(payload), timeout=30)
    if response.ok:
        return response.json()

    logger.warning("BoldSign template/send JSON attempt failed: %s %s", response.status_code, response.text)

    form_payload = {
        "RedirectUrl": redirect_url,
        "Roles[0][RoleIndex]": "1",
        "Roles[0][SignerName]": signer_name,
        "Roles[0][SignerEmail]": signer_email,
        "Roles[0][SignerType]": "Signer",
        "Roles[0][SignerRole]": signer_role,
        "DisableEmails": "true",
    }
    if metadata:
        form_payload["Metadata"] = json.dumps(metadata)

    response_form = requests.post(
        endpoint,
        headers={"X-API-KEY": BOLDSIGN_API_KEY, "Accept": "application/json"},
        data=form_payload,
        timeout=30,
    )
    if not response_form.ok:
        logger.error(
            "BoldSign send failed after JSON+form attempts: json=%s form=%s",
            response.text,
            response_form.text,
        )
        response_form.raise_for_status()
    return response_form.json()


def get_embedded_signing_link(document_id, signer_email):
    query = urlencode({"documentId": document_id, "signerEmail": signer_email})
    endpoint = f"{BOLDSIGN_API_BASE}/document/getEmbeddedSignLink?{query}"
    response = requests.get(endpoint, headers={"X-API-KEY": BOLDSIGN_API_KEY, "Accept": "application/json"}, timeout=30)
    if not response.ok:
        logger.error("BoldSign embedded link failed: %s %s", response.status_code, response.text)
        response.raise_for_status()
    return response.json()


def create_embedded_template_url(file_bytes, filename, redirect_url, title="Track Ops Waiver Template"):
    endpoint = f"{BOLDSIGN_API_BASE}/template/createEmbeddedTemplateUrl"
    files = {"Files": (filename, file_bytes, "application/pdf")}
    data = {
        "Title": title,
        "DocumentTitle": title,
        "ViewOption": "PreparePage",
        "ShowToolbar": "true",
        "ShowSaveButton": "true",
        "ShowSendButton": "true",
        "ShowPreviewButton": "true",
        "ShowNavigationButtons": "true",
        "AllowNewFiles": "true",
        "AllowModifyFiles": "true",
        "Roles[0][name]": "User",
        "Roles[0][index]": "1",
    }
    if redirect_url:
        data["RedirectUrl"] = redirect_url
    response = requests.post(
        endpoint,
        headers={"X-API-KEY": BOLDSIGN_API_KEY, "Accept": "application/json"},
        data=data,
        files=files,
        timeout=60,
    )
    if not response.ok:
        logger.error("BoldSign embedded template create failed: %s %s", response.status_code, response.text)
        response.raise_for_status()
    return response.json()


def download_signed_document(document_id):
    endpoint = f"{BOLDSIGN_API_BASE}/document/download?documentId={document_id}"
    response = requests.get(endpoint, headers=_headers(), timeout=30)
    if not response.ok:
        logger.error("BoldSign download failed: %s %s", response.status_code, response.text)
        response.raise_for_status()
    return response.content


def list_templates(page=1, page_size=50):
    endpoints = [
        f"{BOLDSIGN_API_BASE}/template/list?page={page}&pageSize={page_size}",
        f"{BOLDSIGN_API_BASE}/template/list",
    ]
    last_error = None
    for endpoint in endpoints:
        try:
            response = requests.get(endpoint, headers=_headers(), timeout=30)
            if not response.ok:
                last_error = f"{response.status_code} {response.text}"
                continue
            payload = response.json() or {}
            templates = payload.get("result") or payload.get("data") or payload.get("templates") or []
            if isinstance(templates, dict):
                templates = templates.get("items") or templates.get("results") or []
            normalized = []
            for item in templates:
                template_id = item.get("templateId") or item.get("id")
                title = item.get("title") or item.get("name") or template_id
                if template_id:
                    normalized.append({"template_id": template_id, "title": title})
            return normalized
        except Exception as exc:
            last_error = str(exc)
            continue
    raise RuntimeError(f"BoldSign template list failed: {last_error or 'unknown error'}")


def verify_webhook_signature_details(raw_body, signature_header) -> Tuple[bool, str]:
    if not BOLDSIGN_WEBHOOK_SECRET:
        return False, "missing_webhook_secret"
    if not signature_header:
        return False, "missing_signature_header"

    sent = signature_header.strip()
    if sent.startswith("sha256="):
        sent = sent.split("=", 1)[1]
    if sent and "," not in sent:
        expected_simple = hmac.new(
            BOLDSIGN_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(expected_simple, sent):
            return True, "ok_simple_sha256"

    parsed = {"t": None, "signatures": []}
    for part in signature_header.split(","):
        item = part.strip()
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "t":
            try:
                parsed["t"] = int(value)
            except ValueError:
                return False, "invalid_timestamp"
        elif key in {"s0", "s1"}:
            parsed["signatures"].append(value)

    if parsed["t"] is None or not parsed["signatures"]:
        return False, "missing_timestamp_or_signatures"

    age = abs(int(time.time()) - parsed["t"])
    if age > 300:
        return False, "timestamp_out_of_window"

    payload_to_sign = f"{parsed['t']}.".encode("utf-8") + raw_body
    computed_hex = hmac.new(
        BOLDSIGN_WEBHOOK_SECRET.encode("utf-8"), payload_to_sign, hashlib.sha256
    ).hexdigest()
    computed_b64 = base64.b64encode(
        hmac.new(
        BOLDSIGN_WEBHOOK_SECRET.encode("utf-8"), payload_to_sign, hashlib.sha256
        ).digest()
    ).decode("utf-8")
    if any(hmac.compare_digest(computed_hex, sig) for sig in parsed["signatures"]):
        return True, "ok_timestamped_sha256_hex"
    if any(hmac.compare_digest(computed_b64, sig) for sig in parsed["signatures"]):
        return True, "ok_timestamped_sha256_digest"
    return False, "signature_mismatch"


def verify_webhook_signature(raw_body, signature_header):
    ok, _reason = verify_webhook_signature_details(raw_body, signature_header)
    return ok
