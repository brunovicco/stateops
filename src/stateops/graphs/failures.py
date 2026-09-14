"""Translate reasoning failures into durable metadata-only graph state."""

from stateops.application.ports.clock import Clock
from stateops.application.ports.reasoner import IncidentReasoningError
from stateops.domain.enums import IncidentPhase
from stateops.domain.models import WorkflowError
from stateops.domain.transitions import transition
from stateops.graphs.events import timeline_event
from stateops.graphs.state import IncidentState


def reasoning_error(
    *,
    incident_id: str,
    node: str,
    error: IncidentReasoningError,
    discriminator: str = "0",
) -> WorkflowError:
    """Build a stable serializable error without persisting an exception object."""
    return WorkflowError(
        id=f"{incident_id}:reasoning.failed:{node}:{discriminator}:{error.code}",
        category=error.code,
        node=node,
        retryable=error.retryable,
    )


def failed_reasoning_state(
    clock: Clock,
    state: IncidentState,
    *,
    node: str,
    error: IncidentReasoningError,
    discriminator: str = "0",
) -> IncidentState:
    """Terminate a reasoning step as explicit failed state."""
    phase = transition(state["phase"], IncidentPhase.FAILED)
    return IncidentState(
        phase=phase,
        errors=[
            reasoning_error(
                incident_id=state["incident_id"],
                node=node,
                error=error,
                discriminator=discriminator,
            )
        ],
        timeline=[
            timeline_event(
                clock,
                incident_id=state["incident_id"],
                phase=phase,
                event="reasoning.failed",
                discriminator=f"{node}:{discriminator}:{error.code}",
            )
        ],
    )


def failed_state_from_branch_errors(clock: Clock, state: IncidentState) -> IncidentState:
    """Terminate after parallel investigation when any branch recorded an error."""
    phase = transition(state["phase"], IncidentPhase.FAILED)
    return IncidentState(
        phase=phase,
        timeline=[
            timeline_event(
                clock,
                incident_id=state["incident_id"],
                phase=phase,
                event="reasoning.failed",
                discriminator="investigation-branches",
            )
        ],
    )
