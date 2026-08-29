from datetime import datetime
import os

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .models import DriverWaiver, Event, EventRegistration, TrackWaiverTemplate, db
from .services.boldsign_service import (
    get_document_status,
    get_embedded_signing_link,
    send_waiver_from_template,
    verify_webhook_signature_details,
)


waiver_bp = Blueprint("waiver", __name__)
FORCED_BOLDSIGN_TEMPLATE_ID = os.getenv(
    "BOLDSIGN_FORCED_TEMPLATE_ID", "e5c8f024-64df-4bdc-9142-3a04c01a154a"
)
BOLDSIGN_SIGNER_ROLE = os.getenv("BOLDSIGN_SIGNER_ROLE", "User")
TERMINAL_WAIVER_STATUSES = {"signed", "declined", "expired", "failed"}
BOLDSIGN_STATUS_MAP = {
    "sent": "sent",
    "delivered": "sent",
    "inprogress": "viewed",
    "viewed": "viewed",
    "signed": "signed",
    "completed": "signed",
    "declined": "declined",
    "expired": "expired",
    "revoked": "failed",
    "failed": "failed",
    "sendfailed": "failed",
    "documentsent": "sent",
    "documentdelivered": "sent",
    "documentviewed": "viewed",
    "documentsigned": "signed",
    "documentcompleted": "signed",
    "documentdeclined": "declined",
    "documentexpired": "expired",
    "documentfailed": "failed",
}


def _require_user():
    if not current_user.is_authenticated or getattr(current_user, "account_type", None) != "user":
        abort(403)


def _normalized_status(value):
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _app_url(endpoint, **values):
    path = url_for(endpoint, **values)
    app_base_url = (current_app.config.get("APP_BASE_URL") or "").rstrip("/")
    return f"{app_base_url}{path}" if app_base_url else url_for(endpoint, _external=True, **values)


def _apply_waiver_status(waiver, payload, provider_status, signer_email=None):
    """Apply a BoldSign document status and return whether user-visible data changed."""
    mapped_status = BOLDSIGN_STATUS_MAP.get(_normalized_status(provider_status))
    if not mapped_status:
        return False

    changed = mapped_status != waiver.status
    waiver.status = mapped_status
    waiver.webhook_payload = payload

    if signer_email and signer_email != waiver.boldsign_signer_email:
        waiver.boldsign_signer_email = signer_email
        changed = True

    if mapped_status == "viewed" and waiver.viewed_at is None:
        waiver.viewed_at = datetime.utcnow()
        changed = True
    if mapped_status == "signed" and waiver.signed_at is None:
        waiver.signed_at = datetime.utcnow()
        changed = True

    payload_data = payload.get("data", {}) if isinstance(payload, dict) else {}
    payload_document = payload.get("document", {}) if isinstance(payload, dict) else {}
    payload_data = payload_data if isinstance(payload_data, dict) else {}
    payload_document = payload_document if isinstance(payload_document, dict) else {}
    signed_pdf_url = (
        payload.get("downloadUrl")
        or payload_data.get("downloadUrl")
        or payload_document.get("downloadUrl")
        if isinstance(payload, dict)
        else None
    )
    if signed_pdf_url and signed_pdf_url != waiver.signed_pdf_url:
        waiver.signed_pdf_url = signed_pdf_url
        changed = True

    return changed


def _sync_waiver_from_provider(waiver):
    if not waiver.boldsign_document_id or waiver.status in TERMINAL_WAIVER_STATUSES:
        return False
    try:
        payload, status = get_document_status(waiver.boldsign_document_id)
    except Exception as exc:
        current_app.logger.warning(
            "BoldSign status lookup failed for waiver_id=%s document_id=%s error=%s",
            waiver.id,
            waiver.boldsign_document_id,
            exc,
        )
        return False
    return _apply_waiver_status(waiver, payload, status)


@waiver_bp.route("/driver/waivers")
@login_required
def driver_waivers():
    _require_user()
    waivers = (
        DriverWaiver.query.filter_by(driver_id=current_user.id)
        .order_by(DriverWaiver.updated_at.desc())
        .all()
    )
    templates = (
        TrackWaiverTemplate.query.filter_by(is_active=True)
        .order_by(TrackWaiverTemplate.updated_at.desc())
        .all()
    )
    return render_template("driver/waivers.html", waivers=waivers, templates=templates)


@waiver_bp.route("/driver/waivers/sync", methods=["POST"])
@login_required
def sync_driver_waivers():
    _require_user()
    waivers = DriverWaiver.query.filter_by(driver_id=current_user.id).all()
    updated = False
    for waiver in waivers:
        updated = _sync_waiver_from_provider(waiver) or updated
    if updated:
        db.session.commit()
    return redirect(url_for("waiver.driver_waivers"))


@waiver_bp.route("/driver/waivers/status")
@login_required
def driver_waiver_statuses():
    """Return current waiver state, refreshing pending records from BoldSign first."""
    _require_user()
    waiver_id = request.args.get("waiver_id", type=int)
    query = DriverWaiver.query.filter_by(driver_id=current_user.id)
    if waiver_id:
        query = query.filter_by(id=waiver_id)
    waivers = query.all()

    updated = False
    for waiver in waivers:
        updated = _sync_waiver_from_provider(waiver) or updated
    if updated:
        db.session.commit()

    return jsonify(
        {
            "waivers": [
                {
                    "id": waiver.id,
                    "status": waiver.status,
                    "signed_at": waiver.signed_at.isoformat() if waiver.signed_at else None,
                    "signed_pdf_url": waiver.signed_pdf_url,
                }
                for waiver in waivers
            ],
            "pending": any(
                waiver.boldsign_document_id
                and waiver.status not in TERMINAL_WAIVER_STATUSES
                for waiver in waivers
            ),
        }
    )


@waiver_bp.route("/driver/waivers/<int:waiver_template_id>/send", methods=["POST"])
@login_required
def send_driver_waiver(waiver_template_id):
    _require_user()
    template = TrackWaiverTemplate.query.filter_by(id=waiver_template_id, is_active=True).first_or_404()
    event_id = request.form.get("event_id", type=int)
    event = Event.query.get(event_id) if event_id else None

    waiver = DriverWaiver.query.filter_by(
        track_id=template.track_id,
        driver_id=current_user.id,
        waiver_template_id=template.id,
        event_id=event.id if event else None,
    ).first()
    if not waiver:
        waiver = DriverWaiver(
            track_id=template.track_id,
            driver_id=current_user.id,
            event_id=event.id if event else None,
            waiver_template_id=template.id,
        )
        db.session.add(waiver)
        db.session.flush()

    redirect_url = _app_url("waiver.driver_waiver_return", driver_waiver_id=waiver.id)
    signer_name = f"{current_user.first_name} {current_user.last_name}".strip()
    if not signer_name:
        signer_name = (getattr(current_user, "username", "") or current_user.email).strip()
    metadata = {
        "driverWaiverId": str(waiver.id),
        "trackId": str(template.track_id),
        "driverId": str(current_user.id),
        "localTemplateId": str(template.id),
    }

    template_id_to_send = (template.boldsign_template_id or "").strip() or FORCED_BOLDSIGN_TEMPLATE_ID
    if not template_id_to_send:
        current_app.logger.error("No BoldSign template ID available for waiver send")
        return redirect(url_for("waiver.driver_waivers"))

    try:
        send_result = send_waiver_from_template(
            template_id_to_send,
            signer_name,
            current_user.email,
            redirect_url,
            metadata,
            signer_role=BOLDSIGN_SIGNER_ROLE,
        )
        waiver.boldsign_document_id = send_result.get("documentId") or send_result.get("id")
        waiver.boldsign_signer_email = current_user.email
        waiver.status = "sent"
        waiver.sent_at = datetime.utcnow()

        db.session.commit()
    except Exception as exc:
        waiver.status = "failed"
        db.session.commit()
        current_app.logger.exception("BoldSign send failed: %s", exc)
        return redirect(url_for("waiver.driver_waivers"))

    if not waiver.signing_url and waiver.boldsign_document_id:
        try:
            sign_result = get_embedded_signing_link(
                waiver.boldsign_document_id,
                current_user.email,
                redirect_url=redirect_url,
            )
            waiver.signing_url = sign_result.get("signLink") or sign_result.get("url")
            db.session.commit()
        except Exception as exc:
            current_app.logger.warning("BoldSign embedded link fetch after send failed: %s", exc)

    return redirect(url_for("waiver.driver_sign_waiver", driver_waiver_id=waiver.id))


@waiver_bp.route("/driver/waivers/<int:driver_waiver_id>/sign")
@login_required
def driver_sign_waiver(driver_waiver_id):
    _require_user()
    waiver = DriverWaiver.query.filter_by(id=driver_waiver_id, driver_id=current_user.id).first_or_404()
    if waiver.status == "signed":
        return redirect(url_for("waiver.driver_waivers"))

    if waiver.boldsign_document_id:
        try:
            redirect_url = _app_url(
                "waiver.driver_waiver_return", driver_waiver_id=waiver.id
            )
            sign_result = get_embedded_signing_link(
                waiver.boldsign_document_id,
                current_user.email,
                redirect_url=redirect_url,
            )
            sign_url = sign_result.get("signLink") or sign_result.get("url")
            if sign_url:
                waiver.signing_url = sign_url
                db.session.commit()
                return redirect(sign_url)
        except Exception as exc:
            current_app.logger.warning("BoldSign embedded link refresh failed: %s", exc)

    if waiver.signing_url:
        return redirect(waiver.signing_url)

    return render_template("driver/waiver_sign.html", waiver=waiver)


@waiver_bp.route("/driver/waivers/<int:driver_waiver_id>/return")
@login_required
def driver_waiver_return(driver_waiver_id):
    """Bring drivers back to a page that watches for BoldSign completion."""
    _require_user()
    waiver = DriverWaiver.query.filter_by(
        id=driver_waiver_id, driver_id=current_user.id
    ).first_or_404()
    if _sync_waiver_from_provider(waiver):
        db.session.commit()
    return redirect(url_for("waiver.driver_waivers", watch=waiver.id))


@waiver_bp.route("/webhooks/boldsign", methods=["POST"])
def boldsign_webhook():
    raw_body = request.get_data()
    signature = request.headers.get("X-BoldSign-Signature", "")
    token_header = request.headers.get("X-Webhook-Token", "")
    webhook_secret = os.getenv("BOLDSIGN_WEBHOOK_SECRET", "")

    if webhook_secret and token_header and token_header == webhook_secret:
        verified = True
        verify_reason = "ok_custom_header_token"
    else:
        verified, verify_reason = verify_webhook_signature_details(raw_body, signature)

    if not verified:
        current_app.logger.warning(
            "BoldSign webhook verification failed: reason=%s content_type=%s ua=%s has_sig=%s has_token=%s",
            verify_reason,
            request.headers.get("Content-Type", ""),
            request.headers.get("User-Agent", ""),
            bool(signature),
            bool(token_header),
        )
        return jsonify({"ok": False, "error": "invalid signature"}), 401

    payload = request.get_json(silent=True) or {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    event_type = _normalized_status(
        payload.get("eventType")
        or event.get("eventType")
        or context.get("eventType")
        or payload.get("type")
        or payload.get("eventName")
        or (payload.get("event") if isinstance(payload.get("event"), str) else "")
    )
    document = payload.get("document") if isinstance(payload.get("document"), dict) else {}
    document_id = (
        payload.get("documentId")
        or document.get("documentId")
        or data.get("documentId")
    )
    signer_details = data.get("signerDetails") or []
    first_signer = signer_details[0] if signer_details and isinstance(signer_details[0], dict) else {}
    signer = payload.get("signer") if isinstance(payload.get("signer"), dict) else {}
    signer_email = (
        signer.get("emailAddress")
        or payload.get("signerEmail")
        or first_signer.get("signerEmail")
        or first_signer.get("emailAddress")
    )

    waiver = None
    if document_id:
        waiver = DriverWaiver.query.filter_by(boldsign_document_id=document_id).first()
    if not waiver:
        metadata = (
            payload.get("metadata")
            or data.get("metadata")
            or data.get("metaData")
            or {}
        )
        waiver_id = metadata.get("driverWaiverId") or metadata.get("driver_waiver_id")
        if waiver_id:
            try:
                waiver = DriverWaiver.query.filter_by(id=int(waiver_id)).first()
            except (TypeError, ValueError):
                waiver = None
    if not waiver:
        current_app.logger.warning(
            "BoldSign webhook received but waiver not matched: event_type=%s document_id=%s",
            event_type,
            document_id,
        )
        return jsonify({"ok": True, "matched": False}), 200

    provider_status = data.get("status") or event_type
    _apply_waiver_status(waiver, payload, provider_status, signer_email=signer_email)
    db.session.commit()

    return jsonify({"ok": True, "matched": True, "status": waiver.status}), 200


@waiver_bp.route("/admin/waivers/debug")
@login_required
def waiver_debug():
    account_type = getattr(current_user, "account_type", None)
    if account_type != "admin" and not (
        account_type == "employee" and getattr(current_user, "role", None) == "office_staff"
    ):
        abort(403)
    latest = DriverWaiver.query.order_by(DriverWaiver.updated_at.desc()).limit(20).all()
    return render_template("admin/waivers_debug.html", waivers=latest)


def get_required_waiver_status(track_id, driver_id, event_id=None):
    required_templates = TrackWaiverTemplate.query.filter_by(
        track_id=track_id, is_active=True, required_for_checkin=True
    ).all()
    if not required_templates:
        return "not_required", None
    template_ids = [t.id for t in required_templates]
    query = DriverWaiver.query.filter(
        DriverWaiver.track_id == track_id,
        DriverWaiver.driver_id == driver_id,
        DriverWaiver.waiver_template_id.in_(template_ids),
    )
    if event_id is not None:
        query = query.filter((DriverWaiver.event_id == event_id) | (DriverWaiver.event_id.is_(None)))
    waiver = query.order_by(DriverWaiver.updated_at.desc()).first()
    if waiver and waiver.status == "signed":
        return "signed", waiver
    return "missing", waiver
