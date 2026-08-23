import secrets
import string


_PASSWORD_SYMBOLS = "!@#$%+-_"


def generate_random_password(length=16):
    """Generate a readable password containing every required character class."""
    length = max(12, int(length))
    groups = (string.ascii_uppercase, string.ascii_lowercase, string.digits, _PASSWORD_SYMBOLS)
    password = [secrets.choice(group) for group in groups]
    alphabet = "".join(groups)
    password.extend(secrets.choice(alphabet) for _ in range(length - len(password)))
    secrets.SystemRandom().shuffle(password)
    return "".join(password)
