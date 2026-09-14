"""Explicit incident lifecycle transition policy."""

from stateops.domain.enums import IncidentPhase


class InvalidTransitionError(ValueError):
    """Raised when a node attempts an undeclared lifecycle transition."""


_ALLOWED: dict[IncidentPhase, frozenset[IncidentPhase]] = {
    IncidentPhase.RECEIVED: frozenset({IncidentPhase.ENRICHING, IncidentPhase.FAILED}),
    IncidentPhase.ENRICHING: frozenset({IncidentPhase.CLASSIFIED, IncidentPhase.FAILED}),
    IncidentPhase.CLASSIFIED: frozenset({IncidentPhase.HYPOTHESES_GENERATED, IncidentPhase.FAILED}),
    IncidentPhase.HYPOTHESES_GENERATED: frozenset(
        {IncidentPhase.INVESTIGATING, IncidentPhase.FAILED}
    ),
    IncidentPhase.INVESTIGATING: frozenset({IncidentPhase.EVIDENCE_READY, IncidentPhase.FAILED}),
    IncidentPhase.EVIDENCE_READY: frozenset({IncidentPhase.PLANNING, IncidentPhase.FAILED}),
    IncidentPhase.PLANNING: frozenset({IncidentPhase.WAITING_APPROVAL, IncidentPhase.FAILED}),
    IncidentPhase.WAITING_APPROVAL: frozenset(
        {IncidentPhase.EXECUTING, IncidentPhase.REPLANNING, IncidentPhase.FAILED}
    ),
    IncidentPhase.EXECUTING: frozenset({IncidentPhase.VERIFYING, IncidentPhase.FAILED}),
    IncidentPhase.VERIFYING: frozenset(
        {
            IncidentPhase.RESOLVED,
            IncidentPhase.REPLANNING,
            IncidentPhase.ESCALATED,
            IncidentPhase.FAILED,
        }
    ),
    IncidentPhase.REPLANNING: frozenset(
        {IncidentPhase.PLANNING, IncidentPhase.ESCALATED, IncidentPhase.FAILED}
    ),
    IncidentPhase.RESOLVED: frozenset(),
    IncidentPhase.ESCALATED: frozenset(),
    IncidentPhase.FAILED: frozenset(),
}


def transition(current: IncidentPhase | str, target: IncidentPhase) -> IncidentPhase:
    """Validate and return a lifecycle transition."""
    current_phase = IncidentPhase(current)
    if target not in _ALLOWED[current_phase]:
        raise InvalidTransitionError(f"invalid incident transition: {current_phase} -> {target}")
    return target


def can_transition(current: IncidentPhase | str, target: IncidentPhase) -> bool:
    """Return whether the transition is declared by the lifecycle policy."""
    return target in _ALLOWED[IncidentPhase(current)]
