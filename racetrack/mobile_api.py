"""Versioned JSON API for the Track Ops iOS and Android applications."""

from datetime import date, datetime, timedelta
from functools import wraps
import hashlib
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, current_app, g, jsonify, redirect, request, url_for
from flask_login import login_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, or_
from urllib.parse import urlsplit
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
    ScannerDevice,
    ScannerObservation,
    SocialPost,
    SpectatorOrder,
    SpectatorOrderItem,
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
from .services.capacity_service import ticket_availability
from .services.email_service import (
    send_driver_purchase_receipt,
    send_employee_login_email,
    send_private_rental_confirmation,
    send_spectator_order_receipt,
)
from .services.order_service import load_order_rows, summarize_orders
from .services.payment_service import effective_payment_status, payment_is_confirmed
from .services.ticket_service import ensure_order_ticket_codes, normalize_ticket_code, ticket_verification_url
from .services.wallet_service import wallet_links_for_ticket
from .services.run_service import expire_stale_track_states
from .services.storage_service import build_presigned_read_url
from .security import generate_random_password


mobile_api_bp = Blueprint("mobile_api", __name__, url_prefix="/api/v1/mobile")
ACCESS_TOKEN_SECONDS = 60 * 60
REFRESH_TOKEN_DAYS = 30
WEB_HANDOFF_SECONDS = 90
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


@mobile_api_bp.get("/driver/tickets")
@mobile_login_required("user")
def driver_tickets():
    user = g.mobile_user
    tickets = []
    driver_orders = (
        DriverTicketOrder.query.filter_by(user_id=user.id, payment_status="paid")
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
        .filter(SpectatorOrder.user_id == user.id, SpectatorOrder.payment_status == "paid")
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
