"""Domain lifecycle and deterministic reducer tests."""

from datetime import UTC, datetime, timedelta

import pytest

from stateops.domain.enums import ActionKind, IncidentPhase, Severity
from stateops.domain.models import (
    Evidence,
    Hypothesis,
    RemediationAction,
    TimelineEvent,
    WorkflowError,
)
from stateops.domain.reducers import (
    merge_actions,
    merge_errors,
    merge_evidence,
    merge_hypotheses,
    merge_timeline,
)
from stateops.domain.transitions import InvalidTransitionError, can_transition, transition


def test_lifecycle_accepts_declared_transition_and_rejects_shortcut() -> None:
    assert transition(IncidentPhase.RECEIVED, IncidentPhase.ENRICHING) is IncidentPhase.ENRICHING
    assert can_transition(IncidentPhase.VERIFYING, IncidentPhase.RESOLVED)
    assert not can_transition(IncidentPhase.RECEIVED, IncidentPhase.RESOLVED)
    with pytest.raises(InvalidTransitionError, match="invalid incident transition"):
        transition(IncidentPhase.RECEIVED, IncidentPhase.RESOLVED)


def test_parallel_reducers_are_deterministic_and_last_update_wins_by_identity() -> None:
    old = Hypothesis("b", "old", "old", 0.1)
    replacement = Hypothesis("b", "new", "new", 0.9)
    first = Hypothesis("a", "first", "first", 0.5)
    assert merge_hypotheses([old], [replacement, first]) == [first, replacement]

    evidence_b = Evidence("b", "b", "logs", "second", False)
    evidence_a = Evidence("a", "a", "metrics", "first", True)
    assert merge_evidence([evidence_b], [evidence_a]) == [evidence_a, evidence_b]

    action_v1 = RemediationAction("action", ActionKind.RESTART_SERVICE, (), Severity.LOW)
    action_v2 = RemediationAction(
        "action", ActionKind.RESTART_SERVICE, (), Severity.MEDIUM, revision=2
    )
    assert merge_actions([], [action_v2, action_v1]) == [action_v1, action_v2]

    error = WorkflowError("err", "gateway", "reason", True)
    assert merge_errors([error], [error]) == [error]


def test_timeline_reducer_deduplicates_and_sorts_by_time() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    later = TimelineEvent("later", "later", IncidentPhase.CLASSIFIED, now + timedelta(seconds=1))
    earlier = TimelineEvent("earlier", "earlier", IncidentPhase.RECEIVED, now)
    replacement = TimelineEvent("earlier", "updated", IncidentPhase.ENRICHING, now)
    assert merge_timeline([later, earlier], [replacement]) == [replacement, later]
