"""Exercise website recovery with real CSRF, account records, and mocked SMTP."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import re
from threading import Event
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from werkzeug.security import check_password_hash, generate_password_hash

from racetrack import csrf
from racetrack.mobile_api import mobile_api_bp, _serializer as mobile_serializer
from racetrack.models import db, Employee, EnterpriseAdmin, PasswordResetRequest, Track, User, VendorAccount
from racetrack.services import password_reset_service as recovery
from test_browser_privacy import PageMarkup, make_privacy_test_app


class PasswordResetTest(unittest.TestCase):
    def setUp(self):
        self.app = make_privacy_test_app()
        self.app.config.update(APP_BASE_URL="https://www.trackops.tech", PASSWORD_RESET_SEND_INLINE=True)
        self.app.register_blueprint(mobile_api_bp)
        csrf.exempt(mobile_api_bp)
        self.client = self.app.test_client()
        with self.app.app_context():
            self.original_hash = generate_password_hash("OriginalPassword123!")
            user = User(
                first_name="Reset", last_name="Test", username="reset-test",
                email="reset@example.com", password_hash=self.original_hash,
                must_change_password=False, phone="555-0100", date_of_birth=date(1990, 1, 1),
                street="1 Test St", city="Austin", state="TX", postal_code="78701",
            )
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id
        self.mail_patch = patch("racetrack.services.email_service.send_email", return_value=True)
        self.mail = self.mail_patch.start()
        self.addCleanup(self.mail_patch.stop)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def get(self, path, client=None, **kwargs):
        return (client or self.client).get(path, base_url="https://localhost", **kwargs)

    def post(self, path, data, client=None):
        client = client or self.client
        token = PageMarkup(self.get(path, client).get_data(as_text=True)).csrf_token
        return client.post(path, base_url="https://localhost", data={**data, "csrf_token": token},
                           headers={"Referer": "https://localhost" + path})

    def request_link(self, email="reset@example.com"):
        response = self.post("/forgot-password", {"email": email})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/forgot-password/sent")
        return response

    def reset_path(self):
        calls = [call for call in self.mail.call_args_list if call.args[1] == "Reset your Track Ops password"]
        url = re.search(r"https://[^\s]+", calls[-1].args[2]).group(0)
        parts = urlsplit(url)
        self.assertEqual(parts.netloc, "www.trackops.tech")
        return parts.path + "?" + parts.query

    def reset(self, path, password="ReplacementPassword456!", **extra):
        return self.post(path, {"new_password": password, "confirm_password": password, **extra})

    def test_link_is_visible_and_recovery_pages_are_private(self):
        self.assertIn(b'href="/forgot-password"', self.get("/login").data)
        for path in ("/forgot-password", "/forgot-password/sent", "/reset-password?token=invalid"):
            response = self.get(path)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            self.assertIn("noindex", response.headers["X-Robots-Tag"])
            for asset in PageMarkup(response.get_data(as_text=True)).assets:
                with self.get(asset) as asset_response:
                    self.assertEqual(asset_response.status_code, 200)

    def test_request_leaves_password_unchanged_and_link_is_single_use(self):
        self.request_link(" RESET@EXAMPLE.COM ")
        path = self.reset_path()
        with self.app.app_context():
            self.assertEqual(db.session.get(User, self.user_id).password_hash, self.original_hash)
        # Link previews and mail scanners must not consume the link.
        self.assertEqual(self.get(path).status_code, 200)
        self.assertEqual(self.get(path).status_code, 200)
        result = self.reset(path)
        self.assertEqual(result.location, "/login")
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            self.assertTrue(check_password_hash(user.password_hash, "ReplacementPassword456!"))
            self.assertFalse(user.must_change_password)
        self.assertEqual(self.get(path).status_code, 400)
        with self.client.session_transaction() as saved:
            self.assertNotIn("_user_id", saved)
        self.assertIn("Your Track Ops password was changed", self.mail.call_args.args)
        self.assertNotIn("ReplacementPassword456!", self.mail.call_args.args[2])
        old_login = self.post("/login", {"email": "reset@example.com", "password": "OriginalPassword123!"})
        self.assertEqual(old_login.status_code, 200)
        new_login = self.post("/login", {"email": "reset@example.com", "password": "ReplacementPassword456!"})
        self.assertEqual(new_login.status_code, 302)

    def test_csrf_and_password_validation_do_not_consume_token(self):
        response = self.client.post("/forgot-password", base_url="https://localhost", data={"email": "reset@example.com"})
        self.assertEqual(response.status_code, 400)
        self.mail.assert_not_called()
        self.request_link()
        path = self.reset_path()
        response = self.client.post(path, base_url="https://localhost", data={"new_password": "ReplacementPassword456!"})
        self.assertEqual(response.status_code, 400)
        for password, confirmation in (("short", "short"), ("ReplacementPassword456!", "different"),
                                        ("OriginalPassword123!", "OriginalPassword123!")):
            response = self.reset(path, password, confirm_password=confirmation)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'class="field-error"', response.data)
        self.assertEqual(self.reset(path).status_code, 302)

    def test_unknown_deleted_and_ambiguous_emails_have_same_response(self):
        with self.app.app_context():
            db.session.add(EnterpriseAdmin(full_name="Other account", email="reset@example.com", password_hash=self.original_hash))
            db.session.commit()
        for email in ("missing@example.com", "reset@example.com"):
            self.request_link(email)
        self.mail.assert_not_called()
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            user.email = "deleted@example.com"
            user.deleted_at = datetime.utcnow()
            db.session.commit()
        self.request_link("deleted@example.com")
        self.mail.assert_not_called()

    def test_email_throttle_applies_to_unknown_accounts_too(self):
        self.request_link()
        self.request_link("RESET@example.com")
        self.assertEqual(self.mail.call_count, 1)
        self.request_link("unknown@example.com")
        self.request_link("unknown@example.com")
        with self.app.app_context():
            self.assertEqual(PasswordResetRequest.query.count(), 2)
        self.assertEqual(self.mail.call_count, 1)

    def test_failed_delivery_does_not_change_password_or_activate_link(self):
        self.mail.return_value = False
        self.request_link()
        self.assertEqual(self.get(self.reset_path()).status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.get(User, self.user_id).password_hash, self.original_hash)

    def test_mail_exception_is_contained(self):
        self.mail.side_effect = RuntimeError("SMTP unavailable")
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.request_link()
        with self.app.app_context():
            self.assertEqual(db.session.get(User, self.user_id).password_hash, self.original_hash)

    def test_expired_tampered_and_changed_account_links_fail(self):
        self.request_link()
        path = self.reset_path()
        token = parse_qs(urlsplit(path).query)["token"][0]
        self.assertEqual(self.get(path + "tampered").status_code, 400)
        with self.app.app_context():
            data = recovery._serializer().loads(token)
            with patch("itsdangerous.timed.time.time", return_value=time.time() - 1801):
                expired = recovery._serializer().dumps(data)
        self.assertEqual(self.get("/reset-password?token=" + expired).status_code, 400)
        with self.app.app_context():
            db.session.get(User, self.user_id).email = "changed@example.com"
            db.session.commit()
        self.assertEqual(self.get(path).status_code, 400)

    def test_reset_covers_all_account_types(self):
        with self.app.app_context():
            track = Track(name="Test track", city="Austin", state="TX")
            db.session.add(track)
            db.session.flush()
            accounts = [
                Employee(track_id=track.id, full_name="Staff", email="staff@example.com", password_hash=self.original_hash, must_change_password=True),
                EnterpriseAdmin(full_name="Admin", email="admin@example.com", password_hash=self.original_hash),
                VendorAccount(full_name="Vendor", business_name="Vendor", email="vendor@example.com", phone="555-0100", business_address="Test address", password_hash=self.original_hash),
            ]
            db.session.add_all(accounts)
            db.session.commit()
            records = [(type(account), account.id, account.email) for account in accounts]
        for model, account_id, email in records:
            with self.subTest(email=email):
                self.request_link(email)
                self.assertEqual(self.reset(self.reset_path()).status_code, 302)
                with self.app.app_context():
                    account = db.session.get(model, account_id)
                    self.assertTrue(check_password_hash(account.password_hash, "ReplacementPassword456!"))
                    self.assertFalse(account.must_change_password)

    def test_reset_revokes_browser_mobile_and_handoff_sessions(self):
        browser = self.app.test_client()
        self.post("/login", {"email": "reset@example.com", "password": "OriginalPassword123!"}, browser)
        mobile = self.client.post("/api/v1/mobile/auth/login", json={"email": "reset@example.com", "password": "OriginalPassword123!"}).get_json()
        headers = {"Authorization": "Bearer " + mobile["access_token"]}
        handoff = self.client.post("/api/v1/mobile/auth/web-link", headers=headers, json={"target": "/user/dashboard"}).get_json()["url"]
        self.request_link()
        self.assertEqual(self.reset(self.reset_path()).status_code, 302)
        self.assertEqual(self.get("/login", browser).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/mobile/me", headers=headers).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/mobile/auth/refresh", json={"refresh_token": mobile["refresh_token"]}).status_code, 401)
        handoff_parts = urlsplit(handoff)
        self.assertEqual(self.get(handoff_parts.path + "?" + handoff_parts.query).status_code, 401)

    def test_legacy_mobile_token_can_refresh_without_changing_client_protocol(self):
        mobile = self.client.post("/api/v1/mobile/auth/login", json={"email": "reset@example.com", "password": "OriginalPassword123!"}).get_json()
        with self.app.app_context():
            legacy_token = mobile_serializer().dumps({"type": "user", "id": self.user_id})
        self.assertEqual(self.client.get("/api/v1/mobile/me", headers={"Authorization": "Bearer " + legacy_token}).status_code, 401)
        refreshed = self.client.post("/api/v1/mobile/auth/refresh", json={"refresh_token": mobile["refresh_token"]})
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/mobile/me", headers={"Authorization": "Bearer " + refreshed.get_json()["access_token"]}).status_code, 200)

    def test_browser_password_changes_keep_current_session_and_reject_legacy_sessions(self):
        self.post("/login", {"email": "reset@example.com", "password": "OriginalPassword123!"})
        changed = self.post("/security", {"current_password": "OriginalPassword123!", "new_password": "ReplacementPassword456!", "confirm_password": "ReplacementPassword456!"})
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(self.get("/login").status_code, 302)
        with self.client.session_transaction() as saved:
            saved.pop("credential_version")
        self.assertEqual(self.get("/login").status_code, 200)

    def test_reset_cannot_overwrite_a_password_changed_after_validation(self):
        self.request_link()
        token = parse_qs(urlsplit(self.reset_path()).query)["token"][0]
        with self.app.test_request_context("/reset-password"):
            stale_account = recovery.account_for_reset_token(token)
            db.session.expunge(stale_account)
            competing_hash = generate_password_hash("CompetingPassword789!")
            User.query.filter_by(id=self.user_id).update({"password_hash": competing_hash}, synchronize_session=False)
            db.session.commit()
            # The detached, previously verified account models another request winning first.
            with patch.object(recovery, "account_for_reset_token", return_value=stale_account):
                self.assertFalse(recovery.complete_password_reset(token, "ReplacementPassword456!"))
            self.assertEqual(db.session.get(User, self.user_id).password_hash, competing_hash)

    def test_success_invalidates_every_outstanding_reset_link(self):
        self.request_link()
        first = self.reset_path()
        with self.app.app_context():
            PasswordResetRequest.query.update({"requested_at": datetime.utcnow() - timedelta(minutes=11)})
            db.session.commit()
        self.request_link()
        second = self.reset_path()
        self.assertNotEqual(first, second)
        self.assertEqual(self.reset(second).status_code, 302)
        self.assertEqual(self.get(first).status_code, 400)

    def test_reset_link_uses_configured_origin_not_request_host(self):
        client = self.app.test_client()
        page = client.get("/forgot-password", base_url="https://untrusted.example")
        token = PageMarkup(page.get_data(as_text=True)).csrf_token
        response = client.post("/forgot-password", base_url="https://untrusted.example", data={"email": "reset@example.com", "csrf_token": token}, headers={"Referer": "https://untrusted.example/forgot-password"})
        self.assertEqual(response.status_code, 302)
        self.reset_path()  # Also asserts the canonical host in the emailed URL.

    def test_slow_smtp_does_not_hold_up_the_public_response(self):
        started, release = Event(), Event()

        def slow_mail(*args, **kwargs):
            started.set()
            release.wait(5)
            return True

        self.app.config["PASSWORD_RESET_SEND_INLINE"] = False
        self.mail.side_effect = slow_mail
        with ThreadPoolExecutor(max_workers=1) as executor, patch.object(recovery, "_mail_executor", executor):
            try:
                self.request_link()
                self.assertTrue(started.wait(2))
                self.assertFalse(release.is_set())
            finally:
                release.set()


if __name__ == "__main__":
    unittest.main()
