"""Versioned JSON API for the Track Ops iOS and Android applications."""

from datetime import date, datetime, timedelta
from functools import wraps
import hashlib
import secrets

from flask import Blueprint, current_app, g, jsonify, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, or_
from werkzeug.security import check_password_hash, generate_password_hash

from .models import (
    Car,
    DriverTicketOrder,
    Employee,
    EnterpriseAdmin,
    Event,
    EventRegistration,
    Inspection,
    MobileRefreshToken,
    SpectatorOrder,
    SpectatorOrderItem,
    Track,
    User,
    VendorAccount,
    db,
)
from .services.capacity_service import ticket_availability
from .services.payment_service import effective_payment_status, payment_is_confirmed
from .services.ticket_service import normalize_ticket_code, ticket_verification_url
from .services.wallet_service import wallet_links_for_ticket


mobile_api_bp = Blueprint("mobile_api", __name__, url_prefix="/api/v1/mobile")
ACCESS_TOKEN_SECONDS = 60 * 60
REFRESH_TOKEN_DAYS = 30
ACCOUNT_MODELS = {
    "user": User,
    "employee": Employee,
    "admin": EnterpriseAdmin,
    "vendor": VendorAccount,
}


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="trackops-mobile-v1")


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
            Event.event_date >= date.today(),
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
            Event.event_date >= date.today(),
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


@mobile_api_bp.get("/staff/events")
@mobile_login_required("employee")
def staff_events():
    events = (
        Event.query.filter(
            Event.track_id == g.mobile_user.track_id,
            Event.event_date >= date.today() - timedelta(days=1),
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


def _ticket_match(code, track_id):
    item = (
        SpectatorOrderItem.query.join(Event)
        .filter(SpectatorOrderItem.qr_code == code, Event.track_id == track_id)
        .first()
    )
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
    registration = (
        EventRegistration.query.join(Event)
        .filter(EventRegistration.checkin_code == code, Event.track_id == track_id)
        .first()
    )
    if not registration:
        return None
    order = (
        DriverTicketOrder.query.filter_by(
            event_id=registration.event_id, user_id=registration.user_id
        )
        .order_by(DriverTicketOrder.created_at.desc())
        .first()
    )
    return {
        "code": code,
        "kind": "driver",
        "ticket_type": "Driver admission",
        "name": f"{registration.user.first_name} {registration.user.last_name}".strip(),
        "state": _driver_state(registration, order),
        "event": _event_payload(registration.event),
        "car": _car_payload(registration.car),
        "checked_in_at": _iso(registration.checked_in_at),
    }


@mobile_api_bp.post("/staff/tickets/lookup")
@mobile_login_required("employee")
def staff_ticket_lookup():
    raw_lookup = ((request.get_json(silent=True) or {}).get("query") or "").strip()
    if not raw_lookup:
        return _json_error("Scan a QR code or enter a name, email, or ticket code.")
    code = normalize_ticket_code(raw_lookup)
    direct = _ticket_match(code, g.mobile_user.track_id)
    if direct:
        return jsonify({"results": [direct]})
    like = f"%{raw_lookup}%"
    registrations = (
        EventRegistration.query.join(User).join(Event)
        .filter(
            Event.track_id == g.mobile_user.track_id,
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
    results = [
        match
        for registration in registrations
        if (match := _ticket_match(registration.checkin_code, g.mobile_user.track_id))
    ]
    return jsonify({"results": results})


@mobile_api_bp.post("/staff/tickets/<path:raw_code>/check-in")
@mobile_login_required("employee")
def staff_ticket_check_in(raw_code):
    code = normalize_ticket_code(raw_code)
    employee = g.mobile_user
    item = (
        SpectatorOrderItem.query.join(Event)
        .filter(SpectatorOrderItem.qr_code == code, Event.track_id == employee.track_id)
        .first()
    )
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
        return jsonify({"ticket": _ticket_match(code, employee.track_id)})
    registration = (
        EventRegistration.query.join(Event)
        .filter(EventRegistration.checkin_code == code, Event.track_id == employee.track_id)
        .first()
    )
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
    return jsonify({"ticket": _ticket_match(code, employee.track_id)})
