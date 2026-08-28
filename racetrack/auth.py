from datetime import date
import secrets

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
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from .forms import (
    LoginForm,
    PasswordChangeForm,
    PasswordUpdateForm,
    UserRegistrationForm,
    VendorRegistrationForm,
)
from .models import Employee, EnterpriseAdmin, User, VendorAccount, db
from .security import generate_random_password
from .services.email_service import send_user_login_email, send_vendor_login_email
from .services.storage_service import upload_public_image


auth_bp = Blueprint("auth", __name__)


@auth_bp.before_app_request
def enforce_automated_password_change():
    if not current_user.is_authenticated or not getattr(current_user, "must_change_password", False):
        return None
    if request.endpoint in {"auth.change_password", "auth.logout", "static"}:
        return None
    return redirect(url_for("auth.change_password"))


def _safe_next_url(default_endpoint):
    target = (request.args.get("next") or "").strip()
    if target.startswith("/") and not target.startswith("//"):
        return target
    return url_for(default_endpoint)


def _account_home(account):
    return {
        "user": "user.dashboard",
        "employee": "employee.dashboard",
        "admin": "admin.dashboard",
        "vendor": "vendor.dashboard",
    }.get(getattr(account, "account_type", None), "auth.home")


def _account_email_exists(email):
    return any(
        model.query.filter_by(email=email).first()
        for model in (User, Employee, EnterpriseAdmin, VendorAccount)
    )


def _normalized_website(raw_value):
    website = (raw_value or "").strip()
    if website and not website.lower().startswith(("http://", "https://")):
        website = f"https://{website}"
    return website or None


def _generate_user_qr_code():
    while True:
        code = f"DRV-{secrets.token_hex(4).upper()}"
        if not User.query.filter_by(static_qr_code=code).first():
            return code


@auth_bp.route("/")
def home():
    return render_template("home.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def user_register():
    if current_user.is_authenticated:
        return redirect(url_for(_account_home(current_user)))
    form = UserRegistrationForm()
    if form.validate_on_submit():
        normalized_username = form.username.data.strip().lower()
        existing_username = User.query.filter_by(username=normalized_username).first()
        if existing_username:
            flash("Username already taken.", "error")
            return render_template("auth/register.html", form=form)
        normalized_email = form.email.data.lower().strip()
        if _account_email_exists(normalized_email):
            flash("Email already registered.", "error")
            return render_template("auth/register.html", form=form)
        plaintext_password = generate_random_password()
        user = User(
            first_name=form.full_name.data.strip().split(" ")[0],
            last_name=" ".join(form.full_name.data.strip().split(" ")[1:]) or "-",
            username=normalized_username,
            email=normalized_email,
            phone=(form.phone.data or "").strip() or "N/A",
            driver_class="C",
            static_qr_code=_generate_user_qr_code(),
            date_of_birth=date(1970, 1, 1),
            street="N/A",
            city="N/A",
            state="N/A",
            postal_code="N/A",
            password_hash=generate_password_hash(plaintext_password),
            must_change_password=True,
        )
        db.session.add(user)
        try:
            db.session.flush()
            sent = send_user_login_email(
                user,
                plaintext_password,
                url_for("auth.user_login", _external=True),
            )
        except Exception:
            current_app.logger.exception("Could not send new driver login email")
            sent = False
        if not sent:
            db.session.rollback()
            flash("Account was not created because the login email could not be delivered.", "error")
            return render_template("auth/register.html", form=form)
        db.session.commit()
        flash("Account created. A temporary password has been emailed to you.", "success")
        return redirect(url_for("auth.user_login"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/register/vendor", methods=["GET", "POST"])
def vendor_register():
    if current_user.is_authenticated:
        return redirect(url_for(_account_home(current_user)))
    form = VendorRegistrationForm()
    if form.validate_on_submit():
        normalized_email = form.email.data.lower().strip()
        if _account_email_exists(normalized_email):
            flash("Email already registered.", "error")
            return render_template("auth/vendor_register.html", form=form)
        plaintext_password = generate_random_password()
        vendor = VendorAccount(
            full_name=form.full_name.data.strip(),
            business_name=form.business_name.data.strip(),
            email=normalized_email,
            phone=form.phone.data.strip(),
            business_address=form.business_address.data.strip(),
            website=_normalized_website(form.website.data),
            description=(form.description.data or "").strip() or None,
            password_hash=generate_password_hash(plaintext_password),
            must_change_password=True,
        )
        db.session.add(vendor)
        try:
            db.session.flush()
            if form.logo.data and getattr(form.logo.data, "filename", ""):
                form.logo.data.filename = secure_filename(form.logo.data.filename)
                vendor.logo_image_path = upload_public_image(
                    form.logo.data,
                    bucket=current_app.config["S3_BUCKET"],
                    endpoint_url=current_app.config["S3_API_ENDPOINT_URL"],
                    access_key=current_app.config["S3_ACCESS_KEY"],
                    secret_key=current_app.config["S3_SECRET_KEY"],
                    key_prefix=f"vendors/{vendor.id}",
                )
            sent = send_vendor_login_email(
                vendor,
                plaintext_password,
                url_for("auth.user_login", _external=True),
            )
        except Exception:
            current_app.logger.exception("Could not create or email vendor account")
            sent = False
        if not sent:
            db.session.rollback()
            flash("Account was not created because the login email could not be delivered.", "error")
            return render_template("auth/vendor_register.html", form=form)
        db.session.commit()
        flash("Vendor account created. A temporary password has been emailed to you.", "success")
        return redirect(url_for("auth.user_login"))
    return render_template("auth/vendor_register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def user_login():
    if current_user.is_authenticated:
        return redirect(url_for(_account_home(current_user)))
    form = LoginForm()
    if form.validate_on_submit():
        try:
            email = form.email.data.lower().strip()
            candidates = [
                account
                for account in (
                    EnterpriseAdmin.query.filter_by(email=email).first(),
                    Employee.query.filter_by(email=email).first(),
                    VendorAccount.query.filter_by(email=email).first(),
                    User.query.filter_by(email=email).first(),
                )
                if account and check_password_hash(account.password_hash, form.password.data)
            ]
            if len(candidates) == 1:
                account = candidates[0]
                login_user(account)
                if account.account_type == "admin":
                    session.pop("impersonate_track_id", None)
                if account.must_change_password:
                    return redirect(url_for("auth.change_password"))
                return redirect(_safe_next_url(_account_home(account)))
            if len(candidates) > 1:
                flash("This email matches multiple accounts. Contact an administrator for help.", "error")
                return render_template("auth/login.html", form=form, title="Sign in to Track Ops", login_role="unified")
            flash("Invalid credentials.", "error")
        except SQLAlchemyError:
            flash("Database unavailable. Please try again shortly.", "error")
    return render_template(
        "auth/login.html",
        form=form,
        title="Sign in to Track Ops",
        login_role="unified",
    )


@auth_bp.route("/employee/login", methods=["GET", "POST"])
def employee_login():
    return redirect(url_for("auth.user_login", next=request.args.get("next")))


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    return redirect(url_for("auth.user_login", next=request.args.get("next")))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if not getattr(current_user, "must_change_password", False):
        return redirect(url_for(_account_home(current_user)))
    form = PasswordChangeForm()
    if form.validate_on_submit():
        if check_password_hash(current_user.password_hash, form.new_password.data):
            form.new_password.errors.append("Choose a password different from the temporary password.")
        else:
            current_user.password_hash = generate_password_hash(form.new_password.data)
            current_user.must_change_password = False
            db.session.commit()
            flash("Password updated. Welcome to Track Ops.", "success")
            return redirect(url_for(_account_home(current_user)))
    return render_template("auth/change_password.html", form=form)


@auth_bp.route("/security", methods=["GET", "POST"])
@login_required
def security():
    if getattr(current_user, "must_change_password", False):
        return redirect(url_for("auth.change_password"))
    form = PasswordUpdateForm()
    if form.validate_on_submit():
        if not check_password_hash(current_user.password_hash, form.current_password.data):
            form.current_password.errors.append("Current password is incorrect.")
        elif check_password_hash(current_user.password_hash, form.new_password.data):
            form.new_password.errors.append("Choose a password different from your current password.")
        else:
            current_user.password_hash = generate_password_hash(form.new_password.data)
            db.session.commit()
            flash("Your password has been updated.", "success")
            return redirect(url_for("auth.security"))
    return render_template("auth/security.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("auth.home"))
