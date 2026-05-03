from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from .forms import LoginForm, UserRegistrationForm
from .models import Employee, User, db


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def home():
    return render_template("home.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def user_register():
    if current_user.is_authenticated:
        return redirect(url_for("user.dashboard" if current_user.account_type == "user" else "employee.dashboard"))
    form = UserRegistrationForm()
    if form.validate_on_submit():
        existing = User.query.filter_by(email=form.email.data.lower()).first()
        if existing:
            flash("Email already registered.", "error")
            return render_template("auth/register.html", form=form)
        user = User(
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            email=form.email.data.lower().strip(),
            phone=form.phone.data.strip(),
            date_of_birth=form.date_of_birth.data,
            street=form.street.data.strip(),
            city=form.city.data.strip(),
            state=form.state.data.strip(),
            postal_code=form.postal_code.data.strip(),
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


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("auth.home"))
