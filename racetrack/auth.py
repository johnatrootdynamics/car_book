from datetime import date
import secrets

from flask import Blueprint, flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from .forms import LoginForm, UserRegistrationForm
from .models import Employee, EnterpriseAdmin, User, db


auth_bp = Blueprint("auth", __name__)


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
        return redirect(url_for("user.dashboard" if current_user.account_type == "user" else "employee.dashboard"))
    form = UserRegistrationForm()
    if form.validate_on_submit():
        normalized_username = form.username.data.strip().lower()
        existing_username = User.query.filter_by(username=normalized_username).first()
        if existing_username:
            flash("Username already taken.", "error")
            return render_template("auth/register.html", form=form)
        existing = User.query.filter_by(email=form.email.data.lower()).first()
        if existing:
            flash("Email already registered.", "error")
            return render_template("auth/register.html", form=form)
        user = User(
            first_name=form.full_name.data.strip().split(" ")[0],
            last_name=" ".join(form.full_name.data.strip().split(" ")[1:]) or "-",
            username=normalized_username,
            email=form.email.data.lower().strip(),
            phone=(form.phone.data or "").strip() or "N/A",
            static_qr_code=_generate_user_qr_code(),
            date_of_birth=date(1970, 1, 1),
            street="N/A",
            city="N/A",
            state="N/A",
            postal_code="N/A",
            password_hash=generate_password_hash(form.password.data),
        )
        db.session.add(user)
        db.session.commit()
        flash("Account created. Please sign in.", "success")
        return redirect(url_for("auth.user_login"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def user_login():
    if current_user.is_authenticated:
        return redirect(url_for("user.dashboard" if current_user.account_type == "user" else "employee.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = User.query.filter_by(email=form.email.data.lower().strip()).first()
            if user and check_password_hash(user.password_hash, form.password.data):
                login_user(user)
                return redirect(url_for("user.dashboard"))
            flash("Invalid credentials.", "error")
        except SQLAlchemyError:
            flash("Database unavailable. Please try again shortly.", "error")
    return render_template("auth/login.html", form=form, title="User Login")


@auth_bp.route("/employee/login", methods=["GET", "POST"])
def employee_login():
    if current_user.is_authenticated:
        return redirect(url_for("user.dashboard" if current_user.account_type == "user" else "employee.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        try:
            employee = Employee.query.filter_by(email=form.email.data.lower().strip()).first()
            if employee and check_password_hash(employee.password_hash, form.password.data):
                login_user(employee)
                return redirect(url_for("employee.dashboard"))
            flash("Invalid credentials.", "error")
        except SQLAlchemyError:
            flash("Database unavailable. Please try again shortly.", "error")
    return render_template("auth/login.html", form=form, title="Employee Login")


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        if current_user.account_type == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("user.dashboard" if current_user.account_type == "user" else "employee.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        try:
            admin = EnterpriseAdmin.query.filter_by(email=form.email.data.lower().strip()).first()
            if admin and check_password_hash(admin.password_hash, form.password.data):
                login_user(admin)
                session.pop("impersonate_track_id", None)
                return redirect(url_for("admin.dashboard"))
            flash("Invalid credentials.", "error")
        except SQLAlchemyError:
            flash("Database unavailable. Please try again shortly.", "error")
    return render_template("auth/login.html", form=form, title="Enterprise Admin Login")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("auth.home"))
