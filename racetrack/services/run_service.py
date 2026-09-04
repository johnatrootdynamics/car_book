from datetime import datetime, timedelta

from ..models import TrackCarStatus, TrackRun, TrackRunParticipant, db


AUTO_EXIT_SECONDS = 20


def expire_stale_track_states(track_id, timeout_seconds=AUTO_EXIT_SECONDS):
    """Apply the temporary no-exit-scanner timeout and close completed runs."""
    timeout_at = datetime.utcnow() - timedelta(seconds=timeout_seconds)
    expired_states = TrackCarStatus.query.filter(
        TrackCarStatus.track_id == track_id,
        TrackCarStatus.is_on_track.is_(True),
        TrackCarStatus.changed_at < timeout_at,
    ).all()
    if not expired_states:
        return 0

    affected_runs = {}
    for state in expired_states:
        state.is_on_track = False
        exited_at = state.changed_at + timedelta(seconds=timeout_seconds)
        active_run = (
            TrackRun.query.join(TrackRunParticipant)
            .filter(
                TrackRun.track_id == track_id,
                TrackRun.status == "active",
                TrackRunParticipant.car_id == state.car_id,
            )
            .first()
        )
        if not active_run:
            continue

        previous = affected_runs.get(active_run.id)
        affected_runs[active_run.id] = (
            active_run,
            max(previous[1], exited_at) if previous else exited_at,
        )
        participant = TrackRunParticipant.query.filter_by(
            run_id=active_run.id,
            car_id=state.car_id,
        ).first()
        if participant and not participant.exited_at:
            participant.exited_at = exited_at

    db.session.flush()
    for active_run, timeout_end in affected_runs.values():
        remaining = TrackCarStatus.query.filter_by(
            track_id=track_id,
            event_id=active_run.event_id,
            is_on_track=True,
            is_eligible=True,
        ).count()
        if remaining == 0:
            active_run.status = "completed"
            active_run.ended_at = timeout_end

    db.session.commit()
    return len(expired_states)
