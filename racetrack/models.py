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
    public_key = db.Column(db.String(255), nullable=True)
    secret_key = db.Column(db.String(255), nullable=True)
    webhook_secret = db.Column(db.String(255), nullable=True)
    merchant_id = db.Column(db.String(255), nullable=True)
    extra_config = db.Column(db.Text, nullable=True)
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
    track_layout_id = db.Column(db.Integer, db.ForeignKey("track_layouts.id"), nullable=True)
    event_name = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    driver_price_cents = db.Column(db.Integer, nullable=False, default=0)
    spectator_price_cents = db.Column(db.Integer, nullable=False, default=2500)
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


class EventRegistration(db.Model):
    __tablename__ = "event_registrations"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    checkin_code = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    car = db.relationship("Car")
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
    buyer_type = db.Column(db.String(20), nullable=False, default="guest")
    guest_full_name = db.Column(db.String(150), nullable=True)
    guest_email = db.Column(db.String(255), nullable=True)
    guest_phone = db.Column(db.String(30), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    payment_method = db.Column(db.String(50), nullable=False, default="stripe")
    status = db.Column(db.String(30), nullable=False, default="recorded")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    buyer = db.relationship("User")

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
    price_cents = db.Column(db.Integer, nullable=False, default=2500)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    max_per_order = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SpectatorCart(db.Model):
    __tablename__ = "spectator_carts"

    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(64), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    items = db.relationship("SpectatorCartItem", backref="cart", cascade="all, delete-orphan")


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
    guest_full_name = db.Column(db.String(150), nullable=True)
    guest_email = db.Column(db.String(255), nullable=True)
    guest_phone = db.Column(db.String(30), nullable=True)
    payment_method = db.Column(db.String(50), nullable=False, default="stripe")
    payment_status = db.Column(db.String(30), nullable=False, default="pending")
    provider_session_id = db.Column(db.String(255), nullable=True)
    provider_transaction_id = db.Column(db.String(255), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    failure_reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="recorded")
    total_cents = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    buyer = db.relationship("User")
    items = db.relationship("SpectatorOrderItem", backref="order", cascade="all, delete-orphan")


class SpectatorOrderItem(db.Model):
    __tablename__ = "spectator_order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("spectator_orders.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    ticket_type_name = db.Column(db.String(120), nullable=False)
    unit_price_cents = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    line_total_cents = db.Column(db.Integer, nullable=False, default=0)
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
