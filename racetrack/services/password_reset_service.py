"""Single-use website recovery links, with bounded background email delivery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import secrets
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from flask import current_app, url_for
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from ..models import (
    db, Employee, EnterpriseAdmin, MobileRefreshToken, MobileSocialAuthCode,
    PasswordResetRequest, User, VendorAccount,
)
from ..security import credential_fingerprint, credentials_match
from .email_service import send_password_changed_email, send_password_reset_email


RESET_LINK_SECONDS = 30 * 60
RESET_THROTTLE_MINUTES = 10
ACCOUNT_MODELS = {"user": User, "employee": Employee, "admin": EnterpriseAdmin, "vendor": VendorAccount}
_mail_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="password-mail")
_mail_slots = BoundedSemaphore(32)


def _serializer():
    return URLSafeTimedSerializer(
        current_app.secret_key, salt="trackops-web-password-reset-v1",
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def _email_hash(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _public_url(endpoint, **values):
    # Never let the request Host header choose where a recovery email points.
    base = (current_app.config.get("APP_BASE_URL") or "").rstrip("/")
    parts = urlsplit(base)
    local_http = parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}
    if (parts.scheme != "https" and not local_http) or not parts.hostname or (
        parts.username or parts.password or parts.query or parts.fragment
    ):
        raise ValueError("APP_BASE_URL must be a trusted HTTPS origin")
    return base + url_for(endpoint, **values)


def _queue_mail(operation, *args):
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                operation(*args)
            except Exception:
                db.session.rollback()
                # SMTP exceptions can contain recipient addresses or message data.
                app.logger.error("Password recovery email could not be delivered")

    if app.testing and app.config.get("PASSWORD_RESET_SEND_INLINE"):
        run()
        return
    if not _mail_slots.acquire(blocking=False):
        app.logger.warning("Password recovery email queue is full")
        return
    try:
        future = _mail_executor.submit(run)
        future.add_done_callback(lambda result: _mail_slots.release())
    except RuntimeError:
        _mail_slots.release()
        app.logger.warning("Password recovery email queue is unavailable")


def _deliver_reset(request_id, email, reset_url):
    if send_password_reset_email(email, reset_url, RESET_LINK_SECONDS // 60):
        PasswordResetRequest.query.filter_by(id=request_id).update({"delivered": True})
        db.session.commit()


def request_password_reset(email):
    """Always return the same result, including unknown/ambiguous accounts."""
    email = email.strip().lower()
    now = datetime.utcnow()
    email_hash = _email_hash(email)
    recent = PasswordResetRequest.query.filter(
        PasswordResetRequest.email_hash == email_hash,
        PasswordResetRequest.requested_at >= now - timedelta(minutes=RESET_THROTTLE_MINUTES),
    ).first()
    if recent:
        return
    record = PasswordResetRequest(email_hash=email_hash, requested_at=now)
    db.session.add(record)
    db.session.commit()
    candidates = [
        account for model in ACCOUNT_MODELS.values()
        for account in model.query.filter_by(email=email, deleted_at=None).all()
    ]
    if len(candidates) != 1:
        return
    account = candidates[0]
    token = _serializer().dumps({
        "type": account.account_type, "id": account.id, "request": record.id,
        "version": credential_fingerprint(account), "nonce": secrets.token_urlsafe(24),
    })
    reset_url = _public_url("auth.reset_password", token=token)
    # Keep SMTP latency out of the public response, including unknown addresses.
    _queue_mail(_deliver_reset, record.id, account.email, reset_url)


def account_for_reset_token(token):
    if not token or len(token) > 4096:
        return None
    try:
        data = _serializer().loads(token, max_age=RESET_LINK_SECONDS)
    except BadData:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        return None
    model = ACCOUNT_MODELS.get(data["type"])
    if not model or type(data.get("id")) is not int or type(data.get("request")) is not int:
        return None
    account = db.session.get(model, data["id"])
    record = db.session.get(PasswordResetRequest, data["request"])
    if not account or account.deleted_at or not record or not record.delivered:
        return None
    if record.requested_at < datetime.utcnow() - timedelta(seconds=RESET_LINK_SECONDS):
        return None
    if record.email_hash != _email_hash(account.email) or not credentials_match(account, data.get("version")):
        return None
    return account


def complete_password_reset(token, password):
    account = account_for_reset_token(token)
    if not account:
        return False
    login_url = _public_url("auth.user_login")
    # Compare-and-swap makes simultaneous submissions single-use as well.
    changed = type(account).query.filter_by(
        id=account.id, email=account.email, password_hash=account.password_hash, deleted_at=None,
    ).update({
        "password_hash": generate_password_hash(password), "must_change_password": False,
    }, synchronize_session=False)
    if changed != 1:
        db.session.rollback()
        return False
    now = datetime.utcnow()
    MobileRefreshToken.query.filter_by(
        account_type=account.account_type, account_id=account.id, revoked_at=None,
    ).update({"revoked_at": now})
    MobileSocialAuthCode.query.filter_by(
        account_type=account.account_type, account_id=account.id, redeemed_at=None,
    ).update({"redeemed_at": now})
    email = account.email
    db.session.commit()
    _queue_mail(send_password_changed_email, email, login_url)
    return True
