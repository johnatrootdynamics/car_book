from datetime import date

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, DateField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, ValidationError


def validate_not_past(form, field):
    if field.data and field.data < date.today():
        raise ValidationError("Event date cannot be in the past.")


class UserRegistrationForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[Length(max=30)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=255)])
    submit = SubmitField("Create Account")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Sign In")


class CarForm(FlaskForm):
    make = StringField("Make", validators=[DataRequired(), Length(max=100)])
    model = StringField("Model", validators=[DataRequired(), Length(max=100)])
    car_year = StringField("Year", validators=[DataRequired(), Length(max=4)])
    color = StringField("Color", validators=[Length(max=100)])
    submit = SubmitField("Save Car")


class EventForm(FlaskForm):
    event_name = StringField("Event Name", validators=[DataRequired(), Length(max=200)])
    event_date = DateField(
        "Event Date", validators=[DataRequired(), validate_not_past], format="%Y-%m-%d"
    )
    thumbnail_image = FileField(
        "Event Thumbnail",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only")],
    )
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


class EmployeeCreateForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=150)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=255)])
    submit = SubmitField("Create Employee Account")


class TrackCreateForm(FlaskForm):
    name = StringField("Track Name", validators=[DataRequired(), Length(max=200)])
    city = StringField("City", validators=[DataRequired(), Length(max=100)])
    state = StringField("State", validators=[DataRequired(), Length(max=100)])
    submit = SubmitField("Create Track")


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
    body = StringField("Comment", validators=[DataRequired(), Length(max=400)])
    submit = SubmitField("Post")
