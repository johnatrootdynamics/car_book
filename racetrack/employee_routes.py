import os
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from sqlalchemy import func

from .forms import EventForm, TrackProfileForm
from .models import Event, EventRegistration, Track, db


employee_bp = Blueprint("employee", __name__, url_prefix="/employee")


def require_employee():
    if not current_user.is_authenticated:
        flash("Please sign in as a track employee.", "error")
        return redirect(url_for("auth.employee_login"))
    if current_user.account_type != "employee":
        flash("Employee access required for that page.", "error")
        return redirect(url_for("user.dashboard"))
    return None


@employee_bp.route("/dashboard")
@login_required
def dashboard():
    guard = require_employee()
    if guard:
        return guard
    track = Track.query.get_or_404(current_user.track_id)
    events = (
        Event.query.filter_by(track_id=current_user.track_id)
        .order_by(Event.event_date.asc())
        .all()
    )
    signup_counts_raw = (
        db.session.query(EventRegistration.event_id, func.count(EventRegistration.id))
        .join(Event, Event.id == EventRegistration.event_id)
        .filter(Event.track_id == current_user.track_id)
        .group_by(EventRegistration.event_id)
        .all()
    )
    signup_counts = {event_id: count for event_id, count in signup_counts_raw}
    profile_form = TrackProfileForm(obj=track)
    return render_template(
        "employee/dashboard.html",
        events=events,
        track=track,
        signup_counts=signup_counts,
        profile_form=profile_form,
    )


@employee_bp.route("/track", methods=["POST"])
@login_required
def update_track():
    guard = require_employee()
    if guard:
        return guard
    track = Track.query.get_or_404(current_user.track_id)
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


@employee_bp.route("/events/new", methods=["GET", "POST"])
@login_required
def event_new():
    guard = require_employee()
    if guard:
        return guard
    form = EventForm()
    if form.validate_on_submit():
        event = Event(
            track_id=current_user.track_id,
            event_name=form.event_name.data.strip(),
            event_date=form.event_date.data,
        )
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
    event = Event.query.filter_by(id=event_id, track_id=current_user.track_id).first_or_404()
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
    event = Event.query.filter_by(id=event_id, track_id=current_user.track_id).first_or_404()
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
    event = Event.query.filter_by(id=event_id, track_id=current_user.track_id).first_or_404()
    regs = (
        EventRegistration.query.filter_by(event_id=event.id)
        .order_by(EventRegistration.created_at.asc())
        .all()
    )
    return render_template("employee/participants.html", event=event, registrations=regs)
