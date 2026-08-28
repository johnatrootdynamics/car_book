from collections import OrderedDict
from datetime import date

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from .forms import VendorProfileForm
from .models import (
    Employee,
    EnterpriseAdmin,
    SpectatorOrder,
    SpectatorOrderItem,
    User,
    VendorAccount,
    db,
)
from .services.payment_service import payment_is_confirmed
from .services.storage_service import upload_public_image


vendor_bp = Blueprint("vendor", __name__, url_prefix="/vendor")


def require_vendor():
    if not current_user.is_authenticated:
        flash("Please sign in with your vendor account.", "error")
        return redirect(url_for("auth.user_login", next=request.path))
    if current_user.account_type != "vendor":
        flash("Vendor account access required for that page.", "error")
        return redirect(url_for("auth.home"))
    return None


def _normalized_website(raw_value):
    website = (raw_value or "").strip()
    if website and not website.lower().startswith(("http://", "https://")):
        website = f"https://{website}"
    return website or None


def _email_is_available(email, vendor_id):
    if VendorAccount.query.filter(
        VendorAccount.email == email,
        VendorAccount.id != vendor_id,
    ).first():
        return False
    return not any(
        model.query.filter_by(email=email).first()
        for model in (User, Employee, EnterpriseAdmin)
    )


@vendor_bp.route("/dashboard")
@login_required
def dashboard():
    guard = require_vendor()
    if guard:
        return guard
    items = (
        SpectatorOrderItem.query.join(
            SpectatorOrder,
            SpectatorOrder.id == SpectatorOrderItem.order_id,
        )
        .filter(
            SpectatorOrder.vendor_id == current_user.id,
            SpectatorOrderItem.ticket_category == "vendor",
        )
        .order_by(SpectatorOrder.created_at.desc(), SpectatorOrderItem.id.asc())
        .all()
    )
    paid_items = [
        item
        for item in items
        if payment_is_confirmed(
            item.order.payment_status,
            item.order.payment_method,
            item.order.total_cents,
            item.order.provider_transaction_id,
        )
    ]
    orders = OrderedDict()
    for item in paid_items:
        orders.setdefault(item.order.id, {"order": item.order, "items": []})["items"].append(item)
    return render_template(
        "vendor/dashboard.html",
        orders=list(orders.values()),
        ticket_count=len(paid_items),
        upcoming_count=sum(1 for item in paid_items if item.event.event_date >= date.today()),
    )


@vendor_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    guard = require_vendor()
    if guard:
        return guard
    form = VendorProfileForm(obj=current_user)
    if form.validate_on_submit():
        normalized_email = form.email.data.lower().strip()
        if not _email_is_available(normalized_email, current_user.id):
            flash("That email is already used by another Track Ops account.", "error")
            return render_template("vendor/profile.html", form=form)
        current_user.full_name = form.full_name.data.strip()
        current_user.business_name = form.business_name.data.strip()
        current_user.email = normalized_email
        current_user.phone = form.phone.data.strip()
        current_user.business_address = form.business_address.data.strip()
        current_user.website = _normalized_website(form.website.data)
        current_user.description = (form.description.data or "").strip() or None
        if form.logo.data and getattr(form.logo.data, "filename", ""):
            form.logo.data.filename = secure_filename(form.logo.data.filename)
            current_user.logo_image_path = upload_public_image(
                form.logo.data,
                bucket=current_app.config["S3_BUCKET"],
                endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
                access_key=current_app.config["S3_ACCESS_KEY"],
                secret_key=current_app.config["S3_SECRET_KEY"],
                key_prefix=f"vendors/{current_user.id}",
            )
        db.session.commit()
        flash("Vendor profile updated.", "success")
        return redirect(url_for("vendor.profile"))
    return render_template("vendor/profile.html", form=form)


@vendor_bp.route("/<int:vendor_id>")
def public_profile(vendor_id):
    vendor = VendorAccount.query.get_or_404(vendor_id)
    return render_template("vendor/public_profile.html", vendor=vendor)
