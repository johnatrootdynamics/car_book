from ..models import TrackWaiverTemplate


def required_waiver_template_for_event(event):
    """Return the event waiver, falling back to the track selection for legacy events."""
    if event and event.waiver_template_id:
        return TrackWaiverTemplate.query.filter_by(
            id=event.waiver_template_id,
            track_id=event.track_id,
        ).first()
    if not event:
        return None
    return (
        TrackWaiverTemplate.query.filter_by(
            track_id=event.track_id,
            is_active=True,
            required_for_checkin=True,
        )
        .order_by(TrackWaiverTemplate.updated_at.desc(), TrackWaiverTemplate.id.desc())
        .first()
    )
