import secrets
import os
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash

from .forms import CarForm, DriverCheckoutForm, EventSignupForm, SocialCommentForm, SpectatorCheckoutForm
from .models import (
    Car,
    Event,
    EventClassSlot,
    DriverTicketOrder,
    EventRegistration,
    PrivateRentalBooking,
    PrivateRentalSlot,
    RfidTag,
    RfidTagCartItem,
    RfidTagOrder,
    RfidTagOrderItem,
    RfidTagSettings,
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
    TrackRun,
    TrackRunVote,
    TrackWaiverTemplate,
    User,
    VendorAccount,
    db,
)
from .services.storage_service import upload_public_image
from .services.email_service import send_driver_purchase_receipt, send_private_rental_confirmation, send_spectator_order_receipt
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
    create_private_rental_stripe_checkout_session,
    create_stripe_checkout_session,
    mark_driver_ticket_paid,
    mark_private_rental_paid,
    mark_order_paid,
    payment_is_confirmed,
    paypal_capture_details,
    verify_paypal_webhook_signature,
)
from .services.rental_service import (
    BOOKING_HOLD_MINUTES,
    active_bookings_by_slot,
    booking_is_active,
    rental_month_context,
)
from .services.ticket_service import (
    code_qr_png,
    ensure_order_ticket_codes,
    generate_driver_ticket_code,
    generate_ticket_code,
)

try:
    import stripe
except Exception:  # pragma: no cover
    stripe = None


user_bp = Blueprint("user", __name__, url_prefix="/user")


@user_bp.route("/rfid-tags", methods=["GET", "POST"])
@login_required
def rfid_tags():
    guard = require_user()
    if guard:
        return guard
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.created_at.desc()).all()
    if request.method == "POST":
        serial = (request.form.get("serial") or "").strip().upper()
        code = (request.form.get("activation_code") or "").strip().upper()
        try:
            car_id = int(request.form.get("car_id") or 0)
        except ValueError:
            car_id = 0
        car = Car.query.filter_by(id=car_id, user_id=current_user.id).first()
        tag = RfidTag.query.filter_by(public_serial=serial).first()
        if not car:
            flash("Choose one of your cars.", "error")
        elif not tag or tag.status != "inventory" or not check_password_hash(tag.activation_code_hash, code):
            flash("That tag serial or activation code is invalid.", "error")
        else:
            tag.car_id = car.id
            tag.activated_by_user_id = current_user.id
            tag.activated_at = datetime.utcnow()
            tag.status = "active"
            db.session.commit()
            flash("RFID tag activated and assigned to your car.", "success")
            return redirect(url_for("user.rfid_tags"))
    tags = RfidTag.query.filter_by(activated_by_user_id=current_user.id).order_by(RfidTag.activated_at.desc()).all()
    settings = RfidTagSettings.query.get(1)
    if not settings:
        settings = RfidTagSettings(id=1, price_cents=0)
        db.session.add(settings)
        db.session.commit()
    ordered_car_ids = {
        item.car_id for item in RfidTagOrderItem.query.join(RfidTagOrder).filter(
            RfidTagOrder.user_id == current_user.id,
            RfidTagOrder.fulfillment_status != "cancelled",
        ).all()
    }
    return render_template("user/rfid_tags.html", cars=cars, tags=tags, settings=settings,
                           ordered_car_ids=ordered_car_ids, money=_money)


@user_bp.route("/rfid-tags/cart/add/<int:car_id>", methods=["POST"])
@login_required
def rfid_tag_cart_add(car_id):
    guard = require_user()
    if guard:
        return guard
    car = Car.query.filter_by(id=car_id, user_id=current_user.id).first_or_404()
    if RfidTag.query.filter_by(car_id=car.id, status="active").first():
        flash("That car already has an active RFID tag.", "error")
        return redirect(url_for("user.rfid_tags"))
    existing_order = RfidTagOrderItem.query.join(RfidTagOrder).filter(
        RfidTagOrderItem.car_id == car.id,
        RfidTagOrder.user_id == current_user.id,
        RfidTagOrder.fulfillment_status != "cancelled",
    ).first()
    if existing_order:
        flash("A tag has already been ordered for that car.", "error")
        return redirect(url_for("user.rfid_tags"))
    cart = _get_or_create_spectator_cart()
    if not RfidTagCartItem.query.filter_by(cart_id=cart.id, car_id=car.id).first():
        db.session.add(RfidTagCartItem(cart_id=cart.id, car_id=car.id))
        db.session.commit()
    flash("RFID tag added to your cart.", "success")
    return redirect(url_for("user.spectator_cart"))


@user_bp.route("/rfid-tags/cart/remove/<int:item_id>", methods=["POST"])
@login_required
def rfid_tag_cart_remove(item_id):
    guard = require_user()
    if guard:
        return guard
    cart = _get_or_create_spectator_cart()
    item = RfidTagCartItem.query.filter_by(id=item_id, cart_id=cart.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("RFID tag removed from your cart.", "success")
    return redirect(url_for("user.spectator_cart"))


def _mark_rfid_tag_order_paid(order, transaction_id=None):
    order.payment_status = "paid"
    order.provider_transaction_id = transaction_id
    order.paid_at = order.paid_at or datetime.utcnow()
    db.session.commit()


def _rfid_paypal_credentials():
    return {
        "public_key": current_app.config.get("PAYPAL_CLIENT_ID"),
        "secret_key": current_app.config.get("PAYPAL_SECRET_KEY"),
        "webhook_secret": current_app.config.get("PAYPAL_WEBHOOK_ID"),
        "mode": current_app.config.get("PAYPAL_MODE", "live"),
    }


@user_bp.route("/rfid-tags/checkout", methods=["GET", "POST"])
@login_required
def rfid_tag_checkout():
    guard = require_user()
    if guard:
        return guard
    cart = _get_or_create_spectator_cart()
    items = RfidTagCartItem.query.filter_by(cart_id=cart.id).all()
    if not items:
        flash("There are no RFID tags in your cart.", "error")
        return redirect(url_for("user.rfid_tags"))
    settings = RfidTagSettings.query.get(1) or RfidTagSettings(price_cents=0)
    total_cents = max(0, settings.price_cents or 0) * len(items)
    if request.method == "POST":
        payment_method = (request.form.get("payment_method") or "stripe").lower()
        if payment_method not in {"stripe", "paypal"}:
            payment_method = "stripe"
        order = RfidTagOrder(
            order_number=f"RFID-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}",
            user_id=current_user.id,
            total_cents=total_cents,
            payment_method=payment_method,
            payment_mode=current_app.config.get("PAYPAL_MODE", "live") if payment_method == "paypal" else "live",
            shipping_name=f"{current_user.first_name} {current_user.last_name}",
            shipping_street=current_user.street,
            shipping_city=current_user.city,
            shipping_state=current_user.state,
            shipping_postal_code=current_user.postal_code,
        )
        db.session.add(order)
        db.session.flush()
        for item in items:
            db.session.add(RfidTagOrderItem(order_id=order.id, car_id=item.car_id,
                                            unit_price_cents=max(0, settings.price_cents or 0)))
            db.session.delete(item)
        db.session.commit()
        if total_cents <= 0:
            _mark_rfid_tag_order_paid(order)
            return redirect(url_for("user.rfid_tag_order", order_id=order.id))
        if payment_method == "paypal":
            credentials = _rfid_paypal_credentials()
            if not credentials["public_key"] or not credentials["secret_key"]:
                flash("PayPal payments are not configured yet. Your order was saved pending payment.", "error")
                return redirect(url_for("user.rfid_tag_order", order_id=order.id))
            try:
                paypal_order, approve_url = create_paypal_order(
                    credentials, order.total_cents, "CarBook UHF RFID vehicle tags", f"rfid:{order.id}",
                    url_for("user.rfid_tag_paypal_return", order_id=order.id, _external=True),
                    url_for("user.rfid_tag_order", order_id=order.id, _external=True), f"rfid-create-{order.id}")
                order.provider_session_id = paypal_order["id"]
                db.session.commit()
                return redirect(approve_url)
            except PayPalError:
                current_app.logger.exception("RFID tag PayPal checkout creation failed")
                flash("PayPal could not start checkout. Your order was saved; please try again later.", "error")
                return redirect(url_for("user.rfid_tag_order", order_id=order.id))
        if not stripe or not current_app.config.get("STRIPE_SECRET_KEY"):
            flash("Online tag payments are not configured yet. Your order was saved pending payment.", "error")
            return redirect(url_for("user.rfid_tag_order", order_id=order.id))
        try:
            stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
            checkout = stripe.checkout.Session.create(
                mode="payment",
                customer_email=current_user.email,
                line_items=[{"price_data": {"currency": "usd", "unit_amount": max(0, settings.price_cents or 0),
                             "product_data": {"name": "CarBook UHF RFID vehicle tag"}}, "quantity": len(items)}],
                metadata={"rfid_tag_order_id": str(order.id)},
                success_url=url_for("user.rfid_tag_payment_return", order_id=order.id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=url_for("user.rfid_tag_order", order_id=order.id, _external=True),
            )
            order.provider_session_id = checkout.id
            db.session.commit()
            return redirect(checkout.url, code=303)
        except Exception:
            current_app.logger.exception("RFID tag checkout creation failed")
            flash("Stripe could not start checkout. Your order was saved; please try again later.", "error")
            return redirect(url_for("user.rfid_tag_order", order_id=order.id))
    return render_template("user/rfid_tag_checkout.html", items=items, total_cents=total_cents, money=_money)


@user_bp.route("/rfid-tags/order/<int:order_id>")
@login_required
def rfid_tag_order(order_id):
    order = RfidTagOrder.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    return render_template("user/rfid_tag_order.html", order=order, money=_money)


@user_bp.route("/rfid-tags/order/<int:order_id>/pay", methods=["POST"])
@login_required
def rfid_tag_order_pay(order_id):
    order = RfidTagOrder.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if order.payment_status == "paid":
        return redirect(url_for("user.rfid_tag_order", order_id=order.id))
    payment_method = (request.form.get("payment_method") or order.payment_method or "stripe").lower()
    if payment_method == "paypal":
        credentials = _rfid_paypal_credentials()
        if not credentials["public_key"] or not credentials["secret_key"]:
            flash("PayPal payments are not configured yet.", "error")
            return redirect(url_for("user.rfid_tag_order", order_id=order.id))
        try:
            paypal_order, approve_url = create_paypal_order(
                credentials, order.total_cents, "CarBook UHF RFID vehicle tags", f"rfid:{order.id}",
                url_for("user.rfid_tag_paypal_return", order_id=order.id, _external=True),
                url_for("user.rfid_tag_order", order_id=order.id, _external=True), f"rfid-retry-{order.id}")
            order.payment_method = "paypal"
            order.payment_mode = credentials["mode"]
            order.provider_session_id = paypal_order["id"]
            db.session.commit()
            return redirect(approve_url)
        except PayPalError:
            current_app.logger.exception("RFID tag PayPal retry failed")
            flash("PayPal could not start checkout. Please try again later.", "error")
            return redirect(url_for("user.rfid_tag_order", order_id=order.id))
    if not stripe or not current_app.config.get("STRIPE_SECRET_KEY"):
        flash("Online tag payments are not configured yet.", "error")
        return redirect(url_for("user.rfid_tag_order", order_id=order.id))
    try:
        stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
        checkout = stripe.checkout.Session.create(
            mode="payment", customer_email=current_user.email,
            line_items=[{"price_data": {"currency": "usd", "unit_amount": order.items[0].unit_price_cents,
                         "product_data": {"name": "CarBook UHF RFID vehicle tag"}}, "quantity": len(order.items)}],
            metadata={"rfid_tag_order_id": str(order.id)},
            success_url=url_for("user.rfid_tag_payment_return", order_id=order.id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("user.rfid_tag_order", order_id=order.id, _external=True),
        )
        order.provider_session_id = checkout.id
        order.payment_method = "stripe"
        order.payment_mode = "live"
        db.session.commit()
        return redirect(checkout.url, code=303)
    except Exception:
        current_app.logger.exception("RFID tag payment retry failed")
        flash("Stripe could not start checkout. Please try again later.", "error")
        return redirect(url_for("user.rfid_tag_order", order_id=order.id))


@user_bp.route("/rfid-tags/order/<int:order_id>/paypal-return")
@login_required
def rfid_tag_paypal_return(order_id):
    order = RfidTagOrder.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    paypal_order_id = (request.args.get("token") or "").strip()
    if order.payment_method != "paypal" or paypal_order_id != order.provider_session_id:
        flash("PayPal could not confirm this order.", "error")
        return redirect(url_for("user.rfid_tag_order", order_id=order.id))
    if order.payment_status != "paid":
        try:
            captured = capture_paypal_order(_rfid_paypal_credentials(), paypal_order_id, f"rfid-capture-{order.id}")
            details = paypal_capture_details(captured)
            if (details["status"] != "COMPLETED" or details["currency"] != "USD"
                    or details["value"] != f"{order.total_cents / 100:.2f}" or not details["transaction_id"]):
                raise PayPalError("PayPal capture did not match the RFID order.")
            _mark_rfid_tag_order_paid(order, details["transaction_id"])
            flash(f"Order {order.order_number} paid successfully.", "success")
        except (PayPalError, TypeError, KeyError):
            current_app.logger.exception("PayPal RFID capture failed for order %s", order.id)
            flash("PayPal is still processing this payment. Please try again shortly.", "error")
    return redirect(url_for("user.rfid_tag_order", order_id=order.id))


@user_bp.route("/rfid-tags/order/<int:order_id>/payment-return")
@login_required
def rfid_tag_payment_return(order_id):
    order = RfidTagOrder.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    session_id = request.args.get("session_id")
    if order.payment_status != "paid" and session_id and session_id == order.provider_session_id and stripe:
        try:
            stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
            checkout = stripe.checkout.Session.retrieve(session_id)
            if checkout.payment_status == "paid" and int(checkout.amount_total or -1) == order.total_cents:
                _mark_rfid_tag_order_paid(order, checkout.payment_intent)
        except Exception:
            current_app.logger.exception("Could not verify RFID tag payment return")
    return redirect(url_for("user.rfid_tag_order", order_id=order.id))
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


def _generate_user_qr_code():
    while True:
        code = f"DRV-{secrets.token_hex(4).upper()}"
        if not User.query.filter_by(static_qr_code=code).first():
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
    account_type = getattr(current_user, "account_type", None) if current_user.is_authenticated else None
    owner_field = "user_id" if account_type == "user" else ("vendor_id" if account_type == "vendor" else None)
    owner_id = current_user.id if owner_field else None
    if owner_id:
        owner_filter = {owner_field: owner_id}
        account_cart = SpectatorCart.query.filter_by(**owner_filter).first()
        guest_token = session.get("spectator_cart_token")
        guest_cart = (
            SpectatorCart.query.filter_by(session_token=guest_token).first()
            if guest_token
            else None
        )

        if guest_cart and guest_cart.id != getattr(account_cart, "id", None):
            if not account_cart:
                setattr(guest_cart, owner_field, owner_id)
                guest_cart.session_token = None
                session.pop("spectator_cart_token", None)
                db.session.commit()
                return guest_cart

            guest_items = list(guest_cart.items)
            account_items = list(account_cart.items)
            guest_track_ids = {item.event.track_id for item in guest_items}
            account_track_ids = {item.event.track_id for item in account_items}
            can_merge = not guest_items or not account_items or guest_track_ids == account_track_ids
            if can_merge:
                for guest_item in guest_items:
                    existing = SpectatorCartItem.query.filter_by(
                        cart_id=account_cart.id,
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
                        guest_item.cart = account_cart
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
            return account_cart

        if account_cart:
            return account_cart
        account_cart = SpectatorCart(**owner_filter)
        db.session.add(account_cart)
        db.session.commit()
        return account_cart

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
    return sum(item.quantity for item in cart.items) + len(cart.rfid_tag_items)


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
            checkin_code=generate_driver_ticket_code(),
        )
        db.session.add(reg)
        db.session.flush()

    track_class = TrackDriverClass.query.filter_by(track_id=event.track_id, user_id=user.id).first()
    if not track_class:
        db.session.add(TrackDriverClass(track_id=event.track_id, user_id=user.id, driver_class="C"))

    if event.event_type != "private" and not SocialPost.query.filter_by(event_registration_id=reg.id).first():
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

    return _ensure_driver_event_waivers(event, user)


def _ensure_driver_event_waivers(event, user):
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


def _finalize_private_rental_booking(booking, transaction_id=None):
    if booking.status == "confirmed" and booking.event_id:
        if transaction_id and not booking.provider_transaction_id:
            booking.provider_transaction_id = transaction_id
            booking.paid_at = booking.paid_at or datetime.utcnow()
            db.session.commit()
        return booking.event

    slot = PrivateRentalSlot.query.filter_by(id=booking.slot_id).with_for_update().one()
    conflicting_booking = (
        PrivateRentalBooking.query.filter(
            PrivateRentalBooking.slot_id == slot.id,
            PrivateRentalBooking.id != booking.id,
            PrivateRentalBooking.status == "confirmed",
            PrivateRentalBooking.payment_status == "paid",
        )
        .order_by(PrivateRentalBooking.created_at.asc())
        .first()
    )
    if conflicting_booking:
        raise ValueError("That private rental slot has already been booked.")

    mark_private_rental_paid(booking, transaction_id=transaction_id)
    event = Event(
        track_id=slot.track_id,
        event_name=slot.name,
        event_date=slot.slot_date,
        event_type="private",
        private_owner_user_id=booking.user_id,
        driver_price_cents=0,
        spectator_price_cents=0,
        vendor_price_cents=0,
        driver_capacity=slot.driver_limit,
        spectator_capacity=0,
        vendor_capacity=0,
        event_start_time=slot.start_time,
        event_end_time=slot.end_time,
    )
    db.session.add(event)
    db.session.flush()
    if not booking.car.static_qr_code:
        booking.car.static_qr_code = _generate_car_qr_code()
    db.session.add(
        EventRegistration(
            event_id=event.id,
            user_id=booking.user_id,
            car_id=booking.car_id,
            checkin_code=generate_driver_ticket_code(),
        )
    )
    if not TrackDriverClass.query.filter_by(
        track_id=slot.track_id,
        user_id=booking.user_id,
    ).first():
        db.session.add(
            TrackDriverClass(track_id=slot.track_id, user_id=booking.user_id, driver_class="C")
        )
    if not TrackSubscription.query.filter_by(
        track_id=slot.track_id,
        user_id=booking.user_id,
    ).first():
        db.session.add(TrackSubscription(track_id=slot.track_id, user_id=booking.user_id))
    booking.event_id = event.id
    _ensure_driver_event_waivers(event, booking.buyer)
    db.session.commit()
    _safe_send_email(send_private_rental_confirmation, booking)
    return event


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
                vendor_id=order.vendor_id,
                buyer_type="vendor" if order.vendor_id else ("user" if order.user_id else "guest"),
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
    elif order.vendor_id:
        cart = SpectatorCart.query.filter_by(vendor_id=order.vendor_id).first()
        if cart:
            for item in list(cart.items):
                db.session.delete(item)
    db.session.commit()
    _safe_send_email(send_spectator_order_receipt, order)


def _paypal_credentials_for_order(
    spectator_order=None,
    driver_ticket_order=None,
    private_rental_booking=None,
):
    if spectator_order:
        track = spectator_order.items[0].event.track if spectator_order.items else None
        mode = spectator_order.payment_mode
    elif private_rental_booking:
        track = private_rental_booking.slot.track
        mode = private_rental_booking.payment_mode
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
    if not current_user.static_qr_code:
        current_user.static_qr_code = _generate_user_qr_code()
        db.session.commit()
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
            Event.event_type == "public",
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


@user_bp.route("/private-rentals")
@login_required
def private_rental_tracks():
    guard = require_user()
    if guard:
        return guard
    slots = (
        PrivateRentalSlot.query.filter(
            PrivateRentalSlot.slot_date >= date.today(),
            PrivateRentalSlot.is_active.is_(True),
        )
        .order_by(PrivateRentalSlot.slot_date.asc(), PrivateRentalSlot.start_time.asc())
        .all()
    )
    bookings_by_slot = active_bookings_by_slot([slot.id for slot in slots])
    availability_by_track = {}
    for slot in slots:
        booking = bookings_by_slot.get(slot.id)
        if booking and booking.user_id != current_user.id:
            continue
        summary = availability_by_track.setdefault(
            slot.track_id,
            {
                "track": slot.track,
                "count": 0,
                "from_cents": slot.price_cents,
                "next_date": slot.slot_date,
                "has_booking": False,
            },
        )
        if booking:
            summary["has_booking"] = True
        else:
            summary["count"] += 1
        summary["from_cents"] = min(summary["from_cents"], slot.price_cents)
        summary["next_date"] = min(summary["next_date"], slot.slot_date)
    return render_template(
        "user/private_rental_tracks.html",
        track_options=sorted(
            availability_by_track.values(),
            key=lambda item: (item["next_date"], item["track"].name.lower()),
        ),
        money=_money,
    )


@user_bp.route("/tracks/<int:track_id>/private-rentals")
@login_required
def private_rental_calendar(track_id):
    guard = require_user()
    if guard:
        return guard
    track = Track.query.get_or_404(track_id)
    calendar = rental_month_context(request.args.get("month"))
    slots = (
        PrivateRentalSlot.query.filter(
            PrivateRentalSlot.track_id == track.id,
            PrivateRentalSlot.slot_date >= calendar["range_start"],
            PrivateRentalSlot.slot_date <= calendar["range_end"],
            PrivateRentalSlot.is_active.is_(True),
        )
        .order_by(PrivateRentalSlot.slot_date.asc(), PrivateRentalSlot.start_time.asc())
        .all()
    )
    bookings_by_slot = active_bookings_by_slot([slot.id for slot in slots])
    slots_by_date = {}
    payment_choices_by_slot = {}
    for slot in slots:
        slots_by_date.setdefault(slot.slot_date, []).append(slot)
        payment_choices_by_slot[slot.id] = _configured_payment_choices(track, slot.price_cents)
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.created_at.desc()).all()
    my_bookings = (
        PrivateRentalBooking.query.join(
            PrivateRentalSlot,
            PrivateRentalSlot.id == PrivateRentalBooking.slot_id,
        )
        .filter(
            PrivateRentalBooking.user_id == current_user.id,
            PrivateRentalSlot.track_id == track.id,
            PrivateRentalSlot.slot_date >= date.today(),
            PrivateRentalBooking.status.in_(("pending", "confirmed")),
        )
        .order_by(PrivateRentalSlot.slot_date.asc(), PrivateRentalSlot.start_time.asc())
        .all()
    )
    my_bookings = [booking for booking in my_bookings if booking_is_active(booking)]
    return render_template(
        "user/private_rental_calendar.html",
        track=track,
        calendar=calendar,
        slots=slots,
        slots_by_date=slots_by_date,
        bookings_by_slot=bookings_by_slot,
        payment_choices_by_slot=payment_choices_by_slot,
        cars=cars,
        my_bookings=my_bookings,
        today=date.today(),
        money=_money,
    )


@user_bp.route("/private-rentals/slots/<int:slot_id>/book", methods=["POST"])
@login_required
def private_rental_book(slot_id):
    guard = require_user()
    if guard:
        return guard
    slot = PrivateRentalSlot.query.filter_by(id=slot_id).with_for_update().first_or_404()
    calendar_url = url_for(
        "user.private_rental_calendar",
        track_id=slot.track_id,
        month=slot.slot_date.strftime("%Y-%m"),
    )
    calendar_external_url = url_for(
        "user.private_rental_calendar",
        track_id=slot.track_id,
        month=slot.slot_date.strftime("%Y-%m"),
        _external=True,
    )
    if not slot.is_active or slot.slot_date < date.today():
        flash("That private rental slot is no longer available.", "error")
        return redirect(calendar_url)

    active_booking = active_bookings_by_slot([slot.id]).get(slot.id)
    if active_booking:
        if active_booking.user_id == current_user.id and active_booking.status == "pending":
            if active_booking.provider_checkout_url:
                return redirect(active_booking.provider_checkout_url)
        flash("That private rental slot is already booked or currently in checkout.", "error")
        return redirect(calendar_url)

    car_id = request.form.get("car_id", type=int)
    car = Car.query.filter_by(id=car_id, user_id=current_user.id).first()
    if not car:
        flash("Choose one of your vehicles before booking.", "error")
        return redirect(calendar_url)

    payment_choices = _configured_payment_choices(slot.track, slot.price_cents)
    allowed_providers = {value for value, _label in payment_choices}
    payment_method = (request.form.get("payment_method") or "").strip().lower()
    if payment_method not in allowed_providers:
        flash("Choose an available payment method.", "error")
        return redirect(calendar_url)
    credentials = _payment_credentials(slot.track, payment_method)
    booking = PrivateRentalBooking(
        slot_id=slot.id,
        user_id=current_user.id,
        car_id=car.id,
        amount_cents=max(0, slot.price_cents or 0),
        payment_method=payment_method,
        payment_mode=credentials["mode"],
        payment_status="pending",
        status="pending",
        expires_at=datetime.utcnow() + timedelta(minutes=BOOKING_HOLD_MINUTES),
    )
    db.session.add(booking)
    db.session.flush()

    if booking.amount_cents <= 0:
        event = _finalize_private_rental_booking(booking)
        flash("Your private track rental is confirmed.", "success")
        return redirect(url_for("user.event_schedule", event_id=event.id))

    if payment_method == "stripe" and stripe and credentials["secret_key"] and credentials["webhook_secret"]:
        try:
            stripe.api_key = credentials["secret_key"]
            checkout_session = create_private_rental_stripe_checkout_session(
                stripe,
                booking,
                success_url=url_for(
                    "user.private_rental_booking_success",
                    booking_id=booking.id,
                    _external=True,
                ),
                cancel_url=calendar_external_url,
            )
            booking.provider_session_id = checkout_session.id
            booking.provider_checkout_url = checkout_session.url
            db.session.commit()
            return redirect(checkout_session.url)
        except Exception:
            current_app.logger.exception("Stripe private rental checkout creation failed")
            db.session.rollback()
            flash("Stripe could not start the private rental checkout.", "error")
            return redirect(calendar_url)

    if payment_method == "paypal" and credentials["public_key"] and credentials["secret_key"] and credentials["webhook_secret"]:
        try:
            paypal_order, approve_url = create_paypal_order(
                credentials,
                booking.amount_cents,
                f"Private track rental - {slot.track.name}",
                f"private-rental:{booking.id}",
                url_for(
                    "user.private_rental_paypal_return",
                    booking_id=booking.id,
                    _external=True,
                ),
                calendar_external_url,
                f"private-rental-create-{booking.id}",
            )
            booking.provider_session_id = paypal_order["id"]
            booking.provider_checkout_url = approve_url
            db.session.commit()
            return redirect(approve_url)
        except PayPalError:
            current_app.logger.exception("PayPal private rental checkout creation failed")
            db.session.rollback()
            flash("PayPal could not start the private rental checkout.", "error")
            return redirect(calendar_url)

    db.session.rollback()
    flash("That payment provider cannot confirm private rental payments yet.", "error")
    return redirect(calendar_url)


@user_bp.route("/private-rentals/bookings/<int:booking_id>/success")
@login_required
def private_rental_booking_success(booking_id):
    guard = require_user()
    if guard:
        return guard
    booking = PrivateRentalBooking.query.filter_by(
        id=booking_id,
        user_id=current_user.id,
    ).first_or_404()
    if booking.status == "confirmed" and booking.event_id:
        flash("Your private track rental is confirmed and added to your dashboard.", "success")
        return redirect(url_for("user.dashboard"))
    flash("Payment is processing. Your rental remains held while confirmation completes.", "success")
    return redirect(
        url_for(
            "user.private_rental_calendar",
            track_id=booking.slot.track_id,
            month=booking.slot.slot_date.strftime("%Y-%m"),
        )
    )


@user_bp.route("/private-rentals/bookings/<int:booking_id>/release", methods=["POST"])
@login_required
def private_rental_booking_release(booking_id):
    guard = require_user()
    if guard:
        return guard
    booking = PrivateRentalBooking.query.filter_by(
        id=booking_id,
        user_id=current_user.id,
        status="pending",
    ).first_or_404()
    if booking.payment_status == "paid":
        flash("A paid rental cannot be released from the calendar.", "error")
    else:
        booking.status = "canceled"
        booking.payment_status = "canceled"
        booking.failure_reason = "Released by driver before payment confirmation."
        db.session.commit()
        flash("The rental hold was released.", "success")
    return redirect(
        url_for(
            "user.private_rental_calendar",
            track_id=booking.slot.track_id,
            month=booking.slot.slot_date.strftime("%Y-%m"),
        )
    )


@user_bp.route("/inspection-qr.png")
@login_required
def inspection_qr_image():
    guard = require_user()
    if guard:
        return guard
    if not current_user.static_qr_code:
        current_user.static_qr_code = _generate_user_qr_code()
        db.session.commit()
    return Response(
        code_qr_png(current_user.static_qr_code),
        mimetype="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


def _event_detail_response(event_id):
    event = Event.query.get_or_404(event_id)
    if event.event_type == "private":
        if (
            not current_user.is_authenticated
            or getattr(current_user, "account_type", None) != "user"
        ):
            flash("Sign in to view that private event.", "error")
            return redirect(url_for("auth.user_login", next=url_for("user.event_detail", event_id=event.id)))
        registration = EventRegistration.query.filter_by(
            event_id=event.id,
            user_id=current_user.id,
        ).first()
        if not registration and event.private_owner_user_id != current_user.id:
            return "Event not found", 404
        booking = PrivateRentalBooking.query.filter_by(event_id=event.id).first()
        return render_template(
            "user/private_event_detail.html",
            event=event,
            registration=registration,
            booking=booking,
            money=_money,
        )
    if event.event_date < date.today():
        flash("Spectator tickets are no longer available for this event.", "error")
        return redirect(url_for("user.spectator_events"))
    spectator_ticket_type = _get_or_create_default_ticket_type(event, "spectator")
    is_vendor_account = (
        current_user.is_authenticated
        and getattr(current_user, "account_type", None) == "vendor"
    )
    vendor_ticket_type = (
        _get_or_create_default_ticket_type(event, "vendor")
        if is_vendor_account
        else None
    )
    cart = _get_or_create_spectator_cart()
    availability = _event_ticket_availability(event)
    vendor_items = (
        SpectatorOrderItem.query.join(
            SpectatorOrder,
            SpectatorOrder.id == SpectatorOrderItem.order_id,
        )
        .filter(
            SpectatorOrderItem.event_id == event.id,
            SpectatorOrderItem.ticket_category == "vendor",
            SpectatorOrder.vendor_id.isnot(None),
        )
        .order_by(SpectatorOrder.created_at.asc())
        .all()
    )
    onsite_vendors_by_id = {}
    for item in vendor_items:
        order = item.order
        if order.vendor and payment_is_confirmed(
            order.payment_status,
            order.payment_method,
            order.total_cents,
            order.provider_transaction_id,
        ):
            onsite_vendors_by_id.setdefault(order.vendor.id, order.vendor)
    return render_template(
        "user/spectator_tickets.html",
        event=event,
        spectator_ticket_type=spectator_ticket_type,
        vendor_ticket_type=vendor_ticket_type,
        availability=availability,
        money=_money,
        cart_count=_cart_item_count(cart),
        onsite_vendors=list(onsite_vendors_by_id.values()),
    )


@user_bp.route("/events/<int:event_id>")
def event_detail(event_id):
    return _event_detail_response(event_id)


@user_bp.route("/events/<int:event_id>/spectator-tickets")
def spectator_tickets(event_id):
    return redirect(url_for("user.event_detail", event_id=event_id))


@user_bp.route("/spectator/events")
def spectator_events():
    q = (request.args.get("q") or "").strip()
    query = Event.query.join(Track, Track.id == Event.track_id).filter(
        Event.event_date >= date.today(),
        Event.event_type == "public",
    )
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Event.event_name.ilike(like))
            | (Track.name.ilike(like))
            | (Track.city.ilike(like))
            | (Track.state.ilike(like))
        )
    events = query.order_by(Event.event_date.asc()).limit(60).all()
    calendar = rental_month_context(request.args.get("month"))
    visible_event_filter = Event.event_type == "public"
    if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user":
        visible_event_filter = or_(
            Event.event_type == "public", Event.private_owner_user_id == current_user.id
        )
    calendar_events_query = Event.query.join(Track, Track.id == Event.track_id).filter(
        visible_event_filter,
        Event.event_date >= calendar["range_start"],
        Event.event_date <= calendar["range_end"],
    )
    calendar_slots_query = PrivateRentalSlot.query.join(Track, Track.id == PrivateRentalSlot.track_id).filter(
        PrivateRentalSlot.is_active.is_(True),
        PrivateRentalSlot.slot_date >= calendar["range_start"],
        PrivateRentalSlot.slot_date <= calendar["range_end"],
    )
    if q:
        like = f"%{q}%"
        calendar_events_query = calendar_events_query.filter(
            Event.event_name.ilike(like) | Track.name.ilike(like) |
            Track.city.ilike(like) | Track.state.ilike(like)
        )
        calendar_slots_query = calendar_slots_query.filter(
            PrivateRentalSlot.name.ilike(like) | Track.name.ilike(like) |
            Track.city.ilike(like) | Track.state.ilike(like)
        )
    calendar_events = calendar_events_query.all()
    calendar_slots = calendar_slots_query.all()
    calendar_items_by_date = {}
    for event in calendar_events:
        calendar_items_by_date.setdefault(event.event_date, []).append({"kind": "event", "event": event})
    bookings_by_slot = active_bookings_by_slot([slot.id for slot in calendar_slots])
    for slot in calendar_slots:
        if bookings_by_slot.get(slot.id) and bookings_by_slot[slot.id].event_id:
            continue
        calendar_items_by_date.setdefault(slot.slot_date, []).append({
            "kind": "rental", "slot": slot, "booking": bookings_by_slot.get(slot.id)
        })
    ticket_types_by_event = {}
    availability_by_event = {}
    for event in events:
        ticket_types_by_event[event.id] = {
            "spectator": _get_or_create_default_ticket_type(event, "spectator"),
        }
        if current_user.is_authenticated and getattr(current_user, "account_type", None) == "vendor":
            ticket_types_by_event[event.id]["vendor"] = _get_or_create_default_ticket_type(
                event,
                "vendor",
            )
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
        calendar=calendar,
        calendar_items_by_date=calendar_items_by_date,
        today=date.today(),
    )


@user_bp.route("/spectator/cart/add", methods=["POST"])
def spectator_cart_add():
    event_id = request.form.get("event_id", type=int)
    ticket_type_id = request.form.get("ticket_type_id", type=int)
    quantity = request.form.get("quantity", type=int) or 1
    event = Event.query.get_or_404(event_id)
    if event.event_type == "private":
        flash("Private rentals do not offer public admission.", "error")
        return redirect(url_for("user.spectator_events"))
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
    if ticket_type.ticket_category == "vendor" and (
        not current_user.is_authenticated
        or getattr(current_user, "account_type", None) != "vendor"
    ):
        flash("Vendor admission requires a vendor account.", "error")
        if current_user.is_authenticated:
            return redirect(url_for("user.event_detail", event_id=event.id))
        return redirect(
            url_for(
                "auth.user_login",
                next=url_for("user.event_detail", event_id=event.id),
            )
        )
    purchase_limit, availability = _ticket_purchase_limit(event, ticket_type)
    if purchase_limit <= 0:
        flash(f"{ticket_type.name} is sold out for this event.", "error")
        return redirect(url_for("user.event_detail", event_id=event.id))
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
    tag_items = RfidTagCartItem.query.filter_by(cart_id=cart.id).all()
    tag_settings = RfidTagSettings.query.get(1)
    tag_unit_cents = max(0, tag_settings.price_cents or 0) if tag_settings else 0
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
        tag_items=tag_items,
        tag_unit_cents=tag_unit_cents,
        tag_subtotal_cents=tag_unit_cents * len(tag_items),
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
    if has_vendor_tickets and (
        not current_user.is_authenticated
        or getattr(current_user, "account_type", None) != "vendor"
    ):
        flash("Sign in with a vendor account to purchase vendor admission.", "error")
        if current_user.is_authenticated:
            return redirect(url_for("user.spectator_cart"))
        return redirect(url_for("auth.user_login", next=url_for("user.spectator_checkout")))
    payment_track = items[0].event.track
    payment_choices = _configured_payment_choices(payment_track, subtotal_cents)
    if not payment_choices:
        flash("No payment methods are configured for this track yet.", "error")
        return redirect(url_for("user.spectator_cart"))

    form = SpectatorCheckoutForm()
    form.payment_method.choices = payment_choices
    account_type = getattr(current_user, "account_type", None) if current_user.is_authenticated else None
    if account_type in {"user", "vendor"} and request.method == "GET":
        form.full_name.data = (
            f"{current_user.first_name} {current_user.last_name}".strip()
            if account_type == "user"
            else current_user.full_name
        )
        form.email.data = current_user.email
        form.phone.data = current_user.phone
        if account_type == "vendor":
            form.vendor_business_name.data = current_user.business_name
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
        user_id = current_user.id if account_type == "user" else None
        vendor_id = current_user.id if account_type == "vendor" else None
        buyer_name = form.full_name.data.strip()
        buyer_email = form.email.data.strip().lower()
        buyer_phone = form.phone.data.strip()
        if user_id:
            buyer_name = f"{current_user.first_name} {current_user.last_name}".strip()
            buyer_email = current_user.email
            buyer_phone = current_user.phone
        elif vendor_id:
            buyer_name = current_user.full_name
            buyer_email = current_user.email
            buyer_phone = current_user.phone
            vendor_business_name = current_user.business_name

        order = SpectatorOrder(
            order_number=f"SP-{secrets.token_hex(4).upper()}",
            user_id=user_id,
            vendor_id=vendor_id,
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
                    vendor_id=vendor_id,
                    buyer_type="vendor" if vendor_id else ("user" if user_id else "guest"),
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
    if order.vendor_id and (
        not current_user.is_authenticated
        or getattr(current_user, "account_type", None) != "vendor"
        or current_user.id != order.vendor_id
    ):
        return "Order not found", 404
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
    rfid_order = RfidTagOrder.query.filter_by(provider_session_id=session_id).first()
    driver_ticket_order = None
    private_rental_booking = None
    if not order:
        driver_ticket_order = DriverTicketOrder.query.filter_by(provider_session_id=session_id).first()
    if not order and not driver_ticket_order:
        private_rental_booking = PrivateRentalBooking.query.filter_by(
            provider_session_id=session_id
        ).first()
    if not order and not driver_ticket_order and not private_rental_booking and not rfid_order:
        return "ok", 200
    if rfid_order:
        webhook_secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")
    elif order:
        payment_track = order.items[0].event.track if order.items else None
        webhook_secret = (
            _payment_credentials(payment_track, "stripe", mode=order.payment_mode)["webhook_secret"]
            if payment_track
            else None
        )
    elif driver_ticket_order:
        webhook_secret = _payment_credentials(
            driver_ticket_order.event.track,
            "stripe",
            mode=driver_ticket_order.payment_mode,
        )["webhook_secret"]
    else:
        webhook_secret = _payment_credentials(
            private_rental_booking.slot.track,
            "stripe",
            mode=private_rental_booking.payment_mode,
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
        target = rfid_order or order or driver_ticket_order or private_rental_booking
        if target.payment_status != "paid":
            target.payment_status = "failed"
            if hasattr(target, "status"):
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
        target = rfid_order or order or driver_ticket_order or private_rental_booking
        expected_cents = target.total_cents if (order or rfid_order) else target.amount_cents
        if (
            session_obj.get("payment_status") != "paid"
            or session_obj.get("currency", "").lower() != "usd"
            or int(session_obj.get("amount_total") or -1) != int(expected_cents or 0)
        ):
            current_app.logger.warning(
                "Ignored unconfirmed or mismatched Stripe checkout session %s for %s order %s",
                session_id,
                "rfid" if rfid_order else ("spectator" if order else ("driver" if driver_ticket_order else "private rental")),
                target.id,
            )
            return "ok", 200
        if rfid_order and rfid_order.payment_status != "paid":
            _mark_rfid_tag_order_paid(rfid_order, session_obj.get("payment_intent"))
        elif order and order.payment_status != "paid":
            _finalize_spectator_order(order, transaction_id=session_obj.get("payment_intent"))
        elif driver_ticket_order and driver_ticket_order.payment_status != "paid":
            _finalize_driver_ticket_order(
                driver_ticket_order,
                transaction_id=session_obj.get("payment_intent"),
            )
        elif private_rental_booking and private_rental_booking.payment_status != "paid":
            _finalize_private_rental_booking(
                private_rental_booking,
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


@user_bp.route("/payments/paypal/private-rental/<int:booking_id>/return")
@login_required
def private_rental_paypal_return(booking_id):
    guard = require_user()
    if guard:
        return guard
    booking = PrivateRentalBooking.query.filter_by(
        id=booking_id,
        user_id=current_user.id,
    ).first_or_404()
    paypal_order_id = request.args.get("token", "").strip()
    calendar_url = url_for(
        "user.private_rental_calendar",
        track_id=booking.slot.track_id,
        month=booking.slot.slot_date.strftime("%Y-%m"),
    )
    if (
        booking.payment_method != "paypal"
        or not paypal_order_id
        or paypal_order_id != booking.provider_session_id
    ):
        flash("PayPal could not confirm this private rental.", "error")
        return redirect(calendar_url)
    if booking.payment_status != "paid":
        PrivateRentalSlot.query.filter_by(id=booking.slot_id).with_for_update().one()
        blocking_booking = active_bookings_by_slot([booking.slot_id]).get(booking.slot_id)
        if blocking_booking and blocking_booking.id != booking.id:
            booking.payment_status = "failed"
            booking.status = "failed"
            booking.failure_reason = "The rental slot was booked before PayPal approval."
            db.session.commit()
            flash("That rental slot is no longer available. Your payment was not captured.", "error")
            return redirect(calendar_url)
        credentials = _paypal_credentials_for_order(private_rental_booking=booking)
        try:
            captured = capture_paypal_order(
                credentials,
                paypal_order_id,
                f"private-rental-capture-{booking.id}",
            )
            transaction_id = _validated_paypal_capture(
                paypal_capture_details(captured),
                booking.amount_cents,
            )
            _finalize_private_rental_booking(booking, transaction_id=transaction_id)
        except (PayPalError, TypeError, KeyError, ValueError):
            current_app.logger.exception(
                "PayPal private rental capture failed for booking %s",
                booking.id,
            )
            flash("PayPal is still processing this private rental payment.", "error")
            return redirect(calendar_url)
    return redirect(url_for("user.private_rental_booking_success", booking_id=booking.id))


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
    private_rental_booking = None
    if not spectator_order:
        driver_ticket_order = DriverTicketOrder.query.filter_by(
            provider_session_id=paypal_order_id,
            payment_method="paypal",
        ).first()
    if not spectator_order and not driver_ticket_order:
        private_rental_booking = PrivateRentalBooking.query.filter_by(
            provider_session_id=paypal_order_id,
            payment_method="paypal",
        ).first()
    if not spectator_order and not driver_ticket_order and not private_rental_booking:
        return "ok", 200

    credentials = _paypal_credentials_for_order(
        spectator_order=spectator_order,
        driver_ticket_order=driver_ticket_order,
        private_rental_booking=private_rental_booking,
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
            target = spectator_order or driver_ticket_order or private_rental_booking
            if not reservation_is_active(target):
                if spectator_order:
                    event_ids = sorted({item.event_id for item in spectator_order.items})
                    Event.query.filter(Event.id.in_(event_ids)).order_by(Event.id.asc()).with_for_update().all()
                    capacity_available = spectator_order_fits_capacity(spectator_order)
                elif driver_ticket_order:
                    Event.query.filter_by(id=driver_ticket_order.event_id).with_for_update().one()
                    capacity_available = driver_order_fits_capacity(driver_ticket_order)
                else:
                    PrivateRentalSlot.query.filter_by(
                        id=private_rental_booking.slot_id
                    ).with_for_update().one()
                    blocking_booking = active_bookings_by_slot(
                        [private_rental_booking.slot_id]
                    ).get(private_rental_booking.slot_id)
                    capacity_available = (
                        blocking_booking is None
                        or blocking_booking.id == private_rental_booking.id
                    )
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
                    else (
                        f"driver-capture-{driver_ticket_order.id}"
                        if driver_ticket_order
                        else f"private-rental-capture-{private_rental_booking.id}"
                    )
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
            target = spectator_order or driver_ticket_order or private_rental_booking
            if target.payment_status != "paid":
                target.payment_status = "failed"
                target.failure_reason = "PayPal declined the payment capture."
                db.session.commit()
            return "ok", 200
        else:
            return "ok", 200

        target = spectator_order or driver_ticket_order or private_rental_booking
        expected_cents = spectator_order.total_cents if spectator_order else target.amount_cents
        transaction_id = _validated_paypal_capture(details, expected_cents)
        if spectator_order:
            _finalize_spectator_order(spectator_order, transaction_id=transaction_id)
        elif driver_ticket_order:
            _finalize_driver_ticket_order(driver_ticket_order, transaction_id=transaction_id)
        else:
            _finalize_private_rental_booking(
                private_rental_booking,
                transaction_id=transaction_id,
            )
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


@user_bp.route("/profile")
@login_required
def profile_settings():
    guard = require_user()
    if guard:
        return guard
    from .models import DriverWaiver

    waivers = DriverWaiver.query.filter_by(driver_id=current_user.id).all()
    return render_template(
        "user/profile_settings.html",
        waiver_count=len(waivers),
        pending_waiver_count=sum(1 for waiver in waivers if waiver.status != "signed"),
        car_count=Car.query.filter_by(user_id=current_user.id).count(),
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
        return redirect(url_for("user.profile_settings"))

    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        flash("Profile image must be jpg, jpeg, png, or webp.", "error")
        return redirect(url_for("user.profile_settings"))

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
    return redirect(url_for("user.profile_settings"))


@user_bp.route("/discover")
@login_required
def discover():
    guard = require_user()
    if guard:
        return guard
    q = (request.args.get("q") or "").strip()
    timing = (request.args.get("when") or "all").strip().lower()
    today = date.today()
    subscribed_track_ids = {
        item.track_id
        for item in TrackSubscription.query.filter_by(user_id=current_user.id).all()
    }
    event_query = Event.query.join(Track, Track.id == Event.track_id).filter(
        Event.event_type == "public", Event.event_date >= today
    )
    if timing == "weekend":
        days_until_saturday = (5 - today.weekday()) % 7
        weekend_start = today + timedelta(days=days_until_saturday)
        event_query = event_query.filter(
            Event.event_date >= weekend_start,
            Event.event_date <= weekend_start + timedelta(days=1),
        )
    elif timing == "month":
        event_query = event_query.filter(Event.event_date <= today + timedelta(days=30))
    if q:
        like = f"%{q}%"
        event_query = event_query.filter(
            Event.event_name.ilike(like) | Track.name.ilike(like)
            | Track.city.ilike(like) | Track.state.ilike(like)
        )
    events = event_query.order_by(Event.event_date.asc()).limit(60).all()
    track_query = Track.query
    if q:
        like = f"%{q}%"
        track_query = track_query.filter(
            Track.name.ilike(like) | Track.city.ilike(like) | Track.state.ilike(like)
        )
    tracks = track_query.order_by(Track.name.asc()).limit(40).all()
    upcoming_by_track = {}
    if tracks:
        track_events = (
            Event.query.filter(
                Event.track_id.in_([track.id for track in tracks]),
                Event.event_type == "public",
                Event.event_date >= today,
            ).order_by(Event.event_date.asc()).all()
        )
        for event in track_events:
            if len(upcoming_by_track.setdefault(event.track_id, [])) < 3:
                upcoming_by_track[event.track_id].append(event)
    followed_events = [event for event in events if event.track_id in subscribed_track_ids][:6]
    suggested_events = followed_events or events[:6]
    registrations = {
        registration.event_id
        for registration in EventRegistration.query.filter_by(user_id=current_user.id).all()
    }
    signup_counts = {
        event.id: EventRegistration.query.filter_by(event_id=event.id).count()
        for event in events
    }
    return render_template(
        "user/discover.html",
        q=q,
        timing=timing,
        events=events,
        tracks=tracks,
        suggested_events=suggested_events,
        subscribed_track_ids=subscribed_track_ids,
        upcoming_by_track=upcoming_by_track,
        registrations=registrations,
        signup_counts=signup_counts,
        money=_money,
    )


def _attendee_event_ids(user_id):
    event_ids = {
        row[0] for row in db.session.query(EventRegistration.event_id)
        .filter(EventRegistration.user_id == user_id).all()
    }
    event_ids.update(
        row[0] for row in db.session.query(DriverTicketOrder.event_id)
        .filter(DriverTicketOrder.user_id == user_id, DriverTicketOrder.payment_status == "paid").all()
    )
    event_ids.update(
        row[0] for row in db.session.query(SpectatorOrderItem.event_id)
        .join(SpectatorOrder, SpectatorOrder.id == SpectatorOrderItem.order_id)
        .filter(SpectatorOrder.user_id == user_id, SpectatorOrder.payment_status == "paid").all()
    )
    return event_ids


@user_bp.route("/live")
@login_required
def attendee_live_events():
    guard = require_user()
    if guard:
        return guard
    event_ids = _attendee_event_ids(current_user.id)
    events = Event.query.filter(Event.id.in_(event_ids)).order_by(Event.event_date.desc()).all() if event_ids else []
    active_event_ids = {
        row[0] for row in db.session.query(TrackRun.event_id)
        .filter(TrackRun.event_id.in_(event_ids), TrackRun.status == "active").all()
    } if event_ids else set()
    return render_template("user/live_events.html", events=events, active_event_ids=active_event_ids, today=date.today())


def _attendee_event(event_id):
    if event_id not in _attendee_event_ids(current_user.id):
        return None
    return Event.query.get(event_id)


@user_bp.route("/events/<int:event_id>/live")
@login_required
def attendee_live_track(event_id):
    guard = require_user()
    if guard:
        return guard
    event = _attendee_event(event_id)
    if not event:
        return "Event access requires a paid ticket.", 403
    active_run = TrackRun.query.filter_by(event_id=event.id, status="active").order_by(TrackRun.started_at.desc()).first()
    completed_runs = TrackRun.query.filter_by(event_id=event.id, status="completed").order_by(TrackRun.ended_at.desc()).limit(30).all()
    all_runs = ([active_run] if active_run else []) + completed_runs
    vote_summary = {}
    for run in all_runs:
        vote_summary[run.id] = {
            "up": sum(1 for vote in run.votes if vote.vote == 1),
            "down": sum(1 for vote in run.votes if vote.vote == -1),
            "mine": next((vote.vote for vote in run.votes if vote.user_id == current_user.id), None),
        }
    return render_template("user/live_track.html", event=event, active_run=active_run,
                           completed_runs=completed_runs, vote_summary=vote_summary)


@user_bp.route("/events/<int:event_id>/runs/<int:run_id>/vote", methods=["POST"])
@login_required
def attendee_run_vote(event_id, run_id):
    guard = require_user()
    if guard:
        return guard
    event = _attendee_event(event_id)
    run = TrackRun.query.filter_by(id=run_id, event_id=event_id).first_or_404()
    if not event:
        return "Event access requires a paid ticket.", 403
    if not event.run_voting_enabled:
        flash("Run voting is currently disabled for this event.", "error")
    elif TrackRunVote.query.filter_by(run_id=run.id, user_id=current_user.id).first():
        flash("You already rated this run.", "error")
    else:
        vote_value = request.form.get("vote", type=int)
        if vote_value not in {-1, 1}:
            flash("Choose thumbs up or thumbs down.", "error")
        else:
            db.session.add(TrackRunVote(run_id=run.id, user_id=current_user.id, vote=vote_value))
            try:
                db.session.commit()
                flash("Your run rating was recorded.", "success")
            except IntegrityError:
                db.session.rollback()
                flash("You already rated this run.", "error")
    return redirect(url_for("user.attendee_live_track", event_id=event_id, _anchor=f"run-{run.id}"))


@user_bp.route("/events/<int:event_id>/live/state")
@login_required
def attendee_live_state(event_id):
    guard = require_user()
    if guard:
        return guard
    event = _attendee_event(event_id)
    if not event:
        return {"error": "forbidden"}, 403
    runs = TrackRun.query.filter_by(event_id=event.id).order_by(TrackRun.started_at.desc()).limit(31).all()
    return {"signature": [
        [run.id, run.status, [participant.id for participant in run.participants],
         sum(1 for vote in run.votes if vote.vote == 1), sum(1 for vote in run.votes if vote.vote == -1)]
        for run in runs
    ]}


@user_bp.route("/tracks")
@login_required
def tracks_directory():
    guard = require_user()
    if guard:
        return guard
    return redirect(url_for("user.discover", q=(request.args.get("q") or "").strip()))


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
    return redirect(url_for("user.discover"))


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
    return redirect(url_for("user.discover"))


@user_bp.route("/community")
@login_required
def community():
    guard = require_user()
    if guard:
        return guard
    posts = SocialPost.query.order_by(SocialPost.created_at.desc()).limit(100).all()
    cars = Car.query.order_by(Car.created_at.desc()).limit(100).all()
    events = (
        Event.query.filter(
            Event.event_type == "public",
            Event.event_date >= date.today(),
        )
        .order_by(Event.event_date.asc())
        .limit(24)
        .all()
    )
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


@user_bp.route("/community/posts", methods=["POST"])
@login_required
def community_post_create():
    guard = require_user()
    if guard:
        return guard
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Write something before posting.", "error")
    elif len(body) > 600:
        flash("Community posts must be 600 characters or fewer.", "error")
    else:
        db.session.add(
            SocialPost(
                user_id=current_user.id,
                post_type="driver_update",
                title="Shared an update",
                body=body,
            )
        )
        db.session.commit()
        flash("Your update is live.", "success")
    return redirect(url_for("user.community"))


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
    rental_in_use = PrivateRentalBooking.query.filter(
        PrivateRentalBooking.car_id == car.id,
        PrivateRentalBooking.status.in_(("pending", "confirmed")),
    ).first()
    if in_use or rental_in_use:
        flash("Car cannot be deleted while used in an event signup or private rental.", "error")
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
    if event.event_type == "private":
        flash("Private rental attendance is managed by the renter and track office.", "error")
        return redirect(url_for("user.dashboard"))
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
    if event.event_type == "private":
        flash("Private rentals do not use individual driver checkout.", "error")
        return redirect(url_for("user.event_detail", event_id=event.id))
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
