"""Side-effect capability owned by the application, not the LLM gateway."""

from typing import Protocol

from stateops.domain.models import ExecutionResult, RemediationAction


class RemediationExecutor(Protocol):
    """Execute one bounded remediation idempotently."""

    async def execute(
        self, *, incident_id: str, action: RemediationAction, idempotency_key: str
    ) -> ExecutionResult:
        """Apply or replay the result for one idempotency key."""
        ...
