import secrets
import os
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from .forms import CarForm, DriverCheckoutForm, EventSignupForm, SocialCommentForm, SpectatorCheckoutForm
from .models import (
    Car,
    Event,
    EventClassSlot,
    DriverTicketOrder,
    EventRegistration,
    SocialComment,
    SocialPost,
    SpectatorCart,
    SpectatorCartItem,
    SpectatorOrder,
    SpectatorOrderItem,
    SpectatorTicketOrder,
    SpectatorTicketType,
    Track,
    TrackDriverClass,
    TrackPaymentMethod,
    TrackSubscription,
    TrackWaiverTemplate,
    db,
)
from .services.storage_service import upload_public_image
from .services.email_service import send_driver_purchase_receipt, send_spectator_order_receipt
from .services.capacity_service import (
    driver_already_has_ticket,
    driver_order_fits_capacity,
    driver_payment_in_progress,
    reservation_is_active,
    spectator_order_fits_capacity,
    ticket_availability,
)
from .services.payment_service import (
    PayPalError,
    capture_paypal_order,
    create_paypal_order,
    create_driver_stripe_checkout_session,
    create_stripe_checkout_session,
    mark_driver_ticket_paid,
    mark_order_paid,
    paypal_capture_details,
    verify_paypal_webhook_signature,
)
from .services.ticket_service import ensure_order_ticket_codes, generate_ticket_code

try:
    import stripe
except Exception:  # pragma: no cover
    stripe = None


user_bp = Blueprint("user", __name__, url_prefix="/user")
FORCED_BOLDSIGN_TEMPLATE_ID = os.getenv(
    "BOLDSIGN_FORCED_TEMPLATE_ID", "e5c8f024-64df-4bdc-9142-3a04c01a154a"
)
PAYMENT_PROVIDER_LABELS = {
    "stripe": "Stripe",
    "paypal": "PayPal",
    "toast": "Toast",
    "quickbooks": "QuickBooks Payments",
    "other": "Other / Manual",
}


def _payment_credentials(track, provider, method=None, mode=None):
    if method is None:
        method = TrackPaymentMethod.query.filter_by(
            track_id=track.id,
            provider=provider,
        ).first()
    selected_mode = (mode or (method.mode if method else "live") or "live").lower()
    if selected_mode not in {"live", "test"}:
        selected_mode = "live"

    prefix = "test_" if selected_mode == "test" else ""
    credentials = {
        "method": method,
        "mode": selected_mode,
        "public_key": getattr(method, f"{prefix}public_key", None) if method else None,
        "secret_key": getattr(method, f"{prefix}secret_key", None) if method else None,
        "webhook_secret": getattr(method, f"{prefix}webhook_secret", None) if method else None,
        "merchant_id": getattr(method, f"{prefix}merchant_id", None) if method else None,
        "extra_config": getattr(method, f"{prefix}extra_config", None) if method else None,
    }
    # Tracks configured before provider records existed remain valid in live mode.
    if provider == "stripe" and selected_mode == "live":
        credentials["secret_key"] = credentials["secret_key"] or track.stripe_secret_key
        credentials["webhook_secret"] = credentials["webhook_secret"] or track.stripe_webhook_secret
    return credentials


def _generate_car_qr_code():
    while True:
        code = f"CAR-{secrets.token_hex(4).upper()}"
        if not Car.query.filter_by(static_qr_code=code).first():
            return code


def _money(cents):
    return f"${(cents or 0) / 100:,.2f}"


def _configured_payment_choices(track, amount_cents):
    methods = TrackPaymentMethod.query.filter_by(track_id=track.id, is_enabled=True).all()
    methods_by_provider = {
        method.provider: method
        for method in methods
        if method.provider in PAYMENT_PROVIDER_LABELS
    }
    providers = list(methods_by_provider)
    if not providers:
        providers = [track.spectator_payment_provider or "stripe"]

    choices = []
    for provider in providers:
        credentials = _payment_credentials(
            track,
            provider,
            method=methods_by_provider.get(provider),
        )
        if amount_cents > 0 and provider not in {"stripe", "paypal"}:
            continue
        if provider == "stripe" and amount_cents > 0 and not (
            credentials["secret_key"] and credentials["webhook_secret"]
        ):
            continue
        if provider == "paypal" and amount_cents > 0 and not (
            credentials["public_key"]
            and credentials["secret_key"]
            and credentials["webhook_secret"]
        ):
            continue
        label = PAYMENT_PROVIDER_LABELS.get(provider, provider.title())
        if credentials["mode"] == "test":
            label = f"{label} (Test mode)"
        choices.append((provider, label))
    if not choices and amount_cents <= 0:
        choices.append(("other", PAYMENT_PROVIDER_LABELS["other"]))
    return choices


def _get_or_create_default_ticket_type(event, ticket_category="spectator"):
    ticket_category = "vendor" if ticket_category == "vendor" else "spectator"
    ticket_type = (
        SpectatorTicketType.query.filter_by(
            event_id=event.id,
            ticket_category=ticket_category,
            is_active=True,
        )
        .order_by(SpectatorTicketType.created_at.asc())
        .first()
    )
    if ticket_type:
        return ticket_type
    ticket_type = SpectatorTicketType(
        event_id=event.id,
        name="Vendor Admission" if ticket_category == "vendor" else "General Admission",
        ticket_category=ticket_category,
        price_cents=max(
            0,
            (event.vendor_price_cents if ticket_category == "vendor" else event.spectator_price_cents) or 0,
        ),
        is_active=True,
        max_per_order=20 if ticket_category == "vendor" else 10,
    )
    db.session.add(ticket_type)
    db.session.commit()
    return ticket_type


def _event_ticket_availability(event):
    return {
        category: ticket_availability(event, category)
        for category in ("driver", "spectator", "vendor")
    }


def _ticket_purchase_limit(event, ticket_type):
    category = ticket_type.ticket_category if ticket_type else "spectator"
    availability = ticket_availability(event, category)
    per_order = max(1, int(ticket_type.max_per_order or 10)) if ticket_type else 10
    if availability["unlimited"]:
        return per_order, availability
    return min(per_order, availability["remaining"]), availability


def _get_or_create_spectator_cart():
    user_id = None
    if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user":
        user_id = current_user.id
    if user_id:
        user_cart = SpectatorCart.query.filter_by(user_id=user_id).first()
        guest_token = session.get("spectator_cart_token")
        guest_cart = (
            SpectatorCart.query.filter_by(session_token=guest_token).first()
            if guest_token
            else None
        )

        if guest_cart and guest_cart.id != getattr(user_cart, "id", None):
            if not user_cart:
                guest_cart.user_id = user_id
                guest_cart.session_token = None
                session.pop("spectator_cart_token", None)
                db.session.commit()
                return guest_cart

            guest_items = list(guest_cart.items)
            user_items = list(user_cart.items)
            guest_track_ids = {item.event.track_id for item in guest_items}
            user_track_ids = {item.event.track_id for item in user_items}
            can_merge = not guest_items or not user_items or guest_track_ids == user_track_ids
            if can_merge:
                for guest_item in guest_items:
                    existing = SpectatorCartItem.query.filter_by(
                        cart_id=user_cart.id,
                        event_id=guest_item.event_id,
                        ticket_type_id=guest_item.ticket_type_id,
                    ).first()
                    if existing:
                        max_qty = guest_item.ticket_type.max_per_order if guest_item.ticket_type else 10
                        existing.quantity = min(
                            (existing.quantity or 0) + (guest_item.quantity or 0),
                            max_qty or 10,
                        )
                        db.session.delete(guest_item)
                    else:
                        guest_item.cart = user_cart
                db.session.delete(guest_cart)
                session.pop("spectator_cart_token", None)
                session.pop("spectator_cart_merge_notice", None)
                db.session.commit()
            elif not session.get("spectator_cart_merge_notice"):
                session["spectator_cart_merge_notice"] = True
                flash(
                    "Your saved account cart is for another track, so it was kept separate from the guest cart.",
                    "error",
                )
            return user_cart

        if user_cart:
            return user_cart
        user_cart = SpectatorCart(user_id=user_id)
        db.session.add(user_cart)
        db.session.commit()
        return user_cart

    token = session.get("spectator_cart_token")
    if not token:
        token = secrets.token_hex(16)
        session["spectator_cart_token"] = token
    cart = SpectatorCart.query.filter_by(session_token=token).first()
    if cart:
        return cart
    cart = SpectatorCart(session_token=token)
    db.session.add(cart)
    db.session.commit()
    return cart


def _cart_item_count(cart):
    return sum(item.quantity for item in cart.items)


def require_user():
    if not current_user.is_authenticated:
        flash("Please sign in as a driver.", "error")
        return redirect(url_for("auth.user_login"))
    if current_user.account_type != "user":
        flash("Driver access required for that page.", "error")
        return redirect(url_for("employee.dashboard"))
    return None


def _safe_send_email(send_fn, *args):
    try:
        send_fn(*args)
    except Exception as exc:
        current_app.logger.warning("Email send failed: %s", exc)


def _create_driver_post_purchase_steps(driver_ticket_order):
    event = driver_ticket_order.event
    user = driver_ticket_order.buyer
    car = driver_ticket_order.car
    if not car.static_qr_code:
        car.static_qr_code = _generate_car_qr_code()

    reg = EventRegistration.query.filter_by(event_id=event.id, user_id=user.id).first()
    if not reg:
        reg = EventRegistration(
            event_id=event.id,
            user_id=user.id,
            car_id=car.id,
            checkin_code=car.static_qr_code,
        )
        db.session.add(reg)
        db.session.flush()

    track_class = TrackDriverClass.query.filter_by(track_id=event.track_id, user_id=user.id).first()
    if not track_class:
        db.session.add(TrackDriverClass(track_id=event.track_id, user_id=user.id, driver_class="C"))

    if not SocialPost.query.filter_by(event_registration_id=reg.id).first():
        db.session.add(
            SocialPost(
                user_id=user.id,
                event_id=event.id,
                event_registration_id=reg.id,
                post_type="event_signup",
                title=f"@{user.username} signed up for {event.event_name}",
                body=f"Driving: {car.car_year} {car.make} {car.model}",
            )
        )

    from .models import DriverWaiver

    required_templates = TrackWaiverTemplate.query.filter_by(
        track_id=event.track_id, is_active=True, required_for_checkin=True
    ).all()
    if not required_templates and FORCED_BOLDSIGN_TEMPLATE_ID:
        fallback_template = TrackWaiverTemplate(
            track_id=event.track_id,
            title="Track Waiver",
            boldsign_template_id=FORCED_BOLDSIGN_TEMPLATE_ID,
            is_active=True,
            required_for_checkin=True,
        )
        db.session.add(fallback_template)
        db.session.flush()
        required_templates = [fallback_template]

    created_waiver_id = None
    needs_waiver_action = False
    for template in required_templates:
        exists = DriverWaiver.query.filter_by(
            track_id=event.track_id,
            driver_id=user.id,
            event_id=event.id,
            waiver_template_id=template.id,
        ).first()
        if not exists:
            new_waiver = DriverWaiver(
                track_id=event.track_id,
                driver_id=user.id,
                event_id=event.id,
                waiver_template_id=template.id,
                status="not_sent",
            )
            db.session.add(new_waiver)
            db.session.flush()
            needs_waiver_action = True
            if created_waiver_id is None:
                created_waiver_id = new_waiver.id
        elif exists.status != "signed":
            needs_waiver_action = True
            if created_waiver_id is None:
                created_waiver_id = exists.id
    return needs_waiver_action, created_waiver_id


def _finalize_driver_ticket_order(driver_ticket_order, transaction_id=None):
    if driver_ticket_order.payment_status != "paid":
        mark_driver_ticket_paid(driver_ticket_order, transaction_id=transaction_id)
        needs_waiver_action, created_waiver_id = _create_driver_post_purchase_steps(driver_ticket_order)
        db.session.commit()
        _safe_send_email(send_driver_purchase_receipt, driver_ticket_order)
        return needs_waiver_action, created_waiver_id
    if transaction_id and not driver_ticket_order.provider_transaction_id:
        driver_ticket_order.provider_transaction_id = transaction_id
        driver_ticket_order.paid_at = driver_ticket_order.paid_at or datetime.utcnow()
    needs_waiver_action, created_waiver_id = _create_driver_post_purchase_steps(driver_ticket_order)
    db.session.commit()
    return needs_waiver_action, created_waiver_id


def _finalize_spectator_order(order, transaction_id=None):
    ticket_codes_added = ensure_order_ticket_codes(order)
    if order.payment_status == "paid":
        if transaction_id and not order.provider_transaction_id:
            order.provider_transaction_id = transaction_id
            order.paid_at = order.paid_at or datetime.utcnow()
            db.session.commit()
        elif ticket_codes_added:
            db.session.commit()
        return
    mark_order_paid(order, transaction_id=transaction_id)
    for order_item in SpectatorOrderItem.query.filter_by(order_id=order.id).all():
        db.session.add(
            SpectatorTicketOrder(
                event_id=order_item.event_id,
                user_id=order.user_id,
                buyer_type="user" if order.user_id else "guest",
                guest_full_name=order.guest_full_name,
                guest_email=order.guest_email,
                guest_phone=order.guest_phone,
                quantity=order_item.quantity,
                payment_method=order.payment_method,
                ticket_category=order_item.ticket_category or "spectator",
                status="recorded",
            )
        )
    if order.user_id:
        cart = SpectatorCart.query.filter_by(user_id=order.user_id).first()
        if cart:
            for item in list(cart.items):
                db.session.delete(item)
    db.session.commit()
    _safe_send_email(send_spectator_order_receipt, order)


def _paypal_credentials_for_order(spectator_order=None, driver_ticket_order=None):
    if spectator_order:
        track = spectator_order.items[0].event.track if spectator_order.items else None
        mode = spectator_order.payment_mode
    else:
        track = driver_ticket_order.event.track if driver_ticket_order else None
        mode = driver_ticket_order.payment_mode if driver_ticket_order else None
    return _payment_credentials(track, "paypal", mode=mode) if track else None


def _validated_paypal_capture(details, expected_cents):
    try:
        captured_cents = int(Decimal(str(details.get("value"))) * 100)
    except (InvalidOperation, TypeError, ValueError):
        raise PayPalError("PayPal returned an invalid captured amount.")
    if (
        details.get("status") != "COMPLETED"
        or details.get("currency") != "USD"
        or captured_cents != int(expected_cents or 0)
        or not details.get("transaction_id")
    ):
        raise PayPalError("PayPal payment confirmation did not match the order.")
    return details["transaction_id"]


@user_bp.route("/dashboard")
@login_required
def dashboard():
    guard = require_user()
    if guard:
        return guard
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.created_at.desc()).all()
    signups = {
        reg.event_id: reg
        for reg in EventRegistration.query.filter_by(user_id=current_user.id).all()
    }
    events = (
        Event.query.join(EventRegistration, EventRegistration.event_id == Event.id)
        .filter(
            EventRegistration.user_id == current_user.id,
            Event.event_date >= date.today(),
        )
        .order_by(Event.event_date.asc())
        .all()
    )
    form = EventSignupForm()
    form.car_id.choices = [(car.id, f"{car.car_year} {car.make} {car.model}") for car in cars]
    from .waiver_routes import get_required_waiver_status

    track_classes = (
        TrackDriverClass.query.join(Track, Track.id == TrackDriverClass.track_id)
        .filter(TrackDriverClass.user_id == current_user.id)
        .order_by(Track.name.asc())
        .all()
    )
    track_class_by_track_id = {item.track_id: item.driver_class for item in track_classes}

    waiver_by_event = {}
    slot_notice_by_event = {}
    slot_time_by_event = {}
    for event in events:
        status, waiver = get_required_waiver_status(event.track_id, current_user.id, event.id)
        waiver_by_event[event.id] = {"status": status, "waiver": waiver}
        driver_class = track_class_by_track_id.get(event.track_id, "C")
        slot = (
            EventClassSlot.query.filter_by(event_id=event.id, class_code=driver_class)
            .order_by(EventClassSlot.start_time.asc())
            .first()
        )
        if slot:
            slot_time_by_event[event.id] = slot.start_time.strftime('%I:%M %p').lstrip('0')
            now_dt = datetime.now()
            start_dt = datetime.combine(event.event_date, slot.start_time)
            end_dt = datetime.combine(event.event_date, slot.end_time)
            if start_dt - timedelta(minutes=15) <= now_dt < start_dt:
                slot_notice_by_event[event.id] = f"Your class ({driver_class}) starts at {slot.start_time.strftime('%I:%M %p').lstrip('0')}"
            elif start_dt <= now_dt <= end_dt:
                slot_notice_by_event[event.id] = f"Your class ({driver_class}) is active now"

    subscribed_track_ids = {
        item.track_id
        for item in TrackSubscription.query.filter_by(user_id=current_user.id).all()
    }
    selected_track_id = request.args.get("track_id", type=int)
    if selected_track_id is not None and selected_track_id not in subscribed_track_ids:
        selected_track_id = None
    subscribed_tracks = []
    if subscribed_track_ids:
        subscribed_tracks = (
            Track.query.filter(Track.id.in_(subscribed_track_ids))
            .order_by(Track.name.asc())
            .all()
        )
    subscribed_events = []
    if subscribed_track_ids:
        event_query = Event.query.filter(
            Event.track_id.in_(subscribed_track_ids),
            Event.event_date >= date.today(),
        )
        if selected_track_id:
            event_query = event_query.filter(Event.track_id == selected_track_id)
        subscribed_events = [
            event
            for event in event_query.order_by(Event.event_date.asc()).limit(24).all()
            if event.id not in signups
        ]
    driver_availability_by_event = {
        event.id: ticket_availability(event, "driver")
        for event in subscribed_events
    }

    waivers = []
    for item in waiver_by_event.values():
        if item.get("waiver"):
            waivers.append(item["waiver"])
    return render_template(
        "user/dashboard.html",
        cars=cars,
        events=events,
        signups=signups,
        signup_form=form,
        waiver_by_event=waiver_by_event,
        waivers=waivers,
        slot_notice_by_event=slot_notice_by_event,
        slot_time_by_event=slot_time_by_event,
        subscribed_events=subscribed_events,
        subscribed_tracks=subscribed_tracks,
        selected_track_id=selected_track_id,
        subscribed_track_ids=subscribed_track_ids,
        track_class_by_track_id=track_class_by_track_id,
        driver_availability_by_event=driver_availability_by_event,
    )


@user_bp.route("/events/<int:event_id>/spectator-tickets")
def spectator_tickets(event_id):
    event = Event.query.get_or_404(event_id)
    if event.event_date < date.today():
        flash("Spectator tickets are no longer available for this event.", "error")
        return redirect(url_for("user.spectator_events"))
    spectator_ticket_type = _get_or_create_default_ticket_type(event, "spectator")
    vendor_ticket_type = _get_or_create_default_ticket_type(event, "vendor")
    cart = _get_or_create_spectator_cart()
    availability = _event_ticket_availability(event)
    return render_template(
        "user/spectator_tickets.html",
        event=event,
        spectator_ticket_type=spectator_ticket_type,
        vendor_ticket_type=vendor_ticket_type,
        availability=availability,
        money=_money,
        cart_count=_cart_item_count(cart),
    )


@user_bp.route("/spectator/events")
def spectator_events():
    q = (request.args.get("q") or "").strip()
    query = Event.query.join(Track, Track.id == Event.track_id).filter(Event.event_date >= date.today())
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Event.event_name.ilike(like))
            | (Track.name.ilike(like))
            | (Track.city.ilike(like))
            | (Track.state.ilike(like))
        )
    events = query.order_by(Event.event_date.asc()).limit(60).all()
    ticket_types_by_event = {}
    availability_by_event = {}
    for event in events:
        ticket_types_by_event[event.id] = {
            "spectator": _get_or_create_default_ticket_type(event, "spectator"),
            "vendor": _get_or_create_default_ticket_type(event, "vendor"),
        }
        availability_by_event[event.id] = _event_ticket_availability(event)
    cart = _get_or_create_spectator_cart()
    return render_template(
        "user/spectator_events.html",
        events=events,
        q=q,
        ticket_types_by_event=ticket_types_by_event,
        availability_by_event=availability_by_event,
        money=_money,
        cart_count=_cart_item_count(cart),
    )


@user_bp.route("/spectator/cart/add", methods=["POST"])
def spectator_cart_add():
    event_id = request.form.get("event_id", type=int)
    ticket_type_id = request.form.get("ticket_type_id", type=int)
    quantity = request.form.get("quantity", type=int) or 1
    event = Event.query.get_or_404(event_id)
    if event.event_date < date.today():
        flash("Spectator tickets are no longer available for this event.", "error")
        return redirect(url_for("user.spectator_events"))
    if ticket_type_id:
        ticket_type = SpectatorTicketType.query.filter_by(
            id=ticket_type_id,
            event_id=event.id,
            is_active=True,
        ).first_or_404()
    else:
        ticket_type = _get_or_create_default_ticket_type(event, "spectator")
    purchase_limit, availability = _ticket_purchase_limit(event, ticket_type)
    if purchase_limit <= 0:
        flash(f"{ticket_type.name} is sold out for this event.", "error")
        return redirect(url_for("user.spectator_tickets", event_id=event.id))
    quantity = max(1, min(quantity, purchase_limit))
    cart = _get_or_create_spectator_cart()
    existing_items = SpectatorCartItem.query.filter_by(cart_id=cart.id).all()
    if existing_items and any(item.event.track_id != event.track_id for item in existing_items):
        flash("Cart currently holds tickets for another track. Please checkout or clear cart first.", "error")
        return redirect(url_for("user.spectator_cart"))
    existing = SpectatorCartItem.query.filter_by(
        cart_id=cart.id, event_id=event.id, ticket_type_id=ticket_type.id
    ).first()
    if existing:
        existing.quantity = min((existing.quantity or 0) + quantity, purchase_limit)
    else:
        db.session.add(
            SpectatorCartItem(
                cart_id=cart.id,
                event_id=event.id,
                ticket_type_id=ticket_type.id,
                quantity=quantity,
            )
        )
    db.session.commit()
    flash(f"Added {ticket_type.name} tickets to cart.", "success")
    return redirect(url_for("user.spectator_cart"))


@user_bp.route("/spectator/cart")
def spectator_cart():
    cart = _get_or_create_spectator_cart()
    items = SpectatorCartItem.query.filter_by(cart_id=cart.id).all()
    rows = []
    subtotal_cents = 0
    has_expired = False
    has_unavailable = False
    for item in items:
        unit = item.ticket_type.price_cents if item.ticket_type else 0
        line = unit * item.quantity
        subtotal_cents += line
        expired = item.event.event_date < date.today()
        has_expired = has_expired or expired
        max_qty, availability = _ticket_purchase_limit(item.event, item.ticket_type)
        has_unavailable = has_unavailable or max_qty <= 0 or item.quantity > max_qty
        rows.append(
            {
                "item": item,
                "unit": unit,
                "line": line,
                "expired": expired,
                "max_qty": max_qty,
                "availability": availability,
            }
        )
    return render_template(
        "user/spectator_cart.html",
        cart=cart,
        rows=rows,
        subtotal_cents=subtotal_cents,
        money=_money,
        cart_count=_cart_item_count(cart),
        has_expired=has_expired,
        has_unavailable=has_unavailable,
    )


@user_bp.route("/spectator/cart/update/<int:item_id>", methods=["POST"])
def spectator_cart_update(item_id):
    cart = _get_or_create_spectator_cart()
    item = SpectatorCartItem.query.filter_by(id=item_id, cart_id=cart.id).first_or_404()
    max_qty, availability = _ticket_purchase_limit(item.event, item.ticket_type)
    if max_qty <= 0:
        flash(f"{item.ticket_type.name} is now sold out.", "error")
        return redirect(url_for("user.spectator_cart"))
    qty = request.form.get("quantity", type=int) or 1
    item.quantity = max(1, min(qty, max_qty))
    db.session.commit()
    flash("Cart updated.", "success")
    return redirect(url_for("user.spectator_cart"))


@user_bp.route("/spectator/cart/remove/<int:item_id>", methods=["POST"])
def spectator_cart_remove(item_id):
    cart = _get_or_create_spectator_cart()
    item = SpectatorCartItem.query.filter_by(id=item_id, cart_id=cart.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("Removed item from cart.", "success")
    return redirect(url_for("user.spectator_cart"))


@user_bp.route("/spectator/checkout", methods=["GET", "POST"])
def spectator_checkout():
    cart = _get_or_create_spectator_cart()
    items = SpectatorCartItem.query.filter_by(cart_id=cart.id).all()
    if not items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("user.spectator_events"))
    if any(item.event.event_date < date.today() for item in items):
        flash("Remove expired event tickets before checkout.", "error")
        return redirect(url_for("user.spectator_cart"))
    if request.method == "POST":
        event_ids = sorted({item.event_id for item in items})
        Event.query.filter(Event.id.in_(event_ids)).order_by(Event.id.asc()).with_for_update().all()
    subtotal_cents = 0
    rows = []
    for item in items:
        max_qty, availability = _ticket_purchase_limit(item.event, item.ticket_type)
        if max_qty <= 0 or item.quantity > max_qty:
            label = item.ticket_type.name if item.ticket_type else "Tickets"
            remaining_label = availability["remaining"] if availability["remaining"] is not None else max_qty
            flash(
                f"Only {remaining_label} {label} ticket{'s are' if remaining_label != 1 else ' is'} still available. Update your cart to continue.",
                "error",
            )
            return redirect(url_for("user.spectator_cart"))
        unit = item.ticket_type.price_cents if item.ticket_type else 0
        line = unit * item.quantity
        subtotal_cents += line
        rows.append({"item": item, "unit": unit, "line": line})
    has_vendor_tickets = any(
        item.ticket_type and item.ticket_type.ticket_category == "vendor"
        for item in items
    )
    payment_track = items[0].event.track
    payment_choices = _configured_payment_choices(payment_track, subtotal_cents)
    if not payment_choices:
        flash("No payment methods are configured for this track yet.", "error")
        return redirect(url_for("user.spectator_cart"))

    form = SpectatorCheckoutForm()
    form.payment_method.choices = payment_choices
    if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user" and request.method == "GET":
        form.full_name.data = f"{current_user.first_name} {current_user.last_name}".strip()
        form.email.data = current_user.email
        form.phone.data = current_user.phone
    if request.method == "GET":
        form.payment_method.data = payment_choices[0][0]

    form_is_valid = form.validate_on_submit()
    vendor_business_name = (form.vendor_business_name.data or "").strip()
    if request.method == "POST" and form_is_valid and has_vendor_tickets and not vendor_business_name:
        flash("Business name is required for vendor admission.", "error")
        form_is_valid = False

    if form_is_valid:
        provider = form.payment_method.data
        payment_credentials = _payment_credentials(payment_track, provider)
        user_id = current_user.id if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user" else None
        buyer_name = form.full_name.data.strip()
        buyer_email = form.email.data.strip().lower()
        buyer_phone = form.phone.data.strip()
        if user_id:
            buyer_name = f"{current_user.first_name} {current_user.last_name}".strip()
            buyer_email = current_user.email
            buyer_phone = current_user.phone

        order = SpectatorOrder(
            order_number=f"SP-{secrets.token_hex(4).upper()}",
            user_id=user_id,
            guest_full_name=buyer_name,
            guest_email=buyer_email,
            guest_phone=buyer_phone,
            vendor_business_name=vendor_business_name if has_vendor_tickets else None,
            payment_method=provider,
            payment_mode=payment_credentials["mode"],
            payment_status="pending",
            status="pending",
            total_cents=subtotal_cents,
        )
        db.session.add(order)
        db.session.flush()
        for row in rows:
            item = row["item"]
            for _ in range(item.quantity):
                db.session.add(
                    SpectatorOrderItem(
                        order_id=order.id,
                        event_id=item.event_id,
                        ticket_type_name=item.ticket_type.name if item.ticket_type else "General Admission",
                        ticket_category=(
                            item.ticket_type.ticket_category
                            if item.ticket_type
                            else "spectator"
                        ),
                        unit_price_cents=row["unit"],
                        quantity=1,
                        line_total_cents=row["unit"],
                        qr_code=generate_ticket_code(),
                    )
                )
        db.session.flush()

        if provider == "stripe" and subtotal_cents > 0 and stripe and payment_credentials["secret_key"] and payment_credentials["webhook_secret"]:
            stripe.api_key = payment_credentials["secret_key"]
            success_url = url_for("user.spectator_order_success", order_id=order.id, _external=True)
            cancel_url = url_for("user.spectator_checkout", _external=True)
            checkout_session = create_stripe_checkout_session(
                stripe,
                order,
                rows,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            order.provider_session_id = checkout_session.id
            db.session.commit()
            return redirect(checkout_session.url)

        if provider == "stripe" and subtotal_cents > 0:
            db.session.rollback()
            flash("Stripe payments are not configured for this track yet.", "error")
            return redirect(url_for("user.spectator_checkout"))

        if provider == "paypal" and subtotal_cents > 0:
            if not (
                payment_credentials["public_key"]
                and payment_credentials["secret_key"]
                and payment_credentials["webhook_secret"]
            ):
                db.session.rollback()
                flash("PayPal payments are not configured for this track yet.", "error")
                return redirect(url_for("user.spectator_checkout"))
            try:
                paypal_order, approve_url = create_paypal_order(
                    payment_credentials,
                    subtotal_cents,
                    f"Event tickets - {payment_track.name}",
                    f"spectator:{order.id}",
                    url_for("user.spectator_paypal_return", order_id=order.id, _external=True),
                    url_for("user.spectator_checkout", _external=True),
                    f"spectator-create-{order.id}",
                )
                order.provider_session_id = paypal_order["id"]
                db.session.commit()
                return redirect(approve_url)
            except PayPalError:
                current_app.logger.exception("PayPal spectator checkout creation failed")
                db.session.rollback()
                flash("PayPal could not start checkout. Please try again.", "error")
                return redirect(url_for("user.spectator_checkout"))

        if subtotal_cents > 0:
            db.session.rollback()
            flash("That payment provider cannot confirm online payments yet.", "error")
            return redirect(url_for("user.spectator_checkout"))

        # Free orders do not require an online gateway confirmation.
        order.payment_status = "paid"
        order.status = "recorded"
        mark_order_paid(order)
        for row in rows:
            item = row["item"]
            db.session.add(
                SpectatorTicketOrder(
                    event_id=item.event_id,
                    user_id=user_id,
                    buyer_type="user" if user_id else "guest",
                    guest_full_name=buyer_name,
                    guest_email=buyer_email,
                    guest_phone=buyer_phone,
                    quantity=item.quantity,
                    payment_method=provider,
                    ticket_category=(
                        item.ticket_type.ticket_category
                        if item.ticket_type
                        else "spectator"
                    ),
                    status="recorded",
                )
            )
            db.session.delete(item)
        db.session.commit()
        _safe_send_email(send_spectator_order_receipt, order)
        flash(f"Order {order.order_number} recorded successfully.", "success")
        return redirect(url_for("user.spectator_order_success", order_id=order.id))

    return render_template(
        "user/spectator_checkout.html",
        form=form,
        rows=rows,
        subtotal_cents=subtotal_cents,
        money=_money,
        cart_count=_cart_item_count(cart),
        has_vendor_tickets=has_vendor_tickets,
    )


@user_bp.route("/spectator/order/<int:order_id>")
def spectator_order_success(order_id):
    order = SpectatorOrder.query.get_or_404(order_id)
    items = SpectatorOrderItem.query.filter_by(order_id=order.id).all()
    return render_template("user/spectator_order_success.html", order=order, items=items, money=_money)


@user_bp.route("/payments/stripe/webhook", methods=["POST"])
def stripe_webhook():
    if not stripe:
        return "ignored", 200
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        payload_data = json.loads(payload.decode("utf-8"))
        session_id = ((payload_data.get("data") or {}).get("object") or {}).get("id")
    except Exception:
        session_id = None
    if not session_id:
        return "invalid", 400
    order = SpectatorOrder.query.filter_by(provider_session_id=session_id).first()
    driver_ticket_order = None
    if not order:
        driver_ticket_order = DriverTicketOrder.query.filter_by(provider_session_id=session_id).first()
    if not order and not driver_ticket_order:
        return "ok", 200
    if order:
        payment_track = order.items[0].event.track if order.items else None
        webhook_secret = (
            _payment_credentials(payment_track, "stripe", mode=order.payment_mode)["webhook_secret"]
            if payment_track
            else None
        )
    else:
        webhook_secret = _payment_credentials(
            driver_ticket_order.event.track,
            "stripe",
            mode=driver_ticket_order.payment_mode,
        )["webhook_secret"]
    if not webhook_secret:
        return "ignored", 200
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret,
        )
    except Exception:
        return "invalid", 400

    if event.get("type") in {"checkout.session.async_payment_failed", "checkout.session.expired"}:
        target = order or driver_ticket_order
        if target.payment_status != "paid":
            target.payment_status = "failed"
            target.status = "failed"
            target.failure_reason = (
                "Stripe payment failed."
                if event.get("type") == "checkout.session.async_payment_failed"
                else "Stripe checkout expired before payment."
            )
            db.session.commit()
        return "ok", 200

    if event.get("type") in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        session_obj = event["data"]["object"]
        session_id = session_obj.get("id")
        target = order or driver_ticket_order
        expected_cents = order.total_cents if order else driver_ticket_order.amount_cents
        if (
            session_obj.get("payment_status") != "paid"
            or session_obj.get("currency", "").lower() != "usd"
            or int(session_obj.get("amount_total") or -1) != int(expected_cents or 0)
        ):
            current_app.logger.warning(
                "Ignored unconfirmed or mismatched Stripe checkout session %s for %s order %s",
                session_id,
                "spectator" if order else "driver",
                target.id,
            )
            return "ok", 200
        if order and order.payment_status != "paid":
            _finalize_spectator_order(order, transaction_id=session_obj.get("payment_intent"))
        elif driver_ticket_order and driver_ticket_order.payment_status != "paid":
            _finalize_driver_ticket_order(
                driver_ticket_order,
                transaction_id=session_obj.get("payment_intent"),
            )
    return "ok", 200


@user_bp.route("/payments/paypal/spectator/<int:order_id>/return")
def spectator_paypal_return(order_id):
    order = SpectatorOrder.query.get_or_404(order_id)
    paypal_order_id = request.args.get("token", "").strip()
    if order.payment_method != "paypal" or not paypal_order_id or paypal_order_id != order.provider_session_id:
        flash("PayPal could not confirm this order.", "error")
        return redirect(url_for("user.spectator_checkout"))
    if order.payment_status == "paid":
        return redirect(url_for("user.spectator_order_success", order_id=order.id))
    if not reservation_is_active(order):
        event_ids = sorted({item.event_id for item in order.items})
        Event.query.filter(Event.id.in_(event_ids)).order_by(Event.id.asc()).with_for_update().all()
        if not spectator_order_fits_capacity(order):
            order.payment_status = "failed"
            order.status = "failed"
            order.failure_reason = "Ticket capacity was reached before PayPal payment approval."
            db.session.commit()
            flash("Those tickets sold out before PayPal approval. Your payment was not captured.", "error")
            return redirect(url_for("user.spectator_order_success", order_id=order.id))
    credentials = _paypal_credentials_for_order(spectator_order=order)
    try:
        captured = capture_paypal_order(
            credentials,
            paypal_order_id,
            f"spectator-capture-{order.id}",
        )
        transaction_id = _validated_paypal_capture(
            paypal_capture_details(captured),
            order.total_cents,
        )
        _finalize_spectator_order(order, transaction_id=transaction_id)
    except (PayPalError, TypeError, KeyError):
        current_app.logger.exception("PayPal spectator capture failed for order %s", order.id)
        flash("PayPal is still processing this payment. Please check again shortly.", "error")
        return redirect(url_for("user.spectator_order_success", order_id=order.id))
    flash(f"Order {order.order_number} paid successfully.", "success")
    return redirect(url_for("user.spectator_order_success", order_id=order.id))


@user_bp.route("/payments/paypal/driver/<int:order_id>/return")
@login_required
def driver_paypal_return(order_id):
    guard = require_user()
    if guard:
        return guard
    order = DriverTicketOrder.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    paypal_order_id = request.args.get("token", "").strip()
    if order.payment_method != "paypal" or not paypal_order_id or paypal_order_id != order.provider_session_id:
        flash("PayPal could not confirm this order.", "error")
        return redirect(url_for("user.driver_event_checkout", event_id=order.event_id))
    if order.payment_status != "paid":
        if not reservation_is_active(order):
            Event.query.filter_by(id=order.event_id).with_for_update().one()
            if not driver_order_fits_capacity(order):
                order.payment_status = "failed"
                order.status = "failed"
                order.failure_reason = "Driver capacity was reached before PayPal payment approval."
                db.session.commit()
                flash("Driver tickets sold out before PayPal approval. Your payment was not captured.", "error")
                return redirect(url_for("user.dashboard"))
        credentials = _paypal_credentials_for_order(driver_ticket_order=order)
        try:
            captured = capture_paypal_order(
                credentials,
                paypal_order_id,
                f"driver-capture-{order.id}",
            )
            transaction_id = _validated_paypal_capture(
                paypal_capture_details(captured),
                order.amount_cents,
            )
            _finalize_driver_ticket_order(order, transaction_id=transaction_id)
        except (PayPalError, TypeError, KeyError):
            current_app.logger.exception("PayPal driver capture failed for order %s", order.id)
            flash("PayPal is still processing this payment. Please check again shortly.", "error")
            return redirect(url_for("user.driver_event_checkout_success", order_id=order.id))
    return redirect(url_for("user.driver_event_checkout_success", order_id=order.id))


@user_bp.route("/payments/paypal/webhook", methods=["POST"])
def paypal_webhook():
    event = request.get_json(silent=True) or {}
    event_type = event.get("event_type", "")
    resource = event.get("resource") or {}
    if event_type == "CHECKOUT.ORDER.APPROVED":
        paypal_order_id = resource.get("id")
    else:
        paypal_order_id = (
            ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
        )
    if not paypal_order_id:
        return "ok", 200

    spectator_order = SpectatorOrder.query.filter_by(
        provider_session_id=paypal_order_id,
        payment_method="paypal",
    ).first()
    driver_ticket_order = None
    if not spectator_order:
        driver_ticket_order = DriverTicketOrder.query.filter_by(
            provider_session_id=paypal_order_id,
            payment_method="paypal",
        ).first()
    if not spectator_order and not driver_ticket_order:
        return "ok", 200

    credentials = _paypal_credentials_for_order(
        spectator_order=spectator_order,
        driver_ticket_order=driver_ticket_order,
    )
    if not credentials or not credentials.get("webhook_secret"):
        return "ignored", 200
    try:
        verified = verify_paypal_webhook_signature(
            credentials,
            credentials["webhook_secret"],
            request.headers,
            event,
        )
    except PayPalError:
        current_app.logger.exception("PayPal webhook verification request failed")
        return "retry", 500
    if not verified:
        return "invalid", 400

    try:
        if event_type == "CHECKOUT.ORDER.APPROVED":
            target = spectator_order or driver_ticket_order
            if not reservation_is_active(target):
                if spectator_order:
                    event_ids = sorted({item.event_id for item in spectator_order.items})
                    Event.query.filter(Event.id.in_(event_ids)).order_by(Event.id.asc()).with_for_update().all()
                    capacity_available = spectator_order_fits_capacity(spectator_order)
                else:
                    Event.query.filter_by(id=driver_ticket_order.event_id).with_for_update().one()
                    capacity_available = driver_order_fits_capacity(driver_ticket_order)
                if not capacity_available:
                    target.payment_status = "failed"
                    target.status = "failed"
                    target.failure_reason = "Ticket capacity was reached before PayPal payment approval."
                    db.session.commit()
                    return "ok", 200
            captured = capture_paypal_order(
                credentials,
                paypal_order_id,
                (
                    f"spectator-capture-{spectator_order.id}"
                    if spectator_order
                    else f"driver-capture-{driver_ticket_order.id}"
                ),
            )
            details = paypal_capture_details(captured)
        elif event_type == "PAYMENT.CAPTURE.COMPLETED":
            amount = resource.get("amount") or {}
            details = {
                "status": resource.get("status"),
                "transaction_id": resource.get("id"),
                "currency": amount.get("currency_code"),
                "value": amount.get("value"),
            }
        elif event_type == "PAYMENT.CAPTURE.DENIED":
            target = spectator_order or driver_ticket_order
            if target.payment_status != "paid":
                target.payment_status = "failed"
                target.failure_reason = "PayPal declined the payment capture."
                db.session.commit()
            return "ok", 200
        else:
            return "ok", 200

        target = spectator_order or driver_ticket_order
        expected_cents = spectator_order.total_cents if spectator_order else driver_ticket_order.amount_cents
        transaction_id = _validated_paypal_capture(details, expected_cents)
        if spectator_order:
            _finalize_spectator_order(spectator_order, transaction_id=transaction_id)
        else:
            _finalize_driver_ticket_order(driver_ticket_order, transaction_id=transaction_id)
    except PayPalError:
        current_app.logger.exception("PayPal webhook processing failed for order %s", paypal_order_id)
        return "retry", 500
    return "ok", 200


@user_bp.route("/events/<int:event_id>/schedule")
@login_required
def event_schedule(event_id):
    guard = require_user()
    if guard:
        return guard
    event = Event.query.get_or_404(event_id)
    reg = EventRegistration.query.filter_by(event_id=event.id, user_id=current_user.id).first_or_404()
    track_class = (
        TrackDriverClass.query.filter_by(track_id=event.track_id, user_id=current_user.id).first()
    )
    driver_class = track_class.driver_class if track_class else "C"
    slots = (
        EventClassSlot.query.filter_by(event_id=event.id)
        .order_by(EventClassSlot.start_time.asc())
        .all()
    )

    notice = None
    my_slot = None
    for slot in slots:
        if slot.class_code == driver_class and my_slot is None:
            my_slot = slot
    if my_slot:
        now_dt = datetime.now()
        start_dt = datetime.combine(event.event_date, my_slot.start_time)
        end_dt = datetime.combine(event.event_date, my_slot.end_time)
        if start_dt - timedelta(minutes=15) <= now_dt < start_dt:
            notice = f"Heads up: your class ({driver_class}) starts at {my_slot.start_time.strftime('%I:%M %p').lstrip('0')}"
        elif start_dt <= now_dt <= end_dt:
            notice = f"You're up now. Class {driver_class} is currently running."

    return render_template(
        "user/event_schedule.html",
        event=event,
        registration=reg,
        slots=slots,
        driver_class=driver_class,
        notice=notice,
    )


@user_bp.route("/profile-photo", methods=["POST"])
@login_required
def update_profile_photo():
    guard = require_user()
    if guard:
        return guard

    upload = request.files.get("profile_image")
    if not upload or not getattr(upload, "filename", ""):
        flash("Please select an image to upload.", "error")
        return redirect(url_for("user.dashboard"))

    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        flash("Profile image must be jpg, jpeg, png, or webp.", "error")
        return redirect(url_for("user.dashboard"))

    upload.filename = secure_filename(upload.filename)
    current_user.profile_image_url = upload_public_image(
        upload,
        bucket=current_app.config["S3_BUCKET"],
        endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
        access_key=current_app.config["S3_ACCESS_KEY"],
        secret_key=current_app.config["S3_SECRET_KEY"],
        key_prefix=f"profiles/{current_user.id}",
    )
    db.session.commit()
    flash("Profile photo updated.", "success")
    return redirect(url_for("user.dashboard"))


@user_bp.route("/tracks")
@login_required
def tracks_directory():
    guard = require_user()
    if guard:
        return guard
    q = (request.args.get("q") or "").strip()
    query = Track.query
    if q:
        like = f"%{q}%"
        query = query.filter((Track.name.ilike(like)) | (Track.city.ilike(like)) | (Track.state.ilike(like)))
    tracks = query.order_by(Track.name.asc()).all()
    subscribed_track_ids = {
        item.track_id
        for item in TrackSubscription.query.filter_by(user_id=current_user.id).all()
    }
    return render_template(
        "user/tracks.html",
        tracks=tracks,
        q=q,
        subscribed_track_ids=subscribed_track_ids,
    )


@user_bp.route("/tracks/<int:track_id>/subscribe", methods=["POST"])
@login_required
def subscribe_track(track_id):
    guard = require_user()
    if guard:
        return guard
    Track.query.get_or_404(track_id)
    existing = TrackSubscription.query.filter_by(track_id=track_id, user_id=current_user.id).first()
    if not existing:
        db.session.add(TrackSubscription(track_id=track_id, user_id=current_user.id))
        track_class = TrackDriverClass.query.filter_by(track_id=track_id, user_id=current_user.id).first()
        if not track_class:
            db.session.add(TrackDriverClass(track_id=track_id, user_id=current_user.id, driver_class="C"))
        db.session.commit()
        flash("Track subscribed.", "success")
    return redirect(url_for("user.tracks_directory"))


@user_bp.route("/tracks/<int:track_id>/unsubscribe", methods=["POST"])
@login_required
def unsubscribe_track(track_id):
    guard = require_user()
    if guard:
        return guard
    existing = TrackSubscription.query.filter_by(track_id=track_id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash("Track unsubscribed.", "success")
    return redirect(url_for("user.tracks_directory"))


@user_bp.route("/community")
@login_required
def community():
    guard = require_user()
    if guard:
        return guard
    posts = SocialPost.query.order_by(SocialPost.created_at.desc()).limit(100).all()
    cars = Car.query.order_by(Car.created_at.desc()).limit(100).all()
    events = Event.query.order_by(Event.event_date.asc()).limit(24).all()
    events = [event for event in events if event.event_date >= date.today()]
    event_signup_counts = {
        event.id: EventRegistration.query.filter_by(event_id=event.id).count() for event in events
    }
    driver_availability_by_event = {
        event.id: ticket_availability(event, "driver") for event in events
    }
    user_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.created_at.desc()).all()
    signups = {
        reg.event_id: reg
        for reg in EventRegistration.query.filter_by(user_id=current_user.id).all()
    }
    signup_form = EventSignupForm()
    signup_form.car_id.choices = [
        (car.id, f"{car.car_year} {car.make} {car.model}") for car in user_cars
    ]
    comment_form = SocialCommentForm()
    return render_template(
        "user/community.html",
        posts=posts,
        cars=cars,
        events=events,
        event_signup_counts=event_signup_counts,
        driver_availability_by_event=driver_availability_by_event,
        signups=signups,
        signup_form=signup_form,
        comment_form=comment_form,
    )


@user_bp.route("/cars/new", methods=["GET", "POST"])
@login_required
def car_new():
    guard = require_user()
    if guard:
        return guard
    form = CarForm()
    if form.validate_on_submit():
        if not form.car_year.data.isdigit():
            flash("Car year must be numeric.", "error")
            return render_template("user/car_form.html", form=form, title="Add Car", car=None)
        car = Car(
            user_id=current_user.id,
            make=form.make.data.strip(),
            model=form.model.data.strip(),
            car_year=int(form.car_year.data),
            color=form.color.data.strip() if form.color.data else None,
            static_qr_code=_generate_car_qr_code(),
        )
        upload = form.image.data
        if upload and getattr(upload, "filename", ""):
            upload.filename = secure_filename(upload.filename)
            car.image_url = upload_public_image(
            upload,
            bucket=current_app.config["S3_BUCKET"],
                endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
                access_key=current_app.config["S3_ACCESS_KEY"],
                secret_key=current_app.config["S3_SECRET_KEY"],
                key_prefix=f"cars/{current_user.id}",
            )
        db.session.add(car)
        db.session.commit()
        post = SocialPost(
            user_id=current_user.id,
            post_type="car_spotlight",
            title=f"@{current_user.username} added a car",
            body=f"{car.car_year} {car.make} {car.model}" + (f" ({car.color})" if car.color else ""),
        )
        db.session.add(post)
        db.session.commit()
        flash("Car added.", "success")
        return redirect(url_for("user.dashboard"))
    return render_template("user/car_form.html", form=form, title="Add Car", car=None)


@user_bp.route("/cars/<int:car_id>/edit", methods=["GET", "POST"])
@login_required
def car_edit(car_id):
    guard = require_user()
    if guard:
        return guard
    car = Car.query.filter_by(id=car_id, user_id=current_user.id).first_or_404()
    form = CarForm(obj=car)
    if form.validate_on_submit():
        if not form.car_year.data.isdigit():
            flash("Car year must be numeric.", "error")
            return render_template("user/car_form.html", form=form, title="Edit Car", car=car)
        car.make = form.make.data.strip()
        car.model = form.model.data.strip()
        car.car_year = int(form.car_year.data)
        car.color = form.color.data.strip() if form.color.data else None
        upload = form.image.data
        if upload and getattr(upload, "filename", ""):
            upload.filename = secure_filename(upload.filename)
            car.image_url = upload_public_image(
            upload,
            bucket=current_app.config["S3_BUCKET"],
                endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
                access_key=current_app.config["S3_ACCESS_KEY"],
                secret_key=current_app.config["S3_SECRET_KEY"],
                key_prefix=f"cars/{current_user.id}",
            )
        db.session.commit()
        flash("Car updated.", "success")
        return redirect(url_for("user.dashboard"))
    return render_template("user/car_form.html", form=form, title="Edit Car", car=car)


@user_bp.route("/cars/<int:car_id>/delete", methods=["POST"])
@login_required
def car_delete(car_id):
    guard = require_user()
    if guard:
        return guard
    car = Car.query.filter_by(id=car_id, user_id=current_user.id).first_or_404()
    in_use = EventRegistration.query.filter_by(car_id=car.id).first()
    if in_use:
        flash("Car cannot be deleted while used in an event signup.", "error")
        return redirect(url_for("user.dashboard"))
    db.session.delete(car)
    db.session.commit()
    flash("Car deleted.", "success")
    return redirect(url_for("user.dashboard"))


@user_bp.route("/events/<int:event_id>/signup", methods=["POST"])
@login_required
def signup_event(event_id):
    guard = require_user()
    if guard:
        return guard
    event = Event.query.get_or_404(event_id)
    if event.event_date < date.today():
        flash("Cannot sign up for past events.", "error")
        return redirect(url_for("user.dashboard"))
    if driver_already_has_ticket(event.id, current_user.id):
        flash("You already have a driver ticket for this event. Each driver may purchase only one.", "error")
        return redirect(url_for("user.dashboard"))
    if driver_payment_in_progress(event.id, current_user.id):
        flash("A driver ticket payment is already in progress for this event. Your spot is being held for up to 35 minutes.", "error")
        return redirect(url_for("user.dashboard"))
    availability = ticket_availability(event, "driver")
    if availability["sold_out"]:
        flash("Driver tickets are sold out for this event.", "error")
        return redirect(url_for("user.dashboard"))

    form = EventSignupForm()
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.created_at.desc()).all()
    form.car_id.choices = [(car.id, f"{car.car_year} {car.make} {car.model}") for car in cars]
    if not cars:
        flash("Add a car before signing up.", "error")
        return redirect(url_for("user.car_new"))
    if form.validate_on_submit():
        selected_car = Car.query.filter_by(id=form.car_id.data, user_id=current_user.id).first()
        if not selected_car:
            flash("Invalid car selected.", "error")
            return redirect(url_for("user.dashboard"))
        session[f"driver_checkout_car_{event.id}"] = selected_car.id
        return redirect(url_for("user.driver_event_checkout", event_id=event.id))
    else:
        flash("Please choose a valid car.", "error")
    return redirect(url_for("user.dashboard"))


@user_bp.route("/events/<int:event_id>/driver-checkout", methods=["GET", "POST"])
@login_required
def driver_event_checkout(event_id):
    guard = require_user()
    if guard:
        return guard
    event = Event.query.get_or_404(event_id)
    if event.event_date < date.today():
        flash("Cannot sign up for past events.", "error")
        return redirect(url_for("user.dashboard"))
    if request.method == "POST":
        event = Event.query.filter_by(id=event.id).with_for_update().one()
    if driver_already_has_ticket(event.id, current_user.id):
        flash("You already have a driver ticket for this event. Each driver may purchase only one.", "error")
        return redirect(url_for("user.dashboard"))
    if driver_payment_in_progress(event.id, current_user.id):
        flash("A driver ticket payment is already in progress for this event. Your spot is being held for up to 35 minutes.", "error")
        return redirect(url_for("user.dashboard"))
    availability = ticket_availability(event, "driver")
    if availability["sold_out"]:
        flash("Driver tickets are sold out for this event.", "error")
        return redirect(url_for("user.dashboard"))

    car_id = session.get(f"driver_checkout_car_{event.id}")
    selected_car = Car.query.filter_by(id=car_id, user_id=current_user.id).first() if car_id else None
    if not selected_car:
        flash("Choose a car before checkout.", "error")
        return redirect(url_for("user.dashboard"))

    driver_amount_cents = max(0, event.driver_price_cents or 0)
    payment_choices = _configured_payment_choices(event.track, driver_amount_cents)
    if not payment_choices:
        flash("No payment methods are configured for this track yet.", "error")
        return redirect(url_for("user.dashboard"))

    form = DriverCheckoutForm()
    form.payment_method.choices = payment_choices
    if request.method == "GET":
        form.full_name.data = f"{current_user.first_name} {current_user.last_name}".strip()
        form.email.data = current_user.email
        form.phone.data = current_user.phone
        form.payment_method.data = payment_choices[0][0]

    if form.validate_on_submit():
        if driver_already_has_ticket(event.id, current_user.id):
            flash("You already have a driver ticket for this event. Each driver may purchase only one.", "error")
            return redirect(url_for("user.dashboard"))
        availability = ticket_availability(event, "driver")
        if availability["sold_out"]:
            flash("The final driver ticket was just purchased. This event is now sold out for drivers.", "error")
            return redirect(url_for("user.dashboard"))
        payment_credentials = _payment_credentials(event.track, form.payment_method.data)
        driver_ticket_order = DriverTicketOrder(
            event_id=event.id,
            user_id=current_user.id,
            car_id=selected_car.id,
            amount_cents=max(0, event.driver_price_cents or 0),
            payment_method=form.payment_method.data,
            payment_mode=payment_credentials["mode"],
            payment_status="pending",
            status="pending",
        )
        db.session.add(driver_ticket_order)
        db.session.flush()

        if form.payment_method.data == "stripe" and driver_amount_cents > 0 and stripe and payment_credentials["secret_key"] and payment_credentials["webhook_secret"]:
            stripe.api_key = payment_credentials["secret_key"]
            checkout_session = create_driver_stripe_checkout_session(
                stripe,
                driver_ticket_order,
                success_url=url_for(
                    "user.driver_event_checkout_success",
                    order_id=driver_ticket_order.id,
                    _external=True,
                ),
                cancel_url=url_for("user.driver_event_checkout", event_id=event.id, _external=True),
            )
            driver_ticket_order.provider_session_id = checkout_session.id
            db.session.commit()
            return redirect(checkout_session.url)

        if form.payment_method.data == "stripe" and driver_amount_cents > 0:
            db.session.rollback()
            flash("Stripe payments are not configured for this track yet.", "error")
            return redirect(url_for("user.driver_event_checkout", event_id=event.id))

        if form.payment_method.data == "paypal" and driver_amount_cents > 0:
            if not (
                payment_credentials["public_key"]
                and payment_credentials["secret_key"]
                and payment_credentials["webhook_secret"]
            ):
                db.session.rollback()
                flash("PayPal payments are not configured for this track yet.", "error")
                return redirect(url_for("user.driver_event_checkout", event_id=event.id))
            try:
                paypal_order, approve_url = create_paypal_order(
                    payment_credentials,
                    driver_amount_cents,
                    f"Driver ticket - {event.event_name}",
                    f"driver:{driver_ticket_order.id}",
                    url_for(
                        "user.driver_paypal_return",
                        order_id=driver_ticket_order.id,
                        _external=True,
                    ),
                    url_for("user.driver_event_checkout", event_id=event.id, _external=True),
                    f"driver-create-{driver_ticket_order.id}",
                )
                driver_ticket_order.provider_session_id = paypal_order["id"]
                db.session.commit()
                return redirect(approve_url)
            except PayPalError:
                current_app.logger.exception("PayPal driver checkout creation failed")
                db.session.rollback()
                flash("PayPal could not start checkout. Please try again.", "error")
                return redirect(url_for("user.driver_event_checkout", event_id=event.id))

        if driver_amount_cents > 0:
            db.session.rollback()
            flash("That payment provider cannot confirm online payments yet.", "error")
            return redirect(url_for("user.driver_event_checkout", event_id=event.id))

        needs_waiver_action, created_waiver_id = _finalize_driver_ticket_order(driver_ticket_order)
        session.pop(f"driver_checkout_car_{event.id}", None)
        if needs_waiver_action and created_waiver_id:
            flash("Ticket purchased. Next step: sign waiver.", "success")
            return redirect(url_for("waiver.driver_sign_waiver", driver_waiver_id=created_waiver_id))

        flash("Ticket purchased. Waiver on file. Next step: inspection.", "success")
        return redirect(url_for("waiver.driver_waivers"))

    return render_template(
        "user/driver_event_checkout.html",
        form=form,
        event=event,
        selected_car=selected_car,
        amount_cents=driver_amount_cents,
        payment_choices=payment_choices,
        availability=availability,
    )


@user_bp.route("/driver/orders/<int:order_id>/success")
@login_required
def driver_event_checkout_success(order_id):
    guard = require_user()
    if guard:
        return guard
    driver_ticket_order = DriverTicketOrder.query.filter_by(
        id=order_id,
        user_id=current_user.id,
    ).first_or_404()
    session.pop(f"driver_checkout_car_{driver_ticket_order.event_id}", None)
    if driver_ticket_order.payment_status != "paid":
        flash("Payment is processing. Your signup will unlock as soon as payment is confirmed.", "success")
        return redirect(url_for("user.dashboard"))

    needs_waiver_action, created_waiver_id = _create_driver_post_purchase_steps(driver_ticket_order)
    db.session.commit()
    if needs_waiver_action and created_waiver_id:
        flash("Ticket purchased. Next step: sign waiver.", "success")
        return redirect(url_for("waiver.driver_sign_waiver", driver_waiver_id=created_waiver_id))

    flash("Ticket purchased. Waiver on file. Next step: inspection.", "success")
    return redirect(url_for("waiver.driver_waivers"))


@user_bp.route("/events/<int:event_id>/cancel", methods=["POST"])
@login_required
def cancel_signup(event_id):
    guard = require_user()
    if guard:
        return guard
    reg = EventRegistration.query.filter_by(event_id=event_id, user_id=current_user.id).first_or_404()
    post = SocialPost.query.filter_by(event_registration_id=reg.id).first()
    if post:
        db.session.delete(post)
    db.session.delete(reg)
    db.session.commit()
    flash("Signup canceled.", "success")
    return redirect(url_for("user.dashboard"))


@user_bp.route("/community/posts/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    guard = require_user()
    if guard:
        return guard
    post = SocialPost.query.get_or_404(post_id)
    form = SocialCommentForm()
    if form.validate_on_submit():
        comment = SocialComment(
            post_id=post.id,
            user_id=current_user.id,
            body=form.body.data.strip(),
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comment added.", "success")
    else:
        flash("Comment is required.", "error")
    return redirect(url_for("user.community"))
