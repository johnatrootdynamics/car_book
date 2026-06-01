from datetime import date, datetime
import base64
from io import BytesIO
from decimal import Decimal

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from .forms import EmployeeCreateForm, EventForm, InspectionForm, InspectionRuleForm, TrackProfileForm
from .models import (
    Employee,
    Event,
    EventClassSlot,
    EventRegistration,
    Inspection,
    InspectionItem,
    InspectionRule,
    RunGroup,
    RunGroupAssignment,
    SpectatorOrder,
    SpectatorOrderItem,
    SpectatorTicketType,
    SpectatorTicketOrder,
    Track,
    TrackDriverClass,
    TrackLayout,
    TrackWaiverTemplate,
    User,
    db,
)
from .services.boldsign_service import create_embedded_template_url
from .services.boldsign_service import delete_template as boldsign_delete_template
from .services.storage_service import upload_public_image


employee_bp = Blueprint("employee", __name__, url_prefix="/employee")


def require_employee():
    if not current_user.is_authenticated:
        flash("Please sign in as a track employee.", "error")
        return redirect(url_for("auth.employee_login"))
    if current_user.account_type == "admin":
        if session.get("impersonate_track_id"):
            return None
        flash("Choose a track to impersonate first.", "error")
        return redirect(url_for("admin.dashboard"))
    if current_user.account_type != "employee":
        flash("Employee access required for that page.", "error")
        return redirect(url_for("user.dashboard"))
    return None


def active_track_id():
    if current_user.account_type == "admin":
        return int(session.get("impersonate_track_id"))
    return current_user.track_id


def _get_or_create_track_driver_class(track_id, user_id):
    record = TrackDriverClass.query.filter_by(track_id=track_id, user_id=user_id).first()
    if not record:
        record = TrackDriverClass(track_id=track_id, user_id=user_id, driver_class="C")
        db.session.add(record)
        db.session.flush()
    return record


def _create_track_layout_from_upload(track_id, name, file_storage):
    layout = TrackLayout(track_id=track_id, name=name)
    clean_name = secure_filename(file_storage.filename)
    file_storage.filename = clean_name
    layout.image_path = upload_public_image(
        file_storage,
        bucket=current_app.config["S3_BUCKET"],
        endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
        access_key=current_app.config["S3_ACCESS_KEY"],
        secret_key=current_app.config["S3_SECRET_KEY"],
        key_prefix=f"track_layouts/{track_id}",
    )
    db.session.add(layout)
    db.session.flush()
    return layout


def _apply_event_layout_selection(event, track_id):
    mode = (request.form.get("layout_mode") or "default").strip().lower()
    if mode == "default":
        event.track_layout_id = None
        return None
    if mode == "existing":
        layout_id = request.form.get("track_layout_id", type=int) or 0
        if not layout_id:
            event.track_layout_id = None
            return None
        selected = TrackLayout.query.filter_by(id=layout_id, track_id=track_id).first()
        if not selected:
            return "Selected layout is invalid."
        event.track_layout_id = selected.id
        return None
    if mode == "upload":
        upload = request.files.get("event_layout_upload")
        if not upload or not getattr(upload, "filename", ""):
            return "Please upload a layout image."
        event_name_fallback = (request.form.get("event_name") or "").strip()
        name = (request.form.get("event_layout_name_upload") or "").strip() or event_name_fallback or f"Uploaded Layout {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        layout = _create_track_layout_from_upload(track_id, name, upload)
        event.track_layout_id = layout.id
        return None
    if mode == "draw":
        drawing_data = (request.form.get("event_layout_drawing") or "").strip()
        if not drawing_data.startswith("data:image/png;base64,"):
            return "Please draw a layout before saving."
        try:
            raw = base64.b64decode(drawing_data.split(",", 1)[1])
        except Exception:
            return "Could not process drawn layout image."
        drawing_file = FileStorage(
            stream=BytesIO(raw),
            filename="drawn_layout.png",
            content_type="image/png",
        )
        event_name_fallback = (request.form.get("event_name") or "").strip()
        name = (request.form.get("event_layout_name_draw") or "").strip() or event_name_fallback or f"Drawn Layout {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        layout = _create_track_layout_from_upload(track_id, name, drawing_file)
        event.track_layout_id = layout.id
        return None
    return "Invalid layout selection mode."


def _to_cents(value):
    if value is None:
        return 0
    return int((Decimal(value) * 100).quantize(Decimal("1")))


def _sync_default_spectator_ticket_type(event):
    ticket_type = (
        SpectatorTicketType.query.filter_by(event_id=event.id)
        .order_by(SpectatorTicketType.created_at.asc())
        .first()
    )
    if ticket_type:
        ticket_type.name = ticket_type.name or "General Admission"
        ticket_type.price_cents = max(0, event.spectator_price_cents or 0)
        ticket_type.is_active = True
        if not ticket_type.max_per_order:
            ticket_type.max_per_order = 10
        return
    db.session.add(
        SpectatorTicketType(
            event_id=event.id,
            name="General Admission",
            price_cents=max(0, event.spectator_price_cents or 0),
            is_active=True,
            max_per_order=10,
        )
    )


@employee_bp.route("/dashboard")
@login_required
def dashboard():
    guard = require_employee()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    upcoming_events = (
        Event.query.filter(
            Event.track_id == active_track_id(),
            Event.event_date >= date.today(),
        )
        .order_by(Event.event_date.asc())
        .all()
    )
    past_events = (
        Event.query.filter(
            Event.track_id == active_track_id(),
            Event.event_date < date.today(),
        )
        .order_by(Event.event_date.desc())
        .all()
    )
    signup_counts_raw = (
        db.session.query(EventRegistration.event_id, func.count(EventRegistration.id))
        .join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == active_track_id())
        .group_by(EventRegistration.event_id)
        .all()
    )
    signup_counts = {event_id: count for event_id, count in signup_counts_raw}
    last_event = past_events[0] if past_events else None
    last_event_participants = signup_counts.get(last_event.id, 0) if last_event else 0
    last_event_spectator_tickets = 0
    if last_event:
        tickets_sum = (
            db.session.query(func.coalesce(func.sum(SpectatorTicketOrder.quantity), 0))
            .filter(SpectatorTicketOrder.event_id == last_event.id)
            .scalar()
        )
        last_event_spectator_tickets = int(tickets_sum or 0)
    return render_template(
        "employee/dashboard.html",
        upcoming_events=upcoming_events,
        past_events=past_events,
        track=track,
        signup_counts=signup_counts,
        last_event=last_event,
        last_event_participants=last_event_participants,
        last_event_spectator_tickets=last_event_spectator_tickets,
    )


@employee_bp.route("/events")
@login_required
def events_index():
    guard = require_employee()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    upcoming_events = (
        Event.query.filter(
            Event.track_id == active_track_id(),
            Event.event_date >= date.today(),
        )
        .order_by(Event.event_date.asc())
        .all()
    )
    past_events = (
        Event.query.filter(
            Event.track_id == active_track_id(),
            Event.event_date < date.today(),
        )
        .order_by(Event.event_date.desc())
        .all()
    )
    signup_counts_raw = (
        db.session.query(EventRegistration.event_id, func.count(EventRegistration.id))
        .join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == active_track_id())
        .group_by(EventRegistration.event_id)
        .all()
    )
    signup_counts = {event_id: count for event_id, count in signup_counts_raw}
    return render_template(
        "employee/events_index.html",
        track=track,
        upcoming_events=upcoming_events,
        past_events=past_events,
        signup_counts=signup_counts,
    )


@employee_bp.route("/track-profile", methods=["GET"])
@login_required
def track_profile():
    guard = require_employee()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    form = TrackProfileForm(obj=track)
    layouts = TrackLayout.query.filter_by(track_id=track.id).order_by(TrackLayout.name.asc()).all()
    return render_template("employee/track_profile.html", track=track, form=form, layouts=layouts)


@employee_bp.route("/staff-accounts", methods=["GET"])
@login_required
def staff_accounts():
    guard = require_employee()
    if guard:
        return guard
    form = EmployeeCreateForm()
    staff = Employee.query.filter_by(track_id=active_track_id()).order_by(Employee.created_at.desc()).all()
    return render_template("employee/staff_accounts.html", form=form, staff=staff)


@employee_bp.route("/track", methods=["POST"])
@login_required
def update_track():
    guard = require_employee()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    form = TrackProfileForm()
    if form.validate_on_submit():
        track.name = form.name.data.strip()
        track.city = form.city.data.strip()
        track.state = form.state.data.strip()
        track.spectator_payment_provider = (form.spectator_payment_provider.data or "stripe").strip()
        stripe_secret = (form.stripe_secret_key.data or "").strip()
        stripe_webhook_secret = (form.stripe_webhook_secret.data or "").strip()
        if stripe_secret:
            track.stripe_secret_key = stripe_secret
        if stripe_webhook_secret:
            track.stripe_webhook_secret = stripe_webhook_secret
        upload = form.layout_image.data
        if upload:
            clean_name = secure_filename(upload.filename)
            upload.filename = clean_name
            track.layout_image_path = upload_public_image(
                upload,
                bucket=current_app.config["S3_BUCKET"],
                endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
                access_key=current_app.config["S3_ACCESS_KEY"],
                secret_key=current_app.config["S3_SECRET_KEY"],
                key_prefix=f"tracks/{track.id}",
            )
        db.session.commit()
        flash("Track profile updated.", "success")
    else:
        flash("Could not update track profile. Check form fields.", "error")
    return redirect(url_for("employee.dashboard"))


@employee_bp.route("/track-layouts/new", methods=["POST"])
@login_required
def track_layout_new():
    guard = require_employee()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    name = (request.form.get("name") or "").strip()
    mode = (request.form.get("layout_mode") or "upload").strip().lower()
    upload = request.files.get("image")
    drawing_data = (request.form.get("layout_drawing") or "").strip()
    if not name:
        flash("Layout name is required.", "error")
        return redirect(url_for("employee.track_profile"))
    existing = TrackLayout.query.filter_by(track_id=track.id, name=name).first()
    if existing:
        flash("A layout with that name already exists.", "error")
        return redirect(url_for("employee.track_profile"))
    layout = TrackLayout(track_id=track.id, name=name)
    if mode == "draw":
        if not drawing_data.startswith("data:image/png;base64,"):
            flash("Please draw a layout before saving.", "error")
            return redirect(url_for("employee.track_profile"))
        try:
            raw = base64.b64decode(drawing_data.split(",", 1)[1])
        except Exception:
            flash("Could not process drawn layout image.", "error")
            return redirect(url_for("employee.track_profile"))
        draw_file = FileStorage(
            stream=BytesIO(raw),
            filename="drawn_layout.png",
            content_type="image/png",
        )
        clean_name = secure_filename(draw_file.filename)
        draw_file.filename = clean_name
        layout.image_path = upload_public_image(
            draw_file,
            bucket=current_app.config["S3_BUCKET"],
            endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
            access_key=current_app.config["S3_ACCESS_KEY"],
            secret_key=current_app.config["S3_SECRET_KEY"],
            key_prefix=f"track_layouts/{track.id}",
        )
    elif mode == "default":
        if not track.layout_image_path:
            flash("No default track layout image available to copy.", "error")
            return redirect(url_for("employee.track_profile"))
        layout.image_path = track.layout_image_path
    else:
        if not upload or not getattr(upload, "filename", ""):
            flash("Please upload a layout image.", "error")
            return redirect(url_for("employee.track_profile"))
        clean_name = secure_filename(upload.filename)
        upload.filename = clean_name
        layout.image_path = upload_public_image(
            upload,
            bucket=current_app.config["S3_BUCKET"],
            endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
            access_key=current_app.config["S3_ACCESS_KEY"],
            secret_key=current_app.config["S3_SECRET_KEY"],
            key_prefix=f"track_layouts/{track.id}",
        )
    db.session.add(layout)
    db.session.commit()
    flash("Track layout created.", "success")
    return redirect(url_for("employee.track_profile"))


@employee_bp.route("/track-layouts/<int:layout_id>/delete", methods=["POST"])
@login_required
def track_layout_delete(layout_id):
    guard = require_employee()
    if guard:
        return guard
    layout = TrackLayout.query.filter_by(id=layout_id, track_id=active_track_id()).first_or_404()
    events_using_layout = Event.query.filter_by(track_layout_id=layout.id).count()
    if events_using_layout:
        flash("Cannot delete this layout while events use it.", "error")
        return redirect(url_for("employee.track_profile"))
    db.session.delete(layout)
    db.session.commit()
    flash("Track layout deleted.", "success")
    return redirect(url_for("employee.track_profile"))


@employee_bp.route("/employees/new", methods=["POST"])
@login_required
def create_employee():
    guard = require_employee()
    if guard:
        return guard
    form = EmployeeCreateForm()
    if form.validate_on_submit():
        existing = Employee.query.filter_by(email=form.email.data.lower().strip()).first()
        if existing:
            flash("Employee email already exists.", "error")
        else:
            employee = Employee(
                track_id=active_track_id(),
                full_name=form.full_name.data.strip(),
                email=form.email.data.lower().strip(),
                password_hash=generate_password_hash(form.password.data),
            )
            db.session.add(employee)
            db.session.commit()
            flash("Employee account created.", "success")
    else:
        flash("Could not create employee account.", "error")
    return redirect(url_for("employee.dashboard"))


@employee_bp.route("/events/new", methods=["GET", "POST"])
@login_required
def event_new():
    guard = require_employee()
    if guard:
        return guard
    form = EventForm()
    layouts = TrackLayout.query.filter_by(track_id=active_track_id()).order_by(TrackLayout.name.asc()).all()
    form.track_layout_id.choices = [(0, "Default Track Layout")] + [
        (layout.id, layout.name) for layout in layouts
    ]
    if request.method == "GET":
        form.driver_price.data = Decimal("0.00")
        form.spectator_price.data = Decimal("25.00")
    if form.validate_on_submit():
        if form.event_start_time.data and form.event_end_time.data:
            if form.event_end_time.data <= form.event_start_time.data:
                flash("Event end time must be after start time.", "error")
                return render_template("employee/event_form.html", form=form, title="Create Event")
        event = Event(
            track_id=active_track_id(),
            event_name=form.event_name.data.strip(),
            event_date=form.event_date.data,
            driver_price_cents=_to_cents(form.driver_price.data),
            spectator_price_cents=_to_cents(form.spectator_price.data),
            event_start_time=form.event_start_time.data,
            event_end_time=form.event_end_time.data,
        )
        layout_error = _apply_event_layout_selection(event, active_track_id())
        if layout_error:
            flash(layout_error, "error")
            return render_template("employee/event_form.html", form=form, title="Create Event", track_layouts=layouts, event=None)
        upload = form.thumbnail_image.data
        if upload:
            clean_name = secure_filename(upload.filename)
            upload.filename = clean_name
            event.thumbnail_image_path = upload_public_image(
                upload,
                bucket=current_app.config["S3_BUCKET"],
                endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
                access_key=current_app.config["S3_ACCESS_KEY"],
                secret_key=current_app.config["S3_SECRET_KEY"],
                key_prefix=f"events/{active_track_id()}",
            )
        db.session.add(event)
        db.session.flush()
        _sync_default_spectator_ticket_type(event)
        db.session.commit()
        flash("Event created.", "success")
        return redirect(url_for("employee.dashboard"))
    return render_template("employee/event_form.html", form=form, title="Create Event", track_layouts=layouts, event=None)


@employee_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def event_edit(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    form = EventForm(obj=event)
    layouts = TrackLayout.query.filter_by(track_id=active_track_id()).order_by(TrackLayout.name.asc()).all()
    form.track_layout_id.choices = [(0, "Default Track Layout")] + [
        (layout.id, layout.name) for layout in layouts
    ]
    if request.method == "GET":
        form.track_layout_id.data = event.track_layout_id or 0
        form.driver_price.data = Decimal(event.driver_price_cents or 0) / Decimal(100)
        form.spectator_price.data = Decimal(event.spectator_price_cents or 0) / Decimal(100)
    if form.validate_on_submit():
        if form.event_start_time.data and form.event_end_time.data:
            if form.event_end_time.data <= form.event_start_time.data:
                flash("Event end time must be after start time.", "error")
                return render_template("employee/event_form.html", form=form, title="Edit Event")
        layout_error = _apply_event_layout_selection(event, active_track_id())
        if layout_error:
            flash(layout_error, "error")
            return render_template("employee/event_form.html", form=form, title="Edit Event", track_layouts=layouts, event=event)
        event.event_name = form.event_name.data.strip()
        event.event_date = form.event_date.data
        event.driver_price_cents = _to_cents(form.driver_price.data)
        event.spectator_price_cents = _to_cents(form.spectator_price.data)
        event.event_start_time = form.event_start_time.data
        event.event_end_time = form.event_end_time.data
        upload = form.thumbnail_image.data
        if upload:
            clean_name = secure_filename(upload.filename)
            upload.filename = clean_name
            event.thumbnail_image_path = upload_public_image(
                upload,
                bucket=current_app.config["S3_BUCKET"],
                endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
                access_key=current_app.config["S3_ACCESS_KEY"],
                secret_key=current_app.config["S3_SECRET_KEY"],
                key_prefix=f"events/{active_track_id()}",
            )
        _sync_default_spectator_ticket_type(event)
        db.session.commit()
        flash("Event updated.", "success")
        return redirect(url_for("employee.dashboard"))
    return render_template("employee/event_form.html", form=form, title="Edit Event", track_layouts=layouts, event=event)


@employee_bp.route("/events/<int:event_id>/delete", methods=["POST"])
@login_required
def event_delete(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    db.session.delete(event)
    db.session.commit()
    flash("Event deleted.", "success")
    return redirect(url_for("employee.events_index"))


@employee_bp.route("/events/<int:event_id>/participants")
@login_required
def participants(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    regs = EventRegistration.query.filter_by(event_id=event.id).order_by(EventRegistration.created_at.asc()).all()
    inspections = {
        inspection.event_registration_id: inspection
        for inspection in Inspection.query.join(EventRegistration, EventRegistration.id == Inspection.event_registration_id)
        .filter(EventRegistration.event_id == event.id)
        .all()
    }
    from .waiver_routes import get_required_waiver_status

    waiver_status = {}
    class_by_user = {}
    for reg in regs:
        status, waiver = get_required_waiver_status(event.track_id, reg.user_id, event.id)
        waiver_status[reg.id] = {"status": status, "waiver": waiver}
        class_by_user[reg.user_id] = _get_or_create_track_driver_class(event.track_id, reg.user_id).driver_class
    db.session.commit()
    return render_template(
        "employee/participants.html",
        event=event,
        registrations=regs,
        inspections=inspections,
        waiver_status=waiver_status,
        class_by_user=class_by_user,
    )


@employee_bp.route("/events/<int:event_id>")
@login_required
def event_detail(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    track_layouts = TrackLayout.query.filter_by(track_id=event.track_id).order_by(TrackLayout.name.asc()).all()

    regs = EventRegistration.query.filter_by(event_id=event.id).order_by(EventRegistration.created_at.asc()).all()

    signup_by_day = (
        db.session.query(func.date(EventRegistration.created_at), func.count(EventRegistration.id))
        .filter(EventRegistration.event_id == event.id)
        .group_by(func.date(EventRegistration.created_at))
        .order_by(func.date(EventRegistration.created_at).asc())
        .all()
    )
    signup_trend = [{"day": str(day), "count": count} for day, count in signup_by_day]

    class_counts = {"A": 0, "B": 0, "C": 0}
    for reg in regs:
        dc = _get_or_create_track_driver_class(event.track_id, reg.user_id).driver_class
        if dc not in class_counts:
            class_counts[dc] = 0
        class_counts[dc] += 1
    db.session.commit()

    view = (request.args.get("view") or "general").strip().lower()
    if view not in {"general", "analytics", "participants", "inspect", "slots", "tickets"}:
        view = "general"

    groups = []
    assignments = {}
    participants = []
    class_by_user = {}
    inspections = {}
    class_slots = []
    ticket_orders = []
    ticket_query = (request.args.get("ticket_q") or "").strip()

    if view == "participants":
        participants = (
            EventRegistration.query.filter_by(event_id=event.id)
            .order_by(EventRegistration.created_at.asc())
            .all()
        )
        inspections = {
            inspection.event_registration_id: inspection
            for inspection in Inspection.query.join(
                EventRegistration, EventRegistration.id == Inspection.event_registration_id
            )
            .filter(EventRegistration.event_id == event.id)
            .all()
        }
        for reg in participants:
            class_by_user[reg.user_id] = _get_or_create_track_driver_class(event.track_id, reg.user_id).driver_class
        db.session.commit()

    if view == "slots":
        class_slots = (
            EventClassSlot.query.filter_by(event_id=event.id)
            .order_by(EventClassSlot.start_time.asc())
            .all()
        )

    if view == "tickets":
        query = (
            SpectatorOrder.query.join(SpectatorOrderItem, SpectatorOrderItem.order_id == SpectatorOrder.id)
            .filter(SpectatorOrderItem.event_id == event.id)
            .distinct()
            .order_by(SpectatorOrder.created_at.desc())
        )
        if ticket_query:
            like = f"%{ticket_query}%"
            query = query.filter(
                (SpectatorOrder.order_number.ilike(like))
                | (SpectatorOrder.guest_full_name.ilike(like))
                | (SpectatorOrder.guest_email.ilike(like))
            )
        ticket_orders = query.limit(100).all()

    return render_template(
        "employee/event_detail.html",
        event=event,
        track_layouts=track_layouts,
        total_signups=len(regs),
        signup_trend=signup_trend,
        class_counts=class_counts,
        view=view,
        groups=groups,
        assignments=assignments,
        participants=participants,
        class_by_user=class_by_user,
        inspections=inspections,
        class_slots=class_slots,
        ticket_orders=ticket_orders,
        ticket_query=ticket_query,
    )


@employee_bp.route("/events/<int:event_id>/slots/new", methods=["POST"])
@login_required
def event_slot_new(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    class_code = (request.form.get("class_code") or "").strip().upper()
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    if class_code not in {"A", "B", "C"} or not start_time or not end_time:
        flash("Class, start time, and end time are required.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
    try:
        start_time_value = datetime.strptime(start_time, "%H:%M").time()
        end_time_value = datetime.strptime(end_time, "%H:%M").time()
    except ValueError:
        flash("Invalid time value.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
    if end_time_value <= start_time_value:
        flash("End time must be after start time.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
    overlap = (
        EventClassSlot.query.filter(
            EventClassSlot.event_id == event.id,
            EventClassSlot.start_time < end_time_value,
            EventClassSlot.end_time > start_time_value,
        )
        .first()
    )
    if overlap:
        flash("Class slots cannot overlap. Choose a different time window.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
    db.session.add(
        EventClassSlot(
            event_id=event.id,
            class_code=class_code,
            start_time=start_time_value,
            end_time=end_time_value,
        )
    )
    db.session.commit()
    flash("Class slot created.", "success")
    return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))


@employee_bp.route("/events/<int:event_id>/slots/save", methods=["POST"])
@login_required
def event_slot_save(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    class_code = (request.form.get("class_code") or "").strip().upper()
    slot_id = request.form.get("slot_id", type=int)
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    if class_code not in {"A", "B", "C"} or not start_time or not end_time:
        flash("Class, start time, and end time are required.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
    try:
        start_time_value = datetime.strptime(start_time, "%H:%M").time()
        end_time_value = datetime.strptime(end_time, "%H:%M").time()
    except ValueError:
        flash("Invalid time value.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
    if end_time_value <= start_time_value:
        flash("End time must be after start time.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
    if not event.event_start_time or not event.event_end_time:
        flash("Set event start and end time first in General.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
    if start_time_value < event.event_start_time or end_time_value > event.event_end_time:
        flash("Class slots must be within the event time window.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))

    overlap_query = EventClassSlot.query.filter(
        EventClassSlot.event_id == event.id,
        EventClassSlot.start_time < end_time_value,
        EventClassSlot.end_time > start_time_value,
    )
    if slot_id:
        overlap_query = overlap_query.filter(EventClassSlot.id != slot_id)
    overlap = overlap_query.first()
    if overlap:
        flash("Class slots cannot overlap. Choose a different time window.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))

    if slot_id:
        slot = EventClassSlot.query.filter_by(
            id=slot_id, event_id=event.id, class_code=class_code
        ).first()
        if not slot:
            flash("Slot not found.", "error")
            return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))
        slot.start_time = start_time_value
        slot.end_time = end_time_value
    else:
        db.session.add(
            EventClassSlot(
                event_id=event.id,
                class_code=class_code,
                start_time=start_time_value,
                end_time=end_time_value,
            )
        )
    db.session.commit()
    flash(f"Class {class_code} slot saved.", "success")
    return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))


@employee_bp.route("/events/<int:event_id>/slots/<int:slot_id>/delete", methods=["POST"])
@login_required
def event_slot_delete(event_id, slot_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    slot = EventClassSlot.query.filter_by(id=slot_id, event_id=event.id).first_or_404()
    db.session.delete(slot)
    db.session.commit()
    flash("Class slot deleted.", "success")
    return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))


@employee_bp.route("/events/<int:event_id>/tickets/<int:item_id>/checkin", methods=["POST"])
@login_required
def ticket_checkin(event_id, item_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    item = SpectatorOrderItem.query.filter_by(id=item_id, event_id=event.id).first_or_404()
    if item.checked_in_at:
        flash("Ticket already checked in.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="tickets"))
    item.checked_in_at = datetime.utcnow()
    if current_user.account_type == "employee":
        item.checked_in_by_employee_id = current_user.id
    db.session.commit()
    flash("Spectator ticket checked in.", "success")
    return redirect(url_for("employee.event_detail", event_id=event.id, view="tickets"))


@employee_bp.route("/events/<int:event_id>/run-groups")
@login_required
def run_groups(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    query = (request.args.get("q") or "").strip().lower()

    groups = (
        RunGroup.query.filter_by(event_id=event.id)
        .order_by(RunGroup.is_active.desc(), RunGroup.name.asc())
        .all()
    )
    registrations = (
        EventRegistration.query.filter_by(event_id=event.id)
        .order_by(EventRegistration.created_at.asc())
        .all()
    )

    class_by_user = {}
    for reg in registrations:
        class_by_user[reg.user_id] = _get_or_create_track_driver_class(event.track_id, reg.user_id).driver_class

    assignments = {
        item.event_registration_id: item.run_group_id
        for item in RunGroupAssignment.query.join(
            RunGroup, RunGroup.id == RunGroupAssignment.run_group_id
        )
        .filter(RunGroup.event_id == event.id)
        .all()
    }
    db.session.commit()

    if query:
        registrations = [
            reg
            for reg in registrations
            if query in f"{reg.user.first_name} {reg.user.last_name}".lower()
            or query in (reg.user.email or "").lower()
            or query in (reg.user.username or "").lower()
        ]

    return render_template(
        "employee/run_groups.html",
        event=event,
        groups=groups,
        registrations=registrations,
        assignments=assignments,
        class_by_user=class_by_user,
        q=query,
    )


@employee_bp.route("/events/<int:event_id>/run-groups/new", methods=["POST"])
@login_required
def run_group_new(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Run group name is required.", "error")
        return redirect(url_for("employee.run_groups", event_id=event.id))
    exists = RunGroup.query.filter_by(event_id=event.id, name=name).first()
    if exists:
        flash("Run group name already exists for this event.", "error")
        return redirect(url_for("employee.run_groups", event_id=event.id))
    db.session.add(RunGroup(event_id=event.id, name=name, is_active=True))
    db.session.commit()
    flash("Run group created.", "success")
    return redirect(url_for("employee.run_groups", event_id=event.id))


@employee_bp.route("/events/<int:event_id>/run-groups/<int:group_id>/rename", methods=["POST"])
@login_required
def run_group_rename(event_id, group_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    group = RunGroup.query.filter_by(id=group_id, event_id=event.id).first_or_404()
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Run group name is required.", "error")
        return redirect(url_for("employee.run_groups", event_id=event.id))
    group.name = name
    db.session.commit()
    flash("Run group renamed.", "success")
    return redirect(url_for("employee.run_groups", event_id=event.id))


@employee_bp.route("/events/<int:event_id>/run-groups/<int:group_id>/toggle", methods=["POST"])
@login_required
def run_group_toggle(event_id, group_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    group = RunGroup.query.filter_by(id=group_id, event_id=event.id).first_or_404()
    db.session.delete(group)
    db.session.commit()
    flash("Run group deleted.", "success")
    return redirect(url_for("employee.run_groups", event_id=event.id))


@employee_bp.route("/events/<int:event_id>/run-groups/assign", methods=["POST"])
@login_required
def run_group_assign(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    registration_id = request.form.get("registration_id", type=int)
    group_id = request.form.get("group_id", type=int)

    registration = EventRegistration.query.filter_by(id=registration_id, event_id=event.id).first_or_404()
    existing = RunGroupAssignment.query.filter_by(event_registration_id=registration.id).first()
    if group_id:
        group = RunGroup.query.filter_by(id=group_id, event_id=event.id).first_or_404()
        if existing:
            existing.run_group_id = group.id
        else:
            db.session.add(
                RunGroupAssignment(run_group_id=group.id, event_registration_id=registration.id)
            )
        flash("Driver assigned to run group.", "success")
    else:
        if existing:
            db.session.delete(existing)
        flash("Driver removed from run group.", "success")
    db.session.commit()
    return redirect(url_for("employee.run_groups", event_id=event.id))


@employee_bp.route("/events/<int:event_id>/run-groups/generate", methods=["POST"])
@login_required
def run_group_generate(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    force = request.form.get("force") == "1"

    default_names = ["A", "B", "C"]
    group_by_name = {
        group.name: group
        for group in RunGroup.query.filter_by(event_id=event.id).all()
    }
    for name in default_names:
        if name not in group_by_name:
            group = RunGroup(event_id=event.id, name=name, is_active=True)
            db.session.add(group)
            db.session.flush()
            group_by_name[name] = group

    registrations = EventRegistration.query.filter_by(event_id=event.id).all()
    for reg in registrations:
        driver_class = _get_or_create_track_driver_class(event.track_id, reg.user_id).driver_class
        target_group = group_by_name.get(driver_class) or group_by_name["C"]
        existing = RunGroupAssignment.query.filter_by(event_registration_id=reg.id).first()
        if existing and not force:
            continue
        if existing:
            existing.run_group_id = target_group.id
        else:
            db.session.add(
                RunGroupAssignment(run_group_id=target_group.id, event_registration_id=reg.id)
            )

    db.session.commit()
    flash("Run groups generated from driver classes.", "success")
    return redirect(url_for("employee.run_groups", event_id=event.id))


@employee_bp.route("/events/<int:event_id>/inspect-search")
@login_required
def inspect_search(event_id):
    guard = require_employee()
    if guard:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": True, "rows": []}), 200

    like = f"%{q}%"
    rows = (
        EventRegistration.query.join(User, User.id == EventRegistration.user_id)
        .outerjoin(Inspection, Inspection.event_registration_id == EventRegistration.id)
        .filter(
            EventRegistration.event_id == event.id,
            ((Inspection.id.is_(None)) | (Inspection.passed.is_(False))),
            (User.first_name.ilike(like))
            | (User.last_name.ilike(like))
            | (User.username.ilike(like)),
            
        )
        .order_by(User.first_name.asc(), User.last_name.asc())
        .limit(15)
        .all()
    )

    code_rows = (
        EventRegistration.query.outerjoin(
            Inspection, Inspection.event_registration_id == EventRegistration.id
        ).filter(
            EventRegistration.event_id == event.id,
            ((Inspection.id.is_(None)) | (Inspection.passed.is_(False))),
            EventRegistration.checkin_code.ilike(like),
        )
        .order_by(EventRegistration.created_at.asc())
        .limit(15)
        .all()
    )

    reg_map = {reg.id: reg for reg in rows}
    for reg in code_rows:
        reg_map[reg.id] = reg
    rows = list(reg_map.values())

    from .waiver_routes import get_required_waiver_status

    payload = []
    for reg in rows:
        waiver_status, _ = get_required_waiver_status(event.track_id, reg.user_id, event.id)
        payload.append(
            {
                "registration_id": reg.id,
                "driver_name": f"{reg.user.first_name} {reg.user.last_name}".strip(),
                "username": reg.user.username or f"driver{reg.user.id}",
                "car": f"{reg.car.car_year} {reg.car.make} {reg.car.model}",
                "checkin_code": reg.checkin_code,
                "waiver_ok": waiver_status in {"signed", "not_required"},
                "inspect_url": url_for(
                    "employee.inspect_registration", event_id=event.id, registration_id=reg.id
                ),
            }
        )

    return jsonify({"ok": True, "rows": payload}), 200


@employee_bp.route("/tracks/<int:track_id>/drivers/search")
@login_required
def search_track_drivers(track_id):
    guard = require_employee()
    if guard:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    if track_id != active_track_id():
        return jsonify({"ok": False, "error": "forbidden"}), 403

    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": True, "drivers": []}), 200

    like = f"%{q}%"
    rows = (
        TrackDriverClass.query.join(User, User.id == TrackDriverClass.user_id)
        .filter(
            TrackDriverClass.track_id == track_id,
            (User.first_name.ilike(like))
            | (User.last_name.ilike(like))
            | (User.email.ilike(like))
            | (User.username.ilike(like)),
        )
        .order_by(User.first_name.asc(), User.last_name.asc())
        .limit(20)
        .all()
    )

    payload = []
    for item in rows:
        full_name = f"{item.user.first_name} {item.user.last_name}".strip()
        payload.append(
            {
                "user_id": item.user_id,
                "name": full_name,
                "email": item.user.email,
                "driver_class": item.driver_class,
                "update_url": url_for("employee.update_driver_class", track_id=track_id, user_id=item.user_id),
            }
        )

    return jsonify({"ok": True, "drivers": payload}), 200


@employee_bp.route("/tracks/<int:track_id>/drivers/<int:user_id>/class", methods=["POST"])
@login_required
def update_driver_class(track_id, user_id):
    guard = require_employee()
    if guard:
        return guard
    if track_id != active_track_id():
        flash("You can only update classes for your track.", "error")
        return redirect(url_for("employee.dashboard"))

    selected = (request.form.get("driver_class") or "").strip().upper()
    if selected not in {"A", "B", "C"}:
        flash("Invalid class selected.", "error")
        return redirect(request.referrer or url_for("employee.dashboard"))

    record = _get_or_create_track_driver_class(track_id, user_id)
    record.driver_class = selected
    if current_user.account_type == "employee":
        record.updated_by_employee_id = current_user.id
    db.session.commit()
    flash("Driver class updated.", "success")
    return redirect(request.referrer or url_for("employee.dashboard"))


@employee_bp.route("/inspection-rules", methods=["POST"])
@login_required
def add_inspection_rule():
    guard = require_employee()
    if guard:
        return guard
    form = InspectionRuleForm()
    if form.validate_on_submit():
        max_order = db.session.query(func.max(InspectionRule.sort_order)).filter_by(track_id=active_track_id()).scalar() or 0
        rule = InspectionRule(track_id=active_track_id(), rule_text=form.rule_text.data.strip(), active=True, sort_order=max_order + 1)
        db.session.add(rule)
        db.session.commit()
        flash("Inspection rule added.", "success")
    else:
        flash("Could not add rule.", "error")
    return redirect(url_for("employee.inspection_rules"))


@employee_bp.route("/inspection-rules/<int:rule_id>/toggle", methods=["POST"])
@login_required
def toggle_inspection_rule(rule_id):
    guard = require_employee()
    if guard:
        return guard
    rule = InspectionRule.query.filter_by(id=rule_id, track_id=active_track_id()).first_or_404()
    rule.active = not rule.active
    db.session.commit()
    flash("Inspection rule updated.", "success")
    return redirect(url_for("employee.inspection_rules"))


@employee_bp.route("/inspection-rules/<int:rule_id>/delete", methods=["POST"])
@login_required
def delete_inspection_rule(rule_id):
    guard = require_employee()
    if guard:
        return guard
    rule = InspectionRule.query.filter_by(id=rule_id, track_id=active_track_id()).first_or_404()
    db.session.delete(rule)
    db.session.commit()
    flash("Inspection rule deleted.", "success")
    return redirect(url_for("employee.inspection_rules"))


@employee_bp.route("/inspection-rules")
@login_required
def inspection_rules():
    guard = require_employee()
    if guard:
        return guard
    rules = InspectionRule.query.filter_by(track_id=active_track_id()).order_by(InspectionRule.sort_order.asc(), InspectionRule.id.asc()).all()
    form = InspectionRuleForm()
    return render_template("employee/inspection_rules.html", rules=rules, form=form)


@employee_bp.route("/waivers/template-builder", methods=["GET", "POST"])
@login_required
def waiver_template_builder():
    guard = require_employee()
    if guard:
        return guard
    embedded_url = None
    if request.method == "POST":
        upload = request.files.get("template_file")
        if not upload or not upload.filename:
            flash("Upload a PDF file to create an embedded template.", "error")
        elif not upload.filename.lower().endswith(".pdf"):
            flash("Only PDF files are supported for template creation.", "error")
        else:
            try:
                file_bytes = upload.read()
                redirect_url = f"{current_app.config.get('APP_BASE_URL', '')}{url_for('employee.waiver_template_builder')}"
                result = create_embedded_template_url(
                    file_bytes=file_bytes,
                    filename=upload.filename,
                    redirect_url=redirect_url,
                    title=f"{Track.query.get(active_track_id()).name} Waiver Template",
                )
                embedded_url = result.get("createUrl")
                created_template_id = (result.get("templateId") or "").strip()
                if created_template_id:
                    existing = TrackWaiverTemplate.query.filter_by(
                        track_id=active_track_id(),
                        boldsign_template_id=created_template_id,
                    ).first()
                    if not existing:
                        db.session.add(
                            TrackWaiverTemplate(
                                track_id=active_track_id(),
                                title=f"Track Waiver {created_template_id[:8]}",
                                boldsign_template_id=created_template_id,
                                is_active=True,
                                required_for_checkin=True,
                            )
                        )
                        db.session.commit()
                if not embedded_url:
                    flash("BoldSign did not return an embedded template URL.", "error")
                else:
                    flash("Embedded template editor loaded.", "success")
            except Exception as exc:
                current_app.logger.exception("Embedded template creation failed: %s", exc)
                flash("Could not create embedded template link.", "error")
    templates = (
        TrackWaiverTemplate.query.filter_by(track_id=active_track_id())
        .order_by(TrackWaiverTemplate.updated_at.desc())
        .all()
    )
    return render_template(
        "employee/waiver_template_builder.html",
        embedded_url=embedded_url,
        templates=templates,
    )


@employee_bp.route("/waivers/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def waiver_template_delete(template_id):
    guard = require_employee()
    if guard:
        return guard
    template = TrackWaiverTemplate.query.filter_by(id=template_id, track_id=active_track_id()).first_or_404()
    try:
        if template.boldsign_template_id:
            boldsign_delete_template(template.boldsign_template_id)
    except Exception as exc:
        current_app.logger.warning(
            "BoldSign template delete failed for template_id=%s boldsign_template_id=%s error=%s",
            template.id,
            template.boldsign_template_id,
            exc,
        )
    db.session.delete(template)
    db.session.commit()
    flash("Waiver template deleted.", "success")
    return redirect(url_for("employee.waiver_template_builder"))


def _load_registration_for_track(event_id, registration_id):
    return (
        EventRegistration.query.join(Event, Event.id == EventRegistration.event_id)
        .filter(
            EventRegistration.id == registration_id,
            EventRegistration.event_id == event_id,
            Event.track_id == active_track_id(),
        )
        .first_or_404()
    )


@employee_bp.route("/events/<int:event_id>/inspections")
@login_required
def inspection_lookup(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    code = request.args.get("code", "").strip().upper()
    registration = None
    if code:
        registration = EventRegistration.query.filter_by(event_id=event.id, checkin_code=code).first()
        if not registration:
            flash("No signup found for that scan code in this event.", "error")
    waiver_ctx = None
    if registration:
        from .waiver_routes import get_required_waiver_status

        status, waiver = get_required_waiver_status(event.track_id, registration.user_id, event.id)
        waiver_ctx = {"status": status, "waiver": waiver}
    track_class = None
    if registration:
        track_class = _get_or_create_track_driver_class(event.track_id, registration.user_id)
        db.session.commit()
    return render_template(
        "employee/inspection_lookup.html",
        event=event,
        code=code,
        registration=registration,
        waiver_ctx=waiver_ctx,
        track_class=track_class,
    )


@employee_bp.route("/events/<int:event_id>/inspections/<int:registration_id>", methods=["GET", "POST"])
@login_required
def inspect_registration(event_id, registration_id):
    guard = require_employee()
    if guard:
        return guard
    registration = _load_registration_for_track(event_id, registration_id)
    rules = InspectionRule.query.filter_by(track_id=active_track_id(), active=True).order_by(InspectionRule.sort_order.asc(), InspectionRule.id.asc()).all()
    if not rules:
        flash("Create inspection rules before inspecting cars.", "error")
        return redirect(url_for("employee.dashboard"))

    inspection = Inspection.query.filter_by(event_registration_id=registration.id).first()
    form = InspectionForm(obj=inspection)
    existing_map = {item.inspection_rule_id: item.checked for item in inspection.items} if inspection else {}

    if request.method == "POST" and form.validate_on_submit():
        if not inspection:
            inspector_id = current_user.id if current_user.account_type == "employee" else Employee.query.filter_by(track_id=active_track_id()).first().id
            inspection = Inspection(event_registration_id=registration.id, inspected_by_employee_id=inspector_id)
            db.session.add(inspection)
            db.session.flush()
        for rule in rules:
            checked = request.form.get(f"rule_{rule.id}") == "on"
            item = InspectionItem.query.filter_by(inspection_id=inspection.id, inspection_rule_id=rule.id).first()
            if not item:
                item = InspectionItem(inspection_id=inspection.id, inspection_rule_id=rule.id, checked=checked)
                db.session.add(item)
            else:
                item.checked = checked
        inspection.passed = all(request.form.get(f"rule_{rule.id}") == "on" for rule in rules)
        inspection.notes = form.notes.data.strip() if form.notes.data else None
        db.session.commit()
        flash("Inspection saved.", "success")
        return redirect(url_for("employee.participants", event_id=event_id))

    track_class = _get_or_create_track_driver_class(registration.event.track_id, registration.user_id)
    db.session.commit()
    return render_template(
        "employee/inspection_form.html",
        registration=registration,
        event=registration.event,
        track_class=track_class,
        rules=rules,
        existing_map=existing_map,
        form=form,
        inspection=inspection,
    )
