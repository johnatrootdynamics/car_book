from calendar import Calendar
from datetime import date, datetime, timedelta

from ..models import Event, PrivateRentalBooking, PrivateRentalSlot


BOOKING_HOLD_MINUTES = 35


def rental_month_context(raw_month=None, today=None):
    today = today or date.today()
    first = today.replace(day=1)
    if raw_month:
        try:
            first = datetime.strptime(raw_month, "%Y-%m").date().replace(day=1)
        except (TypeError, ValueError):
            pass
    previous_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return {
        "first": first,
        "weeks": Calendar(firstweekday=6).monthdatescalendar(first.year, first.month),
        "label": first.strftime("%B %Y"),
        "month_value": first.strftime("%Y-%m"),
        "previous_value": previous_month.strftime("%Y-%m"),
        "next_value": next_month.strftime("%Y-%m"),
        "range_start": first - timedelta(days=7),
        "range_end": next_month + timedelta(days=7),
    }


def booking_is_active(booking, now=None):
    now = now or datetime.utcnow()
    if booking.status == "confirmed" and booking.payment_status == "paid":
        return True
    return (
        booking.status == "pending"
        and booking.payment_status == "pending"
        and booking.expires_at is not None
        and booking.expires_at > now
    )


def active_bookings_by_slot(slot_ids, now=None):
    if not slot_ids:
        return {}
    now = now or datetime.utcnow()
    bookings = (
        PrivateRentalBooking.query.filter(
            PrivateRentalBooking.slot_id.in_(slot_ids),
            PrivateRentalBooking.status.in_(("pending", "confirmed")),
        )
        .order_by(PrivateRentalBooking.created_at.desc())
        .all()
    )
    result = {}
    for booking in bookings:
        if booking.slot_id not in result and booking_is_active(booking, now=now):
            result[booking.slot_id] = booking
    return result


def slot_conflicts_with_event(track_id, slot_date, start_time, end_time, exclude_event_id=None):
    query = Event.query.filter(Event.track_id == track_id, Event.event_date == slot_date)
    if exclude_event_id:
        query = query.filter(Event.id != exclude_event_id)
    for event in query.all():
        if not event.event_start_time or not event.event_end_time:
            return event
        if event.event_start_time < end_time and event.event_end_time > start_time:
            return event
    return None


def slot_conflicts_with_slot(
    track_id,
    slot_date,
    start_time,
    end_time,
    exclude_slot_id=None,
):
    query = PrivateRentalSlot.query.filter(
        PrivateRentalSlot.track_id == track_id,
        PrivateRentalSlot.slot_date == slot_date,
        PrivateRentalSlot.is_active.is_(True),
        PrivateRentalSlot.start_time < end_time,
        PrivateRentalSlot.end_time > start_time,
    )
    if exclude_slot_id:
        query = query.filter(PrivateRentalSlot.id != exclude_slot_id)
    return query.order_by(PrivateRentalSlot.start_time.asc()).first()


def event_conflicts_with_rental_slot(
    track_id,
    event_date,
    start_time=None,
    end_time=None,
    exclude_slot_id=None,
):
    query = PrivateRentalSlot.query.filter(
        PrivateRentalSlot.track_id == track_id,
        PrivateRentalSlot.slot_date == event_date,
        PrivateRentalSlot.is_active.is_(True),
    )
    if exclude_slot_id:
        query = query.filter(PrivateRentalSlot.id != exclude_slot_id)
    if start_time and end_time:
        query = query.filter(
            PrivateRentalSlot.start_time < end_time,
            PrivateRentalSlot.end_time > start_time,
        )
    return query.order_by(PrivateRentalSlot.start_time.asc()).first()
