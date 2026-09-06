import hashlib
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.security import generate_password_hash

from .models import CameraDevice, TrackRun, TrackRunVideo, db
from .services.storage_service import build_presigned_upload_url


camera_api_bp = Blueprint("camera_api", __name__, url_prefix="/api/v1/cameras")


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="camera-device-v1")


def _device():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    try:
        device_uuid = _serializer().loads(token)
    except BadSignature:
        return None
    return CameraDevice.query.filter_by(device_uuid=device_uuid, status="active").first()


@camera_api_bp.post("/registration/start")
def registration_start():
    data = request.get_json(silent=True) or {}
    device_uuid = str(data.get("device_uuid") or "").strip()
    pairing_code = str(data.get("pairing_code") or "").strip().upper()
    if len(device_uuid) < 12 or len(pairing_code) < 6:
        return jsonify(error="device_uuid and pairing code are required"), 400
    device = CameraDevice.query.filter_by(device_uuid=device_uuid).first() or CameraDevice(device_uuid=device_uuid)
    db.session.add(device)
    poll_token = secrets.token_urlsafe(32)
    device.status = "pending"
    device.pairing_code_hash = generate_password_hash(pairing_code)
    device.pairing_expires_at = datetime.utcnow() + timedelta(minutes=20)
    device.poll_token_hash = hashlib.sha256(poll_token.encode()).hexdigest()
    device.software_version = str(data.get("software_version") or "")[:60] or None
    db.session.commit()
    return jsonify(status="pending", poll_token=poll_token, expires_at=device.pairing_expires_at.isoformat() + "Z")


@camera_api_bp.get("/registration/<device_uuid>/status")
def registration_status(device_uuid):
    device = CameraDevice.query.filter_by(device_uuid=device_uuid).first()
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    digest = hashlib.sha256(supplied.encode()).hexdigest() if supplied else ""
    if not device or not secrets.compare_digest(device.poll_token_hash or "", digest):
        return jsonify(error="invalid registration credentials"), 401
    if device.status != "active":
        return jsonify(status=device.status)
    return jsonify(status="registered", device_token=_serializer().dumps(device.device_uuid), camera={"name": device.name, "track_id": device.track_id})


@camera_api_bp.post("/heartbeat")
def heartbeat():
    device = _device()
    if not device:
        return jsonify(error="invalid camera token"), 401
    data = request.get_json(silent=True) or {}
    device.last_seen_at = datetime.utcnow()
    device.camera_connected = bool(data.get("camera_connected"))
    device.software_version = str(data.get("software_version") or device.software_version or "")[:60] or None
    device.recording_run_id = data.get("recording_run_id") or None
    active_run = TrackRun.query.filter_by(track_id=device.track_id, status="active").order_by(TrackRun.started_at.desc()).first()
    db.session.commit()
    return jsonify(ok=True, command={"action": "record", "run_id": active_run.id} if active_run else {"action": "standby"})


@camera_api_bp.post("/runs/<int:run_id>/upload-request")
def upload_request(run_id):
    device = _device()
    run = TrackRun.query.filter_by(id=run_id, track_id=device.track_id if device else None).first()
    if not device or not run:
        return jsonify(error="run not available to this camera"), 403
    data = request.get_json(silent=True) or {}
    source_key = str(data.get("source_key") or "camera-1")[:80]
    source_name = str(data.get("source_name") or "Camera 1")[:120]
    video = TrackRunVideo.query.filter_by(run_id=run.id, camera_id=device.id, source_key=source_key).first() or TrackRunVideo(run_id=run.id, camera_id=device.id, source_key=source_key)
    db.session.add(video)
    video.source_name = source_name
    video.status = "uploading"
    video.bytes = max(0, int(data.get("bytes") or 0))
    video.checksum = str(data.get("checksum") or "")[:64] or None
    video.object_key = f"track-videos/{run.track_id}/{run.event_id or 'unassigned'}/{run.id}/{device.id}-{uuid4().hex}.mp4"
    content_type = "video/mp4"
    upload_url = build_presigned_upload_url(
        video.object_key, current_app.config["S3_BUCKET"], current_app.config["S3_API_ENDPOINT_URL"],
        current_app.config["S3_ACCESS_KEY"], current_app.config["S3_SECRET_KEY"], content_type,
    )
    db.session.commit()
    return jsonify(object_key=video.object_key, upload_url=upload_url)


@camera_api_bp.post("/runs/<int:run_id>/recording-complete")
def recording_complete(run_id):
    device = _device()
    run = TrackRun.query.filter_by(id=run_id, track_id=device.track_id if device else None).first()
    if not device or not run:
        return jsonify(error="run not available to this camera"), 403
    db.session.commit()
    return jsonify(ok=True)


@camera_api_bp.post("/runs/<int:run_id>/upload-complete")
def upload_complete(run_id):
    device = _device()
    if not device:
        return jsonify(error="invalid camera token"), 401
    data = request.get_json(silent=True) or {}
    source_key = str(data.get("source_key") or "camera-1")[:80]
    video = TrackRunVideo.query.filter_by(run_id=run_id, camera_id=device.id, source_key=source_key).first()
    if not video:
        return jsonify(error="upload was not requested"), 404
    if data.get("object_key") != video.object_key:
        return jsonify(error="object key mismatch"), 409
    video.status = "ready"
    video.bytes = max(0, int(data.get("bytes") or video.bytes or 0))
    video.checksum = str(data.get("checksum") or video.checksum or "")[:64] or None
    video.uploaded_at = datetime.utcnow()
    db.session.commit()
    return jsonify(ok=True)
