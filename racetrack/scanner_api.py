import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .models import RfidTag, ScannerDevice, ScannerObservation, TrackCarStatus, db


scanner_api_bp = Blueprint("scanner_api", __name__, url_prefix="/api/v1/scanners")


def normalize_epc(value):
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _token_serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="scanner-device-v1")


def _device_from_bearer():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        device_uuid = _token_serializer().loads(header[7:].strip())
    except BadSignature:
        return None
    return ScannerDevice.query.filter_by(device_uuid=device_uuid, status="active").first()


def _parse_datetime(value):
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


@scanner_api_bp.post("/registration/start")
def registration_start():
    data = request.get_json(silent=True) or {}
    device_uuid = str(data.get("device_uuid") or "").strip()
    pairing_code = str(data.get("pairing_code") or "").strip().upper()
    if len(device_uuid) < 12 or len(pairing_code) < 6:
        return jsonify(error="device_uuid and a pairing code of at least 6 characters are required"), 400

    device = ScannerDevice.query.filter_by(device_uuid=device_uuid).first()
    if device and device.status == "active":
        return jsonify(status="registered"), 409
    if not device:
        device = ScannerDevice(device_uuid=device_uuid)
        db.session.add(device)
    poll_token = secrets.token_urlsafe(32)
    device.status = "pending"
    device.pairing_code_hash = generate_password_hash(pairing_code)
    device.pairing_expires_at = datetime.utcnow() + timedelta(minutes=20)
    device.poll_token_hash = hashlib.sha256(poll_token.encode()).hexdigest()
    device.software_version = str(data.get("software_version") or "")[:60] or None
    db.session.commit()
    return jsonify(status="pending", poll_token=poll_token, expires_at=device.pairing_expires_at.isoformat() + "Z")


@scanner_api_bp.get("/registration/<device_uuid>/status")
def registration_status(device_uuid):
    device = ScannerDevice.query.filter_by(device_uuid=device_uuid).first()
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    digest = hashlib.sha256(supplied.encode()).hexdigest() if supplied else ""
    if not device or not secrets.compare_digest(device.poll_token_hash or "", digest):
        return jsonify(error="invalid registration credentials"), 401
    if device.status != "active":
        return jsonify(status=device.status)
    return jsonify(
        status="registered",
        device_token=_token_serializer().dumps(device.device_uuid),
        scanner={"name": device.name, "role": device.role, "track_id": device.track_id},
    )


@scanner_api_bp.post("/heartbeat")
def heartbeat():
    device = _device_from_bearer()
    if not device:
        return jsonify(error="invalid scanner token"), 401
    data = request.get_json(silent=True) or {}
    device.last_seen_at = datetime.utcnow()
    device.reader_connected = bool(data.get("reader_connected", False))
    device.software_version = str(data.get("software_version") or device.software_version or "")[:60] or None
    db.session.commit()
    return jsonify(ok=True, scanner={"name": device.name, "role": device.role})


@scanner_api_bp.post("/observations")
def observations():
    device = _device_from_bearer()
    if not device:
        return jsonify(error="invalid scanner token"), 401
    data = request.get_json(silent=True) or {}
    rows = data.get("observations") if isinstance(data.get("observations"), list) else [data]
    results = []
    for row in rows[:250]:
        event_uuid = str(row.get("event_id") or row.get("event_uuid") or "").strip()
        epc = normalize_epc(row.get("epc") or row.get("tag_value"))
        observed_at = _parse_datetime(row.get("observed_at"))
        if not event_uuid or not epc or not observed_at:
            results.append({"event_id": event_uuid, "status": "invalid"})
            continue
        existing = ScannerObservation.query.filter_by(scanner_id=device.id, event_uuid=event_uuid).first()
        if existing:
            results.append({"event_id": event_uuid, "status": "duplicate"})
            continue
        tag = RfidTag.query.filter_by(epc=epc, status="active").first()
        result, reason = "accepted", None
        if not device.track_id:
            result, reason = "ignored", "scanner is not assigned to a track"
        elif device.role not in {"track_entrance", "track_exit"}:
            result, reason = "ignored", "scanner role is unassigned"
        elif not tag or not tag.car_id:
            result, reason = "unknown_tag", "tag is not activated to a car"
        observation = ScannerObservation(
            scanner_id=device.id, event_uuid=event_uuid, epc=epc, observed_at=observed_at,
            result=result, reason=reason, car_id=tag.car_id if tag else None,
        )
        db.session.add(observation)
        db.session.flush()
        if result == "accepted":
            state = TrackCarStatus.query.filter_by(track_id=device.track_id, car_id=tag.car_id).first()
            if not state:
                state = TrackCarStatus(track_id=device.track_id, car_id=tag.car_id)
                db.session.add(state)
            desired_state = device.role == "track_entrance"
            if not state.changed_at or observed_at >= state.changed_at:
                state.is_on_track = desired_state
                state.last_scanner_id = device.id
                state.last_observation_id = observation.id
                state.changed_at = observed_at
        results.append({"event_id": event_uuid, "status": result})
    device.last_seen_at = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="observation conflict; retry the batch"), 409
    return jsonify(results=results)
