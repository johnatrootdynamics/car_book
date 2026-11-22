"""Explicit, administrator-triggered sample data. No external services are called."""
from datetime import date, datetime, time, timedelta
import secrets

from werkzeug.security import generate_password_hash

from ..models import (Car, DriverTicketOrder, Employee, Event, EventRegistration, Inspection,
                      Track, TrackDriverClass, TrackSubscription, User, db)

DEMO_TRACK_NAME = "DEMO — Track Ops Sample Raceway"
DRIVERS = (
    ("Alex", "Morgan", "Mazda", "MX-5", 2019, "Red"),
    ("Jordan", "Lee", "BMW", "M2", 2018, "Blue"),
    ("Casey", "Rivera", "Toyota", "GR86", 2023, "White"),
    ("Taylor", "Brooks", "Honda", "Civic Type R", 2022, "Black"),
    ("Sam", "Parker", "Ford", "Mustang", 2020, "Silver"),
    ("Riley", "Chen", "Subaru", "BRZ", 2024, "Blue"),
    ("Jamie", "Reed", "Chevrolet", "Corvette", 2017, "Yellow"),
    ("Drew", "Hayes", "Porsche", "Cayman", 2016, "Gray"),
)


def _ensure_free_demo_ticket(event, registration):
    # Public rosters and dashboards require a fulfilled order, even for free tickets.
    existing = DriverTicketOrder.query.filter_by(event_id=event.id, user_id=registration.user_id,
                                                 payment_status="paid").first()
    if not existing:
        db.session.add(DriverTicketOrder(event_id=event.id, user_id=registration.user_id,
                                        car_id=registration.car_id, amount_cents=0,
                                        payment_method="demo_free", payment_mode="test",
                                        payment_status="paid", status="recorded", paid_at=datetime.utcnow()))


def publish_demo_events(track):
    if track.name != DEMO_TRACK_NAME:
        raise ValueError("Only demo track events can be published by this tool.")
    events = Event.query.filter(Event.track_id == track.id, Event.event_type == "private",
                               Event.event_name.startswith("DEMO — "), Event.driver_price_cents == 0).all()
    for event in events:
        event.event_type = "public"
        event.private_owner_user_id = None
        for registration in event.registrations:
            _ensure_free_demo_ticket(event, registration)
    return len(events)


def create_test_event(track, name, event_date, driver_count, workflow):
    """Build a configurable scenario using only this demo track's sample users."""
    if track.name != DEMO_TRACK_NAME:
        raise ValueError("Testing scenarios are available only on the demo track.")
    if not name.strip() or len(name.strip()) > 150:
        raise ValueError("Enter an event name of 150 characters or fewer.")
    if not 1 <= driver_count <= len(DRIVERS):
        raise ValueError("Choose between 1 and 8 drivers.")
    if workflow not in {"registered", "checked_in", "inspection_passed", "inspection_failed"}:
        raise ValueError("Choose a valid workflow stage.")
    drivers = (User.query.join(TrackSubscription, TrackSubscription.user_id == User.id)
               .filter(TrackSubscription.track_id == track.id,
                       User.email.endswith("@trackops-demo.invalid"),
                       User.first_name.startswith("DEMO "), User.deleted_at.is_(None))
               .order_by(User.id).limit(driver_count).all())
    office = Employee.query.filter_by(track_id=track.id, role="office_staff", deleted_at=None).first()
    if len(drivers) != driver_count or not office or any(not d.cars for d in drivers):
        raise ValueError("The demo track needs its sample drivers, vehicles, and office account restored.")
    event = Event(track_id=track.id, event_name=f"DEMO — {name.strip()}",
                  event_date=event_date, event_type="public",
                  event_start_time=time(9), event_end_time=time(17), driver_capacity=12,
                  driver_price_cents=0, spectator_price_cents=0, vendor_price_cents=0)
    db.session.add(event)
    db.session.flush()
    for driver in drivers:
        reg = EventRegistration(event_id=event.id, user_id=driver.id, car_id=driver.cars[0].id,
                                checkin_code=f"DEMO-REG-{secrets.token_hex(16)}",
                                checked_in_at=datetime.utcnow() if workflow != "registered" else None,
                                checked_in_by_employee_id=office.id if workflow != "registered" else None)
        db.session.add(reg)
        db.session.flush()
        _ensure_free_demo_ticket(event, reg)
        if workflow.startswith("inspection_"):
            db.session.add(Inspection(event_registration_id=reg.id, inspected_by_employee_id=office.id,
                                      passed=workflow == "inspection_passed",
                                      notes="DEMO ONLY — fictional inspection result."))
    return event


def create_demo_track(today=None):
    """Create once in the caller's transaction; never update existing records."""
    existing = Track.query.filter_by(name=DEMO_TRACK_NAME).first()
    if existing:
        return {"track": existing, "created": False, "password": None}
    today = today or date.today()
    password = secrets.token_urlsafe(24)
    password_hash = generate_password_hash(password)
    namespace = secrets.token_hex(6)
    track = Track(name=DEMO_TRACK_NAME, city="Demo City", state="TX",
                  spectator_payment_provider="other")
    db.session.add(track)
    db.session.flush()
    office = Employee(track_id=track.id, full_name="DEMO Track Manager",
                      email=f"manager.{namespace}@trackops-demo.invalid",
                      role="office_staff", password_hash=password_hash)
    db.session.add(office)
    db.session.flush()
    drivers = []
    for index, (first, last, make, model, year, color) in enumerate(DRIVERS):
        driver = User(first_name=f"DEMO {first}", last_name=last,
                      username=f"demo-{namespace}-{index+1}",
                      email=f"driver{index+1}.{namespace}@trackops-demo.invalid",
                      phone=f"202-555-01{index:02d}", date_of_birth=date(1990, 1, index+1),
                      street="Demo address — not a real person", city="Demo City",
                      state="TX", postal_code="00000", password_hash=password_hash,
                      static_qr_code=f"DEMO-DRV-{namespace}-{index}")
        db.session.add(driver)
        db.session.flush()
        car = Car(user_id=driver.id, make=make, model=model, car_year=year,
                  color=color, static_qr_code=f"DEMO-CAR-{namespace}-{index}")
        db.session.add(car)
        db.session.flush()
        db.session.add(TrackSubscription(track_id=track.id, user_id=driver.id))
        db.session.add(TrackDriverClass(track_id=track.id, user_id=driver.id,
                                       driver_class=("A", "B", "C")[index % 3]))
        drivers.append((driver, car))
    for event_index, (title, offset) in enumerate((
        ("Practice Day", -7), ("Open Lapping", 7), ("Driver Development", 14),
    )):
        event = Event(track_id=track.id, event_name=f"DEMO — {title}",
                      event_date=today + timedelta(days=offset), event_type="public",
                      event_start_time=time(9), event_end_time=time(17),
                      driver_capacity=12, spectator_capacity=0, vendor_capacity=0,
                      driver_price_cents=0, spectator_price_cents=0, vendor_price_cents=0)
        db.session.add(event)
        db.session.flush()
        for index, (driver, car) in enumerate(drivers):
            checked_in = event_index == 0 or (event_index == 1 and index < 4)
            registration = EventRegistration(
                event_id=event.id, user_id=driver.id, car_id=car.id,
                checkin_code=f"DEMO-REG-{namespace}-{event_index}-{index}",
                checked_in_at=datetime.combine(event.event_date, time(8, 30)) if checked_in else None,
                checked_in_by_employee_id=office.id if checked_in else None,
            )
            db.session.add(registration)
            db.session.flush()
            _ensure_free_demo_ticket(event, registration)
            if event_index == 0 or (event_index == 1 and index < 3):
                db.session.add(Inspection(event_registration_id=registration.id,
                                          inspected_by_employee_id=office.id,
                                          passed=index != 2,
                                          notes="DEMO ONLY — fictional inspection result."))
    return {"track": track, "created": True, "password": password,
            "office_email": office.email, "driver_email": drivers[0][0].email}
