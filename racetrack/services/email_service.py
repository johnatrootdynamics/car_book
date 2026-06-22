import smtplib
from email.message import EmailMessage

from flask import current_app


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
    lines = [
        f"Order {order.order_number}",
        "",
        "Your spectator tickets are confirmed.",
        "",
    ]
    for item in order.items:
        lines.append(f"{item.event.event_name} - {item.ticket_type_name} x {item.quantity}")
    lines.extend([
        "",
        f"Total: ${(order.total_cents or 0) / 100:,.2f}",
        "",
        "Use your name, email, phone, or order number at the gate.",
    ])
    return send_email(order.guest_email, f"Your CarBook tickets: {order.order_number}", "\n".join(lines))


def send_driver_purchase_receipt(driver_ticket_order):
    event = driver_ticket_order.event
    user = driver_ticket_order.buyer
    return send_email(
        user.email,
        f"Driver ticket confirmed: {event.event_name}",
        f"Hi {user.first_name},\n\nYour driver ticket for {event.event_name} is confirmed.\n\nNext steps: complete any required waiver, then inspection before you are ready to race.\n\nTotal: ${(driver_ticket_order.amount_cents or 0) / 100:,.2f}\n\nThanks,\nCarBook",
    )
