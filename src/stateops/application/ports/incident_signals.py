"""Operational-signal capability."""

from typing import Protocol

from stateops.domain.models import (
    IncidentContext,
    IncidentRecord,
    RemediationAction,
    VerificationResult,
)


class IncidentSignals(Protocol):
    """Read incident context and verify a simulated remediation."""

    async def enrich(self, incident: IncidentRecord) -> IncidentContext:
        """Return bounded operational context for an incident."""
        ...

    async def verify(
        self, incident: IncidentRecord, action: RemediationAction
    ) -> VerificationResult:
        """Return post-remediation synthetic metrics."""
        ...
