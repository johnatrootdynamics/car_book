from datetime import date, datetime, timedelta
import base64
from io import BytesIO
from decimal import Decimal

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from .forms import EmployeeCreateForm, EventForm, InspectionForm, InspectionRuleForm, PrivateRentalSlotForm, TrackEmailTemplateForm, TrackProfileForm
from .models import (
    Car,
    DriverClassChange,
    DriverNote,
    DriverTicketOrder,
    Employee,
    Event,
    EventClassSlot,
    EventRegistration,
    Inspection,
    InspectionItem,
    InspectionRule,
    PrivateRentalBooking,
    PrivateRentalSlot,
    RunGroup,
    RunGroupAssignment,
    ScannerDevice,
    ScannerObservation,
    SpectatorOrder,
    SpectatorOrderItem,
    SpectatorTicketType,
    SpectatorTicketOrder,
    Track,
    TrackCarStatus,
    TrackRun,
    TrackRunParticipant,
    TrackDriverClass,
    TrackEmailTemplate,
    TrackLayout,
    TrackPaymentMethod,
    TrackWaiverTemplate,
    User,
    VendorAccount,
    db,
)
from .services.boldsign_service import create_embedded_template_url
from .services.boldsign_service import delete_template as boldsign_delete_template
from .security import generate_random_password
from .services.email_service import (
    send_driver_purchase_receipt,
    send_employee_login_email,
    send_private_rental_confirmation,
    send_spectator_order_receipt,
)
from .services.storage_service import upload_public_image
from .services.storage_service import build_presigned_read_url
from .services.capacity_service import ticket_availability
from .services.order_service import filter_order_rows, format_money, load_order_rows, summarize_orders
from .services.payment_service import effective_payment_status, payment_is_confirmed
from .services.rental_service import (
    active_bookings_by_slot,
    event_conflicts_with_rental_slot,
    rental_month_context,
    slot_conflicts_with_event,
    slot_conflicts_with_slot,
)
from .services.ticket_service import ensure_order_ticket_codes, normalize_ticket_code


employee_bp = Blueprint("employee", __name__, url_prefix="/employee")

EMAIL_TEMPLATE_DEFINITIONS = {
    "spectator_purchase_receipt": {
        "label": "Event Ticket Purchase Receipt",
        "description": "Sent after a spectator or vendor ticket order is paid or recorded.",
        "subject": "Your tickets for {track_name}",
        "body": "Hi {buyer_name},\n\nYour event ticket order {order_number} is confirmed.\n\nEvent tickets:\n{ticket_lines}\n\nTotal: {order_total}\n\nPresent each ticket's QR code at the gate.\n\nThanks,\n{track_name}",
    },
    "driver_purchase_receipt": {
        "label": "Driver Purchase Receipt",
        "description": "Sent after a driver ticket is paid or recorded.",
        "subject": "Driver ticket confirmed for {event_name}",
        "body": "Hi {driver_name},\n\nYour driver ticket for {event_name} at {track_name} is confirmed.\n\nCar: {car_name}\nTotal: {order_total}\nTicket code: {ticket_code}\nQR link: {ticket_qr_link}\n\nPresent the QR code below at driver check-in. Complete any required waiver and inspection before you are ready to race.\n\nThanks,\n{track_name}",
    },
}

PAYMENT_PROVIDER_CHOICES = {
    "stripe": "Stripe",
    "paypal": "PayPal",
    "toast": "Toast",
    "quickbooks": "QuickBooks Payments",
    "other": "Other / Manual",
}

PAYMENT_PROVIDER_DOCS = {
    "stripe": "https://docs.stripe.com/keys",
    "paypal": "https://developer.paypal.com/api/rest/",
    "toast": "https://doc.toasttab.com/doc/devguide/authentication.html",
    "quickbooks": "https://developer.intuit.com/app/developer/qbpayments/docs/develop",
}

STAFF_ROLE_LABELS = {
    "track_staff": "Track staff",
    "office_staff": "Office staff",
}


def require_employee():
    if not current_user.is_authenticated:
        flash("Please sign in as a track employee.", "error")
        return redirect(url_for("auth.user_login"))
    if current_user.account_type == "admin":
        if session.get("impersonate_track_id"):
            return None
        flash("Choose a track to impersonate first.", "error")
        return redirect(url_for("admin.dashboard"))
    if current_user.account_type != "employee":
        flash("Employee access required for that page.", "error")
        return redirect(url_for("user.dashboard"))
    return None


def has_office_access():
    """Office staff and impersonating enterprise admins can manage the back office."""
    if current_user.account_type == "admin":
        return bool(session.get("impersonate_track_id"))
    return current_user.account_type == "employee" and getattr(current_user, "role", None) == "office_staff"


def require_office_staff():
    guard = require_employee()
    if guard:
        return guard
    if not has_office_access():
        flash("Office staff access required for that page.", "error")
        return redirect(url_for("employee.dashboard"))
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


def _current_staff_actor():
    if current_user.account_type == "admin":
        return "admin", current_user.id, current_user.full_name
    return "employee", current_user.id, current_user.full_name


def _scanner_asset_url(stored_value):
    if not stored_value:
        return None
    if stored_value.startswith("uploads/"):
        return url_for("static", filename=stored_value)
    read_key = current_app.config.get("S3_READ_ACCESS_KEY")
    read_secret = current_app.config.get("S3_READ_SECRET_KEY")
    if read_key and read_secret:
        return build_presigned_read_url(
            stored_value,
            bucket=current_app.config["S3_BUCKET"],
            endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
            access_key=read_key,
            secret_key=read_secret,
        )
    return None


@employee_bp.route("/scanners")
@login_required
def scanners():
    guard = require_employee()
    if guard:
        return guard
    track_id = active_track_id()
    devices = ScannerDevice.query.filter_by(track_id=track_id).order_by(ScannerDevice.name.asc()).all()
    recent = (
        ScannerObservation.query.join(ScannerDevice)
        .filter(ScannerDevice.track_id == track_id)
        .order_by(ScannerObservation.received_at.desc()).limit(30).all()
    )
    return render_template("employee/scanners.html", devices=devices, recent=recent)


@employee_bp.post("/scanners/register")
@login_required
def scanner_register():
    guard = require_office_staff()
    if guard:
        return guard
    code = (request.form.get("pairing_code") or "").strip().upper()
    name = (request.form.get("name") or "").strip()
    now = datetime.utcnow()
    pending = ScannerDevice.query.filter(
        ScannerDevice.status == "pending", ScannerDevice.pairing_expires_at >= now
    ).all()
    device = next((item for item in pending if check_password_hash(item.pairing_code_hash or "", code)), None)
    if not device:
        flash("That pairing code is invalid or has expired.", "error")
        return redirect(url_for("employee.scanners"))
    device.track_id = active_track_id()
    device.name = name or f"Scanner {device.id}"
    device.status = "active"
    device.claimed_at = now
    device.pairing_code_hash = None
    device.pairing_expires_at = None
    db.session.commit()
    flash(f"{device.name} is now registered to this track.", "success")
    return redirect(url_for("employee.scanners"))


@employee_bp.post("/scanners/<int:scanner_id>/settings")
@login_required
def scanner_update(scanner_id):
    guard = require_office_staff()
    if guard:
        return guard
    device = ScannerDevice.query.filter_by(id=scanner_id, track_id=active_track_id()).first_or_404()
    role = (request.form.get("role") or "unassigned").strip()
    if role not in {"unassigned", "track_entrance", "track_exit"}:
        role = "unassigned"
    if role != "unassigned":
        ScannerDevice.query.filter(
            ScannerDevice.track_id == active_track_id(),
            ScannerDevice.role == role,
            ScannerDevice.id != device.id,
        ).update({"role": "unassigned"}, synchronize_session=False)
    device.name = (request.form.get("name") or "").strip()[:120] or device.name
    device.role = role
    db.session.commit()
    flash("Scanner settings saved.", "success")
    return redirect(url_for("employee.scanners"))


@employee_bp.get("/scanners/data")
@login_required
def scanner_data():
    guard = require_employee()
    if guard:
        return guard
    track_id = active_track_id()
    rows = (
        ScannerObservation.query.join(ScannerDevice)
        .filter(ScannerDevice.track_id == track_id)
        .order_by(ScannerObservation.received_at.desc()).limit(50).all()
    )
    return jsonify(observations=[{
        "id": row.id, "scanner": row.scanner.name, "role": row.scanner.role,
        "epc": row.epc, "result": row.result, "reason": row.reason,
        "car": f"{row.car.car_year} {row.car.make} {row.car.model}" if row.car else None,
        "driver": f"{row.car.owner.first_name} {row.car.owner.last_name}" if row.car else None,
        "observed_at": row.observed_at.isoformat() + "Z",
    } for row in rows])


@employee_bp.route("/live-track")
@login_required
def live_track():
    guard = require_employee()
    if guard:
        return guard
    return render_template("employee/live_track.html")


@employee_bp.get("/run-history")
@login_required
def run_history():
    guard = require_employee()
    if guard:
        return guard
    events = Event.query.filter_by(track_id=active_track_id()).order_by(Event.event_date.desc(), Event.event_start_time.desc()).all()
    selected_event = None
    raw_event_id = request.args.get("event_id", type=int)
    if raw_event_id:
        selected_event = Event.query.filter_by(id=raw_event_id, track_id=active_track_id()).first_or_404()
    if not selected_event:
        event_ids_with_runs = {
            row[0] for row in db.session.query(TrackRun.event_id)
            .filter(TrackRun.track_id == active_track_id(), TrackRun.event_id.isnot(None)).distinct().all()
        }
        selected_event = next((event for event in events if event.id in event_ids_with_runs), events[0] if events else None)
    runs = []
    if selected_event:
        runs = TrackRun.query.filter_by(
            track_id=active_track_id(), event_id=selected_event.id
        ).order_by(TrackRun.started_at.asc()).all()
    return render_template(
        "employee/run_history.html", events=events,
        selected_event=selected_event, runs=runs,
    )


@employee_bp.get("/live-track/data")
@login_required
def live_track_data():
    guard = require_employee()
    if guard:
        return guard
    timeout_at = datetime.utcnow() - timedelta(seconds=20)
    expired_states = TrackCarStatus.query.filter(
        TrackCarStatus.track_id == active_track_id(),
        TrackCarStatus.is_on_track.is_(True),
        TrackCarStatus.changed_at < timeout_at,
    ).all()
    active_run = TrackRun.query.filter_by(track_id=active_track_id(), status="active").first()
    timeout_end = None
    for state in expired_states:
        state.is_on_track = False
        exited_at = state.changed_at + timedelta(seconds=20)
        timeout_end = max(timeout_end, exited_at) if timeout_end else exited_at
        if active_run:
            participant = TrackRunParticipant.query.filter_by(run_id=active_run.id, car_id=state.car_id).first()
            if participant and not participant.exited_at:
                participant.exited_at = exited_at
    db.session.flush()
    if active_run and TrackCarStatus.query.filter_by(track_id=active_track_id(), is_on_track=True).count() == 0:
        active_run.status = "completed"
        active_run.ended_at = timeout_end or datetime.utcnow()
    db.session.commit()
    states = TrackCarStatus.query.filter_by(track_id=active_track_id(), is_on_track=True).order_by(TrackCarStatus.changed_at.asc()).all()
    today_event_ids = [row[0] for row in db.session.query(Event.id).filter_by(track_id=active_track_id(), event_date=date.today()).all()]
    completed_query = TrackRun.query.filter_by(track_id=active_track_id(), status="completed")
    if today_event_ids:
        completed_query = completed_query.filter(TrackRun.event_id.in_(today_event_ids))
    completed_runs = completed_query.order_by(TrackRun.ended_at.desc()).limit(12).all()
    return jsonify(count=len(states), cars=[{
        "car_id": state.car_id,
        "car": f"{state.car.car_year} {state.car.make} {state.car.model}",
        "color": state.car.color,
        "driver": f"{state.car.owner.first_name} {state.car.owner.last_name}",
        "driver_initials": f"{state.car.owner.first_name[:1]}{state.car.owner.last_name[:1]}",
        "driver_image": _scanner_asset_url(state.car.owner.profile_image_url),
        "car_image": _scanner_asset_url(state.car.image_url),
        "entered_at": state.changed_at.isoformat() + "Z",
        "scanner": state.last_scanner.name if state.last_scanner else None,
    } for state in states], runs=[{
        "id": run.id,
        "event_id": run.event_id,
        "event_name": run.event.event_name if run.event else "Unassigned run",
        "started_at": run.started_at.isoformat() + "Z",
        "ended_at": run.ended_at.isoformat() + "Z" if run.ended_at else None,
        "participants": [{
            "car_id": participant.car_id,
            "car": f"{participant.car.car_year} {participant.car.make} {participant.car.model}",
            "driver": f"{participant.driver.first_name} {participant.driver.last_name}",
            "driver_initials": f"{participant.driver.first_name[:1]}{participant.driver.last_name[:1]}",
            "driver_image": _scanner_asset_url(participant.driver.profile_image_url),
            "car_image": _scanner_asset_url(participant.car.image_url),
        } for participant in run.participants],
    } for run in completed_runs])


def _track_driver_query(track_id):
    registered_driver_ids = (
        db.session.query(EventRegistration.user_id)
        .join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == track_id)
    )
    classified_driver_ids = db.session.query(TrackDriverClass.user_id).filter(
        TrackDriverClass.track_id == track_id
    )
    return User.query.filter(
        (User.id.in_(registered_driver_ids)) | (User.id.in_(classified_driver_ids))
    )


def _load_track_driver(track_id, user_id):
    return _track_driver_query(track_id).filter(User.id == user_id).first_or_404()


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
    configurations = (
        ("spectator", "General Admission", event.spectator_price_cents, 10),
        ("vendor", "Vendor Admission", event.vendor_price_cents, 20),
    )
    for category, default_name, price_cents, max_per_order in configurations:
        ticket_type = (
            SpectatorTicketType.query.filter_by(
                event_id=event.id,
                ticket_category=category,
            )
            .order_by(SpectatorTicketType.created_at.asc())
            .first()
        )
        if ticket_type:
            ticket_type.name = ticket_type.name or default_name
            ticket_type.price_cents = max(0, price_cents or 0)
            ticket_type.is_active = True
            ticket_type.max_per_order = ticket_type.max_per_order or max_per_order
            continue
        db.session.add(
            SpectatorTicketType(
                event_id=event.id,
                name=default_name,
                ticket_category=category,
                price_cents=max(0, price_cents or 0),
                is_active=True,
                max_per_order=max_per_order,
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
    upcoming_driver_count = sum(signup_counts.get(event.id, 0) for event in upcoming_events)
    last_event = past_events[0] if past_events else None
    last_event_participants = signup_counts.get(last_event.id, 0) if last_event else 0
    last_event_spectator_tickets = 0
    last_event_vendor_tickets = 0
    if last_event:
        spectator_sum = (
            db.session.query(func.coalesce(func.sum(SpectatorTicketOrder.quantity), 0))
            .filter(SpectatorTicketOrder.event_id == last_event.id)
            .filter(SpectatorTicketOrder.ticket_category == "spectator")
            .scalar()
        )
        vendor_sum = (
            db.session.query(func.coalesce(func.sum(SpectatorTicketOrder.quantity), 0))
            .filter(SpectatorTicketOrder.event_id == last_event.id)
            .filter(SpectatorTicketOrder.ticket_category == "vendor")
            .scalar()
        )
        last_event_spectator_tickets = int(spectator_sum or 0)
        last_event_vendor_tickets = int(vendor_sum or 0)
    return render_template(
        "employee/dashboard.html",
        upcoming_events=upcoming_events,
        past_events=past_events,
        track=track,
        signup_counts=signup_counts,
        upcoming_driver_count=upcoming_driver_count,
        today=date.today(),
        last_event=last_event,
        last_event_participants=last_event_participants,
        last_event_spectator_tickets=last_event_spectator_tickets,
        last_event_vendor_tickets=last_event_vendor_tickets,
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


@employee_bp.route("/private-rentals", methods=["GET", "POST"])
@login_required
def private_rentals():
    guard = require_office_staff()
    if guard:
        return guard
    track_id = active_track_id()
    track = Track.query.get_or_404(track_id)
    calendar = rental_month_context(request.args.get("month"))
    form = PrivateRentalSlotForm()
    if request.method == "GET":
        form.slot_date.data = max(date.today(), calendar["first"])
        form.start_time.data = datetime.strptime("09:00", "%H:%M").time()
        form.end_time.data = datetime.strptime("17:00", "%H:%M").time()
        form.price.data = Decimal("2500.00")
        form.driver_limit.data = 20

    if form.validate_on_submit():
        if form.end_time.data <= form.start_time.data:
            flash("Rental end time must be after the start time.", "error")
        else:
            Track.query.filter_by(id=track_id).with_for_update().one()
            conflicting_slot = slot_conflicts_with_slot(
                track_id,
                form.slot_date.data,
                form.start_time.data,
                form.end_time.data,
            )
            conflicting_event = slot_conflicts_with_event(
                track_id,
                form.slot_date.data,
                form.start_time.data,
                form.end_time.data,
            )
            if conflicting_slot:
                flash("That time overlaps another private rental slot.", "error")
            elif conflicting_event:
                flash(
                    f"That time overlaps {conflicting_event.event_name}. Choose another window.",
                    "error",
                )
            else:
                slot = PrivateRentalSlot(
                    track_id=track_id,
                    name=form.name.data.strip(),
                    slot_date=form.slot_date.data,
                    start_time=form.start_time.data,
                    end_time=form.end_time.data,
                    price_cents=_to_cents(form.price.data),
                    driver_limit=form.driver_limit.data,
                    created_by_employee_id=(
                        current_user.id if current_user.account_type == "employee" else None
                    ),
                )
                db.session.add(slot)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    flash("That exact rental slot already exists.", "error")
                else:
                    flash("Private rental availability added.", "success")
                    return redirect(
                        url_for(
                            "employee.private_rentals",
                            month=slot.slot_date.strftime("%Y-%m"),
                        )
                    )

    slots = (
        PrivateRentalSlot.query.filter(
            PrivateRentalSlot.track_id == track_id,
            PrivateRentalSlot.slot_date >= calendar["range_start"],
            PrivateRentalSlot.slot_date <= calendar["range_end"],
            PrivateRentalSlot.is_active.is_(True),
        )
        .order_by(PrivateRentalSlot.slot_date.asc(), PrivateRentalSlot.start_time.asc())
        .all()
    )
    bookings_by_slot = active_bookings_by_slot([slot.id for slot in slots])
    slots_by_date = {}
    for slot in slots:
        slots_by_date.setdefault(slot.slot_date, []).append(slot)
    upcoming_slots = (
        PrivateRentalSlot.query.filter(
            PrivateRentalSlot.track_id == track_id,
            PrivateRentalSlot.slot_date >= date.today(),
            PrivateRentalSlot.is_active.is_(True),
        )
        .order_by(PrivateRentalSlot.slot_date.asc(), PrivateRentalSlot.start_time.asc())
        .limit(80)
        .all()
    )
    upcoming_bookings = active_bookings_by_slot([slot.id for slot in upcoming_slots])
    return render_template(
        "employee/private_rentals.html",
        track=track,
        form=form,
        calendar=calendar,
        slots_by_date=slots_by_date,
        bookings_by_slot=bookings_by_slot,
        upcoming_slots=upcoming_slots,
        upcoming_bookings=upcoming_bookings,
        today=date.today(),
        money=format_money,
    )


@employee_bp.route("/private-rentals/<int:slot_id>/remove", methods=["POST"])
@login_required
def private_rental_slot_remove(slot_id):
    guard = require_office_staff()
    if guard:
        return guard
    slot = PrivateRentalSlot.query.filter_by(
        id=slot_id,
        track_id=active_track_id(),
    ).first_or_404()
    active_booking = active_bookings_by_slot([slot.id]).get(slot.id)
    if active_booking:
        flash("Booked or held rental slots cannot be removed.", "error")
    else:
        slot.is_active = False
        db.session.commit()
        flash("Private rental slot removed from the calendar.", "success")
    return redirect(
        url_for("employee.private_rentals", month=slot.slot_date.strftime("%Y-%m"))
    )


@employee_bp.route("/inspections")
@login_required
def inspections_hub():
    guard = require_employee()
    if guard:
        return guard

    track_id = active_track_id()
    track = Track.query.get_or_404(track_id)
    active_rule_count = InspectionRule.query.filter_by(
        track_id=track_id,
        active=True,
    ).count()
    events = (
        Event.query.filter(
            Event.track_id == track_id,
            Event.event_date >= date.today(),
        )
        .order_by(Event.event_date.asc(), Event.id.asc())
        .all()
    )

    selected_event = None
    selected_event_id = request.args.get("event_id", type=int)
    if selected_event_id:
        selected_event = Event.query.filter_by(
            id=selected_event_id,
            track_id=track_id,
        ).first_or_404()
        if selected_event.event_date < date.today():
            flash("Past events are not available in the inspection workspace.", "error")
            return redirect(url_for("employee.inspections_hub"))
    elif events:
        selected_event = events[0]

    scanner_active = request.args.get("scanner") == "1"
    raw_lookup = request.args.get("lookup")
    if raw_lookup is None:
        # Keep old links/bookmarks working while the page moves to one lookup field.
        raw_lookup = request.args.get("scan_code") or request.args.get("q")
    query = (raw_lookup or "").strip()
    scan_code = normalize_ticket_code(query)
    code_lookup = query.lower().startswith(("http://", "https://")) or scan_code.startswith(
        ("DRV-", "CAR-", "DRT-")
    )
    work_items = []
    counts = {
        "total": 0,
        "pending": 0,
        "needs_work": 0,
        "passed": 0,
    }

    if selected_event and query:
        scanned_registration = (
            EventRegistration.query.join(User, User.id == EventRegistration.user_id)
            .join(Car, Car.id == EventRegistration.car_id)
            .filter(
                EventRegistration.event_id == selected_event.id,
                or_(
                    EventRegistration.checkin_code == scan_code,
                    User.static_qr_code == scan_code,
                    Car.static_qr_code == scan_code,
                ),
            )
            .first()
        )
        if scanned_registration:
            from .waiver_routes import get_required_waiver_status

            waiver_state, _ = get_required_waiver_status(
                selected_event.track_id,
                scanned_registration.user_id,
                selected_event.id,
            )
            if not active_rule_count:
                flash("Inspection setup is required before this vehicle can be inspected.", "error")
            elif waiver_state not in {"signed", "not_required"}:
                flash("This driver's waiver must be completed before inspection.", "error")
            else:
                return redirect(
                    url_for(
                        "employee.inspect_registration",
                        event_id=selected_event.id,
                        registration_id=scanned_registration.id,
                        return_to="hub",
                        **({"scanner": 1} if scanner_active else {}),
                    )
                )
            query = f"{scanned_registration.user.first_name} {scanned_registration.user.last_name}".strip()
        elif code_lookup:
            flash("That QR code does not match a driver registered for this event.", "error")

    if selected_event:
        registrations = (
            EventRegistration.query.filter_by(event_id=selected_event.id)
            .order_by(EventRegistration.created_at.asc())
            .all()
        )
        inspections = {
            inspection.event_registration_id: inspection
            for inspection in Inspection.query.join(
                EventRegistration,
                EventRegistration.id == Inspection.event_registration_id,
            )
            .filter(EventRegistration.event_id == selected_event.id)
            .all()
        }

        from .waiver_routes import get_required_waiver_status

        for registration in registrations:
            inspection = inspections.get(registration.id)
            waiver_state, _ = get_required_waiver_status(
                selected_event.track_id,
                registration.user_id,
                selected_event.id,
            )
            work_items.append(
                {
                    "registration": registration,
                    "inspection": inspection,
                    "waiver_state": waiver_state,
                    "waiver_ok": waiver_state in {"signed", "not_required"},
                }
            )

        counts["total"] = len(work_items)
        counts["pending"] = sum(1 for item in work_items if item["inspection"] is None)
        counts["needs_work"] = sum(
            1
            for item in work_items
            if item["inspection"] is not None and not item["inspection"].passed
        )
        counts["passed"] = sum(
            1
            for item in work_items
            if item["inspection"] is not None and item["inspection"].passed
        )
        if query:
            needle = query.casefold()
            work_items = [
                item
                for item in work_items
                if needle
                in " ".join(
                    [
                        item["registration"].user.first_name or "",
                        item["registration"].user.last_name or "",
                        item["registration"].user.username or "",
                        item["registration"].user.email or "",
                        item["registration"].user.static_qr_code or "",
                        item["registration"].checkin_code or "",
                        item["registration"].car.static_qr_code or "",
                        str(item["registration"].car.car_year or ""),
                        item["registration"].car.make or "",
                        item["registration"].car.model or "",
                    ]
                ).casefold()
            ]

        def inspection_priority(item):
            registration = item["registration"]
            inspection = item["inspection"]
            is_complete = bool(inspection and inspection.passed)
            if registration.checked_in_at and not is_complete:
                queue_rank = 0
            elif not is_complete:
                queue_rank = 1
            else:
                queue_rank = 2
            return (
                queue_rank,
                registration.user.last_name.casefold(),
                registration.user.first_name.casefold(),
            )

        work_items.sort(key=inspection_priority)

    return render_template(
        "employee/inspections_hub.html",
        track=track,
        events=events,
        selected_event=selected_event,
        work_items=work_items,
        counts=counts,
        query=query,
        scan_code=scan_code,
        code_lookup=code_lookup,
        scanner_active=scanner_active,
        today=date.today(),
        active_rule_count=active_rule_count,
    )


@employee_bp.route("/track-profile", methods=["GET"])
@login_required
def track_profile():
    guard = require_office_staff()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    form = TrackProfileForm(obj=track)
    layouts = TrackLayout.query.filter_by(track_id=track.id).order_by(TrackLayout.name.asc()).all()
    return render_template("employee/track_profile.html", track=track, form=form, layouts=layouts)


@employee_bp.route("/tickets/verify", methods=["GET", "POST"])
@login_required
def ticket_verification():
    guard = require_employee()
    if guard:
        return guard
    scanner_active = (
        request.form.get("scanner_active") == "1"
        if request.method == "POST"
        else request.args.get("scanner") == "1"
    )
    code = normalize_ticket_code(
        request.form.get("code") if request.method == "POST" else request.args.get("code")
    )
    item = None
    driver_registration = None
    driver_order = None
    verification_state = None
    if code:
        item = (
            SpectatorOrderItem.query.join(Event, Event.id == SpectatorOrderItem.event_id)
            .filter(
                SpectatorOrderItem.qr_code == code,
                Event.track_id == active_track_id(),
            )
            .first()
        )
        if not item:
            driver_registration = (
                EventRegistration.query.join(
                    Event,
                    Event.id == EventRegistration.event_id,
                )
                .filter(
                    EventRegistration.checkin_code == code,
                    Event.track_id == active_track_id(),
                )
                .first()
            )
            if driver_registration:
                driver_order = (
                    DriverTicketOrder.query.filter_by(
                        event_id=driver_registration.event_id,
                        user_id=driver_registration.user_id,
                    )
                    .order_by(DriverTicketOrder.created_at.desc())
                    .first()
                )
        if item and not payment_is_confirmed(
            item.order.payment_status,
            item.order.payment_method,
            item.order.total_cents,
            item.order.provider_transaction_id,
        ):
            verification_state = "unpaid"
        elif item and item.checked_in_at:
            verification_state = "used"
        elif item:
            verification_state = "valid"
        elif driver_registration and driver_order and not payment_is_confirmed(
            driver_order.payment_status,
            driver_order.payment_method,
            driver_order.amount_cents,
            driver_order.provider_transaction_id,
        ):
            verification_state = "unpaid"
        elif driver_registration and not driver_order:
            verification_state = "unpaid"
        elif driver_registration and driver_registration.checked_in_at:
            verification_state = "used"
        elif driver_registration:
            verification_state = "valid"
        else:
            verification_state = "invalid"
    return render_template(
        "employee/ticket_verification.html",
        code=code,
        item=item,
        driver_registration=driver_registration,
        driver_order=driver_order,
        verification_state=verification_state,
        scanner_active=scanner_active,
    )


@employee_bp.route("/vendors")
@login_required
def vendors():
    guard = require_employee()
    if guard:
        return guard
    track_id = active_track_id()
    events = (
        Event.query.filter_by(track_id=track_id)
        .order_by(Event.event_date.desc())
        .all()
    )
    selected_event_id = request.args.get("event_id", type=int)
    selected_event = next((event for event in events if event.id == selected_event_id), None)
    if not selected_event:
        selected_event = next(
            (event for event in reversed(events) if event.event_date >= date.today()),
            events[0] if events else None,
        )

    query_text = (request.args.get("q") or "").strip().lower()
    vendor_tickets = []
    if selected_event:
        candidates = (
            SpectatorOrderItem.query.join(
                SpectatorOrder,
                SpectatorOrder.id == SpectatorOrderItem.order_id,
            )
            .filter(
                SpectatorOrderItem.event_id == selected_event.id,
                SpectatorOrderItem.ticket_category == "vendor",
            )
            .order_by(SpectatorOrder.created_at.asc(), SpectatorOrderItem.id.asc())
            .all()
        )
        for item in candidates:
            if not payment_is_confirmed(
                item.order.payment_status,
                item.order.payment_method,
                item.order.total_cents,
                item.order.provider_transaction_id,
            ):
                continue
            haystack = " ".join(
                [
                    item.order.vendor.business_name if item.order.vendor else (item.order.vendor_business_name or ""),
                    item.order.order_number or "",
                    item.qr_code or "",
                    *(
                        [
                            item.order.vendor.full_name if item.order.vendor else (item.order.guest_full_name or ""),
                            item.order.vendor.email if item.order.vendor else (item.order.guest_email or ""),
                            item.order.vendor.phone if item.order.vendor else (item.order.guest_phone or ""),
                        ]
                        if has_office_access()
                        else []
                    ),
                ]
            ).lower()
            if query_text and query_text not in haystack:
                continue
            vendor_tickets.append(item)

    checked_in_count = sum(1 for item in vendor_tickets if item.checked_in_at)
    business_count = len(
        {
            (
                item.order.vendor.business_name
                if item.order.vendor
                else (item.order.vendor_business_name or item.order.guest_full_name or "Unknown")
            ).casefold()
            for item in vendor_tickets
        }
    )
    return render_template(
        "employee/vendors.html",
        events=events,
        selected_event=selected_event,
        vendor_tickets=vendor_tickets,
        query_text=query_text,
        checked_in_count=checked_in_count,
        business_count=business_count,
    )


@employee_bp.route("/vendor-directory")
@login_required
def vendor_directory():
    guard = require_employee()
    if guard:
        return guard
    query_text = (request.args.get("q") or "").strip()
    return redirect(
        url_for("employee.drivers", view="vendors", **({"q": query_text} if query_text else {}))
    )


@employee_bp.route("/orders")
@login_required
def orders():
    guard = require_employee()
    if guard:
        return guard
    scoped_rows = load_order_rows(track_id=active_track_id())
    if not has_office_access():
        scoped_rows = [row for row in scoped_rows if row["kind"] != "rental"]
        for row in scoped_rows:
            if "vendor" in row.get("ticket_categories", set()):
                row["buyer_name"] = row.get("vendor_business_name") or "Vendor"
                row["buyer_email"] = ""
    search = (request.args.get("q") or "").strip()
    payment_status = (request.args.get("status") or "").strip().lower()
    kind = (request.args.get("kind") or "").strip().lower()
    provider = (request.args.get("provider") or "").strip().lower()
    rows = filter_order_rows(
        scoped_rows,
        search=search,
        payment_status=payment_status,
        kind=kind,
        provider=provider,
    )
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = min(page, total_pages)
    page_rows = rows[(page - 1) * per_page : page * per_page]
    return render_template(
        "shared/orders.html",
        title="Track Orders",
        subtitle="Driver tickets, event tickets, and private rentals for your track.",
        rows=page_rows,
        summary=summarize_orders(rows),
        providers=sorted({row["provider"] for row in scoped_rows}),
        tracks=[],
        selected_track_id=None,
        search=search,
        selected_status=payment_status,
        selected_kind=kind,
        selected_provider=provider,
        page=page,
        total_pages=total_pages,
        list_endpoint="employee.orders",
        detail_endpoint="employee.order_detail",
        show_track=False,
        money=format_money,
    )


@employee_bp.route("/orders/<kind>/<int:order_id>")
@login_required
def order_detail(kind, order_id):
    guard = require_employee()
    if guard:
        return guard
    track_id = active_track_id()
    if kind == "spectator":
        order = (
            SpectatorOrder.query.join(
                SpectatorOrderItem,
                SpectatorOrderItem.order_id == SpectatorOrder.id,
            )
            .join(Event, Event.id == SpectatorOrderItem.event_id)
            .filter(SpectatorOrder.id == order_id, Event.track_id == track_id)
            .distinct()
            .first_or_404()
        )
        if ensure_order_ticket_codes(order):
            db.session.commit()
        items = [item for item in order.items if item.event.track_id == track_id]
        track = items[0].event.track
        registration = None
    elif kind == "driver":
        order = (
            DriverTicketOrder.query.join(Event, Event.id == DriverTicketOrder.event_id)
            .filter(DriverTicketOrder.id == order_id, Event.track_id == track_id)
            .first_or_404()
        )
        track = order.event.track
        registration = EventRegistration.query.filter_by(
            event_id=order.event_id,
            user_id=order.user_id,
        ).first()
    elif kind == "rental":
        guard = require_office_staff()
        if guard:
            return guard
        order = (
            PrivateRentalBooking.query.join(
                PrivateRentalSlot,
                PrivateRentalSlot.id == PrivateRentalBooking.slot_id,
            )
            .filter(
                PrivateRentalBooking.id == order_id,
                PrivateRentalSlot.track_id == track_id,
            )
            .first_or_404()
        )
        track = order.slot.track
        registration = (
            EventRegistration.query.filter_by(
                event_id=order.event_id,
                user_id=order.user_id,
            ).first()
            if order.event_id
            else None
        )
    else:
        return "Unknown order type", 404
    return render_template(
        "shared/order_detail.html",
        title="Order Details",
        kind=kind,
        order=order,
        track=track,
        registration=registration,
        items=items if kind == "spectator" else [],
        payment_status=effective_payment_status(order),
        money=format_money,
        back_endpoint="employee.orders",
        resend_endpoint="employee.resend_order_email",
    )


@employee_bp.route("/orders/<kind>/<int:order_id>/resend-email", methods=["POST"])
@login_required
def resend_order_email(kind, order_id):
    guard = require_employee()
    if guard:
        return guard
    track_id = active_track_id()
    if kind == "spectator":
        order = (
            SpectatorOrder.query.join(
                SpectatorOrderItem,
                SpectatorOrderItem.order_id == SpectatorOrder.id,
            )
            .join(Event, Event.id == SpectatorOrderItem.event_id)
            .filter(SpectatorOrder.id == order_id, Event.track_id == track_id)
            .distinct()
            .first_or_404()
        )
        if ensure_order_ticket_codes(order):
            db.session.commit()
        recipient = order.guest_email
        send_fn = send_spectator_order_receipt
        success_message = f"Tickets were resent to {recipient}."
    elif kind == "driver":
        order = (
            DriverTicketOrder.query.join(Event, Event.id == DriverTicketOrder.event_id)
            .filter(DriverTicketOrder.id == order_id, Event.track_id == track_id)
            .first_or_404()
        )
        recipient = order.buyer.email
        send_fn = send_driver_purchase_receipt
        success_message = f"Driver confirmation was resent to {recipient}."
    elif kind == "rental":
        guard = require_office_staff()
        if guard:
            return guard
        order = (
            PrivateRentalBooking.query.join(
                PrivateRentalSlot,
                PrivateRentalSlot.id == PrivateRentalBooking.slot_id,
            )
            .filter(
                PrivateRentalBooking.id == order_id,
                PrivateRentalSlot.track_id == track_id,
            )
            .first_or_404()
        )
        recipient = order.buyer.email
        send_fn = send_private_rental_confirmation
        success_message = f"Private rental confirmation was resent to {recipient}."
    else:
        return "Unknown order type", 404

    if effective_payment_status(order) != "paid":
        flash("This email cannot be resent until payment is confirmed.", "error")
        return redirect(url_for("employee.order_detail", kind=kind, order_id=order_id))
    try:
        sent = send_fn(order)
    except Exception:
        current_app.logger.exception("Could not resend %s order email for order %s", kind, order_id)
        sent = False
    if not sent:
        flash("The email could not be sent. Check the SMTP settings and try again.", "error")
    else:
        flash(success_message, "success")
    return redirect(url_for("employee.order_detail", kind=kind, order_id=order_id))


@employee_bp.route("/settings", methods=["GET"])
@login_required
def settings():
    guard = require_employee()
    if guard:
        return guard
    can_manage_settings = has_office_access()
    settings_section = (request.args.get("section") or "").strip().lower()
    if not can_manage_settings or settings_section not in {"email", "payments"}:
        settings_section = ""
    track = Track.query.get_or_404(active_track_id())
    templates = {}
    payment_methods = {}
    if settings_section == "email":
        templates = {
            item.template_key: item
            for item in TrackEmailTemplate.query.filter_by(track_id=track.id).all()
        }
    if settings_section == "payments":
        payment_methods = {
            item.provider: item
            for item in TrackPaymentMethod.query.filter_by(track_id=track.id).all()
        }
    app_base_url = (current_app.config.get("APP_BASE_URL") or "").rstrip("/")
    paypal_webhook_path = url_for("user.paypal_webhook")
    if app_base_url:
        paypal_webhook_url = f"{app_base_url}{paypal_webhook_path}"
    else:
        forwarded_scheme = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
        public_scheme = forwarded_scheme if forwarded_scheme in {"http", "https"} else request.scheme
        if public_scheme == "http" and request.host.split(":", 1)[0] not in {"localhost", "127.0.0.1"}:
            public_scheme = "https"
        paypal_webhook_url = f"{public_scheme}://{request.host}{paypal_webhook_path}"
    return render_template(
        "employee/settings.html",
        track=track,
        templates=templates,
        template_definitions=EMAIL_TEMPLATE_DEFINITIONS,
        payment_methods=payment_methods,
        payment_provider_choices=PAYMENT_PROVIDER_CHOICES,
        payment_provider_docs=PAYMENT_PROVIDER_DOCS,
        paypal_webhook_url=paypal_webhook_url,
        can_manage_settings=can_manage_settings,
        settings_section=settings_section,
    )


@employee_bp.route("/settings/payments", methods=["POST"])
@login_required
def payment_methods_update():
    guard = require_office_staff()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    selected = {
        provider
        for provider in PAYMENT_PROVIDER_CHOICES
        if request.form.get(f"provider_enabled_{provider}") == "1"
    }
    if not selected:
        flash("Select at least one payment method.", "error")
        return redirect(url_for("employee.settings", section="payments"))

    for provider in PAYMENT_PROVIDER_CHOICES:
        method = TrackPaymentMethod.query.filter_by(track_id=track.id, provider=provider).first()
        if not method:
            method = TrackPaymentMethod(track_id=track.id, provider=provider)
            db.session.add(method)
        method.is_enabled = provider in selected
        requested_mode = (request.form.get(f"provider_mode_{provider}") or "live").strip().lower()
        method.mode = requested_mode if requested_mode in {"live", "test"} else "live"
        for field in ("public_key", "secret_key", "webhook_secret", "merchant_id", "extra_config"):
            value = (request.form.get(f"{provider}_{field}") or "").strip()
            if value:
                setattr(method, field, value)
            if request.form.get(f"{provider}_clear_{field}") == "1":
                setattr(method, field, None)

            test_field = f"test_{field}"
            test_value = (request.form.get(f"{provider}_{test_field}") or "").strip()
            if test_value:
                setattr(method, test_field, test_value)
            if request.form.get(f"{provider}_clear_{test_field}") == "1":
                setattr(method, test_field, None)
    if track.spectator_payment_provider not in selected:
        track.spectator_payment_provider = sorted(selected)[0]
    stripe_method = TrackPaymentMethod.query.filter_by(track_id=track.id, provider="stripe").first()
    if stripe_method and stripe_method.secret_key:
        track.stripe_secret_key = stripe_method.secret_key
    if stripe_method and stripe_method.webhook_secret:
        track.stripe_webhook_secret = stripe_method.webhook_secret
    if request.form.get("stripe_clear_secret_key") == "1":
        track.stripe_secret_key = None
    if request.form.get("stripe_clear_webhook_secret") == "1":
        track.stripe_webhook_secret = None
    db.session.commit()
    flash("Payment settings updated.", "success")
    return redirect(url_for("employee.settings", section="payments"))


@employee_bp.route("/settings/email-templates/<template_key>", methods=["GET", "POST"])
@login_required
def email_template_edit(template_key):
    guard = require_office_staff()
    if guard:
        return guard
    if template_key not in EMAIL_TEMPLATE_DEFINITIONS:
        flash("Unknown email template.", "error")
        return redirect(url_for("employee.settings", section="email"))
    track = Track.query.get_or_404(active_track_id())
    definition = EMAIL_TEMPLATE_DEFINITIONS[template_key]
    template = TrackEmailTemplate.query.filter_by(track_id=track.id, template_key=template_key).first()
    form = TrackEmailTemplateForm(obj=template)
    if request.method == "GET" and not template:
        form.subject.data = definition["subject"]
        form.body.data = definition["body"]
        form.is_enabled.data = True
    if form.validate_on_submit():
        if not template:
            template = TrackEmailTemplate(track_id=track.id, template_key=template_key)
            db.session.add(template)
        template.subject = form.subject.data.strip()
        template.body = form.body.data.strip()
        template.is_enabled = bool(form.is_enabled.data)
        db.session.commit()
        flash("Email template saved.", "success")
        return redirect(url_for("employee.settings", section="email"))
    return render_template(
        "employee/email_template_form.html",
        track=track,
        form=form,
        template=template,
        template_key=template_key,
        definition=definition,
    )


@employee_bp.route("/staff-accounts", methods=["GET"])
@login_required
def staff_accounts():
    guard = require_employee()
    if guard:
        return guard
    can_manage_staff = has_office_access()
    form = EmployeeCreateForm() if can_manage_staff else None
    staff = Employee.query.filter_by(track_id=active_track_id()).order_by(Employee.created_at.desc()).all()
    if current_user.account_type == "admin" or can_manage_staff:
        resettable_employee_ids = {member.id for member in staff}
    else:
        resettable_employee_ids = {
            member.id
            for member in staff
            if member.role == "track_staff" and member.id != current_user.id
        }
    return render_template(
        "employee/staff_accounts.html",
        form=form,
        staff=staff,
        staff_role_labels=STAFF_ROLE_LABELS,
        can_manage_staff=can_manage_staff,
        resettable_employee_ids=resettable_employee_ids,
    )


@employee_bp.route("/track", methods=["POST"])
@login_required
def update_track():
    guard = require_office_staff()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    form = TrackProfileForm()
    if form.validate_on_submit():
        track.name = form.name.data.strip()
        track.city = form.city.data.strip()
        track.state = form.state.data.strip()
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
    guard = require_office_staff()
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
    guard = require_office_staff()
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
    guard = require_office_staff()
    if guard:
        return guard
    form = EmployeeCreateForm()
    if form.validate_on_submit():
        existing = Employee.query.filter_by(email=form.email.data.lower().strip()).first()
        if existing:
            flash("Employee email already exists.", "error")
        else:
            plaintext_password = generate_random_password()
            track = Track.query.get_or_404(active_track_id())
            employee = Employee(
                track_id=track.id,
                full_name=form.full_name.data.strip(),
                email=form.email.data.lower().strip(),
                password_hash=generate_password_hash(plaintext_password),
                must_change_password=True,
                role=form.role.data,
            )
            db.session.add(employee)
            try:
                db.session.flush()
                sent = send_employee_login_email(
                    employee,
                    plaintext_password,
                    track,
                    url_for("auth.user_login", _external=True),
                )
            except Exception:
                current_app.logger.exception("Could not send employee login email")
                sent = False
            if not sent:
                db.session.rollback()
                flash(
                    "Employee account was not created because the login email could not be delivered.",
                    "error",
                )
                return redirect(url_for("employee.staff_accounts"))
            db.session.commit()
            flash("Employee account created and login details emailed.", "success")
    else:
        flash("Could not create employee account.", "error")
    return redirect(url_for("employee.staff_accounts"))


@employee_bp.route("/employees/<int:employee_id>/role", methods=["POST"])
@login_required
def update_employee_role(employee_id):
    guard = require_office_staff()
    if guard:
        return guard
    employee = Employee.query.filter_by(
        id=employee_id,
        track_id=active_track_id(),
    ).first_or_404()
    role = (request.form.get("role") or "").strip()
    if role not in STAFF_ROLE_LABELS:
        flash("Choose a valid staff role.", "error")
        return redirect(url_for("employee.staff_accounts"))
    if employee.role == "office_staff" and role == "track_staff":
        office_count = Employee.query.filter_by(
            track_id=active_track_id(),
            role="office_staff",
        ).count()
        if office_count <= 1:
            flash("Every track must keep at least one office staff account.", "error")
            return redirect(url_for("employee.staff_accounts"))
    employee.role = role
    db.session.commit()
    flash(f"{employee.full_name} is now {STAFF_ROLE_LABELS[role].lower()}.", "success")
    return redirect(url_for("employee.staff_accounts"))


@employee_bp.route("/employees/<int:employee_id>/reset-password", methods=["POST"])
@login_required
def reset_employee_password(employee_id):
    guard = require_employee()
    if guard:
        return guard
    employee = Employee.query.filter_by(
        id=employee_id,
        track_id=active_track_id(),
    ).first_or_404()

    is_enterprise_admin = current_user.account_type == "admin"
    is_office_staff = has_office_access()
    is_allowed_track_reset = (
        current_user.account_type == "employee"
        and current_user.role == "track_staff"
        and employee.role == "track_staff"
        and employee.id != current_user.id
    )
    if not (is_enterprise_admin or is_office_staff or is_allowed_track_reset):
        flash("You do not have permission to reset that employee’s password.", "error")
        return redirect(url_for("employee.staff_accounts"))

    plaintext_password = generate_random_password()
    employee.password_hash = generate_password_hash(plaintext_password)
    employee.must_change_password = True
    try:
        db.session.flush()
        sent = send_employee_login_email(
            employee,
            plaintext_password,
            employee.track,
            url_for("auth.user_login", _external=True),
            is_reset=True,
        )
    except Exception:
        current_app.logger.exception("Could not send employee password reset email")
        sent = False
    if not sent:
        db.session.rollback()
        flash("Password was not changed because the reset email could not be delivered.", "error")
        return redirect(url_for("employee.staff_accounts"))
    db.session.commit()
    flash(f"A new password was emailed to {employee.email}.", "success")
    return redirect(url_for("employee.staff_accounts"))


@employee_bp.route("/events/new", methods=["GET", "POST"])
@login_required
def event_new():
    guard = require_office_staff()
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
        form.vendor_price.data = Decimal("100.00")
        form.driver_capacity.data = 50
        form.spectator_capacity.data = 100
        form.vendor_capacity.data = 4
    if form.validate_on_submit():
        if form.event_start_time.data and form.event_end_time.data:
            if form.event_end_time.data <= form.event_start_time.data:
                flash("Event end time must be after start time.", "error")
                return render_template("employee/event_form.html", form=form, title="Create Event")
        Track.query.filter_by(id=active_track_id()).with_for_update().one()
        rental_conflict = event_conflicts_with_rental_slot(
            active_track_id(),
            form.event_date.data,
            form.event_start_time.data,
            form.event_end_time.data,
        )
        if rental_conflict:
            flash(
                "This event overlaps private-rental availability. Remove that slot or choose another date and time.",
                "error",
            )
            return render_template(
                "employee/event_form.html",
                form=form,
                title="Create Event",
                track_layouts=layouts,
                event=None,
            )
        event = Event(
            track_id=active_track_id(),
            event_name=form.event_name.data.strip(),
            event_date=form.event_date.data,
            driver_price_cents=_to_cents(form.driver_price.data),
            spectator_price_cents=_to_cents(form.spectator_price.data),
            vendor_price_cents=_to_cents(form.vendor_price.data),
            driver_capacity=form.driver_capacity.data,
            spectator_capacity=form.spectator_capacity.data,
            vendor_capacity=form.vendor_capacity.data,
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
    guard = require_office_staff()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    if event.event_type == "private" and request.method == "POST":
        flash("Private rental dates and times are managed from the rental calendar.", "error")
        return redirect(url_for("employee.private_rentals", month=event.event_date.strftime("%Y-%m")))
    form = EventForm(obj=event)
    layouts = TrackLayout.query.filter_by(track_id=active_track_id()).order_by(TrackLayout.name.asc()).all()
    form.track_layout_id.choices = [(0, "Default Track Layout")] + [
        (layout.id, layout.name) for layout in layouts
    ]
    if request.method == "GET":
        form.track_layout_id.data = event.track_layout_id or 0
        form.driver_price.data = Decimal(event.driver_price_cents or 0) / Decimal(100)
        form.spectator_price.data = Decimal(event.spectator_price_cents or 0) / Decimal(100)
        form.vendor_price.data = Decimal(event.vendor_price_cents or 0) / Decimal(100)
        form.driver_capacity.data = event.driver_capacity or 0
        form.spectator_capacity.data = event.spectator_capacity or 0
        form.vendor_capacity.data = event.vendor_capacity or 0
    if form.validate_on_submit():
        if form.event_start_time.data and form.event_end_time.data:
            if form.event_end_time.data <= form.event_start_time.data:
                flash("Event end time must be after start time.", "error")
                return render_template("employee/event_form.html", form=form, title="Edit Event")
        Track.query.filter_by(id=active_track_id()).with_for_update().one()
        rental_conflict = event_conflicts_with_rental_slot(
            active_track_id(),
            form.event_date.data,
            form.event_start_time.data,
            form.event_end_time.data,
        )
        if rental_conflict:
            flash(
                "This event overlaps private-rental availability. Remove that slot or choose another date and time.",
                "error",
            )
            return render_template(
                "employee/event_form.html",
                form=form,
                title="Edit Event",
                track_layouts=layouts,
                event=event,
            )
        requested_capacities = {
            "driver": form.driver_capacity.data,
            "spectator": form.spectator_capacity.data,
            "vendor": form.vendor_capacity.data,
        }
        for category, requested_capacity in requested_capacities.items():
            sold = ticket_availability(event, category)["sold"]
            if requested_capacity and requested_capacity < sold:
                flash(
                    f"{category.title()} capacity cannot be lower than the {sold} tickets already issued.",
                    "error",
                )
                return render_template(
                    "employee/event_form.html",
                    form=form,
                    title="Edit Event",
                    track_layouts=layouts,
                    event=event,
                )
        layout_error = _apply_event_layout_selection(event, active_track_id())
        if layout_error:
            flash(layout_error, "error")
            return render_template("employee/event_form.html", form=form, title="Edit Event", track_layouts=layouts, event=event)
        event.event_name = form.event_name.data.strip()
        event.event_date = form.event_date.data
        event.driver_price_cents = _to_cents(form.driver_price.data)
        event.spectator_price_cents = _to_cents(form.spectator_price.data)
        event.vendor_price_cents = _to_cents(form.vendor_price.data)
        event.driver_capacity = form.driver_capacity.data
        event.spectator_capacity = form.spectator_capacity.data
        event.vendor_capacity = form.vendor_capacity.data
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
    guard = require_office_staff()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    if event.event_type == "private":
        flash("Private rental events cannot be deleted from the event list.", "error")
        return redirect(url_for("employee.private_rentals", month=event.event_date.strftime("%Y-%m")))
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


@employee_bp.route(
    "/events/<int:event_id>/participants/<int:registration_id>/checkin",
    methods=["POST"],
)
@login_required
def driver_checkin(event_id, registration_id):
    guard = require_employee()
    if guard:
        return guard
    registration = _load_registration_for_track(event_id, registration_id)
    if registration.checked_in_at:
        flash("Driver is already checked in.", "error")
    else:
        from .waiver_routes import get_required_waiver_status

        waiver_status, _ = get_required_waiver_status(
            registration.event.track_id,
            registration.user_id,
            registration.event_id,
        )
        if waiver_status not in {"signed", "not_required"}:
            flash("The driver must complete the required waiver before check-in.", "error")
        else:
            registration.checked_in_at = datetime.utcnow()
            if current_user.account_type == "employee":
                registration.checked_in_by_employee_id = current_user.id
            db.session.commit()
            flash(
                f"{registration.user.first_name} {registration.user.last_name} checked in.",
                "success",
            )

    return_to = (request.form.get("return_to") or "participants").strip()
    if return_to == "event":
        return redirect(url_for("employee.event_detail", event_id=event_id, view="participants"))
    if return_to == "inspection":
        return redirect(
            url_for(
                "employee.inspection_lookup",
                event_id=event_id,
                code=registration.checkin_code,
            )
        )
    if return_to == "inspections":
        return redirect(url_for("employee.inspections_hub", event_id=event_id))
    if return_to == "run_groups":
        return redirect(url_for("employee.event_detail", event_id=event_id, view="slots"))
    if return_to == "ticket_scanner":
        return redirect(
            url_for(
                "employee.ticket_verification",
                code=registration.checkin_code,
                **({"scanner": 1} if request.form.get("scanner_active") == "1" else {}),
            )
        )
    return redirect(url_for("employee.participants", event_id=event_id))


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
    if view not in {"general", "analytics", "participants", "inspect", "slots"}:
        view = "general"
    if view == "analytics" and not has_office_access():
        flash("Office staff access required for event analytics.", "error")
        return redirect(url_for("employee.event_detail", event_id=event.id, view="general"))

    groups = []
    assignments = {}
    participants = []
    class_by_user = {}
    inspections = {}
    waiver_status = {}
    class_slots = []

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
        from .waiver_routes import get_required_waiver_status

        for reg in participants:
            class_by_user[reg.user_id] = _get_or_create_track_driver_class(event.track_id, reg.user_id).driver_class
            status, waiver = get_required_waiver_status(event.track_id, reg.user_id, event.id)
            waiver_status[reg.id] = {"status": status, "waiver": waiver}
        db.session.commit()

    if view == "slots":
        class_slots = (
            EventClassSlot.query.filter_by(event_id=event.id)
            .order_by(EventClassSlot.start_time.asc())
            .all()
        )

    return render_template(
        "employee/event_detail.html",
        event=event,
        event_capacity={
            category: ticket_availability(event, category)
            for category in ("driver", "spectator", "vendor")
        },
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
        waiver_status=waiver_status,
        class_slots=class_slots,
        today=date.today(),
    )


@employee_bp.route("/events/<int:event_id>/slots/new", methods=["POST"])
@login_required
def event_slot_new(event_id):
    guard = require_office_staff()
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
    guard = require_office_staff()
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
    guard = require_office_staff()
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
    scanner_active = request.form.get("scanner_active") == "1"
    scanner_url = url_for(
        "employee.ticket_verification",
        code=item.qr_code,
        **({"scanner": 1} if scanner_active else {}),
    )
    if not payment_is_confirmed(
        item.order.payment_status,
        item.order.payment_method,
        item.order.total_cents,
        item.order.provider_transaction_id,
    ):
        flash("This ticket cannot be checked in because payment is not complete.", "error")
        return redirect(scanner_url)
    if item.checked_in_at:
        flash("Ticket already checked in.", "error")
        return redirect(scanner_url)
    item.checked_in_at = datetime.utcnow()
    if current_user.account_type == "employee":
        item.checked_in_by_employee_id = current_user.id
    db.session.commit()
    checkin_label = (
        item.order.vendor.business_name
        if item.ticket_category == "vendor" and item.order.vendor
        else (
            item.order.vendor_business_name
            if item.ticket_category == "vendor"
            else (item.order.guest_full_name or "guest")
        )
    )
    flash(f"{item.ticket_type_name} ticket checked in for {checkin_label or 'vendor'}.", "success")
    return redirect(scanner_url)


@employee_bp.route("/events/<int:event_id>/run-groups")
@login_required
def run_groups(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    return redirect(url_for("employee.event_detail", event_id=event.id, view="slots"))


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
            | (User.username.ilike(like))
            | (User.email.ilike(like)),
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


@employee_bp.route("/drivers")
@login_required
def drivers():
    guard = require_employee()
    if guard:
        return guard
    track_id = active_track_id()
    track = Track.query.get_or_404(track_id)
    directory_view = (request.args.get("view") or "drivers").strip().lower()
    if directory_view not in {"drivers", "vendors"}:
        directory_view = "drivers"
    query_text = (request.args.get("q") or "").strip()
    if directory_view == "vendors":
        vendor_query = VendorAccount.query
        if query_text:
            pattern = f"%{query_text}%"
            public_filters = [
                VendorAccount.business_name.ilike(pattern),
                VendorAccount.website.ilike(pattern),
                VendorAccount.description.ilike(pattern),
            ]
            if has_office_access():
                public_filters.extend(
                    [
                        VendorAccount.full_name.ilike(pattern),
                        VendorAccount.email.ilike(pattern),
                        VendorAccount.phone.ilike(pattern),
                        VendorAccount.business_address.ilike(pattern),
                    ]
                )
            vendor_query = vendor_query.filter(or_(*public_filters))
        vendor_rows = (
            vendor_query.order_by(VendorAccount.business_name.asc()).limit(250).all()
        )
        return render_template(
            "employee/people.html",
            directory_view=directory_view,
            vendors=vendor_rows,
            rows=[],
            query_text=query_text,
            track=track,
        )

    query = _track_driver_query(track_id)
    if query_text:
        like = f"%{query_text}%"
        query = query.filter(
            (User.first_name.ilike(like))
            | (User.last_name.ilike(like))
            | (User.username.ilike(like))
            | (User.email.ilike(like))
            | (User.phone.ilike(like))
        )
    driver_users = query.order_by(User.last_name.asc(), User.first_name.asc()).limit(200).all()
    driver_ids = [driver.id for driver in driver_users]
    class_records = {
        item.user_id: item
        for item in TrackDriverClass.query.filter(
            TrackDriverClass.track_id == track_id,
            TrackDriverClass.user_id.in_(driver_ids or [-1]),
        ).all()
    }
    registration_stats = {
        user_id: {
            "registered_count": int(registered_count or 0),
            "attended_count": int(attended_count or 0),
            "last_event_date": last_event_date,
        }
        for user_id, registered_count, attended_count, last_event_date in (
            db.session.query(
                EventRegistration.user_id,
                func.count(EventRegistration.id),
                func.sum(
                    case(
                        (
                            (EventRegistration.checked_in_at.isnot(None))
                            | (Inspection.id.isnot(None)),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.max(Event.event_date),
            )
            .join(Event, Event.id == EventRegistration.event_id)
            .outerjoin(Inspection, Inspection.event_registration_id == EventRegistration.id)
            .filter(Event.track_id == track_id, EventRegistration.user_id.in_(driver_ids or [-1]))
            .group_by(EventRegistration.user_id)
            .all()
        )
    }
    note_counts = {
        user_id: int(note_count or 0)
        for user_id, note_count in (
            db.session.query(DriverNote.user_id, func.count(DriverNote.id))
            .filter(DriverNote.track_id == track_id, DriverNote.user_id.in_(driver_ids or [-1]))
            .group_by(DriverNote.user_id)
            .all()
        )
    }
    rows = []
    for driver in driver_users:
        stats = registration_stats.get(
            driver.id,
            {"registered_count": 0, "attended_count": 0, "last_event_date": None},
        )
        rows.append(
            {
                "driver": driver,
                "driver_class": class_records.get(driver.id).driver_class if class_records.get(driver.id) else "C",
                "registered_count": stats["registered_count"],
                "attended_count": stats["attended_count"],
                "last_event_date": stats["last_event_date"],
                "note_count": note_counts.get(driver.id, 0),
            }
        )
    return render_template(
        "employee/people.html",
        directory_view=directory_view,
        rows=rows,
        vendors=[],
        query_text=query_text,
        track=track,
    )


@employee_bp.route("/drivers/<int:user_id>")
@login_required
def driver_profile(user_id):
    guard = require_employee()
    if guard:
        return guard
    track_id = active_track_id()
    driver = _load_track_driver(track_id, user_id)
    registrations = (
        EventRegistration.query.join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == track_id, EventRegistration.user_id == driver.id)
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
    attended_registration_ids = {
        registration.id
        for registration in registrations
        if registration.checked_in_at or inspections.get(registration.id)
    }
    attended_count = len(attended_registration_ids)
    passed_inspection_count = sum(
        1
        for registration in registrations
        if inspections.get(registration.id) and inspections[registration.id].passed
    )
    class_record = TrackDriverClass.query.filter_by(track_id=track_id, user_id=driver.id).first()
    class_changes = (
        DriverClassChange.query.filter_by(track_id=track_id, user_id=driver.id)
        .order_by(DriverClassChange.created_at.desc())
        .all()
    )
    notes = (
        DriverNote.query.filter_by(track_id=track_id, user_id=driver.id)
        .order_by(DriverNote.created_at.desc())
        .all()
    )
    used_cars = []
    seen_car_ids = set()
    for registration in registrations:
        if registration.car_id not in seen_car_ids:
            used_cars.append(registration.car)
            seen_car_ids.add(registration.car_id)
    return render_template(
        "employee/driver_profile.html",
        driver=driver,
        track=Track.query.get_or_404(track_id),
        registrations=registrations,
        inspections=inspections,
        attended_count=attended_count,
        attended_registration_ids=attended_registration_ids,
        passed_inspection_count=passed_inspection_count,
        class_record=class_record,
        current_driver_class=class_record.driver_class if class_record else "C",
        class_changes=class_changes,
        notes=notes,
        used_cars=used_cars,
    )


@employee_bp.route("/drivers/<int:user_id>/notes", methods=["POST"])
@login_required
def add_driver_note(user_id):
    guard = require_employee()
    if guard:
        return guard
    track_id = active_track_id()
    driver = _load_track_driver(track_id, user_id)
    note_text = (request.form.get("note_text") or "").strip()
    if not note_text:
        flash("Enter a note before saving.", "error")
        return redirect(url_for("employee.driver_profile", user_id=driver.id, _anchor="notes"))
    if len(note_text) > 2000:
        flash("Driver notes must be 2,000 characters or fewer.", "error")
        return redirect(url_for("employee.driver_profile", user_id=driver.id, _anchor="notes"))
    actor_type, actor_id, actor_name = _current_staff_actor()
    db.session.add(
        DriverNote(
            track_id=track_id,
            user_id=driver.id,
            note_text=note_text,
            author_type=actor_type,
            author_id=actor_id,
            author_name=actor_name,
        )
    )
    db.session.commit()
    flash("Driver note added for your track staff.", "success")
    return redirect(url_for("employee.driver_profile", user_id=driver.id, _anchor="notes"))


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
        _track_driver_query(track_id)
        .filter(
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
    for driver in rows:
        class_record = TrackDriverClass.query.filter_by(track_id=track_id, user_id=driver.id).first()
        driver_class = class_record.driver_class if class_record else "C"
        full_name = f"{driver.first_name} {driver.last_name}".strip()
        payload.append(
            {
                "user_id": driver.id,
                "name": full_name,
                "email": driver.email,
                "driver_class": driver_class,
                "profile_url": url_for("employee.driver_profile", user_id=driver.id),
                "update_url": url_for("employee.update_driver_class", track_id=track_id, user_id=driver.id),
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
    driver = _load_track_driver(track_id, user_id)

    selected = (request.form.get("driver_class") or "").strip().upper()
    if selected not in {"A", "B", "C"}:
        flash("Invalid class selected.", "error")
        return redirect(request.referrer or url_for("employee.dashboard"))

    record = _get_or_create_track_driver_class(track_id, user_id)
    previous_class = record.driver_class
    if previous_class == selected:
        flash(f"{driver.first_name} is already in class {selected}.", "success")
        return redirect(request.referrer or url_for("employee.driver_profile", user_id=user_id))
    actor_type, actor_id, actor_name = _current_staff_actor()
    record.driver_class = selected
    if current_user.account_type == "employee":
        record.updated_by_employee_id = current_user.id
    db.session.add(
        DriverClassChange(
            track_id=track_id,
            user_id=user_id,
            previous_class=previous_class,
            new_class=selected,
            changed_by_type=actor_type,
            changed_by_id=actor_id,
            changed_by_name=actor_name,
        )
    )
    db.session.commit()
    flash(f"{driver.first_name} {driver.last_name} moved from class {previous_class} to {selected}.", "success")
    return redirect(request.referrer or url_for("employee.driver_profile", user_id=user_id))


@employee_bp.route("/inspection-rules", methods=["POST"])
@login_required
def add_inspection_rule():
    guard = require_office_staff()
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
    guard = require_office_staff()
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
    guard = require_office_staff()
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
    guard = require_office_staff()
    if guard:
        return guard
    rules = InspectionRule.query.filter_by(track_id=active_track_id()).order_by(InspectionRule.sort_order.asc(), InspectionRule.id.asc()).all()
    form = InspectionRuleForm()
    return render_template("employee/inspection_rules.html", rules=rules, form=form)


@employee_bp.route("/waivers/template-builder", methods=["GET", "POST"])
@login_required
def waiver_template_builder():
    guard = require_office_staff()
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
    guard = require_office_staff()
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
    code = normalize_ticket_code(request.args.get("code"))
    registration = None
    if code:
        registration = (
            EventRegistration.query.join(User, User.id == EventRegistration.user_id)
            .join(Car, Car.id == EventRegistration.car_id)
            .filter(
                EventRegistration.event_id == event.id,
                or_(
                    EventRegistration.checkin_code == code,
                    User.static_qr_code == code,
                    Car.static_qr_code == code,
                ),
            )
            .first()
        )
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
        flash("An active inspection checklist is required before inspecting cars.", "error")
        if request.args.get("return_to") == "hub":
            return redirect(
                url_for(
                    "employee.inspections_hub",
                    event_id=event_id,
                    **({"scanner": 1} if request.args.get("scanner") == "1" else {}),
                )
            )
        return redirect(url_for("employee.event_detail", event_id=event_id, view="inspect"))

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
        if request.args.get("return_to") == "hub":
            return redirect(
                url_for(
                    "employee.inspections_hub",
                    event_id=event_id,
                    **({"scanner": 1} if request.args.get("scanner") == "1" else {}),
                )
            )
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
        return_to=request.args.get("return_to"),
        scanner_active=request.args.get("scanner") == "1",
    )
