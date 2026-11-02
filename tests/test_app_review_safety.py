import unittest
from datetime import date, datetime, timedelta

from flask import Flask
from werkzeug.security import generate_password_hash

from racetrack.mobile_api import mobile_api_bp
from racetrack.models import (
    CameraDevice,
    Car,
    CommunityReport,
    DriverConnection,
    Employee,
    EnterpriseAdmin,
    Event,
    SocialPost,
    Track,
    TrackRun,
    TrackRunParticipant,
    TrackRunVideo,
    User,
    UserBlock,
    VendorAccount,
    db,
)


class AppReviewSafetyTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TRACK_TIMEZONE="UTC",
            APP_BASE_URL="https://example.test",
            S3_READ_ACCESS_KEY="",
            S3_READ_SECRET_KEY="",
            APPLE_SIGN_IN_CLIENT_ID="com.rootdynamics.trackops",
        )
        db.init_app(self.app)
        self.app.register_blueprint(mobile_api_bp)
        with self.app.app_context():
            db.create_all()
            self.alex = self._driver("alex@example.test", "alex")
            self.blair = self._driver("blair@example.test", "blair")
            db.session.add(
                DriverConnection(
                    user_one_id=min(self.alex.id, self.blair.id),
                    user_two_id=max(self.alex.id, self.blair.id),
                    requested_by_user_id=self.alex.id,
                    status="accepted",
                )
            )
            db.session.commit()
            self.alex_id = self.alex.id
            self.blair_id = self.blair.id
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _driver(self, email, username):
        user = User(
            first_name=username.title(),
            last_name="Driver",
            username=username,
            email=email,
            phone="555-0100",
            driver_class="C",
            static_qr_code=f"DRV-{username.upper()}",
            date_of_birth=date(1990, 1, 1),
            street="1 Main St",
            city="Austin",
            state="TX",
            postal_code="78701",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(user)
        db.session.flush()
        return user

    def _token(self, email):
        response = self.client.post(
            "/api/v1/mobile/auth/login",
            json={"email": email, "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["access_token"]

    @staticmethod
    def _headers(token):
        return {"Authorization": f"Bearer {token}"}

    def test_reporting_blocking_and_unblocking_are_enforced(self):
        alex_token = self._token("alex@example.test")
        blair_token = self._token("blair@example.test")
        created = self.client.post(
            "/api/v1/mobile/driver/community/posts",
            headers=self._headers(blair_token),
            json={"body": "A clean community post."},
        )
        self.assertEqual(created.status_code, 201)
        post_id = created.get_json()["post"]["id"]

        report = self.client.post(
            f"/api/v1/mobile/driver/community/posts/{post_id}/report",
            headers=self._headers(alex_token),
            json={"reason": "harassment"},
        )
        self.assertEqual(report.status_code, 200)
        with self.app.app_context():
            self.assertEqual(CommunityReport.query.count(), 1)

        blocked = self.client.post(
            f"/api/v1/mobile/driver/community/users/{self.blair_id}/block",
            headers=self._headers(alex_token),
            json={},
        )
        self.assertEqual(blocked.status_code, 200)
        feed = self.client.get(
            "/api/v1/mobile/driver/community",
            headers=self._headers(alex_token),
        ).get_json()
        self.assertEqual(feed["posts"], [])
        self.assertEqual(feed["connections"], [])
        self.assertEqual(feed["blocked_users"][0]["id"], self.blair_id)
        with self.app.app_context():
            self.assertEqual(UserBlock.query.count(), 1)
            self.assertEqual(DriverConnection.query.count(), 0)

        unblocked = self.client.delete(
            f"/api/v1/mobile/driver/community/users/{self.blair_id}/block",
            headers=self._headers(alex_token),
        )
        self.assertEqual(unblocked.status_code, 200)
        with self.app.app_context():
            self.assertEqual(UserBlock.query.count(), 0)

    def test_unsafe_text_is_rejected(self):
        token = self._token("alex@example.test")
        response = self.client.post(
            "/api/v1/mobile/driver/community/posts",
            headers=self._headers(token),
            json={"body": "I will kill you"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "content_not_allowed")

    def test_driver_run_history_is_private_and_can_be_shared_once(self):
        with self.app.app_context():
            track = Track(name="Run History Track", city="Austin", state="TX")
            event = Event(
                track=track,
                event_name="Recorded Track Day",
                event_date=date(2026, 8, 22),
            )
            alex_car = Car(
                user_id=self.alex_id,
                make="Mazda",
                model="MX-5",
                car_year=2024,
                color="Red",
            )
            blair_car = Car(
                user_id=self.blair_id,
                make="Porsche",
                model="Cayman",
                car_year=2023,
                color="Blue",
            )
            db.session.add_all((track, event, alex_car, blair_car))
            db.session.flush()
            started = datetime(2026, 8, 22, 14, 30)
            alex_run = TrackRun(
                track_id=track.id,
                event_id=event.id,
                status="completed",
                started_at=started,
                ended_at=started + timedelta(minutes=8, seconds=12),
            )
            blair_run = TrackRun(
                track_id=track.id,
                event_id=event.id,
                status="completed",
                started_at=started + timedelta(hours=1),
                ended_at=started + timedelta(hours=1, minutes=7),
            )
            db.session.add_all((alex_run, blair_run))
            db.session.flush()
            camera = CameraDevice(
                device_uuid="test-run-camera",
                track_id=track.id,
                name="Front straight",
                status="active",
            )
            db.session.add(camera)
            db.session.flush()
            db.session.add_all(
                (
                    TrackRunParticipant(
                        run_id=alex_run.id,
                        car_id=alex_car.id,
                        driver_id=self.alex_id,
                        entered_at=started,
                        exited_at=alex_run.ended_at,
                    ),
                    TrackRunParticipant(
                        run_id=blair_run.id,
                        car_id=blair_car.id,
                        driver_id=self.blair_id,
                        entered_at=blair_run.started_at,
                        exited_at=blair_run.ended_at,
                    ),
                    TrackRunVideo(
                        run_id=alex_run.id,
                        camera_id=camera.id,
                        source_key="front",
                        source_name="Front straight",
                        status="ready",
                        object_key="https://cdn.example.test/runs/alex.mp4",
                        uploaded_at=alex_run.ended_at,
                    ),
                )
            )
            db.session.commit()
            alex_run_id = alex_run.id
            blair_run_id = blair_run.id

        token = self._token("alex@example.test")
        headers = self._headers(token)
        history = self.client.get("/api/v1/mobile/driver/runs", headers=headers)
        self.assertEqual(history.status_code, 200)
        runs = history.get_json()["runs"]
        self.assertEqual([run["id"] for run in runs], [alex_run_id])
        self.assertEqual(runs[0]["duration_seconds"], 492)
        self.assertEqual(runs[0]["car"]["label"], "2024 Mazda MX-5")
        self.assertEqual(
            runs[0]["videos"][0]["url"],
            "https://cdn.example.test/runs/alex.mp4",
        )

        detail = self.client.get(
            f"/api/v1/mobile/driver/runs/{alex_run_id}", headers=headers
        )
        self.assertEqual(detail.status_code, 200)
        forbidden = self.client.get(
            f"/api/v1/mobile/driver/runs/{blair_run_id}", headers=headers
        )
        self.assertEqual(forbidden.status_code, 404)

        shared = self.client.post(
            f"/api/v1/mobile/driver/runs/{alex_run_id}/share", headers=headers
        )
        self.assertEqual(shared.status_code, 201)
        shared_again = self.client.post(
            f"/api/v1/mobile/driver/runs/{alex_run_id}/share", headers=headers
        )
        self.assertEqual(shared_again.status_code, 200)
        with self.app.app_context():
            self.assertEqual(
                SocialPost.query.filter_by(
                    user_id=self.alex_id, track_run_id=alex_run_id
                ).count(),
                1,
            )

    def test_account_deletion_revokes_access_and_anonymizes_profile(self):
        token = self._token("alex@example.test")
        response = self.client.delete(
            "/api/v1/mobile/account",
            headers=self._headers(token),
            json={"confirmation": "DELETE"},
        )
        self.assertEqual(response.status_code, 200)
        me = self.client.get(
            "/api/v1/mobile/me", headers=self._headers(token)
        )
        self.assertEqual(me.status_code, 401)
        with self.app.app_context():
            deleted = db.session.get(User, self.alex_id)
            self.assertIsNotNone(deleted.deleted_at)
            self.assertEqual(deleted.first_name, "Deleted")
            self.assertTrue(deleted.email.endswith("@deleted.invalid"))
            self.assertEqual(DriverConnection.query.count(), 0)

    def test_every_mobile_account_type_can_delete_its_account(self):
        with self.app.app_context():
            track = Track(name="Test Track", city="Austin", state="TX")
            db.session.add(track)
            db.session.flush()
            employee = Employee(
                track_id=track.id,
                full_name="Office User",
                email="office@example.test",
                password_hash=generate_password_hash("Password123!"),
                role="office_staff",
            )
            admin = EnterpriseAdmin(
                full_name="Admin User",
                email="admin@example.test",
                password_hash=generate_password_hash("Password123!"),
            )
            vendor = VendorAccount(
                full_name="Vendor User",
                business_name="Vendor Business",
                email="vendor@example.test",
                phone="555-0199",
                business_address="2 Main St",
                password_hash=generate_password_hash("Password123!"),
            )
            db.session.add_all((employee, admin, vendor))
            db.session.commit()
            account_ids = {
                "office@example.test": (Employee, employee.id),
                "admin@example.test": (EnterpriseAdmin, admin.id),
                "vendor@example.test": (VendorAccount, vendor.id),
            }

        for email, (model, account_id) in account_ids.items():
            token = self._token(email)
            response = self.client.delete(
                "/api/v1/mobile/account",
                headers=self._headers(token),
                json={"confirmation": "DELETE"},
            )
            self.assertEqual(response.status_code, 200)
            with self.app.app_context():
                deleted = db.session.get(model, account_id)
                self.assertIsNotNone(deleted.deleted_at)
                self.assertTrue(deleted.email.endswith("@deleted.invalid"))


if __name__ == "__main__":
    unittest.main()
