"""Driver vehicle selection is validated at checkout."""
import unittest
from racetrack.models import db, Car, Event, EventRegistration, DriverTicketOrder, User
from racetrack.services.demo_data_service import create_demo_track
from racetrack.employee_routes import employee_bp
from test_browser_privacy import make_privacy_test_app, PageMarkup


class DriverCheckoutVehicleTest(unittest.TestCase):
    def setUp(self):
        self.app = make_privacy_test_app()
        self.app.register_blueprint(employee_bp)
        self.client = self.app.test_client()
        with self.app.app_context():
            demo = create_demo_track()
            db.session.commit()
            driver = User.query.filter_by(email=demo["driver_email"]).one()
            self.user_id = driver.id
            self.car_id = Car.query.filter_by(user_id=driver.id).one().id
            self.foreign_car_id = Car.query.filter(Car.user_id != driver.id).first().id
            event = Event.query.order_by(Event.event_date.desc()).first()
            self.event_id = event.id
            DriverTicketOrder.query.filter_by(event_id=event.id, user_id=driver.id).delete()
            EventRegistration.query.filter_by(event_id=event.id, user_id=driver.id).delete()
            db.session.commit()
            email, password = demo["driver_email"], demo["password"]
        page = self.client.get("/login", base_url="https://localhost")
        self.token = PageMarkup(page.get_data(as_text=True)).csrf_token
        self.client.post("/login", base_url="https://localhost",
                         data=dict(email=email, password=password, csrf_token=self.token),
                         headers={"Referer": "https://localhost/login"})
        self.url = f"/user/events/{self.event_id}/driver-checkout"

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def submit(self, car_id):
        return self.client.post(self.url, base_url="https://localhost",
                                data=dict(car_id=car_id, full_name="Demo Driver",
                                          email="driver@example.com", phone="5555551234",
                                          payment_method="other", csrf_token=self.token),
                                headers={"Referer": "https://localhost" + self.url})

    def test_checkout_opens_without_previous_vehicle_selection(self):
        response = self.client.get(self.url, base_url="https://localhost")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="car_id"', response.get_data(as_text=True))

    def test_foreign_or_missing_vehicle_cannot_create_order(self):
        for car_id in (self.foreign_car_id, ""):
            response = self.submit(car_id)
            self.assertEqual(response.status_code, 200)
            with self.app.app_context():
                self.assertIsNone(DriverTicketOrder.query.filter_by(
                    event_id=self.event_id, user_id=self.user_id).first())

    def test_checkout_attaches_chosen_vehicle(self):
        response = self.submit(self.car_id)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            order = DriverTicketOrder.query.filter_by(
                event_id=self.event_id, user_id=self.user_id).one()
            self.assertEqual(order.car_id, self.car_id)
            self.assertEqual(order.payment_status, "paid")
            registration = EventRegistration.query.filter_by(
                event_id=self.event_id, user_id=self.user_id).one()
            self.assertEqual(registration.car_id, self.car_id)

    def prepare_vehicle_change(self):
        self.assertEqual(self.submit(self.car_id).status_code, 302)
        with self.app.app_context():
            car = Car(user_id=self.user_id, make="BMW", model="M3", car_year=2020)
            db.session.add(car)
            db.session.commit()
            self.second_car_id = car.id
        self.change_url = f"/user/events/{self.event_id}/vehicle"

    def change_vehicle(self, car_id):
        return self.client.post(self.change_url, base_url="https://localhost",
                                data=dict(car_id=car_id, csrf_token=self.token),
                                headers={"Referer": "https://localhost" + self.url})

    def test_change_vehicle_updates_registration_and_ticket(self):
        self.prepare_vehicle_change()
        response = self.change_vehicle(self.second_car_id)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(EventRegistration.query.filter_by(
                event_id=self.event_id, user_id=self.user_id).one().car_id, self.second_car_id)
            self.assertEqual(DriverTicketOrder.query.filter_by(
                event_id=self.event_id, user_id=self.user_id).one().car_id, self.second_car_id)
        page = self.client.get(response.location, base_url="https://localhost")
        self.assertEqual(page.status_code, 200)
        self.assertIn("2020 BMW M3", page.get_data(as_text=True))

    def test_change_vehicle_rejects_foreign_vehicle_and_checked_in_driver(self):
        from datetime import datetime
        self.prepare_vehicle_change()
        self.change_vehicle(self.foreign_car_id)
        with self.app.app_context():
            reg = EventRegistration.query.filter_by(
                event_id=self.event_id, user_id=self.user_id).one()
            self.assertEqual(reg.car_id, self.car_id)
            reg.checked_in_at = datetime.utcnow()
            db.session.commit()
        self.change_vehicle(self.second_car_id)
        with self.app.app_context():
            self.assertEqual(EventRegistration.query.filter_by(
                event_id=self.event_id, user_id=self.user_id).one().car_id, self.car_id)

    def test_inspection_blocks_vehicle_change_even_without_checkin(self):
        from racetrack.models import Inspection, Employee
        self.prepare_vehicle_change()
        with self.app.app_context():
            reg = EventRegistration.query.filter_by(
                event_id=self.event_id, user_id=self.user_id).one()
            db.session.add(Inspection(event_registration_id=reg.id,
                                      inspected_by_employee_id=Employee.query.first().id, passed=True))
            db.session.commit()
        self.change_vehicle(self.second_car_id)
        with self.app.app_context():
            reg = EventRegistration.query.filter_by(
                event_id=self.event_id, user_id=self.user_id).one()
            self.assertEqual(reg.car_id, self.car_id)
            self.assertTrue(Inspection.query.filter_by(event_registration_id=reg.id).one().passed)
