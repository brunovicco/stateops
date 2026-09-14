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


class IncidentReasoningError(RuntimeError):
    """Metadata-safe failure raised by an incident-reasoning implementation."""

    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        """Retain only stable failure metadata that is safe to checkpoint."""
        super().__init__(message)
        self.code = code
        self.retryable = retryable


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
