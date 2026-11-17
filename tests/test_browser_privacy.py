"""Browser-storage regressions using real routes and an isolated SQLite DB."""

from html.parser import HTMLParser
from datetime import date
from pathlib import Path
import unittest

from flask import Flask
from flask_login import current_user
from flask_login.utils import encode_cookie
from jinja2 import StrictUndefined
from werkzeug.security import generate_password_hash

from racetrack import csrf, login_manager
from racetrack.auth import auth_bp
from racetrack.browser_privacy import configure_browser_privacy
from racetrack.models import db, SpectatorCart, User
from racetrack.user_routes import user_bp
from racetrack.waiver_routes import waiver_bp


ROOT = Path(__file__).resolve().parents[1] / "racetrack"


def make_privacy_test_app(*, secure_cookies=True):
    app = Flask("privacy_test", template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.config.update(
        TESTING=True, SECRET_KEY="isolated-privacy-test-secret",
        SQLALCHEMY_DATABASE_URI="sqlite://", SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SUPPORT_EMAIL="support@example.test", TRACK_TIMEZONE="America/New_York",
        APP_BASE_URL="https://localhost", S3_READ_ACCESS_KEY="", S3_READ_SECRET_KEY="",
    )
    app.jinja_env.undefined = StrictUndefined
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    configure_browser_privacy(app, secure_cookies=secure_cookies)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(waiver_bp)

    @app.context_processor
    def roles():
        account_type = getattr(current_user, "account_type", None)
        return {
            "is_user": account_type == "user", "is_employee": account_type == "employee",
            "is_admin": account_type == "admin", "is_vendor": account_type == "vendor",
            "is_office_staff": False, "asset_url": lambda value: value,
        }

    with app.app_context():
        db.create_all()
    return app


class PageMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.csrf_token = None
        self.assets = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrf_token":
            self.csrf_token = attrs.get("value")
        if tag in {"script", "img", "source", "iframe"} and attrs.get("src"):
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") in {"stylesheet", "preload", "icon"}:
            self.assets.append(attrs["href"])


class BrowserPrivacyTest(unittest.TestCase):
    def setUp(self):
        self.app = make_privacy_test_app()
        self.client = self.app.test_client()
        with self.app.app_context():
            driver = User(
                first_name="Privacy", last_name="Test", username="privacy-test",
                email="privacy@example.test", password_hash=generate_password_hash("PrivacyTest123!"),
                static_qr_code="DRV-PRIVACY-TEST", must_change_password=False,
                phone="555-0100", date_of_birth=date(1990, 1, 1),
                street="1 Test Street", city="Austin", state="TX", postal_code="78701",
            )
            db.session.add(driver)
            db.session.commit()
            self.driver_id = driver.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def get(self, path, **kwargs):
        return self.client.get(path, base_url="https://localhost", **kwargs)

    def login(self):
        page = self.get("/login")
        token = PageMarkup(page.get_data(as_text=True)).csrf_token
        return self.client.post("/login", base_url="https://localhost", data={
            "email": "privacy@example.test", "password": "PrivacyTest123!", "csrf_token": token,
        }, headers={"Referer": "https://localhost/login"})

    def test_reading_public_information_does_not_create_cookies(self):
        for path in ["/", "/features", "/cookies", "/privacy", "/terms", "/support", "/community-guidelines"]:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.getlist("Set-Cookie"), [])
                self.assertIsNone(self.client.get_cookie("session"))

    def test_public_assets_are_local_and_exist(self):
        for path in ["/", "/features", "/cookies", "/privacy", "/login", "/register", "/register/vendor"]:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                assets = PageMarkup(response.get_data(as_text=True)).assets
                for asset in assets:
                    self.assertTrue(asset.startswith("/static/"), asset)
                    with self.get(asset) as asset_response:
                        self.assertEqual(asset_response.status_code, 200, asset)

    def test_global_privacy_control_does_not_enable_storage(self):
        response = self.get("/", headers={"Sec-GPC": "1"})
        self.assertEqual(response.headers.getlist("Set-Cookie"), [])
        self.assertIn("Only essential cookies.", response.get_data(as_text=True))

    def test_session_cookie_is_secure_httponly_lax_and_not_persistent(self):
        response = self.get("/login")
        cookie = response.headers["Set-Cookie"]
        for flag in ["Secure", "HttpOnly", "SameSite=Lax"]:
            self.assertIn(flag, cookie)
        self.assertNotIn("Expires=", cookie)
        self.assertNotIn("Max-Age=", cookie)
        self.assertIsNotNone(PageMarkup(response.get_data(as_text=True)).csrf_token)

    def test_cookie_notice_does_not_weaken_form_csrf_protection(self):
        response = self.client.post("/login", base_url="https://localhost", data={
            "email": "privacy@example.test", "password": "PrivacyTest123!",
        })
        self.assertEqual(response.status_code, 400)

    def test_signin_still_works_with_essential_cookies(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as saved_session:
            self.assertEqual(saved_session["_user_id"], f"user:{self.driver_id}")
            self.assertFalse(saved_session.permanent)
        self.assertIsNone(self.client.get_cookie("remember_token"))

    def test_requested_guest_cart_survives_navigation(self):
        response = self.get("/user/spectator/cart")
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as saved_session:
            token = saved_session["spectator_cart_token"]
        self.get("/features")
        self.assertEqual(self.get("/user/spectator/cart").status_code, 200)
        with self.client.session_transaction() as saved_session:
            self.assertEqual(saved_session["spectator_cart_token"], token)
        with self.app.app_context():
            self.assertEqual(SpectatorCart.query.count(), 1)

    def test_logout_clears_session_and_legacy_remember_cookie(self):
        self.login()
        with self.app.app_context():
            remember = encode_cookie(f"user:{self.driver_id}")
        self.client.set_cookie("remember_token", remember)
        response = self.get("/logout")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.client.get_cookie("session"))
        self.assertIsNone(self.client.get_cookie("remember_token"))
        self.assertEqual(self.get("/").headers.getlist("Set-Cookie"), [])

    def test_privacy_pages_remain_accessible_during_required_password_change(self):
        self.login()
        with self.app.app_context():
            db.session.get(User, self.driver_id).must_change_password = True
            db.session.commit()
        for path in ["/privacy", "/cookies", "/terms", "/support"]:
            self.assertEqual(self.get(path).status_code, 200, path)

    def test_marketing_pages_enforce_local_resources(self):
        for path in ["/", "/features", "/cookies"]:
            response = self.get(path)
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
            self.assertIn("frame-src 'none'", response.headers["Content-Security-Policy"])
            self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
