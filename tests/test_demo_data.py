"""Demo generation is additive, repeat-safe, private, and administrator-only."""
from datetime import date
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from racetrack.admin_routes import admin_bp
from racetrack.employee_routes import employee_bp
from racetrack.models import (db, Track, User, Car, Event, EventRegistration, Employee,
                              EnterpriseAdmin, DriverTicketOrder, DriverWaiver, Inspection)
from racetrack.services.demo_data_service import create_demo_track, create_test_event
from test_browser_privacy import make_privacy_test_app, PageMarkup

class DemoDataTest(unittest.TestCase):
    def setUp(self):
        self.app = make_privacy_test_app()
        self.app.register_blueprint(admin_bp)
        self.app.register_blueprint(employee_bp)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.session.add(EnterpriseAdmin(full_name='Test admin', email='admin@example.test',
                                           password_hash=generate_password_hash('TestPassword123!')))
            db.session.add(Track(name='Real track', city='Austin', state='TX'))
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_seed_is_repeat_safe_and_keeps_existing_data(self):
        with self.app.app_context(), patch('racetrack.services.email_service.send_email') as email:
            result = create_demo_track(date(2026, 11, 22))
            db.session.commit()
            again = create_demo_track()
            db.session.commit()
            self.assertTrue(result['created'])
            self.assertFalse(again['created'])
            self.assertIsNone(again['password'])
            self.assertEqual(Track.query.count(), 2)
            self.assertEqual(Track.query.filter_by(name='Real track').one().city, 'Austin')
            self.assertEqual(User.query.count(), 8)
            self.assertEqual(Car.query.count(), 8)
            self.assertEqual(Employee.query.count(), 1)
            self.assertEqual(Event.query.count(), 3)
            self.assertEqual(EventRegistration.query.count(), 24)
            self.assertTrue(all(e.event_type == 'private' and e.driver_price_cents == 0 for e in Event.query.all()))
            self.assertTrue(all(u.email.endswith('@trackops-demo.invalid') and u.first_name.startswith('DEMO ') for u in User.query.all()))
            self.assertEqual(DriverTicketOrder.query.count(), 0)
            self.assertEqual(DriverWaiver.query.count(), 0)
            self.assertGreater(Inspection.query.count(), 0)
            email.assert_not_called()

    def test_driver_and_track_staff_cannot_generate_demo_data(self):
        with self.app.app_context():
            result = create_demo_track()
            db.session.commit()
            credentials = [(result['driver_email'], result['password']),
                           (result['office_email'], result['password'])]
        for email, password in credentials:
            with self.subTest(email=email):
                client = self.app.test_client()
                page = client.get('/login', base_url='https://localhost')
                token = PageMarkup(page.get_data(as_text=True)).csrf_token
                client.post('/login', base_url='https://localhost',
                            data={'email':email,'password':password,'csrf_token':token},
                            headers={'Referer':'https://localhost/login'})
                response = client.post('/admin/demo-data', base_url='https://localhost',
                                       data={'csrf_token':token}, headers={'Referer':'https://localhost/login'})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.location, '/')

    def test_custom_event_date_driver_count_and_workflow(self):
        with self.app.app_context():
            track = create_demo_track()['track']
            db.session.commit()
            for stage in ('registered', 'checked_in', 'inspection_passed', 'inspection_failed'):
                event = create_test_event(track, 'Today test', date(2026, 11, 22), 2, stage)
                db.session.commit()
                self.assertEqual(event.event_date, date(2026, 11, 22))
                self.assertEqual(len(event.registrations), 2)
                for reg in event.registrations:
                    self.assertEqual(bool(reg.checked_in_at), stage != 'registered')
                    inspection = Inspection.query.filter_by(event_registration_id=reg.id).first()
                    self.assertEqual(bool(inspection), stage.startswith('inspection_'))
                    if inspection:
                        self.assertEqual(inspection.passed, stage == 'inspection_passed')
            with self.assertRaises(ValueError):
                create_test_event(Track.query.filter_by(name='Real track').one(), 'Test', date.today(), 2, 'registered')
            with self.assertRaises(ValueError):
                create_test_event(track, 'Test', date.today(), 9, 'registered')

    def test_seed_transaction_can_be_rolled_back(self):
        with self.app.app_context():
            create_demo_track()
            db.session.rollback()
            self.assertEqual(Track.query.count(), 1)
            self.assertEqual(User.query.count(), 0)
            self.assertEqual(Event.query.count(), 0)

    def test_admin_route_requires_login_and_csrf_and_does_not_cache_password(self):
        response = self.client.get('/admin/demo-data', base_url='https://localhost')
        self.assertEqual(response.status_code, 302)
        login = self.client.get('/login', base_url='https://localhost')
        token = PageMarkup(login.get_data(as_text=True)).csrf_token
        self.client.post('/login', base_url='https://localhost',
                         data={'email':'admin@example.test','password':'TestPassword123!','csrf_token':token},
                         headers={'Referer':'https://localhost/login'})
        self.assertEqual(self.client.post('/admin/demo-data', base_url='https://localhost').status_code, 400)
        page = self.client.get('/admin/demo-data', base_url='https://localhost')
        self.assertEqual(page.status_code, 200)
        token = PageMarkup(page.get_data(as_text=True)).csrf_token
        created = self.client.post('/admin/demo-data', base_url='https://localhost', data={'csrf_token':token},
                                   headers={'Referer':'https://localhost/admin/demo-data'})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.headers['Cache-Control'], 'no-store')
        self.assertIn(b'Demo track created', created.data)
        self.assertIn(b'Demo password', created.data)
        self.assertNotIn(b'Demo password', self.client.get('/admin/demo-data', base_url='https://localhost').data)

if __name__ == '__main__':
    unittest.main()
