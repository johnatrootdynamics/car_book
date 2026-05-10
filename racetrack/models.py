from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    driver_class = db.Column(db.String(1), nullable=False, default="C")
    static_qr_code = db.Column(db.String(64), unique=True, nullable=True)
    date_of_birth = db.Column(db.Date, nullable=False)
    street = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    postal_code = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    cars = db.relationship("Car", backref="owner", cascade="all, delete-orphan")
    registrations = db.relationship(
        "EventRegistration", backref="user", cascade="all, delete-orphan"
    )
    social_posts = db.relationship("SocialPost", backref="author", cascade="all, delete-orphan")
    social_comments = db.relationship(
        "SocialComment", backref="author", cascade="all, delete-orphan"
    )
    track_subscriptions = db.relationship(
        "TrackSubscription", backref="user", cascade="all, delete-orphan"
    )
    track_classes = db.relationship(
        "TrackDriverClass", backref="user", cascade="all, delete-orphan"
    )

    @property
    def account_type(self):
        return "user"

    def get_id(self):
        return f"user:{self.id}"


class Track(db.Model):
    __tablename__ = "tracks"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    layout_image_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    employees = db.relationship("Employee", backref="track")
    events = db.relationship("Event", backref="track")
    inspection_rules = db.relationship(
        "InspectionRule", backref="track", cascade="all, delete-orphan"
    )
    subscriptions = db.relationship(
        "TrackSubscription", backref="track", cascade="all, delete-orphan"
    )
    driver_classes = db.relationship(
        "TrackDriverClass", backref="track", cascade="all, delete-orphan"
    )


class Employee(db.Model, UserMixin):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def account_type(self):
        return "employee"

    def get_id(self):
        return f"employee:{self.id}"


class EnterpriseAdmin(db.Model, UserMixin):
    __tablename__ = "enterprise_admins"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def account_type(self):
        return "admin"

    def get_id(self):
        return f"admin:{self.id}"


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    make = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    car_year = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(100), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    static_qr_code = db.Column(db.String(64), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    event_name = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    thumbnail_image_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    registrations = db.relationship(
        "EventRegistration", backref="event", cascade="all, delete-orphan"
    )


class EventRegistration(db.Model):
    __tablename__ = "event_registrations"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    checkin_code = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    car = db.relationship("Car")

    __table_args__ = (
        db.UniqueConstraint("event_id", "user_id", name="uniq_event_user_signup"),
    )


class InspectionRule(db.Model):
    __tablename__ = "inspection_rules"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    rule_text = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Inspection(db.Model):
    __tablename__ = "inspections"

    id = db.Column(db.Integer, primary_key=True)
    event_registration_id = db.Column(
        db.Integer, db.ForeignKey("event_registrations.id"), nullable=False, unique=True
    )
    inspected_by_employee_id = db.Column(
        db.Integer, db.ForeignKey("employees.id"), nullable=False
    )
    passed = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    registration = db.relationship("EventRegistration")
    inspector = db.relationship("Employee")
    items = db.relationship(
        "InspectionItem", backref="inspection", cascade="all, delete-orphan"
    )


class InspectionItem(db.Model):
    __tablename__ = "inspection_items"

    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id"), nullable=False)
    inspection_rule_id = db.Column(
        db.Integer, db.ForeignKey("inspection_rules.id"), nullable=False
    )
    checked = db.Column(db.Boolean, nullable=False, default=False)

    rule = db.relationship("InspectionRule")

    __table_args__ = (
        db.UniqueConstraint("inspection_id", "inspection_rule_id", name="uniq_inspection_rule"),
    )


class SocialPost(db.Model):
    __tablename__ = "social_posts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=True)
    event_registration_id = db.Column(
        db.Integer, db.ForeignKey("event_registrations.id"), nullable=True, unique=True
    )
    post_type = db.Column(db.String(30), nullable=False, default="event_signup")
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(600), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship("Event")
    registration = db.relationship("EventRegistration")
    comments = db.relationship("SocialComment", backref="post", cascade="all, delete-orphan")


class SocialComment(db.Model):
    __tablename__ = "social_comments"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("social_posts.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.String(400), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CommunityGroup(db.Model):
    __tablename__ = "community_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CommunityGroupMember(db.Model):
    __tablename__ = "community_group_members"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("community_groups.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("group_id", "user_id", name="uniq_group_member"),
    )


class TrackSubscription(db.Model):
    __tablename__ = "track_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("track_id", "user_id", name="uniq_track_subscription"),
    )


class TrackDriverClass(db.Model):
    __tablename__ = "track_driver_classes"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    driver_class = db.Column(db.String(1), nullable=False, default="C")
    updated_by_employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    updated_by = db.relationship("Employee")

    __table_args__ = (
        db.UniqueConstraint("track_id", "user_id", name="uniq_track_driver_class"),
    )


class TrackWaiverTemplate(db.Model):
    __tablename__ = "track_waiver_templates"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    boldsign_template_id = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    required_for_checkin = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    track = db.relationship("Track")


class DriverWaiver(db.Model):
    __tablename__ = "driver_waivers"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=True)
    waiver_template_id = db.Column(
        db.Integer, db.ForeignKey("track_waiver_templates.id"), nullable=False
    )
    boldsign_document_id = db.Column(db.String(255), nullable=True)
    boldsign_signer_email = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="not_sent")
    signing_url = db.Column(db.Text, nullable=True)
    signed_pdf_url = db.Column(db.Text, nullable=True)
    webhook_payload = db.Column(db.JSON, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    viewed_at = db.Column(db.DateTime, nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    track = db.relationship("Track")
    driver = db.relationship("User")
    event = db.relationship("Event")
    waiver_template = db.relationship("TrackWaiverTemplate")
