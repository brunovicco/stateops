"""Durable incident runtime capability."""

from collections.abc import AsyncIterator, Mapping
from typing import Protocol

from stateops.application.runtime_models import CheckpointView, RunResult
from stateops.domain.models import IncidentRecord


class IncidentRuntime(Protocol):
    """Operate checkpointed incident threads without exposing LangGraph types."""

    async def start(self, incident_id: str, incident: IncidentRecord) -> RunResult:
        """Start one new incident thread."""
        ...

    async def resume(self, incident_id: str, approval: Mapping[str, object]) -> RunResult:
        """Resume one interrupted incident with a human decision."""
        ...

    async def state(self, incident_id: str) -> Mapping[str, object]:
        """Read the latest checkpoint values."""
        ...

    async def history(self, incident_id: str) -> tuple[CheckpointView, ...]:
        """Read sanitized checkpoint history."""
        ...

    async def replay(self, incident_id: str, checkpoint_id: str) -> RunResult:
        """Re-execute from a historical checkpoint."""
        ...

    async def fork(
        self, incident_id: str, checkpoint_id: str, selected_action_id: str
    ) -> RunResult:
        """Create a branch with one controlled remediation selection change."""
        ...

    def stream_values(
        self, incident_id: str, incident: IncidentRecord
    ) -> AsyncIterator[Mapping[str, object]]:
        """Stream v3 state snapshots for a new incident."""
        ...
