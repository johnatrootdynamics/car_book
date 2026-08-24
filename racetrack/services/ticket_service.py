import secrets
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from flask import url_for


def generate_ticket_code():
    from ..models import SpectatorOrderItem

    while True:
        code = f"TKT-{secrets.token_hex(16).upper()}"
        if not SpectatorOrderItem.query.filter_by(qr_code=code).first():
            return code


def ensure_order_ticket_codes(order):
    changed = False
    for item in order.items:
        if not item.qr_code:
            item.qr_code = generate_ticket_code()
            changed = True
    return changed


def normalize_ticket_code(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return ""
    if value.lower().startswith(("http://", "https://")):
        parsed = urlparse(value)
        value = (parse_qs(parsed.query).get("code") or [""])[0]
    return value.strip().upper()


def ticket_verification_url(code):
    return url_for("employee.ticket_verification", code=code, _external=True)


def ticket_qr_png(code):
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError("QR image support is not installed.") from exc

    image = qrcode.make(ticket_verification_url(code))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
