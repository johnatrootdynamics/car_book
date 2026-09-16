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


def encrypt_secret(value):
    if not value:
        return None
    if isinstance(value, str):
        value = value.encode("utf-8")
    return _credential_cipher().encrypt(value).decode("utf-8")


def decrypt_secret(encrypted_value, *, as_bytes=False):
    if not encrypted_value:
        return b"" if as_bytes else ""
    try:
        value = _credential_cipher().decrypt(encrypted_value.encode("utf-8"))
        return value if as_bytes else value.decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "A saved credential cannot be decrypted. Check SMTP_CREDENTIAL_KEY."
        ) from exc


def encrypt_smtp_password(password):
    return encrypt_secret(password)


def decrypt_smtp_password(encrypted_password):
    return decrypt_secret(encrypted_password)


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


def _event_date_label(event):
    return f"{event.event_date.strftime('%B')} {event.event_date.day}, {event.event_date.year}"


def _event_time_label(event):
    if not event.event_start_time:
        return "Time shown on event page"
    value = event.event_start_time.strftime("%I:%M %p").lstrip("0")
    if event.event_end_time:
        value += f"–{event.event_end_time.strftime('%I:%M %p').lstrip('0')}"
    return value


def _wallet_buttons_html(links):
    buttons = []
    if links.get("apple"):
        buttons.append(
            f"<a href='{html.escape(links['apple'])}' style='display:inline-block;margin:4px 5px;padding:11px 16px;border-radius:8px;background:#050505;color:#fff;text-decoration:none;font-size:13px;font-weight:700'>"
            "&#63743;&nbsp; Add to Apple Wallet</a>"
        )
    if links.get("google"):
        buttons.append(
            f"<a href='{html.escape(links['google'])}' style='display:inline-block;margin:4px 5px;padding:11px 16px;border-radius:8px;background:#111827;color:#fff;text-decoration:none;font-size:13px;font-weight:700'>"
            "G&nbsp; Add to Google Wallet</a>"
        )
    if not buttons:
        return ""
    return (
        "<div style='padding:13px 12px 8px;text-align:center'>"
        + "".join(buttons)
        + "</div>"
    )


def _ticket_card_html(*, event, ticket_type, holder, code, cid, design, order_number, wallet_links):
    event_name = html.escape(event.event_name)
    track_name = html.escape(event.track.name)
    ticket_type = html.escape(ticket_type)
    holder = html.escape(holder or "Ticket holder")
    order_number = html.escape(order_number)
    code = html.escape(code)
    date_label = html.escape(_event_date_label(event))
    time_label = html.escape(_event_time_label(event))
    location = html.escape(f"{event.track.city}, {event.track.state}")
    wallet_buttons = _wallet_buttons_html(wallet_links)

    if design == "clean_grid":
        return (
            "<div style='margin:22px 0;border:1px solid #dbe3ef;border-radius:18px;overflow:hidden;background:#fff;box-shadow:0 8px 24px rgba(15,23,42,.08)'>"
            "<table role='presentation' width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse'>"
            "<tr>"
            "<td width='118' valign='top' style='padding:24px 14px;background:#1d4ed8;color:#fff;text-align:center'>"
            f"<div style='font-size:13px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;opacity:.8'>{html.escape(event.event_date.strftime('%b'))}</div>"
            f"<div style='font-size:42px;line-height:1;font-weight:900;margin:7px 0'>{event.event_date.day}</div>"
            f"<div style='font-size:13px;font-weight:700'>{event.event_date.year}</div>"
            "</td>"
            "<td valign='top' style='padding:23px 20px;color:#0f172a'>"
            f"<div style='font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#2563eb'>{ticket_type} ticket</div>"
            f"<h2 style='margin:6px 0 8px;font-size:24px;line-height:1.15;color:#0f172a'>{event_name}</h2>"
            f"<div style='font-size:14px;line-height:1.6;color:#475569'>{track_name} &middot; {location}<br>{time_label}<br><strong style='color:#0f172a'>{holder}</strong></div>"
            f"<div style='margin-top:16px;font-size:11px;color:#64748b'>ORDER {order_number}</div>"
            "</td>"
            "<td width='174' valign='middle' style='padding:20px;border-left:1px dashed #cbd5e1;text-align:center'>"
            f"<img src='cid:{cid}' width='142' height='142' alt='Ticket QR code' style='display:block;margin:0 auto 8px'>"
            f"<div style='font-family:monospace;font-size:9px;color:#64748b;word-break:break-all'>{code}</div>"
            "</td></tr></table>"
            + wallet_buttons
            + "</div>"
        )

    return (
        "<div style='margin:22px 0;border-radius:18px;overflow:hidden;background:#111827;box-shadow:0 10px 26px rgba(15,23,42,.2)'>"
        "<table role='presentation' width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse'>"
        "<tr><td colspan='2' style='height:7px;background:#f97316;font-size:0'>&nbsp;</td></tr>"
        "<tr>"
        "<td valign='top' style='padding:25px;color:#fff'>"
        f"<div style='font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#fb923c'>Track Ops &middot; {ticket_type}</div>"
        f"<h2 style='margin:8px 0 15px;font-size:26px;line-height:1.12;color:#fff'>{event_name}</h2>"
        f"<div style='font-size:14px;line-height:1.65;color:#cbd5e1'><strong style='color:#fff'>{date_label}</strong> &middot; {time_label}<br>{track_name} &middot; {location}<br>Issued to <strong style='color:#fff'>{holder}</strong></div>"
        f"<div style='margin-top:20px;font-size:10px;letter-spacing:.1em;color:#94a3b8'>ORDER {order_number}</div>"
        "</td>"
        "<td width='192' valign='middle' style='padding:22px;background:#fff;border-left:2px dashed #cbd5e1;text-align:center'>"
        f"<img src='cid:{cid}' width='154' height='154' alt='Ticket QR code' style='display:block;margin:0 auto 8px'>"
        "<div style='font-size:10px;font-weight:800;letter-spacing:.08em;color:#0f172a'>SCAN FOR ENTRY</div>"
        f"<div style='margin-top:5px;font-family:monospace;font-size:9px;color:#64748b;word-break:break-all'>{code}</div>"
        "</td></tr></table>"
        + wallet_buttons
        + "</div>"
    )


def send_spectator_order_receipt(order):
    from .ticket_service import ensure_order_ticket_codes, ticket_qr_png, ticket_verification_url
    from .wallet_service import wallet_links_for_ticket

    ensure_order_ticket_codes(order)
    track = order.items[0].event.track if order.items else None
    ticket_lines = []
    ticket_lines_display = []
    ticket_count = len(order.items)
    for index, item in enumerate(order.items, start=1):
        category_label = "Vendor" if item.ticket_category == "vendor" else "Spectator"
        wallet_links = wallet_links_for_ticket(item.qr_code)
        wallet_lines = "".join(
            f"\n{label}: {url}"
            for label, url in (
                ("Add to Apple Wallet", wallet_links.get("apple")),
                ("Add to Google Wallet", wallet_links.get("google")),
            )
            if url
        )
        ticket_lines.append(
            f"Ticket {index} of {ticket_count}: {category_label} - {item.event.event_name} - {item.ticket_type_name}\n"
            f"Ticket code: {item.qr_code}\n"
            f"QR link: {ticket_verification_url(item.qr_code)}{wallet_lines}"
        )
        ticket_lines_display.append(
            f"Ticket {index} of {ticket_count}: {category_label} - {item.event.event_name} - {item.ticket_type_name}\n"
            f"Ticket code: {item.qr_code}"
        )
    display_ticket_lines = "\n".join(ticket_lines_display)
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
        html_message_body = _render_text(
            template.body,
            {**values, "ticket_lines": display_ticket_lines},
        )
    else:
        subject = f"Your CarBook tickets: {order.order_number}"
        body = (
            f"Order {order.order_number}\n\n"
            "Your event tickets are confirmed.\n\n"
            f"{values['ticket_lines']}\n\n"
            f"Total: {values['order_total']}\n\n"
            "Present the QR code for each ticket at the gate."
        )
        html_message_body = (
            f"Order {order.order_number}\n\n"
            "Your event tickets are confirmed.\n\n"
            f"{display_ticket_lines}\n\n"
            f"Total: {values['order_total']}"
        )

    ticket_cards = []
    inline_images = []
    design = template.ticket_design if template else "pit_pass"
    holder = (
        (order.vendor.business_name if order.vendor else None)
        or (f"{order.buyer.first_name} {order.buyer.last_name}" if order.buyer else None)
        or order.guest_full_name
        or "Ticket holder"
    )
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
            _ticket_card_html(
                event=item.event,
                ticket_type=f"{category_label} · {item.ticket_type_name}",
                holder=holder,
                code=item.qr_code,
                cid=cid,
                design=design,
                order_number=order.order_number,
                wallet_links=wallet_links_for_ticket(item.qr_code),
            )
        )
    html_body = (
        "<div style='max-width:600px;margin:0 auto;font-family:Arial,sans-serif;color:#344054'>"
        f"<div style='white-space:pre-line;line-height:1.55'>{html.escape(html_message_body)}</div>"
        "<h2 style='margin:26px 0 4px;color:#101828'>Your event tickets</h2>"
        "<p style='margin:0 0 12px;color:#667085'>Each ticket has its own QR code. Present one ticket per guest at the gate.</p>"
        + "".join(ticket_cards)
        + "</div>"
    )
    return send_email(
        order.guest_email or (order.vendor.email if order.vendor else None) or (order.buyer.email if order.buyer else None),
        subject,
        body,
        html_body=html_body,
        inline_images=inline_images,
    )


def send_driver_purchase_receipt(driver_ticket_order):
    from ..models import db
    from .ticket_service import (
        ensure_driver_ticket_code,
        ticket_qr_png,
        ticket_verification_url,
    )
    from .wallet_service import wallet_links_for_ticket

    event = driver_ticket_order.event
    user = driver_ticket_order.buyer
    car = driver_ticket_order.car
    registration, code_changed = ensure_driver_ticket_code(driver_ticket_order)
    if not registration:
        current_app.logger.warning(
            "Driver receipt skipped; registration missing for order %s",
            driver_ticket_order.id,
        )
        return False
    if code_changed:
        db.session.commit()
    ticket_code = registration.checkin_code
    ticket_qr_link = ticket_verification_url(ticket_code)
    values = {
        "track_name": event.track.name,
        "event_name": event.event_name,
        "driver_name": f"{user.first_name} {user.last_name}".strip(),
        "car_name": f"{car.car_year} {car.make} {car.model}",
        "order_total": _money(driver_ticket_order.amount_cents),
        "ticket_code": ticket_code,
        "ticket_qr_link": ticket_qr_link,
    }
    template = _get_track_template(event.track_id, "driver_purchase_receipt")
    if template:
        subject = _render_text(template.subject, values)
        body = _render_text(template.body, values)
    else:
        subject = f"Driver ticket confirmed: {event.event_name}"
        body = (
            f"Hi {user.first_name},\n\n"
            f"Your driver ticket for {event.event_name} is confirmed.\n\n"
            f"Car: {values['car_name']}\n"
            f"Total: {values['order_total']}\n"
            f"Ticket code: {ticket_code}\n"
            f"QR link: {ticket_qr_link}\n\n"
            "Present the QR code at driver check-in. Complete any required waiver and inspection before you are ready to race.\n\n"
            f"Thanks,\n{event.track.name}"
        )

    missing_ticket_lines = []
    if ticket_code not in body:
        missing_ticket_lines.append(f"Ticket code: {ticket_code}")
    if ticket_qr_link not in body:
        missing_ticket_lines.append(f"QR link: {ticket_qr_link}")
    if missing_ticket_lines:
        body = f"{body.rstrip()}\n\n" + "\n".join(missing_ticket_lines)

    html_message_body = body
    cid = f"driver-ticket-{driver_ticket_order.id}@trackops"
    wallet_links = wallet_links_for_ticket(ticket_code)
    wallet_text = "".join(
        f"\n{label}: {url}"
        for label, url in (
            ("Add to Apple Wallet", wallet_links.get("apple")),
            ("Add to Google Wallet", wallet_links.get("google")),
        )
        if url
    )
    if wallet_text and "Add to Apple Wallet" not in body and "Add to Google Wallet" not in body:
        body = f"{body.rstrip()}\n\nWallet passes:{wallet_text}"
    design = template.ticket_design if template else "pit_pass"
    html_body = (
        "<div style='max-width:600px;margin:0 auto;font-family:Arial,sans-serif;color:#344054'>"
        f"<div style='white-space:pre-line;line-height:1.55'>{html.escape(html_message_body)}</div>"
        + _ticket_card_html(
            event=event,
            ticket_type=f"Driver · {values['car_name']}",
            holder=values["driver_name"],
            code=ticket_code,
            cid=cid,
            design=design,
            order_number=f"DR-{driver_ticket_order.id:06d}",
            wallet_links=wallet_links,
        )
        + "<p style='margin:8px 0 0;color:#667085;font-size:13px;text-align:center'>Present this QR code to track staff at driver check-in.</p>"
        "</div>"
    )
    return send_email(
        user.email,
        subject,
        body,
        html_body=html_body,
        inline_images=[
            {
                "cid": cid,
                "content": ticket_qr_png(ticket_code),
                "filename": f"DR-{driver_ticket_order.id:06d}-ticket.png",
            }
        ],
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
