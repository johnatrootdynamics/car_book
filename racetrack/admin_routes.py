from flask import Blueprint, flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from .models import Track


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
    return render_template(
        "admin/dashboard.html",
        tracks=tracks,
        impersonating_track_id=impersonating_track_id,
    )


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
