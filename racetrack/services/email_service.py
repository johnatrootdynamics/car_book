import base64
import hashlib
import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app
from cryptography.fernet import Fernet, InvalidToken


class _SafeTemplateDict(dict):
    def __missing__(self, key):
        return ""


def _money(cents):
    return f"${(cents or 0) / 100:,.2f}"


def _render_text(template_text, values):
    return (template_text or "").format_map(_SafeTemplateDict(values))


def _get_track_template(track_id, template_key):
    from ..models import TrackEmailTemplate

    return TrackEmailTemplate.query.filter_by(
        track_id=track_id,
        template_key=template_key,
        is_enabled=True,
    ).first()


def _credential_cipher():
    key_material = (
        current_app.config.get("SMTP_CREDENTIAL_KEY")
        or current_app.config.get("SECRET_KEY")
        or "dev-change-me"
    )
    digest = hashlib.sha256(str(key_material).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_smtp_password(password):
    if not password:
        return None
    return _credential_cipher().encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_smtp_password(encrypted_password):
    if not encrypted_password:
        return ""
    try:
        return _credential_cipher().decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "The saved SMTP password cannot be decrypted. Check SMTP_CREDENTIAL_KEY."
        ) from exc


def _environment_email_configuration():
    use_ssl = bool(current_app.config.get("MAIL_USE_SSL"))
    use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    sender_email = current_app.config.get("MAIL_DEFAULT_SENDER") or ""
    return {
        "enabled": bool(current_app.config.get("MAIL_SERVER") and sender_email),
        "server": current_app.config.get("MAIL_SERVER") or "",
        "port": int(current_app.config.get("MAIL_PORT") or 587),
        "security": "ssl" if use_ssl else ("starttls" if use_tls else "none"),
        "username": current_app.config.get("MAIL_USERNAME") or "",
        "password": current_app.config.get("MAIL_PASSWORD") or "",
        "password_saved": bool(current_app.config.get("MAIL_PASSWORD")),
        "sender_name": current_app.config.get("MAIL_DEFAULT_SENDER_NAME") or "Track Ops",
        "sender_email": sender_email,
        "source": "environment",
    }


def get_email_configuration(include_password=True):
    from ..models import SystemEmailSettings

    settings = SystemEmailSettings.query.get(1)
    if not settings:
        config = _environment_email_configuration()
    else:
        config = {
            "enabled": bool(settings.is_enabled),
            "server": settings.server or "",
            "port": settings.port or 587,
            "security": settings.security or "starttls",
            "username": settings.username or "",
            "password": (
                decrypt_smtp_password(settings.password_encrypted)
                if include_password
                else ""
            ),
            "password_saved": bool(settings.password_encrypted),
            "sender_name": settings.sender_name or "Track Ops",
            "sender_email": settings.sender_email or "",
            "source": "admin",
        }
    config["configured"] = bool(
        config["enabled"] and config["server"] and config["sender_email"]
    )
    if not include_password:
        config.pop("password", None)
    return config


def send_email(to_email, subject, body, html_body=None, inline_images=None):
    if not to_email:
        return False
    config = get_email_configuration()
    if not config["configured"]:
        current_app.logger.info("Email skipped; SMTP delivery is disabled or incomplete")
        return False

    msg = EmailMessage()
    msg["From"] = formataddr((config["sender_name"], config["sender_email"]))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
        html_part = msg.get_payload()[-1]
        for image in inline_images or []:
            html_part.add_related(
                image["content"],
                maintype="image",
                subtype=image.get("subtype", "png"),
                cid=f"<{image['cid']}>",
                filename=image.get("filename"),
            )

    smtp_class = smtplib.SMTP_SSL if config["security"] == "ssl" else smtplib.SMTP
    smtp_kwargs = {"host": config["server"], "port": config["port"], "timeout": 15}
    if config["security"] == "ssl":
        smtp_kwargs["context"] = ssl.create_default_context()
    with smtp_class(**smtp_kwargs) as smtp:
        if config["security"] == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        username = config["username"]
        password = config["password"]
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True


def send_user_login_email(user, plaintext_password, login_url, is_reset=False):
    intro = (
        "Your CarBook password has been reset."
        if is_reset
        else "Your CarBook account is ready."
    )
    return send_email(
        user.email,
        "Your new CarBook password" if is_reset else "Welcome to CarBook",
        (
            f"Hi {user.first_name},\n\n"
            f"{intro}\n\n"
            f"Login: {login_url}\n"
            f"Email: {user.email}\n"
            f"Password: {plaintext_password}\n\n"
            "When you sign in, you will be required to choose a new password before continuing.\n\n"
            "Thanks,\nCarBook"
        ),
    )


def send_vendor_login_email(vendor, plaintext_password, login_url, is_reset=False):
    intro = (
        "Your Track Ops vendor password has been reset."
        if is_reset
        else "Your Track Ops vendor account is ready."
    )
    return send_email(
        vendor.email,
        "Your new Track Ops vendor password" if is_reset else "Welcome to Track Ops",
        (
            f"Hi {vendor.full_name},\n\n"
            f"{intro}\n\n"
            f"Business: {vendor.business_name}\n"
            f"Login: {login_url}\n"
            f"Email: {vendor.email}\n"
            f"Password: {plaintext_password}\n\n"
            "When you sign in, you will be required to choose a new password before continuing.\n\n"
            "Thanks,\nTrack Ops"
        ),
    )


def send_employee_login_email(
    employee,
    plaintext_password,
    track,
    login_url,
    is_reset=False,
):
    role_label = "Office staff" if employee.role == "office_staff" else "Track staff"
    intro = (
        f"Your employee password for {track.name} has been reset."
        if is_reset
        else f"An employee account has been created for you at {track.name}."
    )
    return send_email(
        employee.email,
        (
            f"Your new {track.name} Track Ops password"
            if is_reset
            else f"Your {track.name} Track Ops account"
        ),
        (
            f"Hi {employee.full_name},\n\n"
            f"{intro}\n\n"
            f"Login: {login_url}\n"
            f"Email: {employee.email}\n"
            f"Password: {plaintext_password}\n\n"
            f"Role: {role_label}\n\n"
            "When you sign in, you will be required to choose a new password before continuing.\n\n"
            f"Thanks,\n{track.name}"
        ),
    )


def send_admin_login_email(admin, plaintext_password, login_url, is_reset=True):
    intro = (
        "Your enterprise admin password has been reset."
        if is_reset
        else "Your enterprise admin account is ready."
    )
    return send_email(
        admin.email,
        (
            "Your new CarBook enterprise admin password"
            if is_reset
            else "Your CarBook enterprise admin account"
        ),
        (
            f"Hi {admin.full_name},\n\n"
            f"{intro}\n\n"
            f"Login: {login_url}\n"
            f"Email: {admin.email}\n"
            f"Password: {plaintext_password}\n\n"
            "When you sign in, you will be required to choose a new password before continuing.\n\n"
            "Thanks,\nCarBook"
        ),
    )


def send_spectator_order_receipt(order):
    from .ticket_service import ensure_order_ticket_codes, ticket_qr_png, ticket_verification_url

    ensure_order_ticket_codes(order)
    track = order.items[0].event.track if order.items else None
    ticket_lines = []
    ticket_count = len(order.items)
    for index, item in enumerate(order.items, start=1):
        category_label = "Vendor" if item.ticket_category == "vendor" else "Spectator"
        ticket_lines.append(
            f"Ticket {index} of {ticket_count}: {category_label} - {item.event.event_name} - {item.ticket_type_name}\n"
            f"Ticket code: {item.qr_code}\n"
            f"QR link: {ticket_verification_url(item.qr_code)}"
        )
    values = {
        "track_name": track.name if track else "CarBook",
        "buyer_name": order.guest_full_name or "there",
        "order_number": order.order_number,
        "order_total": _money(order.total_cents),
        "ticket_lines": "\n".join(ticket_lines),
    }
    template = _get_track_template(track.id, "spectator_purchase_receipt") if track else None
    if template:
        subject = _render_text(template.subject, values)
        body = _render_text(template.body, values)
    else:
        subject = f"Your CarBook tickets: {order.order_number}"
        body = (
            f"Order {order.order_number}\n\n"
            "Your event tickets are confirmed.\n\n"
            f"{values['ticket_lines']}\n\n"
            f"Total: {values['order_total']}\n\n"
            "Present the QR code for each ticket at the gate."
        )

    ticket_cards = []
    inline_images = []
    for index, item in enumerate(order.items, start=1):
        category_label = "Vendor" if item.ticket_category == "vendor" else "Spectator"
        cid = f"ticket-{item.id or index}-{order.id}@trackops"
        inline_images.append(
            {
                "cid": cid,
                "content": ticket_qr_png(item.qr_code),
                "filename": f"{order.order_number}-ticket-{index}.png",
            }
        )
        ticket_cards.append(
            "<div style='margin:18px 0;padding:18px;border:1px solid #e4e7ec;border-radius:10px;text-align:center'>"
            f"<h3 style='margin:0 0 4px;color:#101828'>{html.escape(item.event.event_name)}</h3>"
            f"<p style='margin:0 0 12px;color:#667085'>Ticket {index} of {ticket_count} &middot; {category_label} &middot; {html.escape(item.ticket_type_name)}</p>"
            f"<img src='cid:{cid}' width='220' height='220' alt='Ticket QR code' style='display:block;margin:0 auto 10px'>"
            f"<code style='font-size:12px;color:#475467'>{html.escape(item.qr_code)}</code>"
            "</div>"
        )
    html_body = (
        "<div style='max-width:600px;margin:0 auto;font-family:Arial,sans-serif;color:#344054'>"
        f"<div style='white-space:pre-line;line-height:1.55'>{html.escape(body)}</div>"
        "<h2 style='margin:26px 0 4px;color:#101828'>Your QR tickets</h2>"
        "<p style='margin:0 0 12px;color:#667085'>Present each code at the gate. Track staff will scan it to verify admission.</p>"
        + "".join(ticket_cards)
        + "</div>"
    )
    return send_email(
        order.guest_email,
        subject,
        body,
        html_body=html_body,
        inline_images=inline_images,
    )


def send_driver_purchase_receipt(driver_ticket_order):
    event = driver_ticket_order.event
    user = driver_ticket_order.buyer
    car = driver_ticket_order.car
    values = {
        "track_name": event.track.name,
        "event_name": event.event_name,
        "driver_name": f"{user.first_name} {user.last_name}".strip(),
        "car_name": f"{car.car_year} {car.make} {car.model}",
        "order_total": _money(driver_ticket_order.amount_cents),
    }
    template = _get_track_template(event.track_id, "driver_purchase_receipt")
    if template:
        return send_email(user.email, _render_text(template.subject, values), _render_text(template.body, values))

    return send_email(
        user.email,
        f"Driver ticket confirmed: {event.event_name}",
        f"Hi {user.first_name},\n\nYour driver ticket for {event.event_name} is confirmed.\n\nNext steps: complete any required waiver, then inspection before you are ready to race.\n\nTotal: {values['order_total']}\n\nThanks,\nCarBook",
    )


def send_private_rental_confirmation(booking):
    slot = booking.slot
    user = booking.buyer
    date_label = slot.slot_date.strftime("%B %-d, %Y")
    time_label = (
        f"{slot.start_time.strftime('%-I:%M %p')}–"
        f"{slot.end_time.strftime('%-I:%M %p')}"
    )
    return send_email(
        user.email,
        f"Private track rental confirmed: {slot.track.name}",
        (
            f"Hi {user.first_name},\n\n"
            f"Your private track rental at {slot.track.name} is confirmed.\n\n"
            f"Date: {date_label}\n"
            f"Time: {time_label}\n"
            f"Driver limit: {slot.driver_limit}\n"
            f"Total: {_money(booking.amount_cents)}\n\n"
            "The private day is now in your dashboard. The track office can help coordinate additional drivers.\n\n"
            "Thanks,\nTrack Ops"
        ),
    )
