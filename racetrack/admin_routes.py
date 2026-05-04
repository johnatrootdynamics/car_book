from flask import Blueprint, flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from .forms import TrackCreateForm, WaiverTemplateForm
from .models import Track, TrackWaiverTemplate, db


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def require_admin():
    if not current_user.is_authenticated:
        flash("Please sign in as enterprise admin.", "error")
        return redirect(url_for("auth.admin_login"))
    if current_user.account_type != "admin":
        flash("Enterprise admin access required.", "error")
        return redirect(url_for("auth.home"))
    return None


@admin_bp.route("/dashboard")
@login_required
def dashboard():
    guard = require_admin()
    if guard:
        return guard
    tracks = Track.query.order_by(Track.name.asc()).all()
    impersonating_track_id = session.get("impersonate_track_id")
    create_form = TrackCreateForm()
    return render_template(
        "admin/dashboard.html",
        tracks=tracks,
        impersonating_track_id=impersonating_track_id,
        create_form=create_form,
    )


@admin_bp.route("/tracks/new", methods=["POST"])
@login_required
def create_track():
    guard = require_admin()
    if guard:
        return guard
    form = TrackCreateForm()
    if form.validate_on_submit():
        existing = Track.query.filter_by(name=form.name.data.strip()).first()
        if existing:
            flash("Track name already exists.", "error")
        else:
            track = Track(
                name=form.name.data.strip(),
                city=form.city.data.strip(),
                state=form.state.data.strip(),
            )
            db.session.add(track)
            db.session.commit()
            flash("Track created.", "success")
    else:
        flash("Could not create track.", "error")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/impersonate/<int:track_id>", methods=["POST"])
@login_required
def impersonate_track(track_id):
    guard = require_admin()
    if guard:
        return guard
    track = Track.query.get_or_404(track_id)
    session["impersonate_track_id"] = track.id
    flash(f"Now impersonating track: {track.name}", "success")
    return redirect(url_for("employee.dashboard"))


@admin_bp.route("/impersonate/clear", methods=["POST"])
@login_required
def clear_impersonation():
    guard = require_admin()
    if guard:
        return guard
    session.pop("impersonate_track_id", None)
    flash("Impersonation cleared.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/waivers")
@login_required
def waivers():
    guard = require_admin()
    if guard:
        return guard
    track_id = session.get("impersonate_track_id")
    templates = []
    if track_id:
        templates = (
            TrackWaiverTemplate.query.filter_by(track_id=track_id)
            .order_by(TrackWaiverTemplate.updated_at.desc())
            .all()
        )
    return render_template("admin/waivers.html", templates=templates, track_id=track_id)


@admin_bp.route("/waivers/new", methods=["GET", "POST"])
@login_required
def waivers_new():
    guard = require_admin()
    if guard:
        return guard
    track_id = session.get("impersonate_track_id")
    if not track_id:
        flash("Select a track to impersonate first.", "error")
        return redirect(url_for("admin.dashboard"))
    form = WaiverTemplateForm()
    if form.validate_on_submit():
        template = TrackWaiverTemplate(
            track_id=track_id,
            title=form.title.data.strip(),
            boldsign_template_id=form.boldsign_template_id.data.strip(),
            is_active=bool(form.is_active.data),
            required_for_checkin=bool(form.required_for_checkin.data),
        )
        db.session.add(template)
        db.session.commit()
        flash("Waiver template saved.", "success")
        return redirect(url_for("admin.waivers"))
    return render_template("admin/waivers_new.html", form=form)
