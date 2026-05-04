import secrets

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from .forms import CarForm, EventSignupForm, SocialCommentForm
from .models import Car, Event, EventRegistration, SocialComment, SocialPost, db


user_bp = Blueprint("user", __name__, url_prefix="/user")


def _generate_car_qr_code():
    while True:
        code = f"CAR-{secrets.token_hex(4).upper()}"
        if not Car.query.filter_by(static_qr_code=code).first():
            return code


def require_user():
    if not current_user.is_authenticated:
        flash("Please sign in as a driver.", "error")
        return redirect(url_for("auth.user_login"))
    if current_user.account_type != "user":
        flash("Driver access required for that page.", "error")
        return redirect(url_for("employee.dashboard"))
    return None


@user_bp.route("/dashboard")
@login_required
def dashboard():
    guard = require_user()
    if guard:
        return guard
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.created_at.desc()).all()
    events = Event.query.order_by(Event.event_date.asc()).all()
    signups = {
        reg.event_id: reg
        for reg in EventRegistration.query.filter_by(user_id=current_user.id).all()
    }
    form = EventSignupForm()
    form.car_id.choices = [(car.id, f"{car.car_year} {car.make} {car.model}") for car in cars]
    return render_template(
        "user/dashboard.html",
        cars=cars,
        events=events,
        signups=signups,
        signup_form=form,
    )


@user_bp.route("/community")
@login_required
def community():
    guard = require_user()
    if guard:
        return guard
    posts = SocialPost.query.order_by(SocialPost.created_at.desc()).limit(100).all()
    cars = Car.query.order_by(Car.created_at.desc()).limit(100).all()
    events = Event.query.order_by(Event.event_date.asc()).limit(24).all()
    event_signup_counts = {
        event.id: EventRegistration.query.filter_by(event_id=event.id).count() for event in events
    }
    user_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.created_at.desc()).all()
    signups = {
        reg.event_id: reg
        for reg in EventRegistration.query.filter_by(user_id=current_user.id).all()
    }
    signup_form = EventSignupForm()
    signup_form.car_id.choices = [
        (car.id, f"{car.car_year} {car.make} {car.model}") for car in user_cars
    ]
    comment_form = SocialCommentForm()
    return render_template(
        "user/community.html",
        posts=posts,
        cars=cars,
        events=events,
        event_signup_counts=event_signup_counts,
        signups=signups,
        signup_form=signup_form,
        comment_form=comment_form,
    )


@user_bp.route("/cars/new", methods=["GET", "POST"])
@login_required
def car_new():
    guard = require_user()
    if guard:
        return guard
    form = CarForm()
    if form.validate_on_submit():
        if not form.car_year.data.isdigit():
            flash("Car year must be numeric.", "error")
            return render_template("user/car_form.html", form=form, title="Add Car")
        car = Car(
            user_id=current_user.id,
            make=form.make.data.strip(),
            model=form.model.data.strip(),
            car_year=int(form.car_year.data),
            color=form.color.data.strip() if form.color.data else None,
            static_qr_code=_generate_car_qr_code(),
        )
        db.session.add(car)
        db.session.commit()
        post = SocialPost(
            user_id=current_user.id,
            post_type="car_spotlight",
            title=f"{current_user.first_name} added a car",
            body=f"{car.car_year} {car.make} {car.model}" + (f" ({car.color})" if car.color else ""),
        )
        db.session.add(post)
        db.session.commit()
        flash("Car added.", "success")
        return redirect(url_for("user.dashboard"))
    return render_template("user/car_form.html", form=form, title="Add Car")


@user_bp.route("/cars/<int:car_id>/edit", methods=["GET", "POST"])
@login_required
def car_edit(car_id):
    guard = require_user()
    if guard:
        return guard
    car = Car.query.filter_by(id=car_id, user_id=current_user.id).first_or_404()
    form = CarForm(obj=car)
    if form.validate_on_submit():
        if not form.car_year.data.isdigit():
            flash("Car year must be numeric.", "error")
            return render_template("user/car_form.html", form=form, title="Edit Car")
        car.make = form.make.data.strip()
        car.model = form.model.data.strip()
        car.car_year = int(form.car_year.data)
        car.color = form.color.data.strip() if form.color.data else None
        db.session.commit()
        flash("Car updated.", "success")
        return redirect(url_for("user.dashboard"))
    return render_template("user/car_form.html", form=form, title="Edit Car")


@user_bp.route("/cars/<int:car_id>/delete", methods=["POST"])
@login_required
def car_delete(car_id):
    guard = require_user()
    if guard:
        return guard
    car = Car.query.filter_by(id=car_id, user_id=current_user.id).first_or_404()
    in_use = EventRegistration.query.filter_by(car_id=car.id).first()
    if in_use:
        flash("Car cannot be deleted while used in an event signup.", "error")
        return redirect(url_for("user.dashboard"))
    db.session.delete(car)
    db.session.commit()
    flash("Car deleted.", "success")
    return redirect(url_for("user.dashboard"))


@user_bp.route("/events/<int:event_id>/signup", methods=["POST"])
@login_required
def signup_event(event_id):
    guard = require_user()
    if guard:
        return guard
    event = Event.query.get_or_404(event_id)
    if EventRegistration.query.filter_by(event_id=event.id, user_id=current_user.id).first():
        flash("Already signed up for this event.", "error")
        return redirect(url_for("user.dashboard"))

    form = EventSignupForm()
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.created_at.desc()).all()
    form.car_id.choices = [(car.id, f"{car.car_year} {car.make} {car.model}") for car in cars]
    if not cars:
        flash("Add a car before signing up.", "error")
        return redirect(url_for("user.car_new"))
    if form.validate_on_submit():
        selected_car = Car.query.filter_by(id=form.car_id.data, user_id=current_user.id).first()
        if not selected_car:
            flash("Invalid car selected.", "error")
            return redirect(url_for("user.dashboard"))
        if not selected_car.static_qr_code:
            selected_car.static_qr_code = _generate_car_qr_code()
        reg = EventRegistration(
            event_id=event.id,
            user_id=current_user.id,
            car_id=selected_car.id,
            checkin_code=selected_car.static_qr_code,
        )
        db.session.add(reg)
        db.session.commit()
        post = SocialPost(
            user_id=current_user.id,
            event_id=event.id,
            event_registration_id=reg.id,
            post_type="event_signup",
            title=f"{current_user.first_name} signed up for {event.event_name}",
            body=f"Driving: {selected_car.car_year} {selected_car.make} {selected_car.model}",
        )
        db.session.add(post)
        db.session.commit()
        flash("Signed up successfully.", "success")
    else:
        flash("Please choose a valid car.", "error")
    return redirect(url_for("user.dashboard"))


@user_bp.route("/events/<int:event_id>/cancel", methods=["POST"])
@login_required
def cancel_signup(event_id):
    guard = require_user()
    if guard:
        return guard
    reg = EventRegistration.query.filter_by(event_id=event_id, user_id=current_user.id).first_or_404()
    post = SocialPost.query.filter_by(event_registration_id=reg.id).first()
    if post:
        db.session.delete(post)
    db.session.delete(reg)
    db.session.commit()
    flash("Signup canceled.", "success")
    return redirect(url_for("user.dashboard"))


@user_bp.route("/community/posts/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    guard = require_user()
    if guard:
        return guard
    post = SocialPost.query.get_or_404(post_id)
    form = SocialCommentForm()
    if form.validate_on_submit():
        comment = SocialComment(
            post_id=post.id,
            user_id=current_user.id,
            body=form.body.data.strip(),
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comment added.", "success")
    else:
        flash("Comment is required.", "error")
    return redirect(url_for("user.community"))
