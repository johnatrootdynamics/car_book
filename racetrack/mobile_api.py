"""Versioned JSON API for the Track Ops iOS and Android applications."""

import base64
import binascii
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
import hashlib
from io import BytesIO
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, current_app, g, jsonify, redirect, request, url_for
from flask_login import login_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from urllib.parse import urlencode, urlsplit
from werkzeug.datastructures import FileStorage
from werkzeug.security import check_password_hash, generate_password_hash

from .models import (
    Car,
    CameraDevice,
    DriverClassChange,
    DriverNote,
    DriverTicketOrder,
    Employee,
    EnterpriseAdmin,
    Event,
    EventClassSlot,
    EventLineupLane,
    EventRegistration,
    Inspection,
    InspectionItem,
    InspectionRule,
    MobileRefreshToken,
    PrivateRentalBooking,
    PrivateRentalSlot,
    RfidTag,
    RfidTagOrder,
    RfidTagOrderItem,
    RfidTagSettings,
    ScannerDevice,
    ScannerObservation,
    SocialPost,
    SpectatorOrder,
    SpectatorOrderItem,
    SpectatorTicketType,
    Track,
    TrackCarStatus,
    TrackDriverClass,
    TrackDriverClassOption,
    TrackEmailTemplate,
    TrackPaymentMethod,
    TrackWaiverTemplate,
    TrackLayout,
    TrackRun,
    User,
    VendorAccount,
    db,
)
from .services.capacity_service import (
    driver_already_has_ticket,
    driver_order_fits_capacity,
    spectator_order_fits_capacity,
    ticket_availability,
)
from .services.email_service import (
    send_driver_purchase_receipt,
    send_employee_login_email,
    send_private_rental_confirmation,
    send_spectator_order_receipt,
)
from .services.order_service import load_order_rows, summarize_orders
from .services.payment_service import (
    capture_paypal_order,
    create_driver_stripe_checkout_session,
    create_paypal_order,
    create_rfid_stripe_checkout_session,
    create_spectator_order_stripe_checkout_session,
    effective_payment_status,
    payment_is_confirmed,
    paypal_capture_details,
)
from .services.ticket_service import (
    ensure_order_ticket_codes,
    generate_ticket_code,
    normalize_ticket_code,
    ticket_verification_url,
)
from .services.wallet_service import wallet_links_for_ticket
from .services.run_service import expire_stale_track_states
from .services.rental_service import (
    active_bookings_by_slot,
    event_conflicts_with_rental_slot,
    rental_month_context,
    slot_conflicts_with_event,
    slot_conflicts_with_slot,
)
from .services.storage_service import build_presigned_read_url, upload_public_image
from .security import generate_random_password

try:
    import stripe
except Exception:  # pragma: no cover
    stripe = None


mobile_api_bp = Blueprint("mobile_api", __name__, url_prefix="/api/v1/mobile")
ACCESS_TOKEN_SECONDS = 60 * 60
REFRESH_TOKEN_DAYS = 30
WEB_HANDOFF_SECONDS = 90
MOBILE_CHECKOUT_SECONDS = 60 * 60
ACCOUNT_MODELS = {
    "user": User,
    "employee": Employee,
    "admin": EnterpriseAdmin,
    "vendor": VendorAccount,
}
MOBILE_PAYMENT_PROVIDERS = {
    "stripe": "Stripe",
    "paypal": "PayPal",
    "toast": "Toast",
    "quickbooks": "QuickBooks Payments",
    "other": "Other / Manual",
}
MOBILE_EMAIL_TEMPLATES = {
    "spectator_purchase_receipt": "Event ticket purchase receipt",
    "driver_purchase_receipt": "Driver purchase receipt",
}


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="trackops-mobile-v1")


def _web_serializer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="trackops-mobile-web-handoff-v1"
    )


def _checkout_serializer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="trackops-mobile-checkout-v1"
    )


WEB_TARGET_PREFIXES = {
    "user": ("/user/",),
    "employee": ("/employee/",),
    "admin": ("/admin/",),
    "vendor": ("/vendor/", "/user/events/", "/user/spectator/"),
}


def _safe_web_target(account_type, raw_target):
    target = (raw_target or "").strip()
    parsed = urlsplit(target)
    if (
        not target.startswith("/")
        or target.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
    ):
        return None
    if any(parsed.path.startswith(prefix) for prefix in WEB_TARGET_PREFIXES.get(account_type, ())):
        return target
    return None


def _account(account_type, account_id):
    model = ACCOUNT_MODELS.get(account_type)
    return db.session.get(model, account_id) if model else None


def _account_payload(account):
    account_type = account.account_type
    if account_type == "user":
        name = f"{account.first_name} {account.last_name}".strip()
    else:
        name = getattr(account, "full_name", None) or getattr(account, "business_name", "")
    payload = {
        "id": account.id,
        "type": account_type,
        "name": name,
        "email": account.email,
        "must_change_password": bool(account.must_change_password),
    }
    if account_type == "employee":
        payload.update(
            {
                "role": account.role,
                "track_id": account.track_id,
                "track_name": account.track.name,
            }
        )
    if account_type == "vendor":
        payload["business_name"] = account.business_name
    return payload


def _access_token(account):
    return _serializer().dumps({"type": account.account_type, "id": account.id})


def _new_session(account, device_name=None):
    raw_token = secrets.token_urlsafe(48)
    session = MobileRefreshToken(
        account_type=account.account_type,
        account_id=account.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        device_name=(device_name or "Mobile device")[:150],
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_DAYS),
    )
    db.session.add(session)
    db.session.commit()
    return {
        "access_token": _access_token(account),
        "access_token_expires_in": ACCESS_TOKEN_SECONDS,
        "refresh_token": raw_token,
        "account": _account_payload(account),
    }


def _json_error(message, status=400, code=None):
    return jsonify({"error": code or "request_failed", "message": message}), status


def mobile_login_required(*allowed_types, allow_password_change=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return _json_error("Sign in is required.", 401, "authentication_required")
            try:
                payload = _serializer().loads(
                    header.removeprefix("Bearer ").strip(), max_age=ACCESS_TOKEN_SECONDS
                )
            except SignatureExpired:
                return _json_error("Your session needs to be refreshed.", 401, "token_expired")
            except BadSignature:
                return _json_error("The session token is invalid.", 401, "invalid_token")
            account = _account(payload.get("type"), payload.get("id"))
            if not account:
                return _json_error("The account no longer exists.", 401, "invalid_account")
            if allowed_types and account.account_type not in allowed_types:
                return _json_error("This account cannot use that feature.", 403, "forbidden")
            if account.must_change_password and not allow_password_change:
                return _json_error(
                    "Change your temporary password before continuing.",
                    403,
                    "password_change_required",
                )
            g.mobile_user = account
            return view(*args, **kwargs)

        return wrapped

    return decorator


def _iso(value):
    return value.isoformat() if value else None


def _money(cents):
    return round(int(cents or 0) / 100, 2)


def _local_today():
    try:
        timezone = ZoneInfo(current_app.config.get("TRACK_TIMEZONE") or "America/New_York")
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone).date()


def _event_payload(event, include_availability=False):
    result = {
        "id": event.id,
        "name": event.event_name,
        "date": event.event_date.isoformat(),
        "start_time": _iso(event.event_start_time),
        "end_time": _iso(event.event_end_time),
        "type": event.event_type,
        "track": {
            "id": event.track.id,
            "name": event.track.name,
            "location": ", ".join(part for part in (event.track.city, event.track.state) if part),
        },
        "prices": {
            "driver": _money(event.driver_price_cents),
            "spectator": _money(event.spectator_price_cents),
            "vendor": _money(event.vendor_price_cents),
        },
    }
    if include_availability:
        result["availability"] = {
            category: ticket_availability(event, category)
            for category in ("driver", "spectator", "vendor")
        }
    return result


def _mobile_asset_url(stored_value):
    if not stored_value:
        return None
    if stored_value.startswith(("http://", "https://")):
        return stored_value
    if stored_value.startswith("uploads/"):
        return url_for("static", filename=stored_value, _external=True)
    read_key = current_app.config.get("S3_READ_ACCESS_KEY")
    read_secret = current_app.config.get("S3_READ_SECRET_KEY")
    if not read_key or not read_secret:
        return None
    return build_presigned_read_url(
        stored_value,
        bucket=current_app.config["S3_BUCKET"],
        endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
        access_key=read_key,
        secret_key=read_secret,
    )


def _mobile_event_registrations(event):
    query = EventRegistration.query.filter(EventRegistration.event_id == event.id)
    if event.event_type == "public":
        paid_order_exists = db.session.query(DriverTicketOrder.id).filter(
            DriverTicketOrder.event_id == EventRegistration.event_id,
            DriverTicketOrder.user_id == EventRegistration.user_id,
            DriverTicketOrder.payment_status == "paid",
        ).exists()
        query = query.filter(paid_order_exists)
    return query


def _mobile_class_names(track_id):
    options = (
        TrackDriverClassOption.query.filter_by(track_id=track_id)
        .order_by(TrackDriverClassOption.sort_order.asc(), TrackDriverClassOption.id.asc())
        .all()
    )
    return [option.name for option in options] or ["A", "B", "C"]


def _mobile_driver_classes(track_id, registrations):
    user_ids = {registration.user_id for registration in registrations}
    rows = TrackDriverClass.query.filter(
        TrackDriverClass.track_id == track_id,
        TrackDriverClass.user_id.in_(user_ids or {-1}),
    ).all()
    values = {row.user_id: row.driver_class for row in rows}
    options = _mobile_class_names(track_id)
    default_class = "C" if "C" in options else options[0]
    return {user_id: values.get(user_id, default_class) for user_id in user_ids}


def _time_value(value):
    return value.strftime("%H:%M") if value else None


def _car_payload(car):
    return {
        "id": car.id,
        "year": car.car_year,
        "make": car.make,
        "model": car.model,
        "color": car.color,
        "label": f"{car.car_year} {car.make} {car.model}",
        "image_url": car.image_url,
    }


def _car_values(body):
    make = (body.get("make") or "").strip()
    model = (body.get("model") or "").strip()
    color = (body.get("color") or "").strip() or None
    try:
        year = int(body.get("year"))
    except (TypeError, ValueError):
        return None, "Enter a valid four-digit model year."
    if not make or not model:
        return None, "Make and model are required."
    if len(make) > 100 or len(model) > 100 or (color and len(color) > 100):
        return None, "Vehicle details are too long."
    if year < 1886 or year > _local_today().year + 2:
        return None, "Enter a valid four-digit model year."
    return {"make": make, "model": model, "color": color, "year": year}, None


def _driver_order_payload(order):
    status = effective_payment_status(order)
    if status == "pending" and order.status in {"failed", "canceled"}:
        status = order.status
    return {
        "id": order.id,
        "event_id": order.event_id,
        "amount": _money(order.amount_cents),
        "payment_method": order.payment_method,
        "payment_mode": order.payment_mode,
        "payment_status": status,
        "created_at": _iso(order.created_at),
        "failure_reason": order.failure_reason,
    }


def _mobile_checkout_token(order):
    return _checkout_serializer().dumps(
        {
            "order_id": order.id,
            "user_id": order.user_id,
            "event_id": order.event_id,
        }
    )


def _mobile_checkout_order(order_id, token):
    try:
        payload = _checkout_serializer().loads(
            token or "", max_age=MOBILE_CHECKOUT_SECONDS
        )
    except (SignatureExpired, BadSignature):
        return None
    order = db.session.get(DriverTicketOrder, order_id)
    if not order:
        return None
    if (
        payload.get("order_id") != order.id
        or payload.get("user_id") != order.user_id
        or payload.get("event_id") != order.event_id
    ):
        return None
    return order


def _mobile_checkout_app_url(order, status):
    query = urlencode(
        {
            "checkout_status": status,
            "order_id": order.id,
        }
    )
    return f"trackops://event/{order.event_id}/checkout?{query}"


def _spectator_order_event_id(order):
    return order.items[0].event_id if order.items else None


def _spectator_order_payload(order):
    status = effective_payment_status(order)
    if status == "pending" and order.status in {"failed", "canceled"}:
        status = order.status
    return {
        "id": order.id,
        "number": order.order_number,
        "event_id": _spectator_order_event_id(order),
        "amount": _money(order.total_cents),
        "ticket_count": len(order.items),
        "payment_method": order.payment_method,
        "payment_mode": order.payment_mode,
        "payment_status": status,
        "created_at": _iso(order.created_at),
        "failure_reason": order.failure_reason,
    }


def _mobile_spectator_checkout_token(order):
    return _checkout_serializer().dumps(
        {
            "order_type": "spectator",
            "order_id": order.id,
            "user_id": order.user_id,
            "event_id": _spectator_order_event_id(order),
        }
    )


def _mobile_spectator_checkout_order(order_id, token):
    try:
        payload = _checkout_serializer().loads(
            token or "", max_age=MOBILE_CHECKOUT_SECONDS
        )
    except (SignatureExpired, BadSignature):
        return None
    order = db.session.get(SpectatorOrder, order_id)
    if not order or not order.user_id:
        return None
    if (
        payload.get("order_type") != "spectator"
        or payload.get("order_id") != order.id
        or payload.get("user_id") != order.user_id
        or payload.get("event_id") != _spectator_order_event_id(order)
    ):
        return None
    return order


def _mobile_spectator_app_url(order, status):
    event_id = _spectator_order_event_id(order)
    query = urlencode(
        {
            "checkout_status": status,
            "order_id": order.id,
        }
    )
    return f"trackops://event/{event_id}/spectator-checkout?{query}"


def _rfid_order_payload(order):
    return {
        "id": order.id,
        "number": order.order_number,
        "amount": _money(order.total_cents),
        "payment_method": order.payment_method,
        "payment_mode": order.payment_mode,
        "payment_status": effective_payment_status(order),
        "fulfillment_status": order.fulfillment_status,
        "created_at": _iso(order.created_at),
        "fulfilled_at": _iso(order.fulfilled_at),
        "shipping": {
            "name": order.shipping_name,
            "street": order.shipping_street,
            "city": order.shipping_city,
            "state": order.shipping_state,
            "postal_code": order.shipping_postal_code,
        },
        "items": [
            {
                "id": item.id,
                "car": _car_payload(item.car),
                "unit_price": _money(item.unit_price_cents),
                "tag": (
                    {
                        "id": item.tag.id,
                        "serial": item.tag.public_serial,
                        "status": item.tag.status,
                    }
                    if item.tag
                    else None
                ),
            }
            for item in order.items
        ],
    }


def _mobile_rfid_checkout_token(order):
    return _checkout_serializer().dumps(
        {"order_type": "rfid", "order_id": order.id, "user_id": order.user_id}
    )


def _mobile_rfid_checkout_order(order_id, token):
    try:
        payload = _checkout_serializer().loads(
            token or "", max_age=MOBILE_CHECKOUT_SECONDS
        )
    except (SignatureExpired, BadSignature):
        return None
    order = db.session.get(RfidTagOrder, order_id)
    if not order:
        return None
    if (
        payload.get("order_type") != "rfid"
        or payload.get("order_id") != order.id
        or payload.get("user_id") != order.user_id
    ):
        return None
    return order


def _mobile_rfid_app_url(order, status):
    query = urlencode({"checkout_status": status, "order_id": order.id})
    return f"trackops://rfid?{query}"


def _mark_mobile_rfid_order_paid(order, transaction_id=None):
    if (
        int(order.total_cents or 0) > 0
        and order.payment_method in {"stripe", "paypal"}
        and not transaction_id
    ):
        raise ValueError("Paid RFID orders require a provider transaction ID.")
    order.payment_status = "paid"
    if order.fulfillment_status == "cancelled":
        order.fulfillment_status = "pending"
    order.provider_transaction_id = transaction_id
    order.paid_at = order.paid_at or datetime.utcnow()


@mobile_api_bp.post("/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        return _json_error("Email and password are required.", 400, "missing_credentials")
    candidates = [
        account
        for account in (
            EnterpriseAdmin.query.filter_by(email=email).first(),
            Employee.query.filter_by(email=email).first(),
            VendorAccount.query.filter_by(email=email).first(),
            User.query.filter_by(email=email).first(),
        )
        if account and check_password_hash(account.password_hash, password)
    ]
    if len(candidates) > 1:
        return _json_error(
            "This email matches multiple accounts. Contact an administrator.",
            409,
            "ambiguous_account",
        )
    if not candidates:
        return _json_error("The email or password is incorrect.", 401, "invalid_credentials")
    return jsonify(_new_session(candidates[0], body.get("device_name")))


@mobile_api_bp.post("/auth/refresh")
def refresh():
    raw_token = ((request.get_json(silent=True) or {}).get("refresh_token") or "").strip()
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    session = MobileRefreshToken.query.filter_by(token_hash=token_hash).first()
    now = datetime.utcnow()
    if not session or session.revoked_at or session.expires_at <= now:
        return _json_error("Sign in again to continue.", 401, "invalid_refresh_token")
    account = _account(session.account_type, session.account_id)
    if not account:
        return _json_error("The account no longer exists.", 401, "invalid_account")
    session.last_used_at = now
    db.session.commit()
    return jsonify(
        {
            "access_token": _access_token(account),
            "access_token_expires_in": ACCESS_TOKEN_SECONDS,
            "account": _account_payload(account),
        }
    )


@mobile_api_bp.post("/auth/logout")
def logout():
    raw_token = ((request.get_json(silent=True) or {}).get("refresh_token") or "").strip()
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        session = MobileRefreshToken.query.filter_by(token_hash=token_hash).first()
        if session and not session.revoked_at:
            session.revoked_at = datetime.utcnow()
            db.session.commit()
    return jsonify({"ok": True})


@mobile_api_bp.get("/me")
@mobile_login_required("user", "employee", "admin", "vendor", allow_password_change=True)
def me():
    return jsonify({"account": _account_payload(g.mobile_user)})


@mobile_api_bp.post("/auth/change-password")
@mobile_login_required("user", "employee", "admin", "vendor", allow_password_change=True)
def change_password():
    body = request.get_json(silent=True) or {}
    new_password = body.get("new_password") or ""
    current_password = body.get("current_password") or ""
    account = g.mobile_user
    if len(new_password) < 10:
        return _json_error("Use at least 10 characters for your new password.", 400, "weak_password")
    if not account.must_change_password and not check_password_hash(account.password_hash, current_password):
        return _json_error("Your current password is incorrect.", 400, "invalid_current_password")
    if check_password_hash(account.password_hash, new_password):
        return _json_error("Choose a password different from the current password.", 400, "reused_password")
    account.password_hash = generate_password_hash(new_password)
    account.must_change_password = False
    MobileRefreshToken.query.filter_by(
        account_type=account.account_type, account_id=account.id, revoked_at=None
    ).update({"revoked_at": datetime.utcnow()})
    db.session.commit()
    return jsonify(_new_session(account, body.get("device_name")))


@mobile_api_bp.post("/auth/web-link")
@mobile_login_required("user", "employee", "admin", "vendor")
def web_link():
    account = g.mobile_user
    body = request.get_json(silent=True) or {}
    target = _safe_web_target(account.account_type, body.get("target"))
    if not target:
        return _json_error("That destination is not available to this account.", 403, "forbidden")
    token = _web_serializer().dumps(
        {
            "type": account.account_type,
            "id": account.id,
            "target": target,
            "nonce": secrets.token_urlsafe(12),
        }
    )
    path = url_for("mobile_api.web_session", token=token)
    configured_base = (current_app.config.get("APP_BASE_URL") or "").rstrip("/")
    base_url = configured_base or request.url_root.rstrip("/")
    return jsonify({"url": f"{base_url}{path}", "expires_in": WEB_HANDOFF_SECONDS})


@mobile_api_bp.get("/auth/web-session")
def web_session():
    try:
        payload = _web_serializer().loads(
            request.args.get("token", ""), max_age=WEB_HANDOFF_SECONDS
        )
    except (SignatureExpired, BadSignature):
        return _json_error("This secure link expired. Return to the app and try again.", 401, "expired_link")
    account = _account(payload.get("type"), payload.get("id"))
    target = _safe_web_target(payload.get("type"), payload.get("target"))
    if not account or not target or account.must_change_password:
        return _json_error("This secure link is no longer valid.", 401, "invalid_link")
    login_user(account, remember=False, fresh=True)
    return redirect(target)


@mobile_api_bp.get("/driver/dashboard")
@mobile_login_required("user")
def driver_dashboard():
    user = g.mobile_user
    cars = Car.query.filter_by(user_id=user.id).order_by(Car.created_at.desc()).all()
    paid_order_exists = db.session.query(DriverTicketOrder.id).filter(
        DriverTicketOrder.event_id == EventRegistration.event_id,
        DriverTicketOrder.user_id == user.id,
        DriverTicketOrder.payment_status == "paid",
    ).exists()
    upcoming = (
        Event.query.join(EventRegistration, EventRegistration.event_id == Event.id)
        .filter(
            EventRegistration.user_id == user.id,
            Event.event_date >= _local_today(),
            or_(Event.event_type == "private", paid_order_exists),
        )
        .order_by(Event.event_date.asc())
        .all()
    )
    attended = EventRegistration.query.filter(
        EventRegistration.user_id == user.id,
        EventRegistration.checked_in_at.isnot(None),
    ).count()
    tracks = (
        db.session.query(func.count(func.distinct(Event.track_id)))
        .join(EventRegistration, EventRegistration.event_id == Event.id)
        .filter(
            EventRegistration.user_id == user.id,
            EventRegistration.checked_in_at.isnot(None),
        )
        .scalar()
        or 0
    )
    return jsonify(
        {
            "stats": {
                "events_attended": attended,
                "upcoming_events": len(upcoming),
                "tracks_visited": int(tracks),
                "vehicles": len(cars),
            },
            "upcoming_events": [_event_payload(event) for event in upcoming],
            "garage": [_car_payload(car) for car in cars],
        }
    )


@mobile_api_bp.get("/driver/events")
@mobile_login_required("user")
def driver_events():
    user = g.mobile_user
    events = (
        Event.query.filter(
            Event.event_date >= _local_today(),
            or_(Event.event_type == "public", Event.private_owner_user_id == user.id),
        )
        .order_by(Event.event_date.asc(), Event.event_start_time.asc())
        .all()
    )
    paid_event_ids = {
        row.event_id
        for row in DriverTicketOrder.query.filter_by(user_id=user.id, payment_status="paid").all()
        if effective_payment_status(row) == "paid"
    }
    payload = []
    for event in events:
        item = _event_payload(event, include_availability=True)
        item["has_driver_ticket"] = event.id in paid_event_ids or event.event_type == "private"
        payload.append(item)
    return jsonify({"events": payload})


@mobile_api_bp.get("/driver/events/<int:event_id>")
@mobile_login_required("user")
def driver_event(event_id):
    user = g.mobile_user
    event = db.get_or_404(Event, event_id)
    if event.event_type == "private" and event.private_owner_user_id != user.id:
        return _json_error("That private event is not available to this account.", 403, "forbidden")
    result = _event_payload(event, include_availability=True)
    registration = EventRegistration.query.filter_by(event_id=event.id, user_id=user.id).first()
    result["registration"] = (
        {
            "checked_in_at": _iso(registration.checked_in_at),
            "ticket_code": registration.checkin_code,
            "car": _car_payload(registration.car),
        }
        if registration
        else None
    )
    vendor_items = (
        SpectatorOrderItem.query.join(SpectatorOrder)
        .filter(
            SpectatorOrderItem.event_id == event.id,
            SpectatorOrderItem.ticket_category == "vendor",
            SpectatorOrder.payment_status == "paid",
        )
        .all()
    )
    result["vendors"] = [
        {
            "id": item.order.vendor.id if item.order.vendor else None,
            "business_name": (
                item.order.vendor.business_name
                if item.order.vendor
                else (item.order.vendor_business_name or "Vendor")
            ),
            "website": item.order.vendor.website if item.order.vendor else None,
            "logo_url": item.order.vendor.logo_image_path if item.order.vendor else None,
        }
        for item in vendor_items
    ]
    return jsonify({"event": result})


@mobile_api_bp.get("/driver/events/<int:event_id>/checkout")
@mobile_login_required("user")
def driver_event_checkout(event_id):
    from .user_routes import _configured_payment_choices

    user = g.mobile_user
    event = db.session.get(Event, event_id)
    if not event:
        return _json_error("Event not found.", 404, "event_not_found")
    if event.event_type != "public":
        return _json_error(
            "Private rentals do not use individual driver tickets.",
            400,
            "private_event",
        )
    if event.event_date < _local_today():
        return _json_error("Tickets are no longer available for this event.", 400, "past_event")
    if driver_already_has_ticket(event.id, user.id):
        return _json_error(
            "You already have a driver ticket for this event.",
            409,
            "driver_ticket_exists",
        )
    availability = ticket_availability(event, "driver")
    if availability["sold_out"]:
        return _json_error("Driver tickets are sold out for this event.", 409, "sold_out")

    cars = Car.query.filter_by(user_id=user.id).order_by(Car.created_at.desc()).all()
    payment_choices = _configured_payment_choices(
        event.track, max(0, event.driver_price_cents or 0)
    )
    return jsonify(
        {
            "event": _event_payload(event, include_availability=True),
            "cars": [_car_payload(car) for car in cars],
            "payment_methods": [
                {"provider": provider, "label": label}
                for provider, label in payment_choices
            ],
            "buyer": {
                "name": f"{user.first_name} {user.last_name}".strip(),
                "email": user.email,
            },
        }
    )


@mobile_api_bp.post("/driver/events/<int:event_id>/checkout")
@mobile_login_required("user")
def driver_event_checkout_create(event_id):
    from .user_routes import (
        _configured_payment_choices,
        _finalize_driver_ticket_order,
        _payment_credentials,
    )

    user = g.mobile_user
    body = request.get_json(silent=True) or {}
    event = Event.query.filter_by(id=event_id).with_for_update().first()
    if not event:
        return _json_error("Event not found.", 404, "event_not_found")
    if event.event_type != "public":
        return _json_error(
            "Private rentals do not use individual driver tickets.",
            400,
            "private_event",
        )
    if event.event_date < _local_today():
        return _json_error("Tickets are no longer available for this event.", 400, "past_event")
    if driver_already_has_ticket(event.id, user.id):
        return _json_error(
            "Each driver may purchase only one ticket for this event.",
            409,
            "driver_ticket_exists",
        )
    availability = ticket_availability(event, "driver")
    if availability["sold_out"]:
        return _json_error(
            "The final driver ticket was just purchased.", 409, "sold_out"
        )

    try:
        car_id = int(body.get("car_id") or 0)
    except (TypeError, ValueError):
        car_id = 0
    car = Car.query.filter_by(id=car_id, user_id=user.id).first()
    if not car:
        return _json_error("Choose a vehicle from your garage.", 400, "invalid_vehicle")

    amount_cents = max(0, event.driver_price_cents or 0)
    payment_choices = _configured_payment_choices(event.track, amount_cents)
    available_providers = {provider for provider, _label in payment_choices}
    payment_method = (body.get("payment_method") or "").strip().lower()
    if payment_method not in available_providers:
        return _json_error(
            "Choose an available payment method.", 400, "invalid_payment_method"
        )
    credentials = _payment_credentials(event.track, payment_method)

    stale_orders = DriverTicketOrder.query.filter_by(
        event_id=event.id,
        user_id=user.id,
        payment_status="pending",
    ).all()
    for stale_order in stale_orders:
        stale_order.payment_status = "canceled"
        stale_order.status = "canceled"
        stale_order.failure_reason = "Replaced by a new mobile checkout attempt."

    order = DriverTicketOrder(
        event_id=event.id,
        user_id=user.id,
        car_id=car.id,
        amount_cents=amount_cents,
        payment_method=payment_method,
        payment_mode=credentials["mode"],
        payment_status="pending",
        status="pending",
    )
    db.session.add(order)
    db.session.flush()

    if amount_cents <= 0:
        _finalize_driver_ticket_order(order)
        return jsonify(
            {
                "order": _driver_order_payload(order),
                "completed": True,
                "return_url": _mobile_checkout_app_url(order, "paid").split("?", 1)[0],
            }
        ), 201

    checkout_token = _mobile_checkout_token(order)
    success_url = url_for(
        "mobile_api.driver_event_checkout_return",
        order_id=order.id,
        checkout_token=checkout_token,
        _external=True,
    )
    cancel_url = url_for(
        "mobile_api.driver_event_checkout_cancel",
        order_id=order.id,
        checkout_token=checkout_token,
        _external=True,
    )

    try:
        if payment_method == "stripe":
            if not stripe or not credentials["secret_key"] or not credentials["webhook_secret"]:
                db.session.rollback()
                return _json_error(
                    "Stripe is not ready for this track.",
                    503,
                    "payment_provider_unavailable",
                )
            stripe.api_key = credentials["secret_key"]
            checkout = create_driver_stripe_checkout_session(
                stripe,
                order,
                success_url=f"{success_url}&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url,
            )
            order.provider_session_id = checkout.id
            checkout_url = checkout.url
        elif payment_method == "paypal":
            if not (
                credentials["public_key"]
                and credentials["secret_key"]
                and credentials["webhook_secret"]
            ):
                db.session.rollback()
                return _json_error(
                    "PayPal is not ready for this track.",
                    503,
                    "payment_provider_unavailable",
                )
            paypal_order, checkout_url = create_paypal_order(
                credentials,
                amount_cents,
                f"Driver ticket - {event.event_name}",
                f"driver:{order.id}",
                success_url,
                cancel_url,
                f"mobile-driver-create-{order.id}",
            )
            order.provider_session_id = paypal_order["id"]
        else:
            db.session.rollback()
            return _json_error(
                "That provider cannot confirm online payments yet.",
                400,
                "payment_provider_unavailable",
            )
    except Exception:
        current_app.logger.exception(
            "Mobile driver checkout creation failed for event %s", event.id
        )
        db.session.rollback()
        return _json_error(
            "Payment checkout could not be started. Please try again.",
            502,
            "checkout_start_failed",
        )

    db.session.commit()
    return jsonify(
        {
            "order": _driver_order_payload(order),
            "completed": False,
            "checkout_url": checkout_url,
            "return_url": _mobile_checkout_app_url(order, "return").split("?", 1)[0],
        }
    ), 201


@mobile_api_bp.get("/driver/orders/<int:order_id>")
@mobile_login_required("user")
def driver_order_status(order_id):
    order = DriverTicketOrder.query.filter_by(
        id=order_id, user_id=g.mobile_user.id
    ).first()
    if not order:
        return _json_error("Order not found.", 404, "order_not_found")
    return jsonify({"order": _driver_order_payload(order)})


@mobile_api_bp.get("/driver/orders/<int:order_id>/payment-cancel")
def driver_event_checkout_cancel(order_id):
    order = _mobile_checkout_order(order_id, request.args.get("checkout_token"))
    if not order:
        return _json_error("This checkout return link is invalid or expired.", 401, "invalid_checkout")
    return redirect(_mobile_checkout_app_url(order, "canceled"))


@mobile_api_bp.get("/driver/orders/<int:order_id>/payment-return")
def driver_event_checkout_return(order_id):
    from .user_routes import (
        _finalize_driver_ticket_order,
        _payment_credentials,
        _validated_paypal_capture,
    )

    order = _mobile_checkout_order(order_id, request.args.get("checkout_token"))
    if not order:
        return _json_error("This checkout return link is invalid or expired.", 401, "invalid_checkout")
    if effective_payment_status(order) == "paid":
        return redirect(_mobile_checkout_app_url(order, "paid"))
    if order.payment_status == "canceled":
        return redirect(_mobile_checkout_app_url(order, "failed"))

    try:
        Event.query.filter_by(id=order.event_id).with_for_update().one()
        db.session.refresh(order, with_for_update=True)
        if effective_payment_status(order) == "paid":
            return redirect(_mobile_checkout_app_url(order, "paid"))
        if not driver_order_fits_capacity(order):
            order.payment_status = "failed"
            order.status = "failed"
            order.failure_reason = "Driver capacity was reached before payment confirmation."
            db.session.commit()
            return redirect(_mobile_checkout_app_url(order, "failed"))

        credentials = _payment_credentials(
            order.event.track, order.payment_method, mode=order.payment_mode
        )
        if order.payment_method == "stripe":
            session_id = (request.args.get("session_id") or "").strip()
            if not stripe or not session_id or session_id != order.provider_session_id:
                raise ValueError("Stripe checkout session did not match the order.")
            stripe.api_key = credentials["secret_key"]
            checkout = stripe.checkout.Session.retrieve(session_id)
            if (
                checkout.payment_status != "paid"
                or str(checkout.currency or "").lower() != "usd"
                or int(checkout.amount_total or -1) != int(order.amount_cents or 0)
                or not checkout.payment_intent
            ):
                raise ValueError("Stripe payment is not confirmed.")
            _finalize_driver_ticket_order(
                order, transaction_id=str(checkout.payment_intent)
            )
        elif order.payment_method == "paypal":
            paypal_order_id = (request.args.get("token") or "").strip()
            if not paypal_order_id or paypal_order_id != order.provider_session_id:
                raise ValueError("PayPal checkout session did not match the order.")
            captured = capture_paypal_order(
                credentials,
                paypal_order_id,
                f"mobile-driver-capture-{order.id}",
            )
            transaction_id = _validated_paypal_capture(
                paypal_capture_details(captured), order.amount_cents
            )
            _finalize_driver_ticket_order(order, transaction_id=transaction_id)
        else:
            raise ValueError("Unsupported mobile payment provider.")
    except Exception:
        current_app.logger.exception(
            "Mobile driver checkout return could not be confirmed for order %s", order.id
        )
        db.session.rollback()

    status = effective_payment_status(order)
    if status != "paid":
        status = "failed" if order.status == "failed" else "processing"
    return redirect(_mobile_checkout_app_url(order, status))


def _mobile_spectator_ticket_types(event):
    from .user_routes import _get_or_create_default_ticket_type, _ticket_purchase_limit

    ticket_types = (
        SpectatorTicketType.query.filter_by(
            event_id=event.id,
            ticket_category="spectator",
            is_active=True,
        )
        .order_by(SpectatorTicketType.created_at.asc(), SpectatorTicketType.id.asc())
        .all()
    )
    if not ticket_types:
        ticket_types = [_get_or_create_default_ticket_type(event, "spectator")]
    result = []
    for ticket_type in ticket_types:
        purchase_limit, availability = _ticket_purchase_limit(event, ticket_type)
        result.append(
            {
                "id": ticket_type.id,
                "name": ticket_type.name,
                "price": _money(ticket_type.price_cents),
                "max_per_order": max(0, purchase_limit),
                "availability": availability,
            }
        )
    return result


@mobile_api_bp.get("/driver/events/<int:event_id>/spectator-checkout")
@mobile_login_required("user")
def driver_spectator_checkout(event_id):
    from .user_routes import _configured_payment_choices

    user = g.mobile_user
    event = db.session.get(Event, event_id)
    if not event:
        return _json_error("Event not found.", 404, "event_not_found")
    if event.event_type != "public":
        return _json_error(
            "Private rentals do not offer spectator admission.",
            400,
            "private_event",
        )
    if event.event_date < _local_today():
        return _json_error(
            "Spectator tickets are no longer available for this event.",
            400,
            "past_event",
        )
    ticket_types = _mobile_spectator_ticket_types(event)
    purchasable = [item for item in ticket_types if item["max_per_order"] > 0]
    amount_options = [
        int(round(Decimal(str(item["price"])) * 100)) for item in purchasable
    ]
    payment_amount = max(amount_options) if amount_options else 0
    payment_choices = _configured_payment_choices(event.track, payment_amount)
    return jsonify(
        {
            "event": _event_payload(event, include_availability=True),
            "ticket_types": ticket_types,
            "payment_methods": [
                {"provider": provider, "label": label}
                for provider, label in payment_choices
            ],
            "buyer": {
                "name": f"{user.first_name} {user.last_name}".strip(),
                "email": user.email,
            },
        }
    )


@mobile_api_bp.post("/driver/events/<int:event_id>/spectator-checkout")
@mobile_login_required("user")
def driver_spectator_checkout_create(event_id):
    from .user_routes import (
        _configured_payment_choices,
        _finalize_spectator_order,
        _payment_credentials,
        _ticket_purchase_limit,
    )

    user = g.mobile_user
    body = request.get_json(silent=True) or {}
    event = Event.query.filter_by(id=event_id).with_for_update().first()
    if not event:
        return _json_error("Event not found.", 404, "event_not_found")
    if event.event_type != "public":
        return _json_error(
            "Private rentals do not offer spectator admission.",
            400,
            "private_event",
        )
    if event.event_date < _local_today():
        return _json_error(
            "Spectator tickets are no longer available for this event.",
            400,
            "past_event",
        )
    try:
        ticket_type_id = int(body.get("ticket_type_id") or 0)
        quantity = int(body.get("quantity") or 0)
    except (TypeError, ValueError):
        ticket_type_id = 0
        quantity = 0
    ticket_type = SpectatorTicketType.query.filter_by(
        id=ticket_type_id,
        event_id=event.id,
        ticket_category="spectator",
        is_active=True,
    ).first()
    if not ticket_type:
        return _json_error("Choose an available spectator ticket.", 400, "invalid_ticket_type")
    purchase_limit, availability = _ticket_purchase_limit(event, ticket_type)
    if purchase_limit <= 0:
        return _json_error("Spectator tickets are sold out.", 409, "sold_out")
    if quantity < 1 or quantity > purchase_limit:
        return _json_error(
            f"Choose between 1 and {purchase_limit} spectator tickets.",
            400,
            "invalid_quantity",
        )

    total_cents = max(0, int(ticket_type.price_cents or 0)) * quantity
    payment_choices = _configured_payment_choices(event.track, total_cents)
    available_providers = {provider for provider, _label in payment_choices}
    payment_method = (body.get("payment_method") or "").strip().lower()
    if payment_method not in available_providers:
        return _json_error(
            "Choose an available payment method.", 400, "invalid_payment_method"
        )
    credentials = _payment_credentials(event.track, payment_method)

    pending_orders = (
        SpectatorOrder.query.join(SpectatorOrderItem)
        .filter(
            SpectatorOrder.user_id == user.id,
            SpectatorOrder.payment_status == "pending",
            SpectatorOrderItem.event_id == event.id,
        )
        .all()
    )
    for pending in pending_orders:
        pending.payment_status = "canceled"
        pending.status = "canceled"
        pending.failure_reason = "Replaced by a new mobile checkout attempt."

    order = SpectatorOrder(
        order_number=f"SP-{secrets.token_hex(4).upper()}",
        user_id=user.id,
        guest_full_name=f"{user.first_name} {user.last_name}".strip(),
        guest_email=user.email,
        guest_phone=user.phone,
        payment_method=payment_method,
        payment_mode=credentials["mode"],
        payment_status="pending",
        status="pending",
        total_cents=total_cents,
    )
    db.session.add(order)
    db.session.flush()
    for _index in range(quantity):
        db.session.add(
            SpectatorOrderItem(
                order_id=order.id,
                event_id=event.id,
                ticket_type_name=ticket_type.name,
                ticket_category="spectator",
                unit_price_cents=max(0, int(ticket_type.price_cents or 0)),
                quantity=1,
                line_total_cents=max(0, int(ticket_type.price_cents or 0)),
                qr_code=generate_ticket_code(),
            )
        )
    db.session.flush()

    if total_cents <= 0:
        _finalize_spectator_order(order)
        return jsonify(
            {
                "order": _spectator_order_payload(order),
                "completed": True,
                "return_url": _mobile_spectator_app_url(order, "paid").split("?", 1)[0],
            }
        ), 201

    checkout_token = _mobile_spectator_checkout_token(order)
    success_url = url_for(
        "mobile_api.driver_spectator_checkout_return",
        order_id=order.id,
        checkout_token=checkout_token,
        _external=True,
    )
    cancel_url = url_for(
        "mobile_api.driver_spectator_checkout_cancel",
        order_id=order.id,
        checkout_token=checkout_token,
        _external=True,
    )

    try:
        if payment_method == "stripe":
            if not stripe or not credentials["secret_key"] or not credentials["webhook_secret"]:
                db.session.rollback()
                return _json_error(
                    "Stripe is not ready for this track.",
                    503,
                    "payment_provider_unavailable",
                )
            stripe.api_key = credentials["secret_key"]
            checkout = create_spectator_order_stripe_checkout_session(
                stripe,
                order,
                success_url=f"{success_url}&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url,
            )
            order.provider_session_id = checkout.id
            checkout_url = checkout.url
        elif payment_method == "paypal":
            if not (
                credentials["public_key"]
                and credentials["secret_key"]
                and credentials["webhook_secret"]
            ):
                db.session.rollback()
                return _json_error(
                    "PayPal is not ready for this track.",
                    503,
                    "payment_provider_unavailable",
                )
            paypal_order, checkout_url = create_paypal_order(
                credentials,
                total_cents,
                f"Spectator tickets - {event.event_name}",
                f"spectator:{order.id}",
                success_url,
                cancel_url,
                f"mobile-spectator-create-{order.id}",
            )
            order.provider_session_id = paypal_order["id"]
        else:
            db.session.rollback()
            return _json_error(
                "That provider cannot confirm online payments yet.",
                400,
                "payment_provider_unavailable",
            )
    except Exception:
        current_app.logger.exception(
            "Mobile spectator checkout creation failed for event %s", event.id
        )
        db.session.rollback()
        return _json_error(
            "Payment checkout could not be started. Please try again.",
            502,
            "checkout_start_failed",
        )

    db.session.commit()
    return jsonify(
        {
            "order": _spectator_order_payload(order),
            "completed": False,
            "checkout_url": checkout_url,
            "return_url": _mobile_spectator_app_url(order, "return").split("?", 1)[0],
        }
    ), 201


@mobile_api_bp.get("/driver/spectator-orders/<int:order_id>")
@mobile_login_required("user")
def driver_spectator_order_status(order_id):
    order = SpectatorOrder.query.filter_by(
        id=order_id, user_id=g.mobile_user.id
    ).first()
    if not order:
        return _json_error("Order not found.", 404, "order_not_found")
    return jsonify({"order": _spectator_order_payload(order)})


@mobile_api_bp.get("/driver/spectator-orders/<int:order_id>/payment-cancel")
def driver_spectator_checkout_cancel(order_id):
    order = _mobile_spectator_checkout_order(
        order_id, request.args.get("checkout_token")
    )
    if not order:
        return _json_error(
            "This checkout return link is invalid or expired.",
            401,
            "invalid_checkout",
        )
    return redirect(_mobile_spectator_app_url(order, "canceled"))


@mobile_api_bp.get("/driver/spectator-orders/<int:order_id>/payment-return")
def driver_spectator_checkout_return(order_id):
    from .user_routes import (
        _finalize_spectator_order,
        _payment_credentials,
        _validated_paypal_capture,
    )

    order = _mobile_spectator_checkout_order(
        order_id, request.args.get("checkout_token")
    )
    if not order:
        return _json_error(
            "This checkout return link is invalid or expired.",
            401,
            "invalid_checkout",
        )
    if effective_payment_status(order) == "paid":
        return redirect(_mobile_spectator_app_url(order, "paid"))
    if order.payment_status == "canceled":
        return redirect(_mobile_spectator_app_url(order, "failed"))

    try:
        event_ids = sorted({item.event_id for item in order.items})
        Event.query.filter(Event.id.in_(event_ids)).order_by(Event.id.asc()).with_for_update().all()
        db.session.refresh(order, with_for_update=True)
        if effective_payment_status(order) == "paid":
            return redirect(_mobile_spectator_app_url(order, "paid"))
        if not spectator_order_fits_capacity(order):
            order.payment_status = "failed"
            order.status = "failed"
            order.failure_reason = "Ticket capacity was reached before payment confirmation."
            db.session.commit()
            return redirect(_mobile_spectator_app_url(order, "failed"))

        payment_track = order.items[0].event.track
        credentials = _payment_credentials(
            payment_track, order.payment_method, mode=order.payment_mode
        )
        if order.payment_method == "stripe":
            session_id = (request.args.get("session_id") or "").strip()
            if not stripe or not session_id or session_id != order.provider_session_id:
                raise ValueError("Stripe checkout session did not match the order.")
            stripe.api_key = credentials["secret_key"]
            checkout = stripe.checkout.Session.retrieve(session_id)
            if (
                checkout.payment_status != "paid"
                or str(checkout.currency or "").lower() != "usd"
                or int(checkout.amount_total or -1) != int(order.total_cents or 0)
                or not checkout.payment_intent
            ):
                raise ValueError("Stripe payment is not confirmed.")
            _finalize_spectator_order(
                order, transaction_id=str(checkout.payment_intent)
            )
        elif order.payment_method == "paypal":
            paypal_order_id = (request.args.get("token") or "").strip()
            if not paypal_order_id or paypal_order_id != order.provider_session_id:
                raise ValueError("PayPal checkout session did not match the order.")
            captured = capture_paypal_order(
                credentials,
                paypal_order_id,
                f"mobile-spectator-capture-{order.id}",
            )
            transaction_id = _validated_paypal_capture(
                paypal_capture_details(captured), order.total_cents
            )
            _finalize_spectator_order(order, transaction_id=transaction_id)
        else:
            raise ValueError("Unsupported mobile payment provider.")
    except Exception:
        current_app.logger.exception(
            "Mobile spectator checkout return could not be confirmed for order %s",
            order.id,
        )
        db.session.rollback()

    status = effective_payment_status(order)
    if status != "paid":
        status = "failed" if order.status == "failed" else "processing"
    return redirect(_mobile_spectator_app_url(order, status))


@mobile_api_bp.get("/driver/rfid")
@mobile_login_required("user")
def driver_rfid():
    from .user_routes import _rfid_payment_choices

    user = g.mobile_user
    cars = Car.query.filter_by(user_id=user.id).order_by(Car.created_at.desc()).all()
    tags = RfidTag.query.filter_by(activated_by_user_id=user.id).order_by(
        RfidTag.activated_at.desc()
    ).all()
    orders = RfidTagOrder.query.filter_by(user_id=user.id).order_by(
        RfidTagOrder.created_at.desc()
    ).limit(25).all()
    active_by_car = {tag.car_id: tag for tag in tags if tag.car_id and tag.status == "active"}
    open_items = (
        RfidTagOrderItem.query.join(RfidTagOrder)
        .filter(
            RfidTagOrder.user_id == user.id,
            RfidTagOrder.payment_status.in_(("pending", "paid")),
            RfidTagOrder.fulfillment_status != "cancelled",
        )
        .all()
    )
    ordered_by_car = {item.car_id: item.order for item in open_items}
    settings = db.session.get(RfidTagSettings, 1)
    if not settings:
        settings = RfidTagSettings(id=1, price_cents=0)
        db.session.add(settings)
        db.session.commit()
    return jsonify(
        {
            "unit_price": _money(settings.price_cents),
            "cars": [
                {
                    **_car_payload(car),
                    "tag": (
                        {
                            "id": active_by_car[car.id].id,
                            "serial": active_by_car[car.id].public_serial,
                            "status": active_by_car[car.id].status,
                        }
                        if car.id in active_by_car
                        else None
                    ),
                    "open_order": (
                        {
                            "id": ordered_by_car[car.id].id,
                            "number": ordered_by_car[car.id].order_number,
                            "payment_status": effective_payment_status(ordered_by_car[car.id]),
                            "fulfillment_status": ordered_by_car[car.id].fulfillment_status,
                        }
                        if car.id in ordered_by_car
                        else None
                    ),
                }
                for car in cars
            ],
            "tags": [
                {
                    "id": tag.id,
                    "serial": tag.public_serial,
                    "status": tag.status,
                    "activated_at": _iso(tag.activated_at),
                    "car": _car_payload(tag.car) if tag.car else None,
                }
                for tag in tags
            ],
            "orders": [_rfid_order_payload(order) for order in orders],
            "payment_methods": [
                {"provider": provider, "label": label}
                for provider, label in _rfid_payment_choices()
            ],
            "shipping": {
                "name": f"{user.first_name} {user.last_name}".strip(),
                "street": user.street,
                "city": user.city,
                "state": user.state,
                "postal_code": user.postal_code,
            },
        }
    )


@mobile_api_bp.post("/driver/rfid/activate")
@mobile_login_required("user")
def driver_rfid_activate():
    user = g.mobile_user
    body = request.get_json(silent=True) or {}
    serial = (body.get("serial") or "").strip().upper()
    activation_code = (body.get("activation_code") or "").strip().upper()
    try:
        car_id = int(body.get("car_id") or 0)
    except (TypeError, ValueError):
        car_id = 0
    car = Car.query.filter_by(id=car_id, user_id=user.id).first()
    tag = RfidTag.query.filter_by(public_serial=serial).first()
    if not car:
        return _json_error("Choose a vehicle from your garage.", 400, "invalid_vehicle")
    if RfidTag.query.filter_by(car_id=car.id, status="active").first():
        return _json_error("That vehicle already has an active tag.", 409, "tag_exists")
    if (
        not tag
        or tag.status != "inventory"
        or not check_password_hash(tag.activation_code_hash, activation_code)
    ):
        return _json_error(
            "That tag serial or activation code is invalid.", 400, "invalid_activation"
        )
    ordered_item = RfidTagOrderItem.query.filter_by(rfid_tag_id=tag.id).first()
    if ordered_item and (
        ordered_item.order.user_id != user.id or ordered_item.car_id != car.id
    ):
        return _json_error(
            "That tag was fulfilled for a different vehicle.", 403, "wrong_vehicle"
        )
    tag.car_id = car.id
    tag.activated_by_user_id = user.id
    tag.activated_at = datetime.utcnow()
    tag.status = "active"
    db.session.commit()
    return jsonify({"message": f"{tag.public_serial} is now active on {car.car_year} {car.make} {car.model}."})


@mobile_api_bp.post("/driver/rfid/orders")
@mobile_login_required("user")
def driver_rfid_order_create():
    from .user_routes import (
        _enterprise_payment_credentials,
        _rfid_payment_choices,
    )

    user = g.mobile_user
    body = request.get_json(silent=True) or {}
    raw_car_ids = body.get("car_ids") if isinstance(body.get("car_ids"), list) else []
    try:
        car_ids = list(dict.fromkeys(int(value) for value in raw_car_ids))
    except (TypeError, ValueError):
        car_ids = []
    if not car_ids or len(car_ids) > 10:
        return _json_error("Choose between 1 and 10 vehicles.", 400, "invalid_vehicles")
    cars = Car.query.filter(Car.user_id == user.id, Car.id.in_(car_ids)).all()
    if len(cars) != len(car_ids):
        return _json_error("One of those vehicles is not in your garage.", 400, "invalid_vehicle")
    if RfidTag.query.filter(RfidTag.car_id.in_(car_ids), RfidTag.status == "active").first():
        return _json_error("One of those vehicles already has an active tag.", 409, "tag_exists")

    pending_orders = (
        RfidTagOrder.query.join(RfidTagOrderItem)
        .filter(
            RfidTagOrder.user_id == user.id,
            RfidTagOrder.payment_status == "pending",
            RfidTagOrderItem.car_id.in_(car_ids),
        )
        .all()
    )
    for pending in pending_orders:
        pending.payment_status = "canceled"
        pending.fulfillment_status = "cancelled"
    existing = (
        RfidTagOrderItem.query.join(RfidTagOrder)
        .filter(
            RfidTagOrder.user_id == user.id,
            RfidTagOrder.payment_status == "paid",
            RfidTagOrder.fulfillment_status != "cancelled",
            RfidTagOrderItem.car_id.in_(car_ids),
        )
        .first()
    )
    if existing:
        db.session.rollback()
        return _json_error("A tag has already been ordered for one of those vehicles.", 409, "tag_order_exists")

    shipping = body.get("shipping") if isinstance(body.get("shipping"), dict) else {}
    shipping_values = {
        "name": (shipping.get("name") or "").strip(),
        "street": (shipping.get("street") or "").strip(),
        "city": (shipping.get("city") or "").strip(),
        "state": (shipping.get("state") or "").strip(),
        "postal_code": (shipping.get("postal_code") or "").strip(),
    }
    if not all(shipping_values.values()):
        db.session.rollback()
        return _json_error("Enter a complete shipping address.", 400, "shipping_required")

    settings = db.session.get(RfidTagSettings, 1) or RfidTagSettings(id=1, price_cents=0)
    unit_price_cents = max(0, int(settings.price_cents or 0))
    total_cents = unit_price_cents * len(cars)
    choices = _rfid_payment_choices()
    available_providers = {provider for provider, _label in choices}
    payment_method = (body.get("payment_method") or "").strip().lower()
    if total_cents > 0 and payment_method not in available_providers:
        db.session.rollback()
        return _json_error("Choose an available payment method.", 400, "invalid_payment_method")
    if total_cents <= 0:
        payment_method = "free"
        credentials = {"mode": "live"}
    else:
        credentials = _enterprise_payment_credentials(payment_method)

    order = RfidTagOrder(
        order_number=f"RFID-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}",
        user_id=user.id,
        total_cents=total_cents,
        payment_method=payment_method,
        payment_mode=credentials["mode"],
        payment_status="pending",
        fulfillment_status="pending",
        shipping_name=shipping_values["name"][:200],
        shipping_street=shipping_values["street"][:255],
        shipping_city=shipping_values["city"][:100],
        shipping_state=shipping_values["state"][:100],
        shipping_postal_code=shipping_values["postal_code"][:20],
    )
    db.session.add(order)
    db.session.flush()
    car_by_id = {car.id: car for car in cars}
    for car_id in car_ids:
        if car_id in car_by_id:
            db.session.add(
                RfidTagOrderItem(
                    order_id=order.id,
                    car_id=car_id,
                    unit_price_cents=unit_price_cents,
                )
            )
    db.session.flush()

    if total_cents <= 0:
        _mark_mobile_rfid_order_paid(order)
        db.session.commit()
        return jsonify({"order": _rfid_order_payload(order), "completed": True}), 201

    checkout_token = _mobile_rfid_checkout_token(order)
    success_url = url_for(
        "mobile_api.driver_rfid_order_return",
        order_id=order.id,
        checkout_token=checkout_token,
        _external=True,
    )
    cancel_url = url_for(
        "mobile_api.driver_rfid_order_cancel",
        order_id=order.id,
        checkout_token=checkout_token,
        _external=True,
    )
    try:
        if payment_method == "stripe":
            if not stripe or not credentials.get("secret_key") or not credentials.get("webhook_secret"):
                raise ValueError("Stripe is not configured.")
            stripe.api_key = credentials["secret_key"]
            checkout = create_rfid_stripe_checkout_session(
                stripe,
                order,
                success_url=f"{success_url}&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url,
            )
            order.provider_session_id = checkout.id
            checkout_url = checkout.url
        elif payment_method == "paypal":
            if not all(credentials.get(key) for key in ("public_key", "secret_key", "webhook_secret")):
                raise ValueError("PayPal is not configured.")
            paypal_order, checkout_url = create_paypal_order(
                credentials,
                total_cents,
                "TrackOps UHF RFID vehicle tags",
                f"rfid:{order.id}",
                success_url,
                cancel_url,
                f"mobile-rfid-create-{order.id}",
            )
            order.provider_session_id = paypal_order["id"]
        else:
            raise ValueError("Unsupported payment provider.")
    except Exception:
        current_app.logger.exception("Mobile RFID checkout creation failed for order %s", order.id)
        db.session.rollback()
        return _json_error(
            "Payment checkout could not be started. Please try again.",
            502,
            "checkout_start_failed",
        )
    db.session.commit()
    return jsonify(
        {
            "order": _rfid_order_payload(order),
            "completed": False,
            "checkout_url": checkout_url,
            "return_url": _mobile_rfid_app_url(order, "return").split("?", 1)[0],
        }
    ), 201


@mobile_api_bp.get("/driver/rfid/orders/<int:order_id>")
@mobile_login_required("user")
def driver_rfid_order_status(order_id):
    order = RfidTagOrder.query.filter_by(id=order_id, user_id=g.mobile_user.id).first()
    if not order:
        return _json_error("RFID order not found.", 404, "order_not_found")
    return jsonify({"order": _rfid_order_payload(order)})


@mobile_api_bp.get("/driver/rfid/orders/<int:order_id>/payment-cancel")
def driver_rfid_order_cancel(order_id):
    order = _mobile_rfid_checkout_order(order_id, request.args.get("checkout_token"))
    if not order:
        return _json_error("This checkout return link is invalid or expired.", 401, "invalid_checkout")
    if effective_payment_status(order) != "paid":
        order.payment_status = "canceled"
        order.fulfillment_status = "cancelled"
        db.session.commit()
    return redirect(_mobile_rfid_app_url(order, "canceled"))


@mobile_api_bp.get("/driver/rfid/orders/<int:order_id>/payment-return")
def driver_rfid_order_return(order_id):
    from .user_routes import _enterprise_payment_credentials, _validated_paypal_capture

    order = _mobile_rfid_checkout_order(order_id, request.args.get("checkout_token"))
    if not order:
        return _json_error("This checkout return link is invalid or expired.", 401, "invalid_checkout")
    if effective_payment_status(order) == "paid":
        return redirect(_mobile_rfid_app_url(order, "paid"))
    try:
        db.session.refresh(order, with_for_update=True)
        credentials = _enterprise_payment_credentials(order.payment_method, mode=order.payment_mode)
        if order.payment_method == "stripe":
            session_id = (request.args.get("session_id") or "").strip()
            if not stripe or not session_id or session_id != order.provider_session_id:
                raise ValueError("Stripe checkout session did not match the order.")
            stripe.api_key = credentials["secret_key"]
            checkout = stripe.checkout.Session.retrieve(session_id)
            if (
                checkout.payment_status != "paid"
                or str(checkout.currency or "").lower() != "usd"
                or int(checkout.amount_total or -1) != int(order.total_cents or 0)
                or not checkout.payment_intent
            ):
                raise ValueError("Stripe payment is not confirmed.")
            _mark_mobile_rfid_order_paid(order, str(checkout.payment_intent))
        elif order.payment_method == "paypal":
            paypal_order_id = (request.args.get("token") or "").strip()
            if not paypal_order_id or paypal_order_id != order.provider_session_id:
                raise ValueError("PayPal checkout session did not match the order.")
            captured = capture_paypal_order(
                credentials, paypal_order_id, f"mobile-rfid-capture-{order.id}"
            )
            transaction_id = _validated_paypal_capture(
                paypal_capture_details(captured), order.total_cents
            )
            _mark_mobile_rfid_order_paid(order, transaction_id)
        else:
            raise ValueError("Unsupported payment provider.")
        db.session.commit()
    except Exception:
        current_app.logger.exception(
            "Mobile RFID checkout return could not be confirmed for order %s", order.id
        )
        db.session.rollback()
    status = "paid" if effective_payment_status(order) == "paid" else "processing"
    return redirect(_mobile_rfid_app_url(order, status))


@mobile_api_bp.get("/driver/tickets")
@mobile_login_required("user")
def driver_tickets():
    user = g.mobile_user
    tickets = []
    driver_orders = (
        DriverTicketOrder.query.join(Event)
        .filter(
            DriverTicketOrder.user_id == user.id,
            DriverTicketOrder.payment_status == "paid",
            Event.event_date >= _local_today(),
        )
        .order_by(DriverTicketOrder.created_at.desc())
        .all()
    )
    for order in driver_orders:
        if effective_payment_status(order) != "paid":
            continue
        registration = EventRegistration.query.filter_by(
            event_id=order.event_id, user_id=user.id
        ).first()
        if not registration:
            continue
        tickets.append(
            {
                "kind": "driver",
                "code": registration.checkin_code,
                "ticket_type": "Driver admission",
                "event": _event_payload(order.event),
                "checked_in_at": _iso(registration.checked_in_at),
                "qr_value": ticket_verification_url(registration.checkin_code),
                "wallet": wallet_links_for_ticket(registration.checkin_code),
            }
        )
    spectator_items = (
        SpectatorOrderItem.query.join(SpectatorOrder)
        .join(Event, Event.id == SpectatorOrderItem.event_id)
        .filter(
            SpectatorOrder.user_id == user.id,
            SpectatorOrder.payment_status == "paid",
            Event.event_date >= _local_today(),
        )
        .order_by(SpectatorOrder.created_at.desc(), SpectatorOrderItem.id.asc())
        .all()
    )
    for item in spectator_items:
        if not item.qr_code or effective_payment_status(item.order) != "paid":
            continue
        tickets.append(
            {
                "kind": item.ticket_category,
                "code": item.qr_code,
                "ticket_type": item.ticket_type_name,
                "event": _event_payload(item.event),
                "checked_in_at": _iso(item.checked_in_at),
                "qr_value": ticket_verification_url(item.qr_code),
                "wallet": wallet_links_for_ticket(item.qr_code),
            }
        )
    tickets.sort(key=lambda item: item["event"]["date"], reverse=True)
    return jsonify({"tickets": tickets})


@mobile_api_bp.get("/driver/garage")
@mobile_login_required("user")
def driver_garage():
    cars = Car.query.filter_by(user_id=g.mobile_user.id).order_by(Car.created_at.desc()).all()
    return jsonify({"cars": [_car_payload(car) for car in cars]})


@mobile_api_bp.post("/driver/garage")
@mobile_login_required("user")
def driver_garage_create():
    values, error = _car_values(request.get_json(silent=True) or {})
    if error:
        return _json_error(error, 400, "invalid_vehicle")
    car = Car(
        user_id=g.mobile_user.id,
        make=values["make"],
        model=values["model"],
        car_year=values["year"],
        color=values["color"],
        static_qr_code=secrets.token_hex(24),
    )
    db.session.add(car)
    db.session.flush()
    db.session.add(
        SocialPost(
            user_id=g.mobile_user.id,
            post_type="car_spotlight",
            title=f"@{g.mobile_user.username} added a car",
            body=f"{car.car_year} {car.make} {car.model}",
        )
    )
    db.session.commit()
    return jsonify({"car": _car_payload(car)}), 201


@mobile_api_bp.put("/driver/garage/<int:car_id>")
@mobile_login_required("user")
def driver_garage_update(car_id):
    car = Car.query.filter_by(id=car_id, user_id=g.mobile_user.id).first()
    if not car:
        return _json_error("Vehicle not found.", 404, "vehicle_not_found")
    values, error = _car_values(request.get_json(silent=True) or {})
    if error:
        return _json_error(error, 400, "invalid_vehicle")
    car.make = values["make"]
    car.model = values["model"]
    car.car_year = values["year"]
    car.color = values["color"]
    db.session.commit()
    return jsonify({"car": _car_payload(car)})


@mobile_api_bp.delete("/driver/garage/<int:car_id>")
@mobile_login_required("user")
def driver_garage_delete(car_id):
    car = Car.query.filter_by(id=car_id, user_id=g.mobile_user.id).first()
    if not car:
        return _json_error("Vehicle not found.", 404, "vehicle_not_found")
    in_use = EventRegistration.query.filter_by(car_id=car.id).first()
    rental_in_use = PrivateRentalBooking.query.filter(
        PrivateRentalBooking.car_id == car.id,
        PrivateRentalBooking.status.in_(("pending", "confirmed")),
    ).first()
    if in_use or rental_in_use:
        return _json_error(
            "This vehicle is attached to an event or private rental and cannot be deleted.",
            409,
            "vehicle_in_use",
        )
    db.session.delete(car)
    db.session.commit()
    return jsonify({"ok": True})


@mobile_api_bp.get("/vendor/dashboard")
@mobile_login_required("vendor")
def vendor_dashboard():
    vendor = g.mobile_user
    items = (
        SpectatorOrderItem.query.join(SpectatorOrder)
        .filter(
            SpectatorOrder.vendor_id == vendor.id,
            SpectatorOrderItem.ticket_category == "vendor",
        )
        .order_by(SpectatorOrder.created_at.desc())
        .all()
    )
    paid_items = [item for item in items if effective_payment_status(item.order) == "paid"]
    upcoming_events = []
    seen_event_ids = set()
    for item in paid_items:
        if item.event.event_date >= _local_today() and item.event_id not in seen_event_ids:
            seen_event_ids.add(item.event_id)
            upcoming_events.append(_event_payload(item.event))
    profile_fields = (
        vendor.full_name,
        vendor.business_name,
        vendor.phone,
        vendor.business_address,
        vendor.website,
        vendor.logo_image_path,
        vendor.description,
    )
    return jsonify(
        {
            "stats": {
                "tickets": len(paid_items),
                "upcoming_events": len(upcoming_events),
                "profile_percent": round(100 * sum(bool(value) for value in profile_fields) / len(profile_fields)),
            },
            "upcoming_events": upcoming_events,
        }
    )


@mobile_api_bp.get("/admin/dashboard")
@mobile_login_required("admin")
def admin_dashboard():
    return jsonify(
        {
            "stats": {
                "tracks": Track.query.count(),
                "staff": Employee.query.count(),
                "drivers": User.query.count(),
                "vendors": VendorAccount.query.count(),
            }
        }
    )


def _admin_rfid_payload():
    settings = db.session.get(RfidTagSettings, 1) or RfidTagSettings(id=1, price_cents=0)
    tags = RfidTag.query.order_by(RfidTag.created_at.desc()).limit(100).all()
    orders = RfidTagOrder.query.order_by(RfidTagOrder.created_at.desc()).limit(100).all()
    return {
        "unit_price": _money(settings.price_cents),
        "inventory": [
            {
                "id": tag.id,
                "serial": tag.public_serial,
                "epc": tag.epc,
                "tid": tag.tid,
                "status": tag.status,
                "car": _car_payload(tag.car) if tag.car else None,
                "created_at": _iso(tag.created_at),
            }
            for tag in tags
        ],
        "orders": [_rfid_order_payload(order) for order in orders],
    }


@mobile_api_bp.get("/admin/rfid")
@mobile_login_required("admin")
def admin_rfid():
    return jsonify(_admin_rfid_payload())


@mobile_api_bp.put("/admin/rfid/settings")
@mobile_login_required("admin")
def admin_rfid_settings_update():
    raw_price = (request.get_json(silent=True) or {}).get("unit_price")
    try:
        price_cents = int((Decimal(str(raw_price)) * 100).quantize(Decimal("1")))
    except (InvalidOperation, TypeError, ValueError):
        price_cents = -1
    if price_cents < 0:
        return _json_error("Enter a valid non-negative tag price.", 400, "invalid_price")
    settings = db.session.get(RfidTagSettings, 1)
    if not settings:
        settings = RfidTagSettings(id=1)
        db.session.add(settings)
    settings.price_cents = price_cents
    db.session.commit()
    return jsonify({"message": "RFID tag price saved.", **_admin_rfid_payload()})


@mobile_api_bp.post("/admin/rfid/inventory")
@mobile_login_required("admin")
def admin_rfid_inventory_create():
    body = request.get_json(silent=True) or {}
    epc = "".join(ch for ch in (body.get("epc") or "").upper() if ch.isalnum())
    tid = "".join(ch for ch in (body.get("tid") or "").upper() if ch.isalnum()) or None
    if not epc:
        return _json_error("Enter the tag EPC.", 400, "epc_required")
    if RfidTag.query.filter_by(epc=epc).first():
        return _json_error("That EPC is already provisioned.", 409, "epc_exists")
    if tid and RfidTag.query.filter_by(tid=tid).first():
        return _json_error("That TID is already provisioned.", 409, "tid_exists")
    serial = "TAG-" + secrets.token_hex(4).upper()
    activation_code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    tag = RfidTag(
        epc=epc,
        tid=tid,
        public_serial=serial,
        activation_code_hash=generate_password_hash(activation_code),
    )
    db.session.add(tag)
    db.session.commit()
    return jsonify(
        {
            "message": "Tag added to inventory. Save the one-time activation label now.",
            "issued_tag": {"id": tag.id, "serial": serial, "activation_code": activation_code},
            **_admin_rfid_payload(),
        }
    ), 201


@mobile_api_bp.get("/admin/rfid/orders/<int:order_id>")
@mobile_login_required("admin")
def admin_rfid_order(order_id):
    order = db.session.get(RfidTagOrder, order_id)
    if not order:
        return _json_error("RFID order not found.", 404, "order_not_found")
    available_tags = (
        RfidTag.query.outerjoin(RfidTagOrderItem)
        .filter(
            RfidTag.status == "inventory",
            RfidTag.car_id.is_(None),
            RfidTagOrderItem.id.is_(None),
        )
        .order_by(RfidTag.created_at.asc())
        .all()
    )
    return jsonify(
        {
            "order": _rfid_order_payload(order),
            "available_tags": [
                {"id": tag.id, "serial": tag.public_serial, "epc": tag.epc}
                for tag in available_tags
            ],
        }
    )


@mobile_api_bp.post("/admin/rfid/orders/<int:order_id>/fulfill")
@mobile_login_required("admin")
def admin_rfid_order_fulfill(order_id):
    from .services.email_service import send_email

    order = db.session.get(RfidTagOrder, order_id)
    if not order:
        return _json_error("RFID order not found.", 404, "order_not_found")
    if effective_payment_status(order) != "paid":
        return _json_error("Payment must be confirmed before fulfillment.", 409, "payment_required")
    if order.fulfillment_status == "fulfilled":
        return _json_error("That order has already been fulfilled.", 409, "already_fulfilled")
    assignments = (request.get_json(silent=True) or {}).get("assignments")
    if not isinstance(assignments, dict):
        return _json_error("Assign one inventory tag to every vehicle.", 400, "assignments_required")

    chosen = []
    chosen_tag_ids = set()
    for item in order.items:
        try:
            tag_id = int(assignments.get(str(item.id), assignments.get(item.id)) or 0)
        except (TypeError, ValueError):
            tag_id = 0
        tag = RfidTag.query.filter_by(id=tag_id, status="inventory", car_id=None).first()
        assigned_item = RfidTagOrderItem.query.filter_by(rfid_tag_id=tag_id).first() if tag_id else None
        if not tag or assigned_item or tag_id in chosen_tag_ids:
            return _json_error(
                "Choose a different available inventory tag for every vehicle.",
                400,
                "invalid_assignment",
            )
        activation_code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        chosen.append((item, tag, activation_code))
        chosen_tag_ids.add(tag_id)

    lines = [f"Your TrackOps RFID order {order.order_number} has been fulfilled.", ""]
    for item, tag, activation_code in chosen:
        lines.extend(
            [
                f"{item.car.car_year} {item.car.make} {item.car.model}",
                f"Tag serial: {tag.public_serial}",
                f"Activation code: {activation_code}",
                "",
            ]
        )
    lines.append(
        "Open RFID Tags in the TrackOps app and enter the serial and activation code for the matching car."
    )
    now = datetime.utcnow()
    for item, tag, activation_code in chosen:
        tag.activation_code_hash = generate_password_hash(activation_code)
        item.rfid_tag_id = tag.id
        item.fulfilled_at = now
    order.fulfillment_status = "fulfilled"
    order.fulfilled_at = now
    db.session.flush()
    try:
        sent = send_email(
            order.buyer.email,
            f"Your RFID tags are ready — {order.order_number}",
            "\n".join(lines),
        )
    except Exception:
        current_app.logger.exception("Mobile RFID fulfillment email failed")
        sent = False
    if not sent:
        db.session.rollback()
        return _json_error(
            "The fulfillment email could not be sent, so the order was not changed.",
            503,
            "email_failed",
        )
    db.session.commit()
    return jsonify({"message": "Order fulfilled and activation codes emailed to the driver.", **_admin_rfid_payload()})


@mobile_api_bp.get("/staff/dashboard")
@mobile_login_required("employee")
def staff_dashboard():
    employee = g.mobile_user
    events = (
        Event.query.filter(
            Event.track_id == employee.track_id,
            Event.event_date >= _local_today(),
        )
        .order_by(Event.event_date.asc(), Event.event_start_time.asc())
        .all()
    )
    event_ids = [event.id for event in events]
    registrations = (
        EventRegistration.query.filter(EventRegistration.event_id.in_(event_ids)).count()
        if event_ids
        else 0
    )
    return jsonify(
        {
            "stats": {
                "upcoming_events": len(events),
                "upcoming_drivers": registrations,
            },
            "events": [_event_payload(event) for event in events],
        }
    )


@mobile_api_bp.get("/staff/events")
@mobile_login_required("employee")
def staff_events():
    events = (
        Event.query.filter(
            Event.track_id == g.mobile_user.track_id,
            Event.event_date >= _local_today() - timedelta(days=1),
        )
        .order_by(Event.event_date.asc(), Event.event_start_time.asc())
        .all()
    )
    return jsonify({"events": [_event_payload(event) for event in events]})


MOBILE_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MOBILE_IMAGE_LIMIT_BYTES = 8 * 1024 * 1024


def _mobile_image_file(data_url, filename_prefix):
    if not data_url:
        return None, None
    if not isinstance(data_url, str) or ";base64," not in data_url:
        return None, "Choose a valid JPG, PNG, or WebP image."
    header, encoded = data_url.split(",", 1)
    mime_type = header.removeprefix("data:").removesuffix(";base64").lower()
    extension = MOBILE_IMAGE_TYPES.get(mime_type)
    if not extension:
        return None, "Choose a valid JPG, PNG, or WebP image."
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None, "The selected image could not be read."
    if not raw or len(raw) > MOBILE_IMAGE_LIMIT_BYTES:
        return None, "Images must be smaller than 8 MB."
    return FileStorage(
        stream=BytesIO(raw),
        filename=f"{filename_prefix}.{extension}",
        content_type=mime_type,
    ), None


def _mobile_upload_image(file_storage, key_prefix):
    return upload_public_image(
        file_storage,
        bucket=current_app.config["S3_BUCKET"],
        endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
        access_key=current_app.config["S3_ACCESS_KEY"],
        secret_key=current_app.config["S3_SECRET_KEY"],
        key_prefix=key_prefix,
    )


def _mobile_date(raw_value, label="Date"):
    try:
        value = date.fromisoformat((raw_value or "").strip())
    except (AttributeError, TypeError, ValueError):
        return None, f"{label} is required."
    if value < _local_today():
        return None, f"{label} cannot be in the past."
    return value, None


def _mobile_time(raw_value, required=False):
    value = str(raw_value).strip() if raw_value is not None else ""
    if not value:
        return (None, "Start and end times are required.") if required else (None, None)
    try:
        return datetime.strptime(value, "%H:%M").time(), None
    except (TypeError, ValueError):
        return None, "Choose a valid time."


def _mobile_cents(raw_value, label):
    try:
        value = Decimal(str(raw_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None, f"Enter a valid {label.lower()}."
    if not value.is_finite() or value < 0:
        return None, f"{label} cannot be negative."
    return int(value * 100), None


def _mobile_capacity(raw_value, label, minimum=0, maximum=None):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None, f"Enter a valid {label.lower()}."
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            return None, f"{label} must be at least {minimum}."
        return None, f"{label} must be between {minimum} and {maximum}."
    return value, None


def _sync_mobile_event_ticket_types(event):
    configurations = (
        ("spectator", "General Admission", event.spectator_price_cents, 10),
        ("vendor", "Vendor Admission", event.vendor_price_cents, 20),
    )
    for category, name, price_cents, max_per_order in configurations:
        db.session.add(
            SpectatorTicketType(
                event_id=event.id,
                name=name,
                ticket_category=category,
                price_cents=max(0, price_cents or 0),
                is_active=True,
                max_per_order=max_per_order,
            )
        )


def _staff_event_planning_payload():
    track_id = g.mobile_user.track_id
    waivers = (
        TrackWaiverTemplate.query.filter_by(track_id=track_id)
        .order_by(TrackWaiverTemplate.title.asc())
        .all()
    )
    default_waiver = next(
        (
            waiver
            for waiver in sorted(
                waivers, key=lambda item: (item.updated_at or item.created_at), reverse=True
            )
            if waiver.is_active and waiver.required_for_checkin
        ),
        None,
    )
    layouts = (
        TrackLayout.query.filter_by(track_id=track_id)
        .order_by(TrackLayout.name.asc())
        .all()
    )
    return {
        "defaults": {
            "event_type": "public",
            "date": _local_today().isoformat(),
            "driver_price": 0,
            "spectator_price": 25,
            "vendor_price": 100,
            "driver_capacity": 50,
            "spectator_capacity": 100,
            "vendor_capacity": 4,
            "default_waiver_id": default_waiver.id if default_waiver else None,
        },
        "waivers": [
            {
                "id": waiver.id,
                "title": waiver.title,
                "is_active": bool(waiver.is_active),
                "required_for_checkin": bool(waiver.required_for_checkin),
            }
            for waiver in waivers
        ],
        "layouts": [
            {
                "id": layout.id,
                "name": layout.name,
                "image_url": _mobile_asset_url(layout.image_path),
            }
            for layout in layouts
        ],
    }


@mobile_api_bp.get("/staff/event-planning")
@mobile_login_required("employee")
def staff_event_planning():
    guard = _mobile_office_guard()
    if guard:
        return guard
    return jsonify(_staff_event_planning_payload())


@mobile_api_bp.post("/staff/events")
@mobile_login_required("employee")
def staff_event_create():
    guard = _mobile_office_guard()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    event_type = (body.get("event_type") or "public").strip().lower()
    if event_type not in {"public", "private"}:
        return _json_error("Choose a valid event type.", 400, "invalid_event_type")
    name = (body.get("name") or "").strip()
    if not name or len(name) > 200:
        return _json_error("Event name is required and must be 200 characters or fewer.", 400, "invalid_name")
    event_date, error = _mobile_date(body.get("date"), "Event date")
    if error:
        return _json_error(error, 400, "invalid_date")
    start_time, start_error = _mobile_time(body.get("start_time"), required=event_type == "private")
    end_time, end_error = _mobile_time(body.get("end_time"), required=event_type == "private")
    if start_error or end_error:
        return _json_error(start_error or end_error, 400, "invalid_time")
    if start_time and end_time and end_time <= start_time:
        return _json_error("End time must be after the start time.", 400, "invalid_time")

    driver_price, error = _mobile_cents(body.get("driver_price"), "Driver price")
    if error:
        return _json_error(error, 400, "invalid_price")
    driver_capacity, error = _mobile_capacity(
        body.get("driver_capacity"), "Driver capacity", minimum=1 if event_type == "private" else 0,
        maximum=500 if event_type == "private" else None,
    )
    if error:
        return _json_error(error, 400, "invalid_capacity")

    track_id = g.mobile_user.track_id
    if event_type == "private":
        db.session.query(Track).filter(Track.id == track_id).with_for_update().one()
        conflicting_slot = slot_conflicts_with_slot(
            track_id, event_date, start_time, end_time
        )
        conflicting_event = slot_conflicts_with_event(
            track_id, event_date, start_time, end_time
        )
        if conflicting_slot or conflicting_event:
            conflict_name = conflicting_event.event_name if conflicting_event else "another private rental"
            return _json_error(
                f"That rental overlaps {conflict_name}.", 409, "rental_conflict"
            )
        slot = PrivateRentalSlot(
            track_id=track_id,
            name=name[:120],
            slot_date=event_date,
            start_time=start_time,
            end_time=end_time,
            price_cents=driver_price,
            driver_limit=driver_capacity,
            created_by_employee_id=g.mobile_user.id,
        )
        db.session.add(slot)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return _json_error("That exact rental slot already exists.", 409, "duplicate_slot")
        return jsonify({"created": "rental_slot", "slot": _rental_slot_payload(slot)}), 201

    spectator_price, error = _mobile_cents(body.get("spectator_price"), "Spectator price")
    if error:
        return _json_error(error, 400, "invalid_price")
    vendor_price, error = _mobile_cents(body.get("vendor_price"), "Vendor price")
    if error:
        return _json_error(error, 400, "invalid_price")
    spectator_capacity, error = _mobile_capacity(body.get("spectator_capacity"), "Spectator capacity")
    if error:
        return _json_error(error, 400, "invalid_capacity")
    vendor_capacity, error = _mobile_capacity(body.get("vendor_capacity"), "Vendor capacity")
    if error:
        return _json_error(error, 400, "invalid_capacity")
    try:
        waiver_id = int(body.get("waiver_id"))
    except (TypeError, ValueError):
        return _json_error("Select the driver waiver required for this event.", 400, "invalid_waiver")
    waiver = TrackWaiverTemplate.query.filter_by(id=waiver_id, track_id=track_id).first()
    if not waiver:
        return _json_error("Select the driver waiver required for this event.", 400, "invalid_waiver")

    db.session.query(Track).filter(Track.id == track_id).with_for_update().one()
    rental_conflict = event_conflicts_with_rental_slot(
        track_id, event_date, start_time, end_time
    )
    if rental_conflict:
        return _json_error(
            "This event overlaps private-rental availability. Remove that slot or choose another date and time.",
            409,
            "rental_conflict",
        )

    layout_mode = (body.get("layout_mode") or "default").strip().lower()
    layout_id = None
    layout_file = None
    if layout_mode == "existing":
        try:
            selected_layout_id = int(body.get("layout_id"))
        except (TypeError, ValueError):
            return _json_error("Choose a valid track layout.", 400, "invalid_layout")
        selected_layout = TrackLayout.query.filter_by(
            id=selected_layout_id, track_id=track_id
        ).first()
        if not selected_layout:
            return _json_error("Choose a valid track layout.", 400, "invalid_layout")
        layout_id = selected_layout.id
    elif layout_mode in {"upload", "draw"}:
        layout_file, error = _mobile_image_file(
            body.get("layout_image"), "drawn_layout" if layout_mode == "draw" else "uploaded_layout"
        )
        if error:
            return _json_error(error, 400, "invalid_layout_image")
        layout_name = (body.get("layout_name") or name).strip()
        if not layout_name or len(layout_name) > 120:
            return _json_error("Layout name is required and must be 120 characters or fewer.", 400, "invalid_layout_name")
        if TrackLayout.query.filter_by(track_id=track_id, name=layout_name).first():
            return _json_error("A track layout with that name already exists.", 409, "duplicate_layout")
    elif layout_mode != "default":
        return _json_error("Choose a valid layout source.", 400, "invalid_layout")

    thumbnail_file, error = _mobile_image_file(body.get("thumbnail_image"), "event_thumbnail")
    if error:
        return _json_error(error, 400, "invalid_thumbnail")
    event = Event(
        track_id=track_id,
        event_type="public",
        event_name=name,
        event_date=event_date,
        driver_price_cents=driver_price,
        spectator_price_cents=spectator_price,
        vendor_price_cents=vendor_price,
        driver_capacity=driver_capacity,
        spectator_capacity=spectator_capacity,
        vendor_capacity=vendor_capacity,
        event_start_time=start_time,
        event_end_time=end_time,
        waiver_template_id=waiver.id,
        track_layout_id=layout_id,
    )
    try:
        if layout_file:
            layout = TrackLayout(track_id=track_id, name=(body.get("layout_name") or name).strip())
            layout.image_path = _mobile_upload_image(layout_file, f"track_layouts/{track_id}")
            db.session.add(layout)
            db.session.flush()
            event.track_layout_id = layout.id
        if thumbnail_file:
            event.thumbnail_image_path = _mobile_upload_image(
                thumbnail_file, f"events/{track_id}"
            )
        db.session.add(event)
        db.session.flush()
        _sync_mobile_event_ticket_types(event)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not create event from mobile app")
        return _json_error("The event could not be created. Try again.", 500, "event_create_failed")
    return jsonify({"created": "event", "event": _event_payload(event, include_availability=True)}), 201


def _rental_slot_payload(slot, booking=None):
    status = "booked" if booking and booking.status == "confirmed" else "held" if booking else "open"
    return {
        "id": slot.id,
        "name": slot.name,
        "date": slot.slot_date.isoformat(),
        "start_time": _time_value(slot.start_time),
        "end_time": _time_value(slot.end_time),
        "price": _money(slot.price_cents),
        "driver_limit": slot.driver_limit,
        "status": status,
        "booking": (
            {
                "id": booking.id,
                "name": f"{booking.buyer.first_name} {booking.buyer.last_name}".strip(),
                "event_id": booking.event_id,
            }
            if booking
            else None
        ),
    }


def _staff_rental_payload(raw_month=None):
    track_id = g.mobile_user.track_id
    calendar = rental_month_context(raw_month, today=_local_today())
    next_month = (calendar["first"] + timedelta(days=32)).replace(day=1)
    month_slots = (
        PrivateRentalSlot.query.filter(
            PrivateRentalSlot.track_id == track_id,
            PrivateRentalSlot.slot_date >= calendar["first"],
            PrivateRentalSlot.slot_date < next_month,
            PrivateRentalSlot.is_active.is_(True),
        )
        .order_by(PrivateRentalSlot.slot_date.asc(), PrivateRentalSlot.start_time.asc())
        .all()
    )
    upcoming_slots = (
        PrivateRentalSlot.query.filter(
            PrivateRentalSlot.track_id == track_id,
            PrivateRentalSlot.slot_date >= _local_today(),
            PrivateRentalSlot.is_active.is_(True),
        )
        .order_by(PrivateRentalSlot.slot_date.asc(), PrivateRentalSlot.start_time.asc())
        .limit(80)
        .all()
    )
    all_slots = {slot.id: slot for slot in [*month_slots, *upcoming_slots]}
    bookings = active_bookings_by_slot(list(all_slots))
    events = (
        Event.query.filter(
            Event.track_id == track_id,
            Event.event_date >= calendar["first"],
            Event.event_date < next_month,
        )
        .order_by(Event.event_date.asc(), Event.event_start_time.asc())
        .all()
    )
    return {
        "month": {
            "value": calendar["month_value"],
            "label": calendar["label"],
            "previous": calendar["previous_value"],
            "next": calendar["next_value"],
        },
        "today": _local_today().isoformat(),
        "slots": [
            _rental_slot_payload(slot, bookings.get(slot.id)) for slot in month_slots
        ],
        "upcoming": [
            _rental_slot_payload(slot, bookings.get(slot.id)) for slot in upcoming_slots
        ],
        "events": [
            {
                "id": event.id,
                "name": event.event_name,
                "date": event.event_date.isoformat(),
                "start_time": _time_value(event.event_start_time),
                "end_time": _time_value(event.event_end_time),
            }
            for event in events
        ],
    }


@mobile_api_bp.get("/staff/private-rentals")
@mobile_login_required("employee")
def staff_private_rentals():
    guard = _mobile_office_guard()
    if guard:
        return guard
    return jsonify(_staff_rental_payload(request.args.get("month")))


@mobile_api_bp.post("/staff/private-rentals")
@mobile_login_required("employee")
def staff_private_rental_create():
    guard = _mobile_office_guard()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name or len(name) > 120:
        return _json_error("Slot name is required and must be 120 characters or fewer.", 400, "invalid_name")
    slot_date, error = _mobile_date(body.get("date"), "Available date")
    if error:
        return _json_error(error, 400, "invalid_date")
    start_time, start_error = _mobile_time(body.get("start_time"), required=True)
    end_time, end_error = _mobile_time(body.get("end_time"), required=True)
    if start_error or end_error:
        return _json_error(start_error or end_error, 400, "invalid_time")
    if end_time <= start_time:
        return _json_error("Rental end time must be after the start time.", 400, "invalid_time")
    price_cents, error = _mobile_cents(body.get("price"), "Rental price")
    if error:
        return _json_error(error, 400, "invalid_price")
    driver_limit, error = _mobile_capacity(body.get("driver_limit"), "Driver limit", 1, 500)
    if error:
        return _json_error(error, 400, "invalid_capacity")
    track_id = g.mobile_user.track_id
    db.session.query(Track).filter(Track.id == track_id).with_for_update().one()
    if slot_conflicts_with_slot(track_id, slot_date, start_time, end_time):
        return _json_error("That time overlaps another private rental slot.", 409, "rental_conflict")
    conflicting_event = slot_conflicts_with_event(track_id, slot_date, start_time, end_time)
    if conflicting_event:
        return _json_error(
            f"That time overlaps {conflicting_event.event_name}. Choose another window.",
            409,
            "event_conflict",
        )
    slot = PrivateRentalSlot(
        track_id=track_id,
        name=name,
        slot_date=slot_date,
        start_time=start_time,
        end_time=end_time,
        price_cents=price_cents,
        driver_limit=driver_limit,
        created_by_employee_id=g.mobile_user.id,
    )
    db.session.add(slot)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _json_error("That exact rental slot already exists.", 409, "duplicate_slot")
    return jsonify(_staff_rental_payload(slot.slot_date.strftime("%Y-%m"))), 201


@mobile_api_bp.delete("/staff/private-rentals/<int:slot_id>")
@mobile_login_required("employee")
def staff_private_rental_remove(slot_id):
    guard = _mobile_office_guard()
    if guard:
        return guard
    slot = PrivateRentalSlot.query.filter_by(
        id=slot_id, track_id=g.mobile_user.track_id, is_active=True
    ).first()
    if not slot:
        return _json_error("Rental slot not found.", 404, "slot_not_found")
    if active_bookings_by_slot([slot.id]).get(slot.id):
        return _json_error(
            "Booked or held rental slots cannot be removed.", 409, "slot_booked"
        )
    month = slot.slot_date.strftime("%Y-%m")
    slot.is_active = False
    db.session.commit()
    return jsonify(_staff_rental_payload(month))


@mobile_api_bp.get("/staff/events/<int:event_id>")
@mobile_login_required("employee")
def staff_event(event_id):
    event = Event.query.filter_by(id=event_id, track_id=g.mobile_user.track_id).first()
    if not event:
        return _json_error("That event is not part of your track.", 404, "event_not_found")
    result = _event_payload(event, include_availability=True)
    result["registration_count"] = EventRegistration.query.filter_by(event_id=event.id).count()
    result["checked_in_count"] = EventRegistration.query.filter(
        EventRegistration.event_id == event.id,
        EventRegistration.checked_in_at.isnot(None),
    ).count()
    return jsonify({"event": result})


def _mobile_office_guard():
    if g.mobile_user.role != "office_staff":
        return _json_error(
            "Office staff access is required for this setting.",
            403,
            "office_staff_required",
        )
    return None


def _staff_event_for_mobile(event_id):
    return Event.query.filter_by(id=event_id, track_id=g.mobile_user.track_id).first()


def _staff_general_payload(event):
    layouts = (
        TrackLayout.query.filter_by(track_id=event.track_id)
        .order_by(TrackLayout.name.asc())
        .all()
    )
    selected_layout = event.track_layout
    return {
        "event": _event_payload(event, include_availability=True),
        "general": {
            "name": event.event_name,
            "date": event.event_date.isoformat(),
            "start_time": _time_value(event.event_start_time),
            "end_time": _time_value(event.event_end_time),
            "driver_price": _money(event.driver_price_cents),
            "spectator_price": _money(event.spectator_price_cents),
            "vendor_price": _money(event.vendor_price_cents),
            "driver_capacity": event.driver_capacity,
            "spectator_capacity": event.spectator_capacity,
            "vendor_capacity": event.vendor_capacity,
            "run_voting_enabled": bool(event.run_voting_enabled),
            "thumbnail_url": _mobile_asset_url(event.thumbnail_image_path),
            "layout": (
                {
                    "id": selected_layout.id,
                    "name": selected_layout.name,
                    "image_url": _mobile_asset_url(selected_layout.image_path),
                }
                if selected_layout
                else {
                    "id": None,
                    "name": "Default Track Layout",
                    "image_url": _mobile_asset_url(event.track.layout_image_path),
                }
            ),
            "layouts": [
                {
                    "id": layout.id,
                    "name": layout.name,
                    "image_url": _mobile_asset_url(layout.image_path),
                }
                for layout in layouts
            ],
        },
    }


def _staff_participants_payload(event):
    registrations = _mobile_event_registrations(event).order_by(
        EventRegistration.created_at.asc()
    ).all()
    registration_ids = [registration.id for registration in registrations]
    inspections = {
        inspection.event_registration_id: inspection
        for inspection in Inspection.query.filter(
            Inspection.event_registration_id.in_(registration_ids or [-1])
        ).all()
    }
    classes = _mobile_driver_classes(event.track_id, registrations)
    from .waiver_routes import get_required_waiver_status

    items = []
    for registration in registrations:
        waiver_status, _ = get_required_waiver_status(
            event.track_id, registration.user_id, event.id
        )
        inspection = inspections.get(registration.id)
        items.append(
            {
                "registration_id": registration.id,
                "user_id": registration.user_id,
                "name": f"{registration.user.first_name} {registration.user.last_name}".strip(),
                "email": registration.user.email,
                "car": _car_payload(registration.car),
                "driver_class": classes[registration.user_id],
                "checked_in_at": _iso(registration.checked_in_at),
                "waiver_status": waiver_status,
                "inspection_status": (
                    "passed"
                    if inspection and inspection.passed
                    else "needs_attention"
                    if inspection
                    else "not_started"
                ),
            }
        )
    return {"event": _event_payload(event), "participants": items}


def _staff_schedule_payload(event):
    slots = (
        EventClassSlot.query.filter_by(event_id=event.id)
        .order_by(EventClassSlot.start_time.asc(), EventClassSlot.id.asc())
        .all()
    )
    return {
        "event": _event_payload(event),
        "schedule": {
            "start_time": _time_value(event.event_start_time),
            "end_time": _time_value(event.event_end_time),
            "classes": _mobile_class_names(event.track_id),
            "can_edit": g.mobile_user.role == "office_staff",
            "slots": [
                {
                    "id": slot.id,
                    "class_code": slot.class_code,
                    "start_time": _time_value(slot.start_time),
                    "end_time": _time_value(slot.end_time),
                }
                for slot in slots
            ],
        },
    }


def _staff_lanes_payload(event):
    lanes = (
        EventLineupLane.query.filter_by(event_id=event.id)
        .order_by(EventLineupLane.sort_order.asc(), EventLineupLane.id.asc())
        .all()
    )
    return {
        "event": _event_payload(event),
        "lanes": [
            {"id": lane.id, "name": lane.name, "description": lane.description or ""}
            for lane in lanes
        ],
    }


def _staff_analytics_payload(event):
    registrations = _mobile_event_registrations(event).order_by(
        EventRegistration.created_at.asc()
    ).all()
    classes = _mobile_driver_classes(event.track_id, registrations)
    class_names = _mobile_class_names(event.track_id)
    class_counts = {name: 0 for name in class_names}
    signup_counts = {}
    for registration in registrations:
        class_code = classes[registration.user_id]
        class_counts[class_code] = class_counts.get(class_code, 0) + 1
        signup_day = registration.created_at.date().isoformat()
        signup_counts[signup_day] = signup_counts.get(signup_day, 0) + 1
    return {
        "event": _event_payload(event),
        "analytics": {
            "total_signups": len(registrations),
            "checked_in": sum(1 for registration in registrations if registration.checked_in_at),
            "signup_trend": [
                {"day": day, "count": signup_counts[day]}
                for day in sorted(signup_counts)
            ],
            "class_counts": [
                {"class_code": name, "count": class_counts.get(name, 0)}
                for name in class_names
            ],
        },
    }


def _run_participant_payload(participant):
    return {
        "car_id": participant.car_id,
        "car": _car_payload(participant.car),
        "driver_id": participant.driver_id,
        "driver": f"{participant.driver.first_name} {participant.driver.last_name}".strip(),
        "driver_initials": f"{participant.driver.first_name[:1]}{participant.driver.last_name[:1]}",
        "driver_image_url": _mobile_asset_url(participant.driver.profile_image_url),
        "car_image_url": _mobile_asset_url(participant.car.image_url),
        "entered_at": _iso(participant.entered_at),
        "exited_at": _iso(participant.exited_at),
    }


def _staff_live_payload(event):
    expire_stale_track_states(event.track_id)
    states = (
        TrackCarStatus.query.filter_by(
            track_id=event.track_id, event_id=event.id, is_on_track=True
        )
        .order_by(TrackCarStatus.changed_at.asc())
        .all()
    )
    completed_runs = (
        TrackRun.query.filter_by(track_id=event.track_id, event_id=event.id, status="completed")
        .order_by(TrackRun.ended_at.desc())
        .limit(12)
        .all()
    )
    return {
        "event": _event_payload(event),
        "live": {
            "count": len(states),
            "cars": [
                {
                    "car_id": state.car_id,
                    "car": _car_payload(state.car),
                    "driver_id": state.car.owner.id,
                    "driver": f"{state.car.owner.first_name} {state.car.owner.last_name}".strip(),
                    "driver_initials": f"{state.car.owner.first_name[:1]}{state.car.owner.last_name[:1]}",
                    "driver_image_url": _mobile_asset_url(state.car.owner.profile_image_url),
                    "car_image_url": _mobile_asset_url(state.car.image_url),
                    "entered_at": _iso(state.changed_at),
                    "scanner": state.last_scanner.name if state.last_scanner else None,
                    "eligible": bool(state.is_eligible),
                    "eligibility_reason": state.eligibility_reason,
                }
                for state in states
            ],
            "runs": [
                {
                    "id": run.id,
                    "started_at": _iso(run.started_at),
                    "ended_at": _iso(run.ended_at),
                    "participants": [
                        _run_participant_payload(participant)
                        for participant in run.participants
                    ],
                }
                for run in completed_runs
            ],
        },
    }


def _staff_history_payload(event):
    runs = (
        TrackRun.query.filter_by(track_id=event.track_id, event_id=event.id)
        .order_by(TrackRun.started_at.desc())
        .all()
    )
    return {
        "event": _event_payload(event),
        "history": {
            "runs": [
                {
                    "id": run.id,
                    "status": run.status,
                    "started_at": _iso(run.started_at),
                    "ended_at": _iso(run.ended_at),
                    "participants": [
                        _run_participant_payload(participant)
                        for participant in run.participants
                    ],
                    "votes": {
                        "up": sum(1 for vote in run.votes if vote.vote == 1),
                        "down": sum(1 for vote in run.votes if vote.vote == -1),
                    },
                    "videos": [
                        {
                            "id": video.id,
                            "name": video.source_name,
                            "source_key": video.source_key,
                            "status": video.status,
                            "url": _mobile_asset_url(video.object_key)
                            if video.status == "ready"
                            else None,
                        }
                        for video in run.videos
                    ],
                }
                for run in runs
            ]
        },
    }


@mobile_api_bp.get("/staff/events/<int:event_id>/operations/<action>")
@mobile_login_required("employee")
def staff_event_operation(event_id, action):
    event = _staff_event_for_mobile(event_id)
    if not event:
        return _json_error("That event is not part of your track.", 404, "event_not_found")
    if action in {"general", "analytics"} and g.mobile_user.role != "office_staff":
        return _json_error("Office staff access is required for this event tool.", 403, "office_staff_required")
    payloads = {
        "general": _staff_general_payload,
        "participants": _staff_participants_payload,
        "schedule": _staff_schedule_payload,
        "lanes": _staff_lanes_payload,
        "live": _staff_live_payload,
        "history": _staff_history_payload,
        "analytics": _staff_analytics_payload,
    }
    payload = payloads.get(action)
    if not payload:
        return _json_error("Unknown event tool.", 404, "event_tool_not_found")
    return jsonify(payload(event))


@mobile_api_bp.patch("/staff/events/<int:event_id>/operations/general")
@mobile_login_required("employee")
def staff_event_general_update(event_id):
    guard = _mobile_office_guard()
    if guard:
        return guard
    event = _staff_event_for_mobile(event_id)
    if not event:
        return _json_error("That event is not part of your track.", 404, "event_not_found")
    if event.event_type == "private":
        return _json_error("Private rental details are managed from rental availability.", 400, "private_event")
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    try:
        event_date = date.fromisoformat((body.get("date") or "").strip())
        start_time = datetime.strptime(body.get("start_time") or "", "%H:%M").time()
        end_time = datetime.strptime(body.get("end_time") or "", "%H:%M").time()
        prices = {
            category: int(round(float(body.get(f"{category}_price")) * 100))
            for category in ("driver", "spectator", "vendor")
        }
        capacities = {
            category: int(body.get(f"{category}_capacity"))
            for category in ("driver", "spectator", "vendor")
        }
    except (TypeError, ValueError):
        return _json_error("Enter valid dates, times, prices, and capacities.", 400, "invalid_event")
    if not name or len(name) > 200:
        return _json_error("Event name is required and must be 200 characters or fewer.", 400, "invalid_name")
    if end_time <= start_time:
        return _json_error("Event end time must be after the start time.", 400, "invalid_time")
    if any(value < 0 for value in (*prices.values(), *capacities.values())):
        return _json_error("Prices and capacities cannot be negative.", 400, "invalid_amount")
    layout_id = body.get("layout_id")
    layout = None
    if layout_id not in (None, "", 0, "0"):
        try:
            layout_id = int(layout_id)
        except (TypeError, ValueError):
            return _json_error("Choose a valid track layout.", 400, "invalid_layout")
        layout = TrackLayout.query.filter_by(id=layout_id, track_id=event.track_id).first()
        if not layout:
            return _json_error("Choose a valid track layout.", 400, "invalid_layout")
    event.event_name = name
    event.event_date = event_date
    event.event_start_time = start_time
    event.event_end_time = end_time
    event.driver_price_cents = prices["driver"]
    event.spectator_price_cents = prices["spectator"]
    event.vendor_price_cents = prices["vendor"]
    event.driver_capacity = capacities["driver"]
    event.spectator_capacity = capacities["spectator"]
    event.vendor_capacity = capacities["vendor"]
    event.track_layout_id = layout.id if layout else None
    event.run_voting_enabled = bool(body.get("run_voting_enabled"))
    db.session.commit()
    return jsonify(_staff_general_payload(event))


@mobile_api_bp.post("/staff/events/<int:event_id>/participants/<int:registration_id>/check-in")
@mobile_login_required("employee")
def staff_event_participant_check_in(event_id, registration_id):
    event = _staff_event_for_mobile(event_id)
    if not event:
        return _json_error("That event is not part of your track.", 404, "event_not_found")
    registration = _mobile_event_registrations(event).filter(
        EventRegistration.id == registration_id
    ).first()
    if not registration:
        return _json_error("Driver registration not found.", 404, "registration_not_found")
    if registration.checked_in_at:
        return _json_error("This driver is already checked in.", 409, "already_checked_in")
    from .waiver_routes import get_required_waiver_status

    waiver_status, _ = get_required_waiver_status(
        event.track_id, registration.user_id, event.id
    )
    if waiver_status not in {"signed", "not_required"}:
        return _json_error("The driver must complete the required waiver before check-in.", 409, "waiver_required")
    registration.checked_in_at = datetime.utcnow()
    registration.checked_in_by_employee_id = g.mobile_user.id
    db.session.commit()
    return jsonify(_staff_participants_payload(event))


def _event_slot_values(event, body, slot_id=None):
    class_code = (body.get("class_code") or "").strip()
    if class_code not in _mobile_class_names(event.track_id):
        return None, "Choose a valid driver class."
    try:
        start_time = datetime.strptime(body.get("start_time") or "", "%H:%M").time()
        end_time = datetime.strptime(body.get("end_time") or "", "%H:%M").time()
    except ValueError:
        return None, "Enter start and end times as HH:MM."
    if end_time <= start_time:
        return None, "End time must be after start time."
    if not event.event_start_time or not event.event_end_time:
        return None, "Set the event start and end time in General first."
    if start_time < event.event_start_time or end_time > event.event_end_time:
        return None, "Class slots must stay within the event time window."
    overlap = EventClassSlot.query.filter(
        EventClassSlot.event_id == event.id,
        EventClassSlot.start_time < end_time,
        EventClassSlot.end_time > start_time,
    )
    if slot_id:
        overlap = overlap.filter(EventClassSlot.id != slot_id)
    if overlap.first():
        return None, "Class slots cannot overlap."
    return {"class_code": class_code, "start_time": start_time, "end_time": end_time}, None


@mobile_api_bp.post("/staff/events/<int:event_id>/operations/schedule")
@mobile_login_required("employee")
def staff_event_slot_save(event_id):
    guard = _mobile_office_guard()
    if guard:
        return guard
    event = _staff_event_for_mobile(event_id)
    if not event:
        return _json_error("That event is not part of your track.", 404, "event_not_found")
    body = request.get_json(silent=True) or {}
    try:
        slot_id = int(body.get("slot_id")) if body.get("slot_id") else None
    except (TypeError, ValueError):
        return _json_error("Choose a valid schedule slot.", 400, "invalid_slot")
    values, error = _event_slot_values(event, body, slot_id)
    if error:
        return _json_error(error, 400, "invalid_slot")
    slot = EventClassSlot.query.filter_by(id=slot_id, event_id=event.id).first() if slot_id else None
    if slot_id and not slot:
        return _json_error("Schedule slot not found.", 404, "slot_not_found")
    if not slot:
        slot = EventClassSlot(event_id=event.id)
        db.session.add(slot)
    slot.class_code = values["class_code"]
    slot.start_time = values["start_time"]
    slot.end_time = values["end_time"]
    db.session.commit()
    return jsonify(_staff_schedule_payload(event))


@mobile_api_bp.delete("/staff/events/<int:event_id>/operations/schedule/<int:slot_id>")
@mobile_login_required("employee")
def staff_event_slot_remove(event_id, slot_id):
    guard = _mobile_office_guard()
    if guard:
        return guard
    event = _staff_event_for_mobile(event_id)
    if not event:
        return _json_error("That event is not part of your track.", 404, "event_not_found")
    slot = EventClassSlot.query.filter_by(id=slot_id, event_id=event.id).first()
    if not slot:
        return _json_error("Schedule slot not found.", 404, "slot_not_found")
    db.session.delete(slot)
    db.session.commit()
    return jsonify(_staff_schedule_payload(event))


@mobile_api_bp.put("/staff/events/<int:event_id>/operations/lanes")
@mobile_login_required("employee")
def staff_event_lanes_update(event_id):
    event = _staff_event_for_mobile(event_id)
    if not event:
        return _json_error("That event is not part of your track.", 404, "event_not_found")
    raw_lanes = (request.get_json(silent=True) or {}).get("lanes")
    if not isinstance(raw_lanes, list):
        return _json_error("Send a valid lineup lane list.", 400, "invalid_lanes")
    lanes = []
    for raw_lane in raw_lanes:
        if not isinstance(raw_lane, dict):
            return _json_error("Send a valid lineup lane list.", 400, "invalid_lanes")
        name = (raw_lane.get("name") or "").strip()
        description = (raw_lane.get("description") or "").strip()
        if not name:
            continue
        if len(name) > 80 or len(description) > 240:
            return _json_error("Lane names are limited to 80 characters and instructions to 240.", 400, "invalid_lanes")
        lanes.append((name, description))
    if len(lanes) > 20:
        return _json_error("An event can have up to 20 lineup lanes.", 400, "too_many_lanes")
    EventLineupLane.query.filter_by(event_id=event.id).delete(synchronize_session=False)
    for index, (name, description) in enumerate(lanes):
        db.session.add(
            EventLineupLane(
                event_id=event.id,
                name=name,
                description=description or None,
                sort_order=index,
                updated_by_employee_id=g.mobile_user.id,
            )
        )
    db.session.commit()
    return jsonify(_staff_lanes_payload(event))


def _staff_driver_query(track_id):
    return (
        User.query.join(EventRegistration, EventRegistration.user_id == User.id)
        .join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == track_id)
        .distinct()
    )


def _staff_driver_or_none(track_id, user_id):
    return _staff_driver_query(track_id).filter(User.id == user_id).first()


def _driver_directory_payload(driver, track_id):
    registrations = (
        EventRegistration.query.join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == track_id, EventRegistration.user_id == driver.id)
        .all()
    )
    registration_ids = [registration.id for registration in registrations]
    inspected_ids = {
        row[0]
        for row in db.session.query(Inspection.event_registration_id)
        .filter(Inspection.event_registration_id.in_(registration_ids or [-1]))
        .all()
    }
    class_record = TrackDriverClass.query.filter_by(
        track_id=track_id, user_id=driver.id
    ).first()
    attended = sum(
        1
        for registration in registrations
        if registration.checked_in_at or registration.id in inspected_ids
    )
    last_date = max((registration.event.event_date for registration in registrations), default=None)
    return {
        "id": driver.id,
        "name": f"{driver.first_name} {driver.last_name}".strip(),
        "username": driver.username,
        "email": driver.email,
        "phone": driver.phone,
        "profile_image_url": driver.profile_image_url,
        "driver_class": class_record.driver_class if class_record else "C",
        "registered_count": len(registrations),
        "attended_count": attended,
        "note_count": DriverNote.query.filter_by(track_id=track_id, user_id=driver.id).count(),
        "last_event_date": last_date.isoformat() if last_date else None,
    }


@mobile_api_bp.get("/staff/people")
@mobile_login_required("employee")
def staff_people():
    employee = g.mobile_user
    directory_view = (request.args.get("view") or "drivers").strip().lower()
    query_text = (request.args.get("q") or "").strip()
    if directory_view == "vendors":
        query = VendorAccount.query
        if query_text:
            like = f"%{query_text}%"
            filters = [
                VendorAccount.business_name.ilike(like),
                VendorAccount.website.ilike(like),
                VendorAccount.description.ilike(like),
            ]
            if employee.role == "office_staff":
                filters.extend(
                    [
                        VendorAccount.full_name.ilike(like),
                        VendorAccount.email.ilike(like),
                        VendorAccount.phone.ilike(like),
                    ]
                )
            query = query.filter(or_(*filters))
        vendors = query.order_by(VendorAccount.business_name.asc()).limit(200).all()
        return jsonify(
            {
                "view": "vendors",
                "vendors": [
                    {
                        "id": vendor.id,
                        "business_name": vendor.business_name,
                        "website": vendor.website,
                        "description": vendor.description,
                        "logo_url": vendor.logo_image_path,
                        **(
                            {
                                "contact_name": vendor.full_name,
                                "email": vendor.email,
                                "phone": vendor.phone,
                                "business_address": vendor.business_address,
                            }
                            if employee.role == "office_staff"
                            else {}
                        ),
                    }
                    for vendor in vendors
                ],
            }
        )
    query = _staff_driver_query(employee.track_id)
    if query_text:
        like = f"%{query_text}%"
        query = query.filter(
            or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.username.ilike(like),
                User.email.ilike(like),
                User.phone.ilike(like),
            )
        )
    drivers = query.order_by(User.last_name.asc(), User.first_name.asc()).limit(200).all()
    return jsonify(
        {
            "view": "drivers",
            "drivers": [
                _driver_directory_payload(driver, employee.track_id) for driver in drivers
            ],
        }
    )


@mobile_api_bp.get("/staff/people/drivers/<int:user_id>")
@mobile_login_required("employee")
def staff_driver_detail(user_id):
    employee = g.mobile_user
    driver = _staff_driver_or_none(employee.track_id, user_id)
    if not driver:
        return _json_error("Driver not found at your track.", 404, "driver_not_found")
    registrations = (
        EventRegistration.query.join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == employee.track_id, EventRegistration.user_id == driver.id)
        .order_by(Event.event_date.desc(), EventRegistration.created_at.desc())
        .all()
    )
    registration_ids = [registration.id for registration in registrations]
    inspections = {
        inspection.event_registration_id: inspection
        for inspection in Inspection.query.filter(
            Inspection.event_registration_id.in_(registration_ids or [-1])
        ).all()
    }
    notes = (
        DriverNote.query.filter_by(track_id=employee.track_id, user_id=driver.id)
        .order_by(DriverNote.created_at.desc())
        .all()
    )
    class_changes = (
        DriverClassChange.query.filter_by(track_id=employee.track_id, user_id=driver.id)
        .order_by(DriverClassChange.created_at.desc())
        .limit(25)
        .all()
    )
    class_options = (
        TrackDriverClassOption.query.filter_by(track_id=employee.track_id)
        .order_by(TrackDriverClassOption.sort_order.asc(), TrackDriverClassOption.name.asc())
        .all()
    )
    summary = _driver_directory_payload(driver, employee.track_id)
    return jsonify(
        {
            "driver": summary,
            "class_options": [option.name for option in class_options]
            or [summary["driver_class"]],
            "events": [
                {
                    "registration_id": registration.id,
                    "event": _event_payload(registration.event),
                    "car": _car_payload(registration.car),
                    "checked_in_at": _iso(registration.checked_in_at),
                    "inspection_state": (
                        "passed"
                        if inspections.get(registration.id) and inspections[registration.id].passed
                        else "needs_attention"
                        if inspections.get(registration.id)
                        else "not_started"
                    ),
                }
                for registration in registrations
            ],
            "notes": [
                {
                    "id": note.id,
                    "text": note.note_text,
                    "author": note.author_name,
                    "created_at": _iso(note.created_at),
                }
                for note in notes
            ],
            "class_changes": [
                {
                    "id": change.id,
                    "previous": change.previous_class,
                    "new": change.new_class,
                    "author": change.changed_by_name,
                    "created_at": _iso(change.created_at),
                }
                for change in class_changes
            ],
        }
    )


@mobile_api_bp.post("/staff/people/drivers/<int:user_id>/notes")
@mobile_login_required("employee")
def staff_driver_note_create(user_id):
    employee = g.mobile_user
    driver = _staff_driver_or_none(employee.track_id, user_id)
    if not driver:
        return _json_error("Driver not found at your track.", 404, "driver_not_found")
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text or len(text) > 2000:
        return _json_error("Enter a note between 1 and 2,000 characters.", 400, "invalid_note")
    note = DriverNote(
        track_id=employee.track_id,
        user_id=driver.id,
        note_text=text,
        author_type="employee",
        author_id=employee.id,
        author_name=employee.full_name,
    )
    db.session.add(note)
    db.session.commit()
    return jsonify(
        {
            "note": {
                "id": note.id,
                "text": note.note_text,
                "author": note.author_name,
                "created_at": _iso(note.created_at),
            }
        }
    ), 201


@mobile_api_bp.put("/staff/people/drivers/<int:user_id>/class")
@mobile_login_required("employee")
def staff_driver_class_update(user_id):
    employee = g.mobile_user
    driver = _staff_driver_or_none(employee.track_id, user_id)
    if not driver:
        return _json_error("Driver not found at your track.", 404, "driver_not_found")
    selected = ((request.get_json(silent=True) or {}).get("driver_class") or "").strip()
    valid = {
        option.name
        for option in TrackDriverClassOption.query.filter_by(track_id=employee.track_id).all()
    }
    if selected not in valid:
        return _json_error("Choose a valid driver class.", 400, "invalid_driver_class")
    record = TrackDriverClass.query.filter_by(
        track_id=employee.track_id, user_id=driver.id
    ).first()
    if not record:
        record = TrackDriverClass(
            track_id=employee.track_id,
            user_id=driver.id,
            driver_class=selected,
            updated_by_employee_id=employee.id,
        )
        previous = driver.driver_class or "C"
        db.session.add(record)
    else:
        previous = record.driver_class
        record.driver_class = selected
        record.updated_by_employee_id = employee.id
    if previous != selected:
        db.session.add(
            DriverClassChange(
                track_id=employee.track_id,
                user_id=driver.id,
                previous_class=previous,
                new_class=selected,
                changed_by_type="employee",
                changed_by_id=employee.id,
                changed_by_name=employee.full_name,
            )
        )
    db.session.commit()
    return jsonify({"driver_class": selected})


def _staff_order_rows(employee):
    rows = load_order_rows(track_id=employee.track_id)
    if employee.role != "office_staff":
        rows = [row for row in rows if row["kind"] != "rental"]
        for row in rows:
            if "vendor" in row.get("ticket_categories", set()):
                row["buyer_name"] = row.get("vendor_business_name") or "Vendor"
                row["buyer_email"] = ""
    return rows


def _order_row_payload(row):
    return {
        "kind": row["kind"],
        "kind_label": row["kind_label"],
        "id": row["id"],
        "number": row["number"],
        "event_names": row["event_names"],
        "buyer_name": row["buyer_name"],
        "buyer_email": row["buyer_email"],
        "amount": _money(row["amount_cents"]),
        "provider": row["provider"],
        "mode": row["mode"],
        "payment_status": row["payment_status"],
        "transaction_id": row["transaction_id"],
        "created_at": _iso(row["created_at"]),
        "paid_at": _iso(row["paid_at"]),
    }


@mobile_api_bp.get("/staff/orders")
@mobile_login_required("employee")
def staff_orders():
    rows = _staff_order_rows(g.mobile_user)
    query_text = (request.args.get("q") or "").strip().lower()
    if query_text:
        rows = [
            row
            for row in rows
            if query_text
            in " ".join(
                [
                    row["number"],
                    row["buyer_name"],
                    row["buyer_email"],
                    row["provider"],
                    *row["event_names"],
                ]
            ).lower()
        ]
    summary = summarize_orders(rows)
    return jsonify(
        {
            "summary": {
                **summary,
                "paid_total": _money(summary["paid_cents"]),
            },
            "orders": [_order_row_payload(row) for row in rows[:200]],
        }
    )


def _staff_order_row_or_none(kind, order_id):
    return next(
        (
            row
            for row in _staff_order_rows(g.mobile_user)
            if row["kind"] == kind and row["id"] == order_id
        ),
        None,
    )


@mobile_api_bp.get("/staff/orders/<kind>/<int:order_id>")
@mobile_login_required("employee")
def staff_order_detail(kind, order_id):
    row = _staff_order_row_or_none(kind, order_id)
    if not row:
        return _json_error("Order not found at your track.", 404, "order_not_found")
    order = row["order"]
    payload = _order_row_payload(row)
    payload["items"] = []
    if kind == "spectator":
        payload["items"] = [
            {
                "id": item.id,
                "label": item.ticket_type_name,
                "category": item.ticket_category,
                "event": item.event.event_name,
                "quantity": item.quantity,
                "amount": _money(item.line_total_cents),
                "checked_in_at": _iso(item.checked_in_at),
            }
            for item in order.items
            if item.event.track_id == g.mobile_user.track_id
        ]
    elif kind == "driver":
        registration = EventRegistration.query.filter_by(
            event_id=order.event_id, user_id=order.user_id
        ).first()
        payload["items"] = [
            {
                "label": "Driver admission",
                "event": order.event.event_name,
                "car": _car_payload(order.car),
                "checked_in_at": _iso(registration.checked_in_at) if registration else None,
            }
        ]
    elif kind == "rental":
        payload["items"] = [
            {
                "label": order.slot.name,
                "event": order.event.event_name if order.event else None,
                "date": order.slot.slot_date.isoformat(),
                "car": _car_payload(order.car),
            }
        ]
    return jsonify({"order": payload})


@mobile_api_bp.post("/staff/orders/<kind>/<int:order_id>/resend")
@mobile_login_required("employee")
def staff_order_resend(kind, order_id):
    row = _staff_order_row_or_none(kind, order_id)
    if not row:
        return _json_error("Order not found at your track.", 404, "order_not_found")
    order = row["order"]
    if effective_payment_status(order) != "paid":
        return _json_error(
            "Payment must be confirmed before an email can be resent.",
            409,
            "payment_not_confirmed",
        )
    if kind == "spectator":
        if ensure_order_ticket_codes(order):
            db.session.commit()
        send_fn = send_spectator_order_receipt
    elif kind == "driver":
        send_fn = send_driver_purchase_receipt
    elif kind == "rental" and g.mobile_user.role == "office_staff":
        send_fn = send_private_rental_confirmation
    else:
        return _json_error("This order email cannot be resent.", 403, "forbidden")
    try:
        sent = send_fn(order)
    except Exception:
        current_app.logger.exception("Could not resend mobile order email")
        sent = False
    if not sent:
        return _json_error(
            "The email could not be sent. Check the track SMTP settings.",
            503,
            "email_failed",
        )
    return jsonify({"message": f"The {row['kind_label'].lower()} email was resent."})


@mobile_api_bp.get("/staff/hardware")
@mobile_login_required("employee")
def staff_hardware():
    track_id = g.mobile_user.track_id
    scanners = ScannerDevice.query.filter_by(track_id=track_id).order_by(ScannerDevice.name).all()
    cameras = CameraDevice.query.filter_by(track_id=track_id).order_by(CameraDevice.name).all()
    observations = (
        ScannerObservation.query.join(ScannerDevice)
        .filter(ScannerDevice.track_id == track_id)
        .order_by(ScannerObservation.received_at.desc())
        .limit(20)
        .all()
    )
    return jsonify(
        {
            "scanners": [
                {
                    "id": scanner.id,
                    "name": scanner.name,
                    "role": scanner.role,
                    "status": scanner.status,
                    "reader_connected": scanner.reader_connected,
                    "last_seen_at": _iso(scanner.last_seen_at),
                    "software_version": scanner.software_version,
                }
                for scanner in scanners
            ],
            "cameras": [
                {
                    "id": camera.id,
                    "name": camera.name,
                    "status": camera.status,
                    "camera_connected": camera.camera_connected,
                    "last_seen_at": _iso(camera.last_seen_at),
                    "software_version": camera.software_version,
                }
                for camera in cameras
            ],
            "observations": [
                {
                    "id": observation.id,
                    "scanner": observation.scanner.name,
                    "role": observation.scanner.role,
                    "result": observation.result,
                    "reason": observation.reason,
                    "epc": observation.epc,
                    "driver": (
                        f"{observation.car.owner.first_name} {observation.car.owner.last_name}".strip()
                        if observation.car
                        else None
                    ),
                    "car": _car_payload(observation.car) if observation.car else None,
                    "observed_at": _iso(observation.observed_at),
                }
                for observation in observations
            ],
        }
    )


@mobile_api_bp.put("/staff/hardware/scanners/<int:scanner_id>")
@mobile_login_required("employee")
def staff_scanner_update(scanner_id):
    guard = _mobile_office_guard()
    if guard:
        return guard
    scanner = ScannerDevice.query.filter_by(
        id=scanner_id, track_id=g.mobile_user.track_id
    ).first()
    if not scanner:
        return _json_error("Scanner not found.", 404, "scanner_not_found")
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or scanner.name).strip()[:120]
    role = (body.get("role") or scanner.role).strip()
    if role not in {"unassigned", "track_entrance", "track_exit"}:
        return _json_error("Choose a valid scanner zone.", 400, "invalid_scanner_role")
    if role != "unassigned":
        ScannerDevice.query.filter(
            ScannerDevice.track_id == g.mobile_user.track_id,
            ScannerDevice.role == role,
            ScannerDevice.id != scanner.id,
        ).update({"role": "unassigned"}, synchronize_session=False)
    scanner.name = name or scanner.name
    scanner.role = role
    db.session.commit()
    return jsonify({"message": "Scanner settings saved."})


@mobile_api_bp.post("/staff/hardware/scanners/register")
@mobile_login_required("employee")
def staff_scanner_register():
    guard = _mobile_office_guard()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    pairing_code = (body.get("pairing_code") or "").strip().upper()
    name = (body.get("name") or "").strip()[:120]
    if not pairing_code or not name:
        return _json_error("Enter the scanner name and pairing code.", 400, "pairing_required")
    now = datetime.utcnow()
    pending = ScannerDevice.query.filter(
        ScannerDevice.status == "pending", ScannerDevice.pairing_expires_at >= now
    ).all()
    device = next(
        (
            item
            for item in pending
            if check_password_hash(item.pairing_code_hash or "", pairing_code)
        ),
        None,
    )
    if not device:
        return _json_error(
            "That pairing code is invalid or has expired.", 400, "invalid_pairing_code"
        )
    device.track_id = g.mobile_user.track_id
    device.name = name
    device.status = "active"
    device.claimed_at = now
    device.pairing_code_hash = None
    device.pairing_expires_at = None
    db.session.commit()
    return jsonify({"message": f"{device.name} is now registered to this track."}), 201


def _staff_settings_payload(employee):
    track = db.session.get(Track, employee.track_id)
    payment_records = {
        item.provider: item
        for item in TrackPaymentMethod.query.filter_by(track_id=track.id).all()
    }
    staff = Employee.query.filter_by(track_id=track.id).order_by(Employee.full_name).all()
    rules = InspectionRule.query.filter_by(track_id=track.id).order_by(
        InspectionRule.sort_order.asc(), InspectionRule.id.asc()
    ).all()
    waivers = TrackWaiverTemplate.query.filter_by(track_id=track.id).order_by(
        TrackWaiverTemplate.updated_at.desc()
    ).all()
    email_records = {
        item.template_key: item
        for item in TrackEmailTemplate.query.filter_by(track_id=track.id).all()
    }
    class_options = TrackDriverClassOption.query.filter_by(track_id=track.id).order_by(
        TrackDriverClassOption.sort_order.asc(), TrackDriverClassOption.name.asc()
    ).all()
    return {
        "track": {"id": track.id, "name": track.name, "city": track.city, "state": track.state},
        "payments": [
            {
                "provider": provider,
                "label": label,
                "enabled": bool(payment_records.get(provider) and payment_records[provider].is_enabled),
                "mode": payment_records[provider].mode if payment_records.get(provider) else "live",
                "live_configured": bool(
                    payment_records.get(provider)
                    and (
                        payment_records[provider].public_key
                        or payment_records[provider].secret_key
                        or payment_records[provider].merchant_id
                    )
                ),
                "test_configured": bool(
                    payment_records.get(provider)
                    and (
                        payment_records[provider].test_public_key
                        or payment_records[provider].test_secret_key
                        or payment_records[provider].test_merchant_id
                    )
                ),
            }
            for provider, label in MOBILE_PAYMENT_PROVIDERS.items()
        ],
        "staff": [
            {
                "id": member.id,
                "name": member.full_name,
                "email": member.email,
                "role": member.role,
                "must_change_password": member.must_change_password,
                "can_reset": member.id != employee.id,
            }
            for member in staff
        ],
        "inspection_rules": [
            {"id": rule.id, "text": rule.rule_text, "active": rule.active}
            for rule in rules
        ],
        "waivers": [
            {
                "id": waiver.id,
                "title": waiver.title,
                "active": waiver.is_active,
                "required_for_checkin": waiver.required_for_checkin,
            }
            for waiver in waivers
        ],
        "email_templates": [
            {
                "key": key,
                "label": label,
                "configured": key in email_records,
                "enabled": email_records[key].is_enabled if key in email_records else True,
                "ticket_design": email_records[key].ticket_design if key in email_records else "pit_pass",
            }
            for key, label in MOBILE_EMAIL_TEMPLATES.items()
        ],
        "driver_classes": [
            {"id": option.id, "name": option.name} for option in class_options
        ],
    }


@mobile_api_bp.get("/staff/settings")
@mobile_login_required("employee")
def staff_settings():
    guard = _mobile_office_guard()
    if guard:
        return guard
    return jsonify({"settings": _staff_settings_payload(g.mobile_user)})


@mobile_api_bp.put("/staff/settings/track")
@mobile_login_required("employee")
def staff_settings_track_update():
    guard = _mobile_office_guard()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    city = (body.get("city") or "").strip()
    state = (body.get("state") or "").strip()
    if not name or not city or not state:
        return _json_error("Track name, city, and state are required.", 400, "invalid_track")
    track = db.session.get(Track, g.mobile_user.track_id)
    duplicate = Track.query.filter(Track.name == name, Track.id != track.id).first()
    if duplicate:
        return _json_error("Another track already uses that name.", 409, "track_name_taken")
    track.name = name[:200]
    track.city = city[:100]
    track.state = state[:100]
    db.session.commit()
    return jsonify({"settings": _staff_settings_payload(g.mobile_user)})


@mobile_api_bp.put("/staff/settings/payments/<provider>")
@mobile_login_required("employee")
def staff_settings_payment_update(provider):
    guard = _mobile_office_guard()
    if guard:
        return guard
    if provider not in MOBILE_PAYMENT_PROVIDERS:
        return _json_error("Unknown payment provider.", 404, "provider_not_found")
    body = request.get_json(silent=True) or {}
    record = TrackPaymentMethod.query.filter_by(
        track_id=g.mobile_user.track_id, provider=provider
    ).first()
    if body.get("enabled") is False:
        other_enabled = TrackPaymentMethod.query.filter(
            TrackPaymentMethod.track_id == g.mobile_user.track_id,
            TrackPaymentMethod.provider != provider,
            TrackPaymentMethod.is_enabled.is_(True),
        ).first()
        if not other_enabled:
            return _json_error(
                "Keep at least one payment provider enabled.",
                409,
                "payment_provider_required",
            )
    if not record:
        record = TrackPaymentMethod(track_id=g.mobile_user.track_id, provider=provider)
        db.session.add(record)
    if "enabled" in body:
        record.is_enabled = bool(body["enabled"])
    mode = (body.get("mode") or record.mode or "live").strip().lower()
    if mode not in {"live", "test"}:
        return _json_error("Payment mode must be live or test.", 400, "invalid_payment_mode")
    record.mode = mode
    for field in (
        "public_key",
        "secret_key",
        "webhook_secret",
        "merchant_id",
        "test_public_key",
        "test_secret_key",
        "test_webhook_secret",
        "test_merchant_id",
    ):
        if field in body:
            value = (body.get(field) or "").strip()
            setattr(record, field, value or None)
    db.session.flush()
    track = db.session.get(Track, g.mobile_user.track_id)
    enabled = TrackPaymentMethod.query.filter_by(
        track_id=g.mobile_user.track_id, is_enabled=True
    ).order_by(TrackPaymentMethod.id.asc()).all()
    enabled_names = {item.provider for item in enabled}
    if track.spectator_payment_provider not in enabled_names and enabled:
        track.spectator_payment_provider = enabled[0].provider
    db.session.commit()
    return jsonify({"settings": _staff_settings_payload(g.mobile_user)})


@mobile_api_bp.post("/staff/settings/inspection-rules")
@mobile_login_required("employee")
def staff_settings_rule_create():
    guard = _mobile_office_guard()
    if guard:
        return guard
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text or len(text) > 255:
        return _json_error("Enter a checklist item up to 255 characters.", 400, "invalid_rule")
    max_order = db.session.query(func.max(InspectionRule.sort_order)).filter_by(
        track_id=g.mobile_user.track_id
    ).scalar() or 0
    db.session.add(
        InspectionRule(
            track_id=g.mobile_user.track_id,
            rule_text=text,
            active=True,
            sort_order=max_order + 1,
        )
    )
    db.session.commit()
    return jsonify({"settings": _staff_settings_payload(g.mobile_user)}), 201


@mobile_api_bp.put("/staff/settings/inspection-rules/<int:rule_id>")
@mobile_login_required("employee")
def staff_settings_rule_update(rule_id):
    guard = _mobile_office_guard()
    if guard:
        return guard
    rule = InspectionRule.query.filter_by(
        id=rule_id, track_id=g.mobile_user.track_id
    ).first()
    if not rule:
        return _json_error("Inspection rule not found.", 404, "rule_not_found")
    body = request.get_json(silent=True) or {}
    if "active" in body:
        rule.active = bool(body["active"])
    db.session.commit()
    return jsonify({"settings": _staff_settings_payload(g.mobile_user)})


@mobile_api_bp.post("/staff/settings/staff")
@mobile_login_required("employee")
def staff_settings_staff_create():
    guard = _mobile_office_guard()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    role = (body.get("role") or "track_staff").strip()
    if not name or "@" not in email or role not in {"track_staff", "office_staff"}:
        return _json_error("Enter a name, valid email, and staff role.", 400, "invalid_staff")
    if Employee.query.filter(func.lower(Employee.email) == email).first():
        return _json_error("An employee already uses that email.", 409, "email_exists")
    password = generate_random_password()
    track = db.session.get(Track, g.mobile_user.track_id)
    employee = Employee(
        track_id=track.id,
        full_name=name[:150],
        email=email[:255],
        password_hash=generate_password_hash(password),
        must_change_password=True,
        role=role,
    )
    db.session.add(employee)
    try:
        db.session.flush()
        sent = send_employee_login_email(
            employee,
            password,
            track,
            url_for("auth.user_login", _external=True),
        )
    except Exception:
        current_app.logger.exception("Could not send mobile employee welcome email")
        sent = False
    if not sent:
        db.session.rollback()
        return _json_error(
            "The account was not created because the welcome email could not be delivered.",
            503,
            "email_failed",
        )
    db.session.commit()
    return jsonify({"settings": _staff_settings_payload(g.mobile_user)}), 201


@mobile_api_bp.post("/staff/settings/staff/<int:employee_id>/reset-password")
@mobile_login_required("employee")
def staff_settings_staff_reset(employee_id):
    guard = _mobile_office_guard()
    if guard:
        return guard
    employee = Employee.query.filter_by(
        id=employee_id, track_id=g.mobile_user.track_id
    ).first()
    if not employee or employee.id == g.mobile_user.id:
        return _json_error("That staff account cannot be reset here.", 404, "staff_not_found")
    password = generate_random_password()
    employee.password_hash = generate_password_hash(password)
    employee.must_change_password = True
    try:
        db.session.flush()
        sent = send_employee_login_email(
            employee,
            password,
            employee.track,
            url_for("auth.user_login", _external=True),
            is_reset=True,
        )
    except Exception:
        current_app.logger.exception("Could not send mobile employee reset email")
        sent = False
    if not sent:
        db.session.rollback()
        return _json_error(
            "The password was not changed because the reset email could not be delivered.",
            503,
            "email_failed",
        )
    db.session.commit()
    return jsonify({"message": f"A new password was emailed to {employee.email}."})


@mobile_api_bp.put("/staff/settings/staff/<int:employee_id>/role")
@mobile_login_required("employee")
def staff_settings_staff_role(employee_id):
    guard = _mobile_office_guard()
    if guard:
        return guard
    employee = Employee.query.filter_by(
        id=employee_id, track_id=g.mobile_user.track_id
    ).first()
    if not employee:
        return _json_error("Staff account not found.", 404, "staff_not_found")
    role = ((request.get_json(silent=True) or {}).get("role") or "").strip()
    if role not in {"track_staff", "office_staff"}:
        return _json_error("Choose a valid staff role.", 400, "invalid_staff_role")
    if employee.role == "office_staff" and role == "track_staff":
        office_count = Employee.query.filter_by(
            track_id=g.mobile_user.track_id, role="office_staff"
        ).count()
        if office_count <= 1:
            return _json_error(
                "Every track must keep at least one office staff account.",
                409,
                "office_staff_required",
            )
    employee.role = role
    db.session.commit()
    return jsonify({"settings": _staff_settings_payload(g.mobile_user)})


def _spectator_state(item):
    paid = payment_is_confirmed(
        item.order.payment_status,
        item.order.payment_method,
        item.order.total_cents,
        item.order.provider_transaction_id,
    )
    return "unpaid" if not paid else ("used" if item.checked_in_at else "valid")


def _driver_state(registration, order):
    paid = order and payment_is_confirmed(
        order.payment_status,
        order.payment_method,
        order.amount_cents,
        order.provider_transaction_id,
    )
    return "unpaid" if not paid else ("used" if registration.checked_in_at else "valid")


def _inspection_state(registration):
    inspection = Inspection.query.filter_by(event_registration_id=registration.id).first()
    if not inspection:
        return "not_started"
    return "passed" if inspection.passed else "needs_attention"


def _driver_ticket_payload(registration):
    order = (
        DriverTicketOrder.query.filter_by(
            event_id=registration.event_id, user_id=registration.user_id
        )
        .order_by(DriverTicketOrder.created_at.desc())
        .first()
    )
    return {
        "code": registration.checkin_code,
        "kind": "driver",
        "ticket_type": "Driver admission",
        "name": f"{registration.user.first_name} {registration.user.last_name}".strip(),
        "state": _driver_state(registration, order),
        "event": _event_payload(registration.event),
        "car": _car_payload(registration.car),
        "registration_id": registration.id,
        "inspection_state": _inspection_state(registration),
        "checked_in_at": _iso(registration.checked_in_at),
    }


def _ticket_match(code, track_id, event_id=None):
    item_query = SpectatorOrderItem.query.join(Event).filter(
        SpectatorOrderItem.qr_code == code, Event.track_id == track_id
    )
    if event_id:
        item_query = item_query.filter(Event.id == event_id)
    item = item_query.first()
    if item:
        order = item.order
        name = (
            (order.vendor.business_name if order.vendor else None)
            or (f"{order.buyer.first_name} {order.buyer.last_name}".strip() if order.buyer else None)
            or order.guest_full_name
            or "Guest"
        )
        return {
            "code": code,
            "kind": item.ticket_category,
            "ticket_type": item.ticket_type_name,
            "name": name,
            "state": _spectator_state(item),
            "event": _event_payload(item.event),
            "checked_in_at": _iso(item.checked_in_at),
        }
    registration_query = EventRegistration.query.join(Event).filter(
        EventRegistration.checkin_code == code, Event.track_id == track_id
    )
    if event_id:
        registration_query = registration_query.filter(Event.id == event_id)
    registration = registration_query.first()
    if not registration:
        return None
    return _driver_ticket_payload(registration)


@mobile_api_bp.post("/staff/tickets/lookup")
@mobile_login_required("employee")
def staff_ticket_lookup():
    body = request.get_json(silent=True) or {}
    raw_lookup = (body.get("query") or "").strip()
    if not raw_lookup:
        return _json_error("Scan a QR code or enter a name, email, or ticket code.")
    event_id = body.get("event_id")
    if event_id is not None:
        try:
            event_id = int(event_id)
        except (TypeError, ValueError):
            return _json_error("Select a valid event.", 400, "invalid_event")
        event = Event.query.filter_by(id=event_id, track_id=g.mobile_user.track_id).first()
        if not event:
            return _json_error("That event is not part of your track.", 404, "event_not_found")
    code = normalize_ticket_code(raw_lookup)
    direct = _ticket_match(code, g.mobile_user.track_id, event_id)
    if not direct:
        registration = (
            EventRegistration.query.join(User, User.id == EventRegistration.user_id)
            .join(Car, Car.id == EventRegistration.car_id)
            .join(Event, Event.id == EventRegistration.event_id)
            .filter(
                Event.track_id == g.mobile_user.track_id,
                Event.event_date >= _local_today(),
                *([Event.id == event_id] if event_id else []),
                or_(User.static_qr_code == code, Car.static_qr_code == code),
            )
            .order_by(Event.event_date.asc())
            .first()
        )
        if registration:
            direct = _driver_ticket_payload(registration)
    if direct:
        return jsonify({"results": [direct]})
    like = f"%{raw_lookup}%"
    registrations = (
        EventRegistration.query.join(User, User.id == EventRegistration.user_id)
        .join(Event, Event.id == EventRegistration.event_id)
        .filter(
            Event.track_id == g.mobile_user.track_id,
            Event.event_date >= _local_today(),
            *([Event.id == event_id] if event_id else []),
            or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                User.username.ilike(like),
            ),
        )
        .order_by(Event.event_date.desc())
        .limit(20)
        .all()
    )
    results = [_driver_ticket_payload(registration) for registration in registrations]
    return jsonify({"results": results})


@mobile_api_bp.post("/staff/tickets/<path:raw_code>/check-in")
@mobile_login_required("employee")
def staff_ticket_check_in(raw_code):
    code = normalize_ticket_code(raw_code)
    employee = g.mobile_user
    body = request.get_json(silent=True) or {}
    event_id = body.get("event_id")
    if event_id is not None:
        try:
            event_id = int(event_id)
        except (TypeError, ValueError):
            return _json_error("Select a valid event.", 400, "invalid_event")
        if not Event.query.filter_by(id=event_id, track_id=employee.track_id).first():
            return _json_error("That event is not part of your track.", 404, "event_not_found")
    item_query = SpectatorOrderItem.query.join(Event).filter(
        SpectatorOrderItem.qr_code == code, Event.track_id == employee.track_id
    )
    if event_id:
        item_query = item_query.filter(Event.id == event_id)
    item = item_query.first()
    now = datetime.utcnow()
    if item:
        state = _spectator_state(item)
        if state == "unpaid":
            return _json_error("Payment has not been confirmed for this ticket.", 409, "unpaid_ticket")
        if state == "used":
            return _json_error("STOP — this ticket was already used.", 409, "ticket_already_used")
        item.checked_in_at = now
        item.checked_in_by_employee_id = employee.id
        db.session.commit()
        return jsonify({"ticket": _ticket_match(code, employee.track_id, event_id)})
    registration_query = EventRegistration.query.join(Event).filter(
        EventRegistration.checkin_code == code, Event.track_id == employee.track_id
    )
    if event_id:
        registration_query = registration_query.filter(Event.id == event_id)
    registration = registration_query.first()
    if not registration:
        return _json_error("No ticket at this track matches that code.", 404, "ticket_not_found")
    order = (
        DriverTicketOrder.query.filter_by(
            event_id=registration.event_id, user_id=registration.user_id
        )
        .order_by(DriverTicketOrder.created_at.desc())
        .first()
    )
    state = _driver_state(registration, order)
    if state == "unpaid":
        return _json_error("Payment has not been confirmed for this driver ticket.", 409, "unpaid_ticket")
    if state == "used":
        return _json_error("STOP — this ticket was already used.", 409, "ticket_already_used")
    registration.checked_in_at = now
    registration.checked_in_by_employee_id = employee.id
    db.session.commit()
    return jsonify({"ticket": _ticket_match(code, employee.track_id, event_id)})


def _staff_registration(registration_id):
    return (
        EventRegistration.query.join(Event)
        .filter(
            EventRegistration.id == registration_id,
            Event.track_id == g.mobile_user.track_id,
        )
        .first()
    )


def _inspection_detail(registration):
    rules = (
        InspectionRule.query.filter_by(track_id=g.mobile_user.track_id, active=True)
        .order_by(InspectionRule.sort_order.asc(), InspectionRule.id.asc())
        .all()
    )
    inspection = Inspection.query.filter_by(event_registration_id=registration.id).first()
    checked_ids = {
        item.inspection_rule_id for item in inspection.items if item.checked
    } if inspection else set()
    return {
        "registration_id": registration.id,
        "driver": f"{registration.user.first_name} {registration.user.last_name}".strip(),
        "car": _car_payload(registration.car),
        "event": _event_payload(registration.event),
        "checked_in": bool(registration.checked_in_at),
        "rules": [
            {"id": rule.id, "text": rule.rule_text, "checked": rule.id in checked_ids}
            for rule in rules
        ],
        "notes": inspection.notes if inspection else "",
        "status": _inspection_state(registration),
    }


@mobile_api_bp.get("/staff/inspections/<int:registration_id>")
@mobile_login_required("employee")
def staff_inspection(registration_id):
    registration = _staff_registration(registration_id)
    if not registration:
        return _json_error("Driver registration not found at your track.", 404, "registration_not_found")
    return jsonify({"inspection": _inspection_detail(registration)})


@mobile_api_bp.put("/staff/inspections/<int:registration_id>")
@mobile_login_required("employee")
def staff_inspection_save(registration_id):
    registration = _staff_registration(registration_id)
    if not registration:
        return _json_error("Driver registration not found at your track.", 404, "registration_not_found")
    if not registration.checked_in_at:
        return _json_error("Check the driver in before starting inspection.", 409, "check_in_required")
    rules = InspectionRule.query.filter_by(track_id=g.mobile_user.track_id, active=True).all()
    if not rules:
        return _json_error("Your track has no active inspection checklist.", 409, "checklist_required")
    body = request.get_json(silent=True) or {}
    try:
        checked_ids = {int(value) for value in body.get("checked_rule_ids", [])}
    except (TypeError, ValueError):
        return _json_error("The inspection checklist is invalid.", 400, "invalid_checklist")
    valid_ids = {rule.id for rule in rules}
    if checked_ids - valid_ids:
        return _json_error("The inspection checklist is out of date. Reload it and try again.", 409, "checklist_changed")
    notes = (body.get("notes") or "").strip()
    if len(notes) > 500:
        return _json_error("Inspection notes must be 500 characters or fewer.", 400, "notes_too_long")
    inspection = Inspection.query.filter_by(event_registration_id=registration.id).first()
    if not inspection:
        inspection = Inspection(
            event_registration_id=registration.id,
            inspected_by_employee_id=g.mobile_user.id,
        )
        db.session.add(inspection)
        db.session.flush()
    else:
        inspection.inspected_by_employee_id = g.mobile_user.id
    existing = {item.inspection_rule_id: item for item in inspection.items}
    for rule in rules:
        item = existing.get(rule.id)
        if item:
            item.checked = rule.id in checked_ids
        else:
            db.session.add(
                InspectionItem(
                    inspection_id=inspection.id,
                    inspection_rule_id=rule.id,
                    checked=rule.id in checked_ids,
                )
            )
    inspection.passed = checked_ids == valid_ids
    inspection.notes = notes or None
    db.session.commit()
    return jsonify({"inspection": _inspection_detail(registration)})
