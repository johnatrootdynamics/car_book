from ..models import DriverTicketOrder, Event, SpectatorOrder, SpectatorOrderItem
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
        buyer_name = order.guest_full_name or (
            f"{order.buyer.first_name} {order.buyer.last_name}" if order.buyer else "Guest"
        )
        buyer_email = order.guest_email or (order.buyer.email if order.buyer else "")
        rows.append(
            {
                "kind": "spectator",
                "kind_label": "Spectator",
                "id": order.id,
                "number": order.order_number,
                "track": track,
                "track_id": track.id,
                "event_names": event_names,
                "buyer_name": buyer_name,
                "buyer_email": buyer_email,
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
