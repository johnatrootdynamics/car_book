import base64
import hashlib
import json
import re
import time
import zipfile
from datetime import datetime, time as datetime_time, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12, pkcs7
from flask import current_app, url_for


def _decode_base64(value):
    if not value:
        return b""
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return b""


def _environment_wallet_configuration():
    google_json = current_app.config.get("GOOGLE_WALLET_SERVICE_ACCOUNT_JSON") or ""
    if google_json and not google_json.lstrip().startswith("{"):
        decoded = _decode_base64(google_json)
        google_json = decoded.decode("utf-8") if decoded else ""
    apple_certificate = _decode_base64(
        current_app.config.get("APPLE_WALLET_CERTIFICATE_BASE64") or ""
    )
    return {
        "source": "environment",
        "apple_enabled": bool(
            current_app.config.get("APPLE_WALLET_PASS_TYPE_ID")
            and current_app.config.get("APPLE_WALLET_TEAM_ID")
            and apple_certificate
        ),
        "apple_pass_type_id": current_app.config.get("APPLE_WALLET_PASS_TYPE_ID") or "",
        "apple_team_id": current_app.config.get("APPLE_WALLET_TEAM_ID") or "",
        "apple_certificate": apple_certificate,
        "apple_certificate_password": current_app.config.get("APPLE_WALLET_CERTIFICATE_PASSWORD") or "",
        "google_enabled": bool(
            current_app.config.get("GOOGLE_WALLET_ISSUER_ID") and google_json
        ),
        "google_issuer_id": current_app.config.get("GOOGLE_WALLET_ISSUER_ID") or "",
        "google_service_account_json": google_json,
    }


def get_wallet_configuration(include_secrets=True):
    from ..models import SystemWalletSettings
    from .email_service import decrypt_secret

    settings = SystemWalletSettings.query.get(1)
    if not settings:
        config = _environment_wallet_configuration()
    else:
        config = {
            "source": "admin",
            "apple_enabled": bool(settings.apple_enabled),
            "apple_pass_type_id": settings.apple_pass_type_id or "",
            "apple_team_id": settings.apple_team_id or "",
            "apple_certificate": (
                decrypt_secret(settings.apple_certificate_encrypted, as_bytes=True)
                if include_secrets
                else b""
            ),
            "apple_certificate_password": (
                decrypt_secret(settings.apple_certificate_password_encrypted)
                if include_secrets
                else ""
            ),
            "google_enabled": bool(settings.google_enabled),
            "google_issuer_id": settings.google_issuer_id or "",
            "google_service_account_json": (
                decrypt_secret(settings.google_service_account_encrypted)
                if include_secrets
                else ""
            ),
            "apple_certificate_saved": bool(settings.apple_certificate_encrypted),
            "google_service_account_saved": bool(settings.google_service_account_encrypted),
        }
    if config.get("source") == "environment":
        config["apple_certificate_saved"] = bool(config.get("apple_certificate"))
        config["google_service_account_saved"] = bool(
            config.get("google_service_account_json")
        )
    config["apple_ready"] = bool(
        config.get("apple_enabled")
        and config.get("apple_pass_type_id")
        and config.get("apple_team_id")
        and config.get("apple_certificate_saved", config.get("apple_certificate"))
    )
    config["google_ready"] = bool(
        config.get("google_enabled")
        and config.get("google_issuer_id")
        and config.get(
            "google_service_account_saved", config.get("google_service_account_json")
        )
    )
    if not include_secrets:
        config.pop("apple_certificate", None)
        config.pop("apple_certificate_password", None)
        config.pop("google_service_account_json", None)
    return config


def _safe_id(value):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value))


def _event_datetime(event):
    event_time = event.event_start_time or datetime_time(hour=9)
    timezone = ZoneInfo(current_app.config.get("TRACK_TIMEZONE") or "America/New_York")
    return datetime.combine(event.event_date, event_time, tzinfo=timezone)


def _localized(value):
    return {"defaultValue": {"language": "en-US", "value": str(value)}}


def resolve_wallet_ticket(code):
    from ..models import DriverTicketOrder, EventRegistration, SpectatorOrderItem, TrackEmailTemplate
    from .payment_service import effective_payment_status

    normalized = (code or "").strip().upper()
    item = SpectatorOrderItem.query.filter_by(qr_code=normalized).first()
    if item and effective_payment_status(item.order) == "paid":
        order = item.order
        holder = (
            (order.vendor.business_name if order.vendor else None)
            or (f"{order.buyer.first_name} {order.buyer.last_name}" if order.buyer else None)
            or order.guest_full_name
            or "Ticket holder"
        )
        template = TrackEmailTemplate.query.filter_by(
            track_id=item.event.track_id,
            template_key="spectator_purchase_receipt",
            is_enabled=True,
        ).first()
        return {
            "code": normalized,
            "event": item.event,
            "track": item.event.track,
            "holder": holder,
            "ticket_type": "Vendor" if item.ticket_category == "vendor" else item.ticket_type_name,
            "order_number": order.order_number,
            "design": template.ticket_design if template else "pit_pass",
        }

    registrations = EventRegistration.query.filter_by(checkin_code=normalized).order_by(
        EventRegistration.id.desc()
    )
    for registration in registrations:
        order = DriverTicketOrder.query.filter_by(
            event_id=registration.event_id,
            user_id=registration.user_id,
        ).order_by(DriverTicketOrder.id.desc()).first()
        if not order or effective_payment_status(order) != "paid":
            continue
        template = TrackEmailTemplate.query.filter_by(
            track_id=registration.event.track_id,
            template_key="driver_purchase_receipt",
            is_enabled=True,
        ).first()
        return {
            "code": normalized,
            "event": registration.event,
            "track": registration.event.track,
            "holder": f"{registration.user.first_name} {registration.user.last_name}".strip(),
            "ticket_type": "Driver",
            "order_number": f"DR-{order.id:06d}",
            "design": template.ticket_design if template else "pit_pass",
        }
    return None


def wallet_links_for_ticket(code):
    config = get_wallet_configuration(include_secrets=False)
    links = {}
    if config["apple_ready"]:
        links["apple"] = url_for("user.apple_wallet_ticket", code=code, _external=True)
    if config["google_ready"]:
        links["google"] = url_for("user.google_wallet_ticket", code=code, _external=True)
    return links


def _wallet_icon(size, design):
    from PIL import Image, ImageDraw

    background = "#111827" if design == "pit_pass" else "#1d4ed8"
    accent = "#f97316" if design == "pit_pass" else "#ffffff"
    image = Image.new("RGB", (size, size), background)
    draw = ImageDraw.Draw(image)
    unit = max(2, size // 6)
    top = max(2, size // 5)
    left = max(2, size // 5)
    for row in range(4):
        for column in range(4):
            if (row + column) % 2 == 0:
                draw.rectangle(
                    (left + column * unit, top + row * unit, left + (column + 1) * unit, top + (row + 1) * unit),
                    fill=accent,
                )
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def build_apple_pass(ticket):
    config = get_wallet_configuration()
    if not config["apple_ready"]:
        raise RuntimeError("Apple Wallet is not configured.")

    event = ticket["event"]
    track = ticket["track"]
    start = _event_datetime(event)
    verify_url = url_for("employee.ticket_verification", code=ticket["code"], _external=True)
    pit_pass = ticket.get("design") != "clean_grid"
    pass_json = {
        "formatVersion": 1,
        "passTypeIdentifier": config["apple_pass_type_id"],
        "serialNumber": hashlib.sha256(ticket["code"].encode()).hexdigest()[:32],
        "teamIdentifier": config["apple_team_id"],
        "organizationName": track.name,
        "description": f"{ticket['ticket_type']} ticket for {event.event_name}",
        "logoText": track.name,
        "foregroundColor": "rgb(255, 255, 255)",
        "labelColor": "rgb(203, 213, 225)" if pit_pass else "rgb(219, 234, 254)",
        "backgroundColor": "rgb(17, 24, 39)" if pit_pass else "rgb(29, 78, 216)",
        "relevantDate": start.isoformat(),
        "expirationDate": (start + timedelta(days=1)).isoformat(),
        "eventTicket": {
            "primaryFields": [
                {"key": "event", "label": "EVENT", "value": event.event_name}
            ],
            "secondaryFields": [
                {"key": "date", "label": "DATE", "value": start.isoformat(), "dateStyle": "PKDateStyleMedium", "timeStyle": "PKDateStyleShort"},
                {"key": "type", "label": "ADMISSION", "value": ticket["ticket_type"]},
            ],
            "auxiliaryFields": [
                {"key": "holder", "label": "TICKET HOLDER", "value": ticket["holder"]},
                {"key": "order", "label": "ORDER", "value": ticket["order_number"]},
            ],
            "backFields": [
                {"key": "venue", "label": "VENUE", "value": f"{track.name}, {track.city}, {track.state}"},
                {"key": "instructions", "label": "ENTRY", "value": "Present this QR code to track staff for admission."},
            ],
        },
        "barcode": {
            "format": "PKBarcodeFormatQR",
            "message": verify_url,
            "messageEncoding": "iso-8859-1",
            "altText": ticket["code"],
        },
        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": verify_url,
                "messageEncoding": "iso-8859-1",
                "altText": ticket["code"],
            }
        ],
    }
    files = {
        "pass.json": json.dumps(pass_json, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        "icon.png": _wallet_icon(29, ticket.get("design")),
        "icon@2x.png": _wallet_icon(58, ticket.get("design")),
        "logo.png": _wallet_icon(40, ticket.get("design")),
        "logo@2x.png": _wallet_icon(80, ticket.get("design")),
    }
    manifest = {
        name: hashlib.sha1(content).hexdigest() for name, content in files.items()
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    files["manifest.json"] = manifest_bytes

    password = config["apple_certificate_password"].encode() or None
    private_key, certificate, extra_certificates = pkcs12.load_key_and_certificates(
        config["apple_certificate"], password
    )
    if not private_key or not certificate:
        raise RuntimeError("The Apple Wallet certificate file does not contain a signing identity.")
    builder = pkcs7.PKCS7SignatureBuilder().set_data(manifest_bytes).add_signer(
        certificate, private_key, hashes.SHA256()
    )
    for extra_certificate in extra_certificates or []:
        if isinstance(extra_certificate, x509.Certificate):
            builder = builder.add_certificate(extra_certificate)
    files["signature"] = builder.sign(
        serialization.Encoding.DER,
        [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary],
    )

    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def build_google_wallet_url(ticket):
    config = get_wallet_configuration()
    if not config["google_ready"]:
        raise RuntimeError("Google Wallet is not configured.")
    service_account = json.loads(config["google_service_account_json"])
    issuer_id = _safe_id(config["google_issuer_id"])
    event = ticket["event"]
    track = ticket["track"]
    start = _event_datetime(event)
    class_id = f"{issuer_id}.event_{event.id}"
    object_suffix = hashlib.sha256(ticket["code"].encode()).hexdigest()[:28]
    object_id = f"{issuer_id}.ticket_{object_suffix}"
    verify_url = url_for("employee.ticket_verification", code=ticket["code"], _external=True)
    wallet_class = {
        "id": class_id,
        "issuerName": track.name[:80],
        "reviewStatus": "UNDER_REVIEW",
        "eventId": f"trackops-event-{event.id}",
        "eventName": _localized(event.event_name[:80]),
        "dateTime": {"start": start.isoformat()},
    }
    wallet_object = {
        "id": object_id,
        "classId": class_id,
        "state": "ACTIVE",
        "ticketHolderName": ticket["holder"][:80],
        "ticketNumber": ticket["code"],
        "ticketType": _localized(ticket["ticket_type"][:60]),
        "reservationInfo": {"confirmationCode": ticket["order_number"]},
        "hexBackgroundColor": "#111827" if ticket.get("design") != "clean_grid" else "#1d4ed8",
        "barcode": {
            "type": "QR_CODE",
            "value": verify_url,
            "alternateText": ticket["code"],
        },
    }
    payload = {
        "iss": service_account["client_email"],
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(time.time()),
        "origins": [],
        "payload": {
            "eventTicketClasses": [wallet_class],
            "eventTicketObjects": [wallet_object],
        },
    }
    header = {"alg": "RS256", "typ": "JWT"}

    def encode_part(value):
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    encoded_header = encode_part(header)
    encoded_payload = encode_part(payload)
    signing_input = encoded_header + b"." + encoded_payload
    private_key = serialization.load_pem_private_key(
        service_account["private_key"].encode("utf-8"), password=None
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    token = b".".join((encoded_header, encoded_payload, encoded_signature)).decode("ascii")
    return f"https://pay.google.com/gp/v/save/{token}"
