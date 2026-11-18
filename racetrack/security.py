import hashlib
import hmac
import secrets
import string

from flask import current_app


_PASSWORD_SYMBOLS = "!@#$%+-_"


def credential_fingerprint(account):
    """Bind a session or recovery link to the account's current password."""
    value = f"{account.account_type}:{account.id}:{account.password_hash}"
    return hmac.new(
        current_app.secret_key.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def credentials_match(account, fingerprint):
    return isinstance(fingerprint, str) and hmac.compare_digest(
        credential_fingerprint(account), fingerprint
    )


def generate_random_password(length=16):
    """Generate a readable password containing every required character class."""
    length = max(12, int(length))
    groups = (string.ascii_uppercase, string.ascii_lowercase, string.digits, _PASSWORD_SYMBOLS)
    password = [secrets.choice(group) for group in groups]
    alphabet = "".join(groups)
    password.extend(secrets.choice(alphabet) for _ in range(length - len(password)))
    secrets.SystemRandom().shuffle(password)
    return "".join(password)
