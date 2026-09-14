"""Explicit serializable state schema for the incident graph."""

from typing import Annotated, TypedDict

from stateops.domain.enums import IncidentPhase, Severity
from stateops.domain.models import (
    ApprovalDecision,
    Evidence,
    ExecutionResult,
    Hypothesis,
    IncidentContext,
    IncidentRecord,
    RemediationAction,
    RootCause,
    TimelineEvent,
    VerificationResult,
    WorkflowError,
)
from stateops.domain.reducers import (
    merge_actions,
    merge_errors,
    merge_evidence,
    merge_hypotheses,
    merge_timeline,
)


class IncidentState(TypedDict, total=False):
    """Checkpointed state channels for one incident thread."""

    incident_id: str
    phase: IncidentPhase
    severity: Severity
    incident: IncidentRecord
    context: IncidentContext
    hypotheses: Annotated[list[Hypothesis], merge_hypotheses]
    evidence: Annotated[list[Evidence], merge_evidence]
    root_cause: RootCause
    candidate_actions: Annotated[list[RemediationAction], merge_actions]
    preferred_action_id: str | None
    selected_action: RemediationAction | None
    approval: ApprovalDecision | None
    execution_result: ExecutionResult | None
    verification_result: VerificationResult | None
    attempts: int
    errors: Annotated[list[WorkflowError], merge_errors]
    timeline: Annotated[list[TimelineEvent], merge_timeline]


def initial_incident_state(incident_id: str, incident: IncidentRecord) -> IncidentState:
    """Create a complete initial snapshot with explicit reducer identities."""
    return IncidentState(
        incident_id=incident_id,
        phase=IncidentPhase.RECEIVED,
        severity=Severity.LOW,
        incident=incident,
        hypotheses=[],
        evidence=[],
        candidate_actions=[],
        preferred_action_id=None,
        selected_action=None,
        approval=None,
        execution_result=None,
        verification_result=None,
        attempts=0,
        errors=[],
        timeline=[],
    )
