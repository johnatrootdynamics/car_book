from datetime import datetime


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
    order.payment_status = "paid"
    order.status = "recorded"
    order.paid_at = datetime.utcnow()
    if transaction_id:
        order.provider_transaction_id = transaction_id


def mark_driver_ticket_paid(driver_ticket_order, transaction_id=None):
    driver_ticket_order.payment_status = "paid"
    driver_ticket_order.status = "recorded"
    driver_ticket_order.paid_at = datetime.utcnow()
    if transaction_id:
        driver_ticket_order.provider_transaction_id = transaction_id
