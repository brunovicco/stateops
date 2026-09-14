"""Checkpoint serialization security and type-invariant tests."""

from dataclasses import dataclass
from datetime import UTC, datetime

from stateops.adapters.persistence.checkpointer import redis_checkpoint_serializer
from stateops.domain.enums import ActionKind, IncidentPhase, Severity
from stateops.domain.models import IncidentRecord, RemediationAction, TimelineEvent


@dataclass(frozen=True, slots=True)
class UnallowlistedValue:
    value: str


def test_redis_serializer_restores_allowlisted_domain_invariants() -> None:
    serializer = redis_checkpoint_serializer()
    stored = {
        "incident": IncidentRecord(
            "checkout", 0.2, 18.0, "v2.31", datetime(2026, 9, 14, tzinfo=UTC)
        ),
        "action": RemediationAction(
            "rollback",
            ActionKind.ROLLBACK_DEPLOYMENT,
            (("service", "checkout"),),
            Severity.HIGH,
        ),
        "event": TimelineEvent(
            "event-1",
            "approval.requested",
            IncidentPhase.WAITING_APPROVAL,
            datetime(2026, 9, 14, tzinfo=UTC),
        ),
    }

    restored = serializer.loads_typed(serializer.dumps_typed(stored))

    assert isinstance(restored["incident"].started_at, datetime)
    assert restored["action"].kind is ActionKind.ROLLBACK_DEPLOYMENT
    assert restored["action"].parameters == (("service", "checkout"),)
    assert restored["event"].phase is IncidentPhase.WAITING_APPROVAL
    assert isinstance(restored["event"].occurred_at, datetime)


def test_redis_serializer_does_not_construct_unallowlisted_dataclass() -> None:
    serializer = redis_checkpoint_serializer()

    restored = serializer.loads_typed(serializer.dumps_typed(UnallowlistedValue("blocked")))

    assert not isinstance(restored, UnallowlistedValue)
