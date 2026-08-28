from datetime import date

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, DateField, DecimalField, IntegerField, PasswordField, SelectField, StringField, SubmitField, TextAreaField, TimeField
from wtforms.validators import DataRequired, Email, EqualTo, InputRequired, Length, NumberRange, Optional, ValidationError


def validate_not_past(form, field):
    if field.data and field.data < date.today():
        raise ValidationError("Event date cannot be in the past.")


class UserRegistrationForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=50)])
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[Length(max=30)])
    submit = SubmitField("Create Account & Email Password")


class VendorRegistrationForm(FlaskForm):
    full_name = StringField("Contact Name", validators=[DataRequired(), Length(max=150)])
    business_name = StringField("Business Name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[DataRequired(), Length(max=30)])
    business_address = TextAreaField(
        "Business Address", validators=[DataRequired(), Length(max=500)]
    )
    website = StringField("Website", validators=[Optional(), Length(max=500)])
    logo = FileField(
        "Picture or Logo",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only")],
    )
    description = TextAreaField("Public Description", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Create Vendor Account & Email Password")


class VendorProfileForm(FlaskForm):
    full_name = StringField("Contact Name", validators=[DataRequired(), Length(max=150)])
    business_name = StringField("Business Name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[DataRequired(), Length(max=30)])
    business_address = TextAreaField(
        "Business Address", validators=[DataRequired(), Length(max=500)]
    )
    website = StringField("Website", validators=[Optional(), Length(max=500)])
    logo = FileField(
        "Replace Picture or Logo",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only")],
    )
    description = TextAreaField("Public Description", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Save Vendor Profile")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Sign In")


class PasswordChangeForm(FlaskForm):
    new_password = PasswordField(
        "New Password",
        validators=[DataRequired(), Length(min=10, max=255)],
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit = SubmitField("Set New Password")


class PasswordUpdateForm(FlaskForm):
    current_password = PasswordField(
        "Current Password",
        validators=[DataRequired(), Length(max=255)],
    )
    new_password = PasswordField(
        "New Password",
        validators=[DataRequired(), Length(min=10, max=255)],
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit = SubmitField("Update Password")


class CarForm(FlaskForm):
    make = StringField("Make", validators=[DataRequired(), Length(max=100)])
    model = StringField("Model", validators=[DataRequired(), Length(max=100)])
    car_year = StringField("Year", validators=[DataRequired(), Length(max=4)])
    color = StringField("Color", validators=[Length(max=100)])
    image = FileField(
        "Car Photo",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only")],
    )
    submit = SubmitField("Save Car")


class EventForm(FlaskForm):
    event_name = StringField("Event Name", validators=[DataRequired(), Length(max=200)])
    event_date = DateField(
        "Event Date", validators=[DataRequired(), validate_not_past], format="%Y-%m-%d"
    )
    event_start_time = TimeField("Event Start Time", validators=[Optional()])
    event_end_time = TimeField("Event End Time", validators=[Optional()])
    driver_price = DecimalField("Driver Price", places=2, validators=[InputRequired(), NumberRange(min=0)])
    spectator_price = DecimalField("Spectator Price", places=2, validators=[InputRequired(), NumberRange(min=0)])
    vendor_price = DecimalField("Vendor Price", places=2, validators=[InputRequired(), NumberRange(min=0)])
    driver_capacity = IntegerField("Driver Capacity", validators=[InputRequired(), NumberRange(min=0)])
    spectator_capacity = IntegerField("Spectator Capacity", validators=[InputRequired(), NumberRange(min=0)])
    vendor_capacity = IntegerField("Vendor Capacity", validators=[InputRequired(), NumberRange(min=0)])
    thumbnail_image = FileField(
        "Event Thumbnail",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only")],
    )
    track_layout_id = SelectField("Track Layout", coerce=int, validators=[Optional()])
    submit = SubmitField("Create Event")


class EventSignupForm(FlaskForm):
    car_id = SelectField("Select Car", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Sign Up")


class TrackProfileForm(FlaskForm):
    name = StringField("Track Name", validators=[DataRequired(), Length(max=200)])
    city = StringField("City", validators=[DataRequired(), Length(max=100)])
    state = StringField("State", validators=[DataRequired(), Length(max=100)])
    layout_image = FileField(
        "Track Layout Image",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only")],
    )
    submit = SubmitField("Save Track Profile")


class TrackEmailTemplateForm(FlaskForm):
    subject = StringField("Subject", validators=[DataRequired(), Length(max=255)])
    body = TextAreaField("Body", validators=[DataRequired(), Length(max=5000)])
    is_enabled = BooleanField("Enabled", default=True)
    submit = SubmitField("Save Email Template")


class EmployeeCreateForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField(
        "Role",
        choices=[("track_staff", "Track staff"), ("office_staff", "Office staff")],
        validators=[DataRequired()],
        default="track_staff",
    )
    submit = SubmitField("Create & Email Login")


class TrackCreateForm(FlaskForm):
    name = StringField("Track Name", validators=[DataRequired(), Length(max=200)])
    city = StringField("City", validators=[DataRequired(), Length(max=100)])
    state = StringField("State", validators=[DataRequired(), Length(max=100)])
    owner_name = StringField("First Office User Name", validators=[DataRequired(), Length(max=150)])
    owner_email = StringField(
        "First Office User Email",
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    submit = SubmitField("Create Track & Send Welcome")


class InspectionRuleForm(FlaskForm):
    rule_text = StringField("Condition", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Add Rule")


class InspectionForm(FlaskForm):
    notes = TextAreaField("Inspector Notes", validators=[Length(max=500)])
    submit = SubmitField("Save Inspection")

    def set_rule_fields(self, rules):
        for rule in rules:
            field_name = f"rule_{rule.id}"
            if not hasattr(self, field_name):
                setattr(self, field_name, BooleanField(rule.rule_text))


class SocialCommentForm(FlaskForm):
    body = TextAreaField("Comment", validators=[DataRequired(), Length(max=400)])
    submit = SubmitField("Post")


class WaiverTemplateForm(FlaskForm):
    title = StringField("Waiver Title", validators=[DataRequired(), Length(max=255)])
    boldsign_template_id = StringField(
        "BoldSign Template ID", validators=[DataRequired(), Length(max=255)]
    )
    is_active = BooleanField("Active", default=True)
    required_for_checkin = BooleanField("Required for check-in", default=True)
    submit = SubmitField("Save Template")


class SpectatorTicketForm(FlaskForm):
    full_name = StringField("Full Name", validators=[Length(max=150)])
    email = StringField("Email", validators=[Length(max=255)])
    phone = StringField("Phone", validators=[Length(max=30)])
    quantity = SelectField(
        "Tickets",
        coerce=int,
        choices=[(1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5"), (10, "10")],
        validators=[DataRequired()],
    )
    payment_method = SelectField(
        "Payment Method",
        choices=[
            ("stripe", "Stripe"),
            ("paypal", "PayPal"),
            ("toast", "Toast"),
            ("quickbooks", "QuickBooks Payments"),
            ("other", "Other"),
        ],
        validators=[DataRequired()],
    )
    submit = SubmitField("Complete Ticket Purchase")


class SpectatorCheckoutForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[DataRequired(), Length(max=30)])
    vendor_business_name = StringField("Vendor Business Name", validators=[Optional(), Length(max=150)])
    payment_method = SelectField("Payment Method", validators=[DataRequired(), Length(max=50)])
    submit = SubmitField("Place Order")


class DriverCheckoutForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[DataRequired(), Length(max=30)])
    payment_method = SelectField("Payment Method", validators=[DataRequired(), Length(max=50)])
    submit = SubmitField("Purchase Ticket & Sign Up")
