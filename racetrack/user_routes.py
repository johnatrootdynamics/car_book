import secrets
import os
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from .forms import CarForm, EventSignupForm, SocialCommentForm, SpectatorCheckoutForm, SpectatorTicketForm
from .models import (
    Car,
    Event,
    EventClassSlot,
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
    TrackSubscription,
    TrackWaiverTemplate,
    db,
)
from .services.storage_service import upload_public_image


user_bp = Blueprint("user", __name__, url_prefix="/user")
FORCED_BOLDSIGN_TEMPLATE_ID = os.getenv(
    "BOLDSIGN_FORCED_TEMPLATE_ID", "e5c8f024-64df-4bdc-9142-3a04c01a154a"
)


def _generate_car_qr_code():
    while True:
        code = f"CAR-{secrets.token_hex(4).upper()}"
        if not Car.query.filter_by(static_qr_code=code).first():
            return code


def _money(cents):
    return f"${(cents or 0) / 100:,.2f}"


def _get_or_create_default_ticket_type(event):
    ticket_type = (
        SpectatorTicketType.query.filter_by(event_id=event.id, is_active=True)
        .order_by(SpectatorTicketType.created_at.asc())
        .first()
    )
    if ticket_type:
        return ticket_type
    ticket_type = SpectatorTicketType(
        event_id=event.id,
        name="General Admission",
        price_cents=2500,
        is_active=True,
        max_per_order=10,
    )
    db.session.add(ticket_type)
    db.session.commit()
    return ticket_type


def _get_or_create_spectator_cart():
    user_id = None
    if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user":
        user_id = current_user.id
    if user_id:
        cart = SpectatorCart.query.filter_by(user_id=user_id).first()
        if cart:
            return cart
        cart = SpectatorCart(user_id=user_id)
        db.session.add(cart)
        db.session.commit()
        return cart

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


def require_user():
    if not current_user.is_authenticated:
        flash("Please sign in as a driver.", "error")
        return redirect(url_for("auth.user_login"))
    if current_user.account_type != "user":
        flash("Driver access required for that page.", "error")
        return redirect(url_for("employee.dashboard"))
    return None


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
    )


@user_bp.route("/events/<int:event_id>/spectator-tickets", methods=["GET", "POST"])
def spectator_tickets(event_id):
    event = Event.query.get_or_404(event_id)
    form = SpectatorTicketForm()
    if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user":
        if request.method == "GET":
            form.full_name.data = f"{current_user.first_name} {current_user.last_name}".strip()
            form.email.data = current_user.email
    if form.validate_on_submit():
        buyer_type = "guest"
        user_id = None
        full_name = (form.full_name.data or "").strip()
        email = (form.email.data or "").strip().lower()
        if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user":
            buyer_type = "user"
            user_id = current_user.id
            if not full_name:
                full_name = f"{current_user.first_name} {current_user.last_name}".strip()
            if not email:
                email = current_user.email
        if not full_name or not email:
            flash("Name and email are required for ticket purchases.", "error")
            return render_template("user/spectator_tickets.html", event=event, form=form)
        order = SpectatorTicketOrder(
            event_id=event.id,
            user_id=user_id,
            buyer_type=buyer_type,
            guest_full_name=full_name,
            guest_email=email,
            quantity=form.quantity.data,
            payment_method=form.payment_method.data,
            status="recorded",
        )
        db.session.add(order)
        db.session.commit()
        flash("Spectator ticket purchase recorded.", "success")
        return redirect(url_for("user.spectator_tickets", event_id=event.id))
    return render_template("user/spectator_tickets.html", event=event, form=form)


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
    ticket_type_by_event = {}
    for event in events:
        ticket_type_by_event[event.id] = _get_or_create_default_ticket_type(event)
    return render_template(
        "user/spectator_events.html",
        events=events,
        q=q,
        ticket_type_by_event=ticket_type_by_event,
        money=_money,
    )


@user_bp.route("/spectator/cart/add", methods=["POST"])
def spectator_cart_add():
    event_id = request.form.get("event_id", type=int)
    quantity = request.form.get("quantity", type=int) or 1
    event = Event.query.get_or_404(event_id)
    ticket_type = _get_or_create_default_ticket_type(event)
    quantity = max(1, min(quantity, ticket_type.max_per_order or 10))
    cart = _get_or_create_spectator_cart()
    existing = SpectatorCartItem.query.filter_by(
        cart_id=cart.id, event_id=event.id, ticket_type_id=ticket_type.id
    ).first()
    if existing:
        existing.quantity = min((existing.quantity or 0) + quantity, ticket_type.max_per_order or 10)
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
    flash("Added tickets to cart.", "success")
    return redirect(url_for("user.spectator_cart"))


@user_bp.route("/spectator/cart")
def spectator_cart():
    cart = _get_or_create_spectator_cart()
    items = SpectatorCartItem.query.filter_by(cart_id=cart.id).all()
    rows = []
    subtotal_cents = 0
    for item in items:
        unit = item.ticket_type.price_cents if item.ticket_type else 0
        line = unit * item.quantity
        subtotal_cents += line
        rows.append({"item": item, "unit": unit, "line": line})
    return render_template(
        "user/spectator_cart.html",
        cart=cart,
        rows=rows,
        subtotal_cents=subtotal_cents,
        money=_money,
    )


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
    subtotal_cents = 0
    rows = []
    for item in items:
        unit = item.ticket_type.price_cents if item.ticket_type else 0
        line = unit * item.quantity
        subtotal_cents += line
        rows.append({"item": item, "unit": unit, "line": line})

    form = SpectatorCheckoutForm()
    if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user" and request.method == "GET":
        form.full_name.data = f"{current_user.first_name} {current_user.last_name}".strip()
        form.email.data = current_user.email

    if form.validate_on_submit():
        user_id = current_user.id if current_user.is_authenticated and getattr(current_user, "account_type", None) == "user" else None
        order = SpectatorOrder(
            order_number=f"SP-{secrets.token_hex(4).upper()}",
            user_id=user_id,
            guest_full_name=form.full_name.data.strip(),
            guest_email=form.email.data.strip().lower(),
            payment_method=form.payment_method.data,
            status="recorded",
            total_cents=subtotal_cents,
        )
        db.session.add(order)
        db.session.flush()
        for row in rows:
            item = row["item"]
            db.session.add(
                SpectatorOrderItem(
                    order_id=order.id,
                    event_id=item.event_id,
                    ticket_type_name=item.ticket_type.name if item.ticket_type else "General Admission",
                    unit_price_cents=row["unit"],
                    quantity=item.quantity,
                    line_total_cents=row["line"],
                )
            )
            db.session.add(
                SpectatorTicketOrder(
                    event_id=item.event_id,
                    user_id=user_id,
                    buyer_type="user" if user_id else "guest",
                    guest_full_name=form.full_name.data.strip(),
                    guest_email=form.email.data.strip().lower(),
                    quantity=item.quantity,
                    payment_method=form.payment_method.data,
                    status="recorded",
                )
            )
            db.session.delete(item)
        db.session.commit()
        flash(f"Order {order.order_number} recorded successfully.", "success")
        return redirect(url_for("user.spectator_order_success", order_id=order.id))

    return render_template(
        "user/spectator_checkout.html",
        form=form,
        rows=rows,
        subtotal_cents=subtotal_cents,
        money=_money,
    )


@user_bp.route("/spectator/order/<int:order_id>")
def spectator_order_success(order_id):
    order = SpectatorOrder.query.get_or_404(order_id)
    items = SpectatorOrderItem.query.filter_by(order_id=order.id).all()
    return render_template("user/spectator_order_success.html", order=order, items=items, money=_money)


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
    if EventRegistration.query.filter_by(event_id=event.id, user_id=current_user.id).first():
        flash("Already signed up for this event.", "error")
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
        if not selected_car.static_qr_code:
            selected_car.static_qr_code = _generate_car_qr_code()
        reg = EventRegistration(
            event_id=event.id,
            user_id=current_user.id,
            car_id=selected_car.id,
            checkin_code=selected_car.static_qr_code,
        )
        db.session.add(reg)
        track_class = TrackDriverClass.query.filter_by(
            track_id=event.track_id, user_id=current_user.id
        ).first()
        if not track_class:
            db.session.add(
                TrackDriverClass(track_id=event.track_id, user_id=current_user.id, driver_class="C")
            )
        db.session.commit()
        post = SocialPost(
            user_id=current_user.id,
            event_id=event.id,
            event_registration_id=reg.id,
            post_type="event_signup",
            title=f"@{current_user.username} signed up for {event.event_name}",
            body=f"Driving: {selected_car.car_year} {selected_car.make} {selected_car.model}",
        )
        db.session.add(post)
        db.session.commit()

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
                driver_id=current_user.id,
                event_id=event.id,
                waiver_template_id=template.id,
            ).first()
            if not exists:
                new_waiver = DriverWaiver(
                    track_id=event.track_id,
                    driver_id=current_user.id,
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
        db.session.commit()
        if needs_waiver_action and created_waiver_id:
            flash("Signed up successfully. Please sign the waiver to complete check-in.", "success")
            return redirect(url_for("waiver.driver_sign_waiver", driver_waiver_id=created_waiver_id))
        flash("Signed up successfully.", "success")
    else:
        flash("Please choose a valid car.", "error")
    return redirect(url_for("user.dashboard"))


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
