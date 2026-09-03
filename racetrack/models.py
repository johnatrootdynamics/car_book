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
    profile_image_url = db.Column(db.String(500), nullable=True)
    static_qr_code = db.Column(db.String(64), unique=True, nullable=True)
    date_of_birth = db.Column(db.Date, nullable=False)
    street = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    postal_code = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
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
    spectator_payment_provider = db.Column(db.String(50), nullable=False, default="stripe")
    stripe_secret_key = db.Column(db.String(255), nullable=True)
    stripe_webhook_secret = db.Column(db.String(255), nullable=True)
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
    layouts = db.relationship("TrackLayout", backref="track", cascade="all, delete-orphan")


class TrackLayout(db.Model):
    __tablename__ = "track_layouts"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    image_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("track_id", "name", name="uniq_track_layout_name"),
    )


class TrackEmailTemplate(db.Model):
    __tablename__ = "track_email_templates"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    template_key = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    track = db.relationship("Track")

    __table_args__ = (
        db.UniqueConstraint("track_id", "template_key", name="uniq_track_email_template"),
    )


class TrackPaymentMethod(db.Model):
    __tablename__ = "track_payment_methods"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    provider = db.Column(db.String(50), nullable=False)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    mode = db.Column(db.String(10), nullable=False, default="live")
    public_key = db.Column(db.String(255), nullable=True)
    secret_key = db.Column(db.String(255), nullable=True)
    webhook_secret = db.Column(db.String(255), nullable=True)
    merchant_id = db.Column(db.String(255), nullable=True)
    extra_config = db.Column(db.Text, nullable=True)
    test_public_key = db.Column(db.String(255), nullable=True)
    test_secret_key = db.Column(db.String(255), nullable=True)
    test_webhook_secret = db.Column(db.String(255), nullable=True)
    test_merchant_id = db.Column(db.String(255), nullable=True)
    test_extra_config = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    track = db.relationship("Track")

    __table_args__ = (
        db.UniqueConstraint("track_id", "provider", name="uniq_track_payment_method"),
    )


class Employee(db.Model, UserMixin):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    role = db.Column(db.String(20), nullable=False, default="track_staff")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def account_type(self):
        return "employee"

    @property
    def is_office_staff(self):
        return self.role == "office_staff"

    def get_id(self):
        return f"employee:{self.id}"


class EnterpriseAdmin(db.Model, UserMixin):
    __tablename__ = "enterprise_admins"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def account_type(self):
        return "admin"

    def get_id(self):
        return f"admin:{self.id}"


class VendorAccount(db.Model, UserMixin):
    __tablename__ = "vendor_accounts"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    business_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    business_address = db.Column(db.String(500), nullable=False)
    website = db.Column(db.String(500), nullable=True)
    logo_image_path = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    @property
    def account_type(self):
        return "vendor"

    def get_id(self):
        return f"vendor:{self.id}"


class SystemEmailSettings(db.Model):
    __tablename__ = "system_email_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    is_enabled = db.Column(db.Boolean, nullable=False, default=False)
    server = db.Column(db.String(255), nullable=True)
    port = db.Column(db.Integer, nullable=False, default=587)
    security = db.Column(db.String(20), nullable=False, default="starttls")
    username = db.Column(db.String(255), nullable=True)
    password_encrypted = db.Column(db.Text, nullable=True)
    sender_name = db.Column(db.String(150), nullable=True)
    sender_email = db.Column(db.String(255), nullable=True)
    updated_by_admin_id = db.Column(
        db.Integer,
        db.ForeignKey("enterprise_admins.id"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    updated_by = db.relationship("EnterpriseAdmin")


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
    track_layout_id = db.Column(db.Integer, db.ForeignKey("track_layouts.id"), nullable=True)
    event_name = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    event_type = db.Column(db.String(20), nullable=False, default="public")
    private_owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    driver_price_cents = db.Column(db.Integer, nullable=False, default=0)
    spectator_price_cents = db.Column(db.Integer, nullable=False, default=2500)
    vendor_price_cents = db.Column(db.Integer, nullable=False, default=10000)
    driver_capacity = db.Column(db.Integer, nullable=False, default=0)
    spectator_capacity = db.Column(db.Integer, nullable=False, default=0)
    vendor_capacity = db.Column(db.Integer, nullable=False, default=0)
    event_start_time = db.Column(db.Time, nullable=True)
    event_end_time = db.Column(db.Time, nullable=True)
    thumbnail_image_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    registrations = db.relationship(
        "EventRegistration", backref="event", cascade="all, delete-orphan"
    )
    run_groups = db.relationship(
        "RunGroup", backref="event", cascade="all, delete-orphan"
    )
    class_slots = db.relationship(
        "EventClassSlot", backref="event", cascade="all, delete-orphan"
    )
    spectator_ticket_orders = db.relationship(
        "SpectatorTicketOrder", backref="event", cascade="all, delete-orphan"
    )
    driver_ticket_orders = db.relationship(
        "DriverTicketOrder", backref="event", cascade="all, delete-orphan"
    )
    spectator_ticket_types = db.relationship(
        "SpectatorTicketType", backref="event", cascade="all, delete-orphan"
    )
    track_layout = db.relationship("TrackLayout")
    private_owner = db.relationship("User", foreign_keys=[private_owner_user_id])


class PrivateRentalSlot(db.Model):
    __tablename__ = "private_rental_slots"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False, default="Private track rental")
    slot_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    driver_limit = db.Column(db.Integer, nullable=False, default=1)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    track = db.relationship("Track")
    created_by = db.relationship("Employee")
    bookings = db.relationship(
        "PrivateRentalBooking", backref="slot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "track_id",
            "slot_date",
            "start_time",
            "end_time",
            name="uniq_private_rental_slot_window",
        ),
        db.CheckConstraint("end_time > start_time", name="chk_private_rental_slot_time"),
        db.CheckConstraint("price_cents >= 0", name="chk_private_rental_slot_price"),
        db.CheckConstraint("driver_limit > 0", name="chk_private_rental_driver_limit"),
    )


class PrivateRentalBooking(db.Model):
    __tablename__ = "private_rental_bookings"

    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("private_rental_slots.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=True, unique=True)
    amount_cents = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(50), nullable=False, default="stripe")
    payment_mode = db.Column(db.String(10), nullable=False, default="live")
    payment_status = db.Column(db.String(30), nullable=False, default="pending")
    provider_session_id = db.Column(db.String(255), nullable=True)
    provider_checkout_url = db.Column(db.Text, nullable=True)
    provider_transaction_id = db.Column(db.String(255), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    failure_reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="pending")
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    buyer = db.relationship("User")
    car = db.relationship("Car")
    event = db.relationship("Event")

    __table_args__ = (
        db.Index("idx_private_rental_booking_slot_status", "slot_id", "status"),
    )


class EventRegistration(db.Model):
    __tablename__ = "event_registrations"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    checkin_code = db.Column(db.String(64), nullable=False)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    checked_in_by_employee_id = db.Column(
        db.Integer, db.ForeignKey("employees.id"), nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    car = db.relationship("Car")
    checked_in_by = db.relationship("Employee")
    run_group_assignment = db.relationship(
        "RunGroupAssignment", backref="registration", uselist=False, cascade="all, delete-orphan"
    )

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


class DriverClassChange(db.Model):
    __tablename__ = "driver_class_changes"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    previous_class = db.Column(db.String(1), nullable=False)
    new_class = db.Column(db.String(1), nullable=False)
    changed_by_type = db.Column(db.String(20), nullable=False)
    changed_by_id = db.Column(db.Integer, nullable=False)
    changed_by_name = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    driver = db.relationship("User")

    __table_args__ = (
        db.Index("idx_driver_class_change_track_user_date", "track_id", "user_id", "created_at"),
    )


class DriverNote(db.Model):
    __tablename__ = "driver_notes"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    note_text = db.Column(db.Text, nullable=False)
    author_type = db.Column(db.String(20), nullable=False)
    author_id = db.Column(db.Integer, nullable=False)
    author_name = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    driver = db.relationship("User")

    __table_args__ = (
        db.Index("idx_driver_note_track_user_date", "track_id", "user_id", "created_at"),
    )


class RunGroup(db.Model):
    __tablename__ = "run_groups"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    assignments = db.relationship(
        "RunGroupAssignment", backref="run_group", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("event_id", "name", name="uniq_run_group_name_per_event"),
    )


class RunGroupAssignment(db.Model):
    __tablename__ = "run_group_assignments"

    id = db.Column(db.Integer, primary_key=True)
    run_group_id = db.Column(db.Integer, db.ForeignKey("run_groups.id"), nullable=False)
    event_registration_id = db.Column(
        db.Integer, db.ForeignKey("event_registrations.id"), nullable=False
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "event_registration_id", name="uniq_registration_run_group_assignment"
        ),
    )


class EventClassSlot(db.Model):
    __tablename__ = "event_class_slots"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    class_code = db.Column(db.String(1), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.CheckConstraint("class_code IN ('A','B','C')", name="chk_event_class_slot_code"),
    )


class SpectatorTicketOrder(db.Model):
    __tablename__ = "spectator_ticket_orders"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendor_accounts.id"), nullable=True)
    buyer_type = db.Column(db.String(20), nullable=False, default="guest")
    guest_full_name = db.Column(db.String(150), nullable=True)
    guest_email = db.Column(db.String(255), nullable=True)
    guest_phone = db.Column(db.String(30), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    payment_method = db.Column(db.String(50), nullable=False, default="stripe")
    ticket_category = db.Column(db.String(20), nullable=False, default="spectator")
    status = db.Column(db.String(30), nullable=False, default="recorded")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    buyer = db.relationship("User")
    vendor = db.relationship("VendorAccount")

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="chk_spectator_ticket_quantity"),
    )


class DriverTicketOrder(db.Model):
    __tablename__ = "driver_ticket_orders"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(50), nullable=False, default="stripe")
    payment_mode = db.Column(db.String(10), nullable=False, default="live")
    payment_status = db.Column(db.String(30), nullable=False, default="pending")
    provider_session_id = db.Column(db.String(255), nullable=True)
    provider_transaction_id = db.Column(db.String(255), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    failure_reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    buyer = db.relationship("User")
    car = db.relationship("Car")


class SpectatorTicketType(db.Model):
    __tablename__ = "spectator_ticket_types"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False, default="General Admission")
    ticket_category = db.Column(db.String(20), nullable=False, default="spectator")
    price_cents = db.Column(db.Integer, nullable=False, default=2500)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    max_per_order = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SpectatorCart(db.Model):
    __tablename__ = "spectator_carts"

    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(64), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendor_accounts.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    items = db.relationship("SpectatorCartItem", backref="cart", cascade="all, delete-orphan")
    vendor = db.relationship("VendorAccount")


class SpectatorCartItem(db.Model):
    __tablename__ = "spectator_cart_items"

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("spectator_carts.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey("spectator_ticket_types.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship("Event")
    ticket_type = db.relationship("SpectatorTicketType")


class SpectatorOrder(db.Model):
    __tablename__ = "spectator_orders"

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(40), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendor_accounts.id"), nullable=True)
    guest_full_name = db.Column(db.String(150), nullable=True)
    guest_email = db.Column(db.String(255), nullable=True)
    guest_phone = db.Column(db.String(30), nullable=True)
    vendor_business_name = db.Column(db.String(150), nullable=True)
    payment_method = db.Column(db.String(50), nullable=False, default="stripe")
    payment_mode = db.Column(db.String(10), nullable=False, default="live")
    payment_status = db.Column(db.String(30), nullable=False, default="pending")
    provider_session_id = db.Column(db.String(255), nullable=True)
    provider_transaction_id = db.Column(db.String(255), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    failure_reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="recorded")
    total_cents = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    buyer = db.relationship("User")
    vendor = db.relationship("VendorAccount")
    items = db.relationship(
        "SpectatorOrderItem",
        backref="order",
        cascade="all, delete-orphan",
        order_by="SpectatorOrderItem.id",
    )


class SpectatorOrderItem(db.Model):
    __tablename__ = "spectator_order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("spectator_orders.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    ticket_type_name = db.Column(db.String(120), nullable=False)
    ticket_category = db.Column(db.String(20), nullable=False, default="spectator")
    unit_price_cents = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    line_total_cents = db.Column(db.Integer, nullable=False, default=0)
    qr_code = db.Column(db.String(64), nullable=True, unique=True)
    checked_in_at = db.Column(db.DateTime, nullable=True)
    checked_in_by_employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=True)

    event = db.relationship("Event")
    checked_in_by = db.relationship("Employee")


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


class ScannerDevice(db.Model):
    __tablename__ = "scanner_devices"

    id = db.Column(db.Integer, primary_key=True)
    device_uuid = db.Column(db.String(64), nullable=False, unique=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False, default="New scanner")
    role = db.Column(db.String(24), nullable=False, default="unassigned")
    status = db.Column(db.String(20), nullable=False, default="pending")
    pairing_code_hash = db.Column(db.String(255), nullable=True)
    pairing_expires_at = db.Column(db.DateTime, nullable=True)
    poll_token_hash = db.Column(db.String(64), nullable=True)
    api_token_hash = db.Column(db.String(64), nullable=True, unique=True)
    claimed_at = db.Column(db.DateTime, nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    software_version = db.Column(db.String(60), nullable=True)
    reader_connected = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    track = db.relationship("Track")


class RfidTag(db.Model):
    __tablename__ = "rfid_tags"

    id = db.Column(db.Integer, primary_key=True)
    epc = db.Column(db.String(128), nullable=False, unique=True)
    tid = db.Column(db.String(128), nullable=True, unique=True)
    public_serial = db.Column(db.String(32), nullable=False, unique=True)
    activation_code_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="inventory")
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=True, index=True)
    activated_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    activated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    car = db.relationship("Car")
    activated_by = db.relationship("User")


class ScannerObservation(db.Model):
    __tablename__ = "scanner_observations"

    id = db.Column(db.Integer, primary_key=True)
    scanner_id = db.Column(db.Integer, db.ForeignKey("scanner_devices.id"), nullable=False, index=True)
    event_uuid = db.Column(db.String(64), nullable=False)
    epc = db.Column(db.String(128), nullable=False, index=True)
    observed_at = db.Column(db.DateTime, nullable=False)
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    result = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=True)

    scanner = db.relationship("ScannerDevice")
    car = db.relationship("Car")
    __table_args__ = (db.UniqueConstraint("scanner_id", "event_uuid", name="uniq_scanner_event_uuid"),)


class TrackCarStatus(db.Model):
    __tablename__ = "track_car_statuses"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False, index=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False, index=True)
    is_on_track = db.Column(db.Boolean, nullable=False, default=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=True)
    is_eligible = db.Column(db.Boolean, nullable=False, default=False)
    eligibility_reason = db.Column(db.String(255), nullable=True)
    last_scanner_id = db.Column(db.Integer, db.ForeignKey("scanner_devices.id"), nullable=True)
    last_observation_id = db.Column(db.Integer, db.ForeignKey("scanner_observations.id"), nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    track = db.relationship("Track")
    car = db.relationship("Car")
    event = db.relationship("Event")
    last_scanner = db.relationship("ScannerDevice")
    last_observation = db.relationship("ScannerObservation")
    __table_args__ = (db.UniqueConstraint("track_id", "car_id", name="uniq_track_car_status"),)


class TrackRun(db.Model):
    __tablename__ = "track_runs"

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    track = db.relationship("Track")
    event = db.relationship("Event")
    participants = db.relationship(
        "TrackRunParticipant", backref="run", cascade="all, delete-orphan",
        order_by="TrackRunParticipant.entered_at",
    )


class TrackRunParticipant(db.Model):
    __tablename__ = "track_run_participants"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("track_runs.id"), nullable=False, index=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    entered_at = db.Column(db.DateTime, nullable=False)
    exited_at = db.Column(db.DateTime, nullable=True)

    car = db.relationship("Car")
    driver = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("run_id", "car_id", name="uniq_run_car"),)
