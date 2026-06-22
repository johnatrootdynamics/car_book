import smtplib
from email.message import EmailMessage

from flask import current_app


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


def send_email(to_email, subject, body):
    if not to_email:
        return False
    server = current_app.config.get("MAIL_SERVER")
    sender = current_app.config.get("MAIL_DEFAULT_SENDER")
    if not server or not sender:
        current_app.logger.info("Email skipped; MAIL_SERVER or MAIL_DEFAULT_SENDER is not configured")
        return False

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    port = current_app.config.get("MAIL_PORT", 587)
    username = current_app.config.get("MAIL_USERNAME")
    password = current_app.config.get("MAIL_PASSWORD")
    use_tls = current_app.config.get("MAIL_USE_TLS", True)

    with smtplib.SMTP(server, port, timeout=10) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True


def send_user_welcome_email(user):
    return send_email(
        user.email,
        "Welcome to CarBook",
        f"Hi {user.first_name},\n\nYour CarBook account is ready. Sign in to find events, buy tickets, complete waivers, and manage your cars.\n\nThanks,\nCarBook",
    )


def send_spectator_order_receipt(order):
    track = order.items[0].event.track if order.items else None
    ticket_lines = []
    for item in order.items:
        ticket_lines.append(f"{item.event.event_name} - {item.ticket_type_name} x {item.quantity}")
    values = {
        "track_name": track.name if track else "CarBook",
        "buyer_name": order.guest_full_name or "there",
        "order_number": order.order_number,
        "order_total": _money(order.total_cents),
        "ticket_lines": "\n".join(ticket_lines),
    }
    template = _get_track_template(track.id, "spectator_purchase_receipt") if track else None
    if template:
        return send_email(order.guest_email, _render_text(template.subject, values), _render_text(template.body, values))

    body = (
        f"Order {order.order_number}\n\n"
        "Your spectator tickets are confirmed.\n\n"
        f"{values['ticket_lines']}\n\n"
        f"Total: {values['order_total']}\n\n"
        "Use your name, email, phone, or order number at the gate."
    )
    return send_email(order.guest_email, f"Your CarBook tickets: {order.order_number}", body)


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
