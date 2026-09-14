"""Provider-neutral incident-reasoning capability."""

from typing import Protocol

from stateops.domain.models import (
    Evidence,
    Hypothesis,
    IncidentContext,
    IncidentRecord,
    RemediationAction,
    RootCause,
)


class IncidentReasoner(Protocol):
    """Reason about incidents without exposing model or provider selection."""

    async def generate_hypotheses(
        self, incident: IncidentRecord, context: IncidentContext
    ) -> tuple[Hypothesis, ...]:
        """Generate a variable-length set of candidate causes."""
        ...

    async def investigate(
        self, incident: IncidentRecord, context: IncidentContext, hypothesis: Hypothesis
    ) -> Evidence:
        """Investigate one hypothesis independently."""
        ...

    async def synthesize(
        self, hypotheses: tuple[Hypothesis, ...], evidence: tuple[Evidence, ...]
    ) -> RootCause:
        """Choose the best-supported root cause."""
        ...

    async def propose_remediations(
        self, incident: IncidentRecord, root_cause: RootCause
    ) -> tuple[RemediationAction, ...]:
        """Return allowlisted remediation candidates."""
        ...
