import os
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from .forms import EmployeeCreateForm, EventForm, InspectionForm, InspectionRuleForm, TrackProfileForm
from .models import Employee, Event, EventRegistration, Inspection, InspectionItem, InspectionRule, Track, db


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


@employee_bp.route("/dashboard")
@login_required
def dashboard():
    guard = require_employee()
    if guard:
        return guard
    track = Track.query.get_or_404(active_track_id())
    events = Event.query.filter_by(track_id=active_track_id()).order_by(Event.event_date.asc()).all()
    signup_counts_raw = (
        db.session.query(EventRegistration.event_id, func.count(EventRegistration.id))
        .join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == active_track_id())
        .group_by(EventRegistration.event_id)
        .all()
    )
    signup_counts = {event_id: count for event_id, count in signup_counts_raw}
    return render_template(
        "employee/dashboard.html",
        events=events,
        track=track,
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
    return render_template("employee/track_profile.html", track=track, form=form)


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
        upload = form.layout_image.data
        if upload:
            clean_name = secure_filename(upload.filename)
            ext = os.path.splitext(clean_name)[1].lower()
            new_name = f"track_{track.id}_{uuid4().hex}{ext}"
            out_path = os.path.join(current_app.config["UPLOAD_FOLDER"], new_name)
            upload.save(out_path)
            track.layout_image_path = f"uploads/tracks/{new_name}"
        db.session.commit()
        flash("Track profile updated.", "success")
    else:
        flash("Could not update track profile. Check form fields.", "error")
    return redirect(url_for("employee.dashboard"))


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
    if form.validate_on_submit():
        event = Event(track_id=active_track_id(), event_name=form.event_name.data.strip(), event_date=form.event_date.data)
        db.session.add(event)
        db.session.commit()
        flash("Event created.", "success")
        return redirect(url_for("employee.dashboard"))
    return render_template("employee/event_form.html", form=form, title="Create Event")


@employee_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def event_edit(event_id):
    guard = require_employee()
    if guard:
        return guard
    event = Event.query.filter_by(id=event_id, track_id=active_track_id()).first_or_404()
    form = EventForm(obj=event)
    if form.validate_on_submit():
        event.event_name = form.event_name.data.strip()
        event.event_date = form.event_date.data
        db.session.commit()
        flash("Event updated.", "success")
        return redirect(url_for("employee.dashboard"))
    return render_template("employee/event_form.html", form=form, title="Edit Event")


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
    return redirect(url_for("employee.dashboard"))


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
    return render_template("employee/participants.html", event=event, registrations=regs, inspections=inspections)


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
    return render_template("employee/inspection_lookup.html", event=event, code=code, registration=registration)


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

    return render_template(
        "employee/inspection_form.html",
        registration=registration,
        event=registration.event,
        rules=rules,
        existing_map=existing_map,
        form=form,
        inspection=inspection,
    )
