"""Idempotent, non-production remediation simulation."""

import asyncio

from stateops.application.ports.clock import Clock
from stateops.domain.enums import ActionKind, ExecutionStatus
from stateops.domain.models import ExecutionResult, RemediationAction


class SimulatedRemediationExecutor:
    """Execute allowlisted actions once per idempotency key in the current process."""

    def __init__(self, clock: Clock) -> None:
        """Initialize an isolated result ledger."""
        self._clock = clock
        self._results: dict[str, ExecutionResult] = {}
        self._lock = asyncio.Lock()
        self.execution_count = 0

    async def execute(
        self, *, incident_id: str, action: RemediationAction, idempotency_key: str
    ) -> ExecutionResult:
        """Return the prior result on duplicate execution instead of repeating the effect."""
        del incident_id
        async with self._lock:
            existing = self._results.get(idempotency_key)
            if existing is not None:
                return ExecutionResult(
                    action_id=existing.action_id,
                    idempotency_key=existing.idempotency_key,
                    started_at=existing.started_at,
                    completed_at=existing.completed_at,
                    status=existing.status,
                    synthetic_effect=existing.synthetic_effect,
                    duplicate=True,
                )
            started_at = self._clock.now()
            completed_at = self._clock.now()
            result = ExecutionResult(
                action_id=action.id,
                idempotency_key=idempotency_key,
                started_at=started_at,
                completed_at=completed_at,
                status=ExecutionStatus.SUCCEEDED,
                synthetic_effect=f"simulated:{ActionKind(action.kind).value}",
            )
            self._results[idempotency_key] = result
            self.execution_count += 1
            return result
