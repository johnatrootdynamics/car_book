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


def _require_user():
    if not current_user.is_authenticated or getattr(current_user, "account_type", None) != "user":
        abort(403)


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
    updated = 0
    for waiver in waivers:
        if not waiver.boldsign_document_id or waiver.status == "signed":
            continue
        try:
            payload, status = get_document_status(waiver.boldsign_document_id)
        except Exception as exc:
            current_app.logger.warning(
                "BoldSign status lookup failed for waiver_id=%s document_id=%s error=%s",
                waiver.id,
                waiver.boldsign_document_id,
                exc,
            )
            continue

        status_map = {
            "sent": "sent",
            "inprogress": "viewed",
            "completed": "signed",
            "declined": "declined",
            "expired": "expired",
            "revoked": "failed",
            "failed": "failed",
        }
        mapped = status_map.get(status)
        if mapped and mapped != waiver.status:
            waiver.status = mapped
            waiver.webhook_payload = payload
            if mapped == "signed" and waiver.signed_at is None:
                waiver.signed_at = datetime.utcnow()
            if mapped == "viewed" and waiver.viewed_at is None:
                waiver.viewed_at = datetime.utcnow()
            updated += 1

    if updated:
        db.session.commit()
        return redirect(url_for("waiver.driver_waivers"))
    return redirect(url_for("waiver.driver_waivers"))


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

    redirect_url = f"{current_app.config.get('APP_BASE_URL', '')}{url_for('user.dashboard')}"
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

    if waiver.signing_url:
        return redirect(waiver.signing_url)

    if waiver.boldsign_document_id:
        try:
            redirect_url = f"{current_app.config.get('APP_BASE_URL', '')}{url_for('user.dashboard')}"
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

    return render_template("driver/waiver_sign.html", waiver=waiver)


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
    event_type = (
        payload.get("eventType")
        or payload.get("event")
        or payload.get("type")
        or payload.get("eventName")
        or ""
    ).lower()
    document_id = (
        payload.get("documentId")
        or payload.get("document", {}).get("documentId")
        or payload.get("data", {}).get("documentId")
    )
    signer_email = payload.get("signer", {}).get("emailAddress") or payload.get("signerEmail")

    waiver = None
    if document_id:
        waiver = DriverWaiver.query.filter_by(boldsign_document_id=document_id).first()
    if not waiver:
        metadata = payload.get("metadata") or payload.get("data", {}).get("metadata") or {}
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

    status_map = {
        "documentsent": "sent",
        "documentdelivered": "sent",
        "documentviewed": "viewed",
        "documentcompleted": "signed",
        "documentsigned": "signed",
        "completed": "signed",
        "documentdeclined": "declined",
        "documentexpired": "expired",
        "documentfailed": "failed",
    }
    waiver.status = status_map.get(event_type, waiver.status)
    waiver.boldsign_signer_email = signer_email or waiver.boldsign_signer_email
    waiver.webhook_payload = payload
    if waiver.status == "viewed" and waiver.viewed_at is None:
        waiver.viewed_at = datetime.utcnow()
    if waiver.status == "signed":
        waiver.signed_at = datetime.utcnow()
        waiver.signed_pdf_url = payload.get("downloadUrl") or payload.get("document", {}).get("downloadUrl")
    db.session.commit()

    return jsonify({"ok": True, "matched": True, "status": waiver.status}), 200


@waiver_bp.route("/admin/waivers/debug")
@login_required
def waiver_debug():
    if getattr(current_user, "account_type", None) not in {"admin", "employee"}:
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
