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
        metadata={"order_id": str(order.id), "order_number": order.order_number},
    )
    return session


def mark_order_paid(order, transaction_id=None):
    order.payment_status = "paid"
    order.status = "recorded"
    order.paid_at = datetime.utcnow()
    if transaction_id:
        order.provider_transaction_id = transaction_id
