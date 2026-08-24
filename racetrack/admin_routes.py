from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_
from email_validator import EmailNotValidError, validate_email
from werkzeug.security import generate_password_hash

from .forms import TrackCreateForm, WaiverTemplateForm
from .models import (
    DriverTicketOrder,
    DriverWaiver,
    Employee,
    EnterpriseAdmin,
    EventRegistration,
    SpectatorOrder,
    SystemEmailSettings,
    Track,
    TrackWaiverTemplate,
    User,
    db,
)
from .security import generate_random_password
from .services.boldsign_service import list_templates
from .services.email_service import (
    encrypt_smtp_password,
    get_email_configuration,
    send_email,
    send_admin_login_email,
    send_driver_purchase_receipt,
    send_employee_login_email,
    send_spectator_order_receipt,
    send_user_login_email,
)
from .services.order_service import filter_order_rows, format_money, load_order_rows, summarize_orders
from .services.payment_service import effective_payment_status


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


@admin_bp.route("/settings")
@login_required
def settings():
    guard = require_admin()
    if guard:
        return guard
    smtp_settings = SystemEmailSettings.query.get(1)
    email_config = get_email_configuration(include_password=False)
    return render_template(
        "admin/settings.html",
        smtp_settings=smtp_settings,
        email_config=email_config,
    )


@admin_bp.route("/settings/smtp", methods=["POST"])
@login_required
def update_smtp_settings():
    guard = require_admin()
    if guard:
        return guard

    smtp_settings = SystemEmailSettings.query.get(1)
    if not smtp_settings:
        smtp_settings = SystemEmailSettings(id=1)
        db.session.add(smtp_settings)

    server = (request.form.get("server") or "").strip()
    username = (request.form.get("username") or "").strip()
    sender_name = (request.form.get("sender_name") or "").strip()
    sender_email = (request.form.get("sender_email") or "").strip()
    security = (request.form.get("security") or "starttls").strip().lower()
    password = request.form.get("password") or ""
    is_enabled = request.form.get("is_enabled") == "1"

    try:
        port = int(request.form.get("port") or "587")
    except ValueError:
        port = 0

    errors = []
    if not server:
        errors.append("SMTP server is required.")
    if not 1 <= port <= 65535:
        errors.append("SMTP port must be between 1 and 65535.")
    if security not in {"starttls", "ssl", "none"}:
        errors.append("Select a valid SMTP security method.")
    if not sender_email:
        errors.append("Sender email is required.")
    else:
        try:
            sender_email = validate_email(
                sender_email,
                check_deliverability=False,
            ).normalized
        except EmailNotValidError:
            errors.append("Enter a valid sender email address.")
    password_will_exist = bool(password or smtp_settings.password_encrypted)
    if username and not password_will_exist:
        errors.append("Enter the SMTP password for this username.")

    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.settings"))

    smtp_settings.is_enabled = is_enabled
    smtp_settings.server = server
    smtp_settings.port = port
    smtp_settings.security = security
    smtp_settings.username = username or None
    smtp_settings.sender_name = sender_name or "Track Ops"
    smtp_settings.sender_email = sender_email
    smtp_settings.updated_by_admin_id = current_user.id
    if password:
        smtp_settings.password_encrypted = encrypt_smtp_password(password)

    db.session.commit()
    flash(
        "SMTP settings saved. Send a test email to verify delivery."
        if is_enabled
        else "SMTP settings saved with email delivery disabled.",
        "success",
    )
    return redirect(url_for("admin.settings"))


@admin_bp.route("/settings/smtp/test", methods=["POST"])
@login_required
def test_smtp_settings():
    guard = require_admin()
    if guard:
        return guard
    recipient = (request.form.get("test_email") or current_user.email or "").strip()
    try:
        recipient = validate_email(recipient, check_deliverability=False).normalized
    except EmailNotValidError:
        flash("Enter a valid test recipient email address.", "error")
        return redirect(url_for("admin.settings"))

    try:
        sent = send_email(
            recipient,
            "Track Ops SMTP test",
            "Your Track Ops SMTP configuration is working.\n\nYou can now send account credentials, order receipts, and other platform emails.",
        )
    except Exception as exc:
        current_app.logger.exception("SMTP test email failed")
        flash(f"SMTP test failed: {exc}", "error")
        return redirect(url_for("admin.settings"))
    if not sent:
        flash("SMTP test was not sent. Enable email delivery and complete the settings first.", "error")
        return redirect(url_for("admin.settings"))
    flash(f"Test email sent to {recipient}.", "success")
    return redirect(url_for("admin.settings"))


@admin_bp.route("/orders")
@login_required
def orders():
    guard = require_admin()
    if guard:
        return guard
    all_rows = load_order_rows()
    search = (request.args.get("q") or "").strip()
    payment_status = (request.args.get("status") or "").strip().lower()
    kind = (request.args.get("kind") or "").strip().lower()
    provider = (request.args.get("provider") or "").strip().lower()
    selected_track_id = request.args.get("track_id", type=int)
    rows = filter_order_rows(
        all_rows,
        search=search,
        payment_status=payment_status,
        kind=kind,
        provider=provider,
        track_id=selected_track_id,
    )
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = min(page, total_pages)
    page_rows = rows[(page - 1) * per_page : page * per_page]
    return render_template(
        "shared/orders.html",
        title="All Orders",
        subtitle="Every driver and spectator order across all tracks.",
        rows=page_rows,
        summary=summarize_orders(rows),
        providers=sorted({row["provider"] for row in all_rows}),
        tracks=Track.query.order_by(Track.name.asc()).all(),
        selected_track_id=selected_track_id,
        search=search,
        selected_status=payment_status,
        selected_kind=kind,
        selected_provider=provider,
        page=page,
        total_pages=total_pages,
        list_endpoint="admin.orders",
        detail_endpoint="admin.order_detail",
        show_track=True,
        money=format_money,
    )


@admin_bp.route("/orders/<kind>/<int:order_id>")
@login_required
def order_detail(kind, order_id):
    guard = require_admin()
    if guard:
        return guard
    if kind == "spectator":
        order = SpectatorOrder.query.get_or_404(order_id)
        if not order.items:
            return "Order has no event items", 404
        track = order.items[0].event.track
        items = list(order.items)
        registration = None
    elif kind == "driver":
        order = DriverTicketOrder.query.get_or_404(order_id)
        track = order.event.track
        registration = EventRegistration.query.filter_by(
            event_id=order.event_id,
            user_id=order.user_id,
        ).first()
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
        back_endpoint="admin.orders",
        resend_endpoint="admin.resend_order_email",
    )


@admin_bp.route("/orders/<kind>/<int:order_id>/resend-email", methods=["POST"])
@login_required
def resend_order_email(kind, order_id):
    guard = require_admin()
    if guard:
        return guard
    if kind == "spectator":
        order = SpectatorOrder.query.get_or_404(order_id)
        recipient = order.guest_email
        send_fn = send_spectator_order_receipt
        success_message = f"Tickets were resent to {recipient}."
    elif kind == "driver":
        order = DriverTicketOrder.query.get_or_404(order_id)
        recipient = order.buyer.email
        send_fn = send_driver_purchase_receipt
        success_message = f"Driver confirmation was resent to {recipient}."
    else:
        return "Unknown order type", 404

    if effective_payment_status(order) != "paid":
        flash("This email cannot be resent until payment is confirmed.", "error")
        return redirect(url_for("admin.order_detail", kind=kind, order_id=order_id))
    try:
        sent = send_fn(order)
    except Exception:
        current_app.logger.exception("Could not resend %s order email for order %s", kind, order_id)
        sent = False
    if not sent:
        flash("The email could not be sent. Check the SMTP settings and try again.", "error")
    else:
        flash(success_message, "success")
    return redirect(url_for("admin.order_detail", kind=kind, order_id=order_id))


@admin_bp.route("/accounts")
@login_required
def accounts():
    guard = require_admin()
    if guard:
        return guard
    query = (request.args.get("q") or "").strip()
    employees_query = Employee.query.join(Track)
    users_query = User.query
    admins_query = EnterpriseAdmin.query
    if query:
        pattern = f"%{query}%"
        employees_query = employees_query.filter(
            or_(
                Employee.full_name.ilike(pattern),
                Employee.email.ilike(pattern),
                Track.name.ilike(pattern),
            )
        )
        users_query = users_query.filter(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.username.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
        admins_query = admins_query.filter(
            or_(
                EnterpriseAdmin.full_name.ilike(pattern),
                EnterpriseAdmin.email.ilike(pattern),
            )
        )
    employees = employees_query.order_by(Employee.created_at.desc()).limit(100).all()
    users = users_query.order_by(User.created_at.desc()).limit(100).all()
    admins = admins_query.order_by(EnterpriseAdmin.created_at.desc()).limit(100).all()
    return render_template(
        "admin/accounts.html",
        employees=employees,
        users=users,
        admins=admins,
        query=query,
    )


@admin_bp.route(
    "/accounts/<account_type>/<int:account_id>/reset-password",
    methods=["POST"],
)
@login_required
def reset_account_password(account_type, account_id):
    guard = require_admin()
    if guard:
        return guard
    account_models = {
        "driver": User,
        "employee": Employee,
        "admin": EnterpriseAdmin,
    }
    model = account_models.get(account_type)
    if not model:
        flash("Unknown account type.", "error")
        return redirect(url_for("admin.accounts"))
    account = model.query.get_or_404(account_id)
    plaintext_password = generate_random_password()
    account.password_hash = generate_password_hash(plaintext_password)
    try:
        db.session.flush()
        if account_type == "driver":
            sent = send_user_login_email(
                account,
                plaintext_password,
                url_for("auth.user_login", _external=True),
                is_reset=True,
            )
        elif account_type == "employee":
            sent = send_employee_login_email(
                account,
                plaintext_password,
                account.track,
                url_for("auth.employee_login", _external=True),
                is_reset=True,
            )
        else:
            sent = send_admin_login_email(
                account,
                plaintext_password,
                url_for("auth.admin_login", _external=True),
                is_reset=True,
            )
    except Exception:
        current_app.logger.exception("Could not send enterprise password reset email")
        sent = False
    if not sent:
        db.session.rollback()
        flash("Password was not changed because the reset email could not be delivered.", "error")
        return redirect(url_for("admin.accounts", q=(request.form.get("q") or "").strip()))
    db.session.commit()
    flash(f"A new password was emailed to {account.email}.", "success")
    return redirect(url_for("admin.accounts", q=(request.form.get("q") or "").strip()))


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
    waiver_records = []
    boldsign_templates = []
    if track_id:
        templates = (
            TrackWaiverTemplate.query.filter_by(track_id=track_id)
            .order_by(TrackWaiverTemplate.updated_at.desc())
            .all()
        )
        waiver_records = (
            DriverWaiver.query.filter_by(track_id=track_id)
            .order_by(DriverWaiver.updated_at.desc())
            .limit(100)
            .all()
        )
        try:
            boldsign_templates = list_templates()
        except Exception as exc:
            flash(f"Could not load BoldSign templates: {exc}", "error")
    return render_template(
        "admin/waivers.html",
        templates=templates,
        waiver_records=waiver_records,
        boldsign_templates=boldsign_templates,
        track_id=track_id,
    )


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
    if request.method == "GET":
        pref_template_id = request.args.get("template_id", "").strip()
        pref_title = request.args.get("title", "").strip()
        if pref_template_id and not form.boldsign_template_id.data:
            form.boldsign_template_id.data = pref_template_id
        if pref_title and not form.title.data:
            form.title.data = pref_title
    if form.validate_on_submit():
        existing = TrackWaiverTemplate.query.filter_by(
            track_id=track_id, boldsign_template_id=form.boldsign_template_id.data.strip()
        ).first()
        if existing:
            flash("That BoldSign template is already linked for this track.", "error")
            return render_template("admin/waivers_new.html", form=form)
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


@admin_bp.route("/waivers/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def waivers_delete_template(template_id):
    guard = require_admin()
    if guard:
        return guard
    track_id = session.get("impersonate_track_id")
    template = TrackWaiverTemplate.query.get_or_404(template_id)
    if not track_id or template.track_id != track_id:
        flash("Template does not belong to the impersonated track.", "error")
        return redirect(url_for("admin.waivers"))
    db.session.delete(template)
    db.session.commit()
    flash("Waiver template deleted.", "success")
    return redirect(url_for("admin.waivers"))


@admin_bp.route("/waivers/records/<int:waiver_id>/delete", methods=["POST"])
@login_required
def waivers_delete_record(waiver_id):
    guard = require_admin()
    if guard:
        return guard
    track_id = session.get("impersonate_track_id")
    waiver = DriverWaiver.query.get_or_404(waiver_id)
    if not track_id or waiver.track_id != track_id:
        flash("Waiver record does not belong to the impersonated track.", "error")
        return redirect(url_for("admin.waivers"))
    db.session.delete(waiver)
    db.session.commit()
    flash("Driver waiver record deleted.", "success")
    return redirect(url_for("admin.waivers"))
