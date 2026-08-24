from datetime import datetime

import requests

ONLINE_PAYMENT_PROVIDERS = {"stripe", "paypal"}


def payment_is_confirmed(payment_status, provider, amount_cents, transaction_id):
    if payment_status != "paid":
        return False
    if int(amount_cents or 0) <= 0 or provider not in ONLINE_PAYMENT_PROVIDERS:
        return True
    return bool(transaction_id)


def effective_payment_status(order):
    status = order.payment_status or "pending"
    amount_cents = getattr(order, "total_cents", None)
    if amount_cents is None:
        amount_cents = getattr(order, "amount_cents", 0)
    if status == "paid" and not payment_is_confirmed(
        status,
        order.payment_method,
        amount_cents,
        order.provider_transaction_id,
    ):
        return "unverified"
    return status


class PayPalError(RuntimeError):
    """Raised when PayPal cannot complete a payment operation."""


def _paypal_api_base(mode):
    return (
        "https://api-m.sandbox.paypal.com"
        if (mode or "live").lower() == "test"
        else "https://api-m.paypal.com"
    )


def _paypal_access_token(client_id, secret_key, mode):
    try:
        response = requests.post(
            f"{_paypal_api_base(mode)}/v1/oauth2/token",
            auth=(client_id, secret_key),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise PayPalError("PayPal authentication is temporarily unavailable.") from exc
    if not response.ok:
        raise PayPalError(f"PayPal authentication failed ({response.status_code}).")
    try:
        token = (response.json() or {}).get("access_token")
    except ValueError as exc:
        raise PayPalError("PayPal returned an invalid authentication response.") from exc
    if not token:
        raise PayPalError("PayPal did not return an access token.")
    return token


def _paypal_headers(credentials, request_id=None):
    token = _paypal_access_token(
        credentials["public_key"],
        credentials["secret_key"],
        credentials["mode"],
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    return headers


def create_paypal_order(
    credentials,
    amount_cents,
    description,
    custom_id,
    return_url,
    cancel_url,
    request_id,
):
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "custom_id": custom_id,
                "description": description[:127],
                "amount": {
                    "currency_code": "USD",
                    "value": f"{int(amount_cents) / 100:.2f}",
                },
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "brand_name": "TrackOps",
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "PAY_NOW",
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                }
            }
        },
    }
    try:
        response = requests.post(
            f"{_paypal_api_base(credentials['mode'])}/v2/checkout/orders",
            headers=_paypal_headers(credentials, request_id=request_id),
            json=payload,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise PayPalError("PayPal checkout is temporarily unavailable.") from exc
    if not response.ok:
        raise PayPalError(f"PayPal could not create the order ({response.status_code}).")
    try:
        order = response.json() or {}
    except ValueError as exc:
        raise PayPalError("PayPal returned an invalid order response.") from exc
    approve_url = next(
        (link.get("href") for link in order.get("links", []) if link.get("rel") in {"approve", "payer-action"}),
        None,
    )
    if not order.get("id") or not approve_url:
        raise PayPalError("PayPal did not return an approval link.")
    return order, approve_url


def capture_paypal_order(credentials, paypal_order_id, request_id):
    try:
        response = requests.post(
            f"{_paypal_api_base(credentials['mode'])}/v2/checkout/orders/{paypal_order_id}/capture",
            headers=_paypal_headers(credentials, request_id=request_id),
            json={},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise PayPalError("PayPal capture is temporarily unavailable.") from exc
    if not response.ok:
        raise PayPalError(f"PayPal could not capture the payment ({response.status_code}).")
    try:
        return response.json() or {}
    except ValueError as exc:
        raise PayPalError("PayPal returned an invalid capture response.") from exc


def verify_paypal_webhook_signature(credentials, webhook_id, headers, event):
    verification = {
        "auth_algo": headers.get("PAYPAL-AUTH-ALGO", ""),
        "cert_url": headers.get("PAYPAL-CERT-URL", ""),
        "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID", ""),
        "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG", ""),
        "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME", ""),
        "webhook_id": webhook_id,
        "webhook_event": event,
    }
    try:
        response = requests.post(
            f"{_paypal_api_base(credentials['mode'])}/v1/notifications/verify-webhook-signature",
            headers=_paypal_headers(credentials),
            json=verification,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise PayPalError("PayPal webhook verification is temporarily unavailable.") from exc
    if not response.ok:
        raise PayPalError(f"PayPal could not verify the webhook ({response.status_code}).")
    try:
        return (response.json() or {}).get("verification_status") == "SUCCESS"
    except ValueError as exc:
        raise PayPalError("PayPal returned an invalid webhook verification response.") from exc


def paypal_capture_details(paypal_order):
    purchase_units = paypal_order.get("purchase_units") or []
    captures = ((purchase_units[0].get("payments") or {}).get("captures") or []) if purchase_units else []
    capture = captures[0] if captures else {}
    amount = capture.get("amount") or {}
    return {
        "status": capture.get("status") or paypal_order.get("status"),
        "transaction_id": capture.get("id"),
        "currency": amount.get("currency_code"),
        "value": amount.get("value"),
    }


def create_stripe_checkout_session(stripe_client, order, rows, success_url, cancel_url):
    line_items = []
    for row in rows:
        item = row["item"]
        line_items.append(
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(row["unit"]),
                    "product_data": {
                        "name": f"{item.event.event_name} - {item.ticket_type.name}",
                    },
                },
                "quantity": int(item.quantity),
            }
        )

    session = stripe_client.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"order_type": "spectator", "order_id": str(order.id), "order_number": order.order_number},
    )
    return session


def create_driver_stripe_checkout_session(stripe_client, driver_ticket_order, success_url, cancel_url):
    event = driver_ticket_order.event
    session = stripe_client.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(driver_ticket_order.amount_cents or 0),
                    "product_data": {"name": f"Driver ticket - {event.event_name}"},
                },
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"order_type": "driver", "driver_ticket_order_id": str(driver_ticket_order.id)},
    )
    return session


def mark_order_paid(order, transaction_id=None):
    if (
        int(order.total_cents or 0) > 0
        and order.payment_method in ONLINE_PAYMENT_PROVIDERS
        and not transaction_id
    ):
        raise ValueError("Online spectator orders require a provider transaction ID.")
    order.payment_status = "paid"
    order.status = "recorded"
    order.paid_at = datetime.utcnow()
    if transaction_id:
        order.provider_transaction_id = transaction_id


def mark_driver_ticket_paid(driver_ticket_order, transaction_id=None):
    if (
        int(driver_ticket_order.amount_cents or 0) > 0
        and driver_ticket_order.payment_method in ONLINE_PAYMENT_PROVIDERS
        and not transaction_id
    ):
        raise ValueError("Online driver orders require a provider transaction ID.")
    driver_ticket_order.payment_status = "paid"
    driver_ticket_order.status = "recorded"
    driver_ticket_order.paid_at = datetime.utcnow()
    if transaction_id:
        driver_ticket_order.provider_transaction_id = transaction_id
