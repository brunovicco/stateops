"""Metadata-only timeline event construction."""

from stateops.application.ports.clock import Clock
from stateops.domain.enums import IncidentPhase
from stateops.domain.models import TimelineEvent


def timeline_event(
    clock: Clock,
    *,
    incident_id: str,
    phase: IncidentPhase,
    event: str,
    discriminator: str = "0",
) -> TimelineEvent:
    """Create a deterministic identity while retaining the real event timestamp."""
    return TimelineEvent(
        id=f"{incident_id}:{event}:{discriminator}",
        event=event,
        phase=phase,
        occurred_at=clock.now(),
    )
