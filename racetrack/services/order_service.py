from ..models import (
    DriverTicketOrder,
    Event,
    PrivateRentalBooking,
    PrivateRentalSlot,
    SpectatorOrder,
    SpectatorOrderItem,
)
from .payment_service import effective_payment_status


def format_money(cents):
    return f"${(cents or 0) / 100:,.2f}"


def load_order_rows(track_id=None):
    spectator_query = SpectatorOrder.query
    if track_id is not None:
        spectator_query = (
            spectator_query.join(
                SpectatorOrderItem,
                SpectatorOrderItem.order_id == SpectatorOrder.id,
            )
            .join(Event, Event.id == SpectatorOrderItem.event_id)
            .filter(Event.track_id == track_id)
            .distinct()
        )

    driver_query = DriverTicketOrder.query.join(Event, Event.id == DriverTicketOrder.event_id)
    if track_id is not None:
        driver_query = driver_query.filter(Event.track_id == track_id)

    rental_query = PrivateRentalBooking.query.join(
        PrivateRentalSlot,
        PrivateRentalSlot.id == PrivateRentalBooking.slot_id,
    )
    if track_id is not None:
        rental_query = rental_query.filter(PrivateRentalSlot.track_id == track_id)

    rows = []
    for order in spectator_query.all():
        items = [
            item
            for item in order.items
            if track_id is None or item.event.track_id == track_id
        ]
        if not items:
            continue
        track = items[0].event.track
        event_names = sorted({item.event.event_name for item in items})
        ticket_categories = {item.ticket_category or "spectator" for item in items}
        if ticket_categories == {"vendor"}:
            order_kind_label = "Vendor"
        elif "vendor" in ticket_categories:
            order_kind_label = "Mixed tickets"
        else:
            order_kind_label = "Spectator"
        buyer_name = order.guest_full_name or (
            f"{order.buyer.first_name} {order.buyer.last_name}" if order.buyer else "Guest"
        )
        buyer_email = order.guest_email or (order.buyer.email if order.buyer else "")
        if order.vendor:
            buyer_name = order.vendor.full_name
            buyer_email = order.vendor.email
        rows.append(
            {
                "kind": "spectator",
                "kind_label": order_kind_label,
                "id": order.id,
                "number": order.order_number,
                "track": track,
                "track_id": track.id,
                "event_names": event_names,
                "buyer_name": buyer_name,
                "buyer_email": buyer_email,
                "vendor_business_name": (
                    order.vendor.business_name if order.vendor else (order.vendor_business_name or "")
                ),
                "ticket_categories": ticket_categories,
                "amount_cents": (
                    order.total_cents or 0
                    if track_id is None
                    else sum(item.line_total_cents or 0 for item in items)
                ),
                "provider": order.payment_method or "other",
                "mode": order.payment_mode or "live",
                "payment_status": effective_payment_status(order),
                "transaction_id": order.provider_transaction_id,
                "created_at": order.created_at,
                "paid_at": order.paid_at,
                "order": order,
            }
        )

    for order in driver_query.all():
        buyer = order.buyer
        rows.append(
            {
                "kind": "driver",
                "kind_label": "Driver",
                "id": order.id,
                "number": f"DR-{order.id:06d}",
                "track": order.event.track,
                "track_id": order.event.track_id,
                "event_names": [order.event.event_name],
                "buyer_name": (
                    f"{buyer.first_name} {buyer.last_name}".strip() if buyer else "Unknown driver"
                ),
                "buyer_email": buyer.email if buyer else "",
                "amount_cents": order.amount_cents or 0,
                "provider": order.payment_method or "other",
                "mode": order.payment_mode or "live",
                "payment_status": effective_payment_status(order),
                "transaction_id": order.provider_transaction_id,
                "created_at": order.created_at,
                "paid_at": order.paid_at,
                "order": order,
            }
        )

    for booking in rental_query.all():
        buyer = booking.buyer
        slot = booking.slot
        rows.append(
            {
                "kind": "rental",
                "kind_label": "Private rental",
                "id": booking.id,
                "number": f"PR-{booking.id:06d}",
                "track": slot.track,
                "track_id": slot.track_id,
                "event_names": [
                    f"{slot.name} · {slot.slot_date.strftime('%b %-d, %Y')}"
                ],
                "buyer_name": (
                    f"{buyer.first_name} {buyer.last_name}".strip()
                    if buyer
                    else "Unknown driver"
                ),
                "buyer_email": buyer.email if buyer else "",
                "amount_cents": booking.amount_cents or 0,
                "provider": booking.payment_method or "other",
                "mode": booking.payment_mode or "live",
                "payment_status": effective_payment_status(booking),
                "transaction_id": booking.provider_transaction_id,
                "created_at": booking.created_at,
                "paid_at": booking.paid_at,
                "order": booking,
            }
        )

    return sorted(rows, key=lambda row: (row["created_at"], row["kind"], row["id"]), reverse=True)


def filter_order_rows(rows, search="", payment_status="", kind="", provider="", track_id=None):
    search = (search or "").strip().lower()
    payment_status = (payment_status or "").strip().lower()
    kind = (kind or "").strip().lower()
    provider = (provider or "").strip().lower()
    filtered = []
    for row in rows:
        if track_id and row["track_id"] != track_id:
            continue
        if payment_status and row["payment_status"] != payment_status:
            continue
        if kind and row["kind"] != kind:
            continue
        if provider and row["provider"] != provider:
            continue
        if search:
            haystack = " ".join(
                [
                    row["number"],
                    row["track"].name,
                    row["buyer_name"],
                    row["buyer_email"],
                    row["provider"],
                    row.get("vendor_business_name", ""),
                    *row["event_names"],
                ]
            ).lower()
            if search not in haystack:
                continue
        filtered.append(row)
    return filtered


def summarize_orders(rows):
    return {
        "count": len(rows),
        "paid": sum(1 for row in rows if row["payment_status"] == "paid"),
        "pending": sum(1 for row in rows if row["payment_status"] == "pending"),
        "failed": sum(
            1
            for row in rows
            if row["payment_status"] in {"failed", "canceled", "cancelled", "unverified"}
        ),
        "paid_cents": sum(
            row["amount_cents"] for row in rows if row["payment_status"] == "paid"
        ),
    }
