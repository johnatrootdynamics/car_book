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
    for item in list(order.items):
        quantity = max(int(item.quantity or 1), 1)
        if quantity > 1:
            from ..models import SpectatorOrderItem

            line_total = (
                int(item.line_total_cents)
                if item.line_total_cents is not None
                else int(item.unit_price_cents or 0) * quantity
            )
            amount_per_ticket, remainder = divmod(line_total, quantity)
            item.quantity = 1
            item.line_total_cents = amount_per_ticket + (1 if remainder else 0)
            for ticket_index in range(1, quantity):
                order.items.append(
                    SpectatorOrderItem(
                        event_id=item.event_id,
                        ticket_type_name=item.ticket_type_name,
                        unit_price_cents=item.unit_price_cents,
                        quantity=1,
                        line_total_cents=amount_per_ticket + (1 if ticket_index < remainder else 0),
                        qr_code=generate_ticket_code(),
                        checked_in_at=item.checked_in_at,
                        checked_in_by_employee_id=item.checked_in_by_employee_id,
                    )
                )
            changed = True

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
