from datetime import datetime, timedelta

from sqlalchemy import func, or_

from ..models import (
    DriverTicketOrder,
    Event,
    EventRegistration,
    SpectatorOrder,
    SpectatorOrderItem,
    SpectatorTicketOrder,
    db,
)


CAPACITY_FIELDS = {
    "driver": "driver_capacity",
    "spectator": "spectator_capacity",
    "vendor": "vendor_capacity",
}
RESERVATION_MINUTES = 35


def reservation_cutoff():
    return datetime.utcnow() - timedelta(minutes=RESERVATION_MINUTES)


def reservation_is_active(order):
    return bool(order.created_at and order.created_at >= reservation_cutoff())


def normalized_ticket_category(category):
    return category if category in CAPACITY_FIELDS else "spectator"


def ticket_capacity(event, category):
    field_name = CAPACITY_FIELDS[normalized_ticket_category(category)]
    return max(0, int(getattr(event, field_name, 0) or 0))


def tickets_sold(event_id, category):
    category = normalized_ticket_category(category)
    if category == "driver":
        paid_order_exists = db.session.query(DriverTicketOrder.id).filter(
            DriverTicketOrder.event_id == EventRegistration.event_id,
            DriverTicketOrder.user_id == EventRegistration.user_id,
            DriverTicketOrder.payment_status == "paid",
        ).exists()
        return (
            EventRegistration.query.join(Event, Event.id == EventRegistration.event_id)
            .filter(
                EventRegistration.event_id == event_id,
                or_(Event.event_type == "private", paid_order_exists),
            )
            .count()
        )
    total = (
        db.session.query(func.coalesce(func.sum(SpectatorTicketOrder.quantity), 0))
        .filter(
            SpectatorTicketOrder.event_id == event_id,
            SpectatorTicketOrder.ticket_category == category,
        )
        .scalar()
    )
    return int(total or 0)


def tickets_held(event_id, category):
    # Starting an external checkout never reserves inventory. Capacity is claimed
    # only when payment is confirmed and the ticket/registration is issued.
    return 0


def ticket_availability(event, category):
    category = normalized_ticket_category(category)
    capacity = ticket_capacity(event, category)
    sold = tickets_sold(event.id, category)
    held = tickets_held(event.id, category)
    unlimited = capacity == 0
    remaining = None if unlimited else max(0, capacity - sold - held)
    return {
        "category": category,
        "capacity": capacity,
        "sold": sold,
        "held": held,
        "remaining": remaining,
        "unlimited": unlimited,
        "sold_out": not unlimited and remaining == 0,
    }


def driver_already_has_ticket(event_id, user_id):
    return (
        DriverTicketOrder.query.filter_by(
            event_id=event_id,
            user_id=user_id,
            payment_status="paid",
        ).first()
        is not None
    )


def driver_payment_in_progress(event_id, user_id):
    # Pending provider sessions are intentionally non-blocking. A driver can
    # restart checkout after navigating away from PayPal or Stripe.
    return False


def spectator_order_fits_capacity(order):
    requested = {}
    for item in order.items:
        category = normalized_ticket_category(item.ticket_category)
        key = (item.event_id, category)
        requested[key] = requested.get(key, 0) + int(item.quantity or 0)
    for (event_id, category), quantity in requested.items():
        event = next((item.event for item in order.items if item.event_id == event_id), None)
        if event is None:
            return False
        availability = ticket_availability(event, category)
        if not availability["unlimited"] and quantity > availability["remaining"]:
            return False
    return True


def driver_order_fits_capacity(order):
    if DriverTicketOrder.query.filter(
        DriverTicketOrder.event_id == order.event_id,
        DriverTicketOrder.user_id == order.user_id,
        DriverTicketOrder.payment_status == "paid",
        DriverTicketOrder.id != order.id,
    ).first():
        return False
    availability = ticket_availability(order.event, "driver")
    return availability["unlimited"] or availability["remaining"] >= 1
