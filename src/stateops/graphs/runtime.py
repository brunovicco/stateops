"""LangGraph-backed implementation of durable incident operations."""

from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Any, cast

from langgraph.types import Command

from stateops.application.runtime_models import CheckpointView, RunResult
from stateops.domain.enums import IncidentPhase
from stateops.domain.models import IncidentRecord, RemediationAction
from stateops.graphs.state import IncidentState, initial_incident_state


def _config(incident_id: str, checkpoint_id: str | None = None) -> dict[str, object]:
    configurable: dict[str, str] = {"thread_id": incident_id}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def _as_mapping(values: object) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise RuntimeError("LangGraph returned a non-mapping incident state")
    return cast(Mapping[str, object], values)


def _deepest_values(snapshot: Any) -> Mapping[str, object]:
    """Return active subgraph state when a per-invocation subgraph is paused."""
    for task in snapshot.tasks:
        nested = task.state
        if nested is not None and hasattr(nested, "values"):
            return _deepest_values(nested)
    return _as_mapping(snapshot.values)


class GraphIncidentRuntime:
    """Drive graph runs, checkpoints, replay, and controlled forks."""

    def __init__(self, graph: Any) -> None:
        """Wrap one compiled graph whose checkpointer owns durability."""
        self._graph = graph

    async def _run(self, graph_input: object, config: Mapping[str, object]) -> RunResult:
        stream = await self._graph.astream_events(graph_input, config=config, version="v3")
        await stream.output()
        interrupted = await stream.interrupted()
        interrupts = tuple(item.value for item in await stream.interrupts())
        values = await self._latest(config)
        return RunResult(values=values, interrupted=interrupted, interrupts=interrupts)

    async def _latest(self, config: Mapping[str, object]) -> Mapping[str, object]:
        snapshot = await self._graph.aget_state(config, subgraphs=True)
        return _deepest_values(snapshot)

    async def start(self, incident_id: str, incident: IncidentRecord) -> RunResult:
        """Start a thread whose stable thread ID equals the incident ID."""
        return await self._run(initial_incident_state(incident_id, incident), _config(incident_id))

    async def resume(self, incident_id: str, approval: Mapping[str, object]) -> RunResult:
        """Resume the latest interrupt on the same incident thread."""
        return await self._run(Command(resume=dict(approval)), _config(incident_id))

    async def state(self, incident_id: str) -> Mapping[str, object]:
        """Return the current persisted state."""
        return await self._latest(_config(incident_id))

    async def _checkpoint(self, incident_id: str, checkpoint_id: str) -> Any:
        async for snapshot in self._graph.aget_state_history(_config(incident_id)):
            current = snapshot.config.get("configurable", {}).get("checkpoint_id")
            if current == checkpoint_id:
                return snapshot
        raise KeyError(f"checkpoint not found: {checkpoint_id}")

    async def history(self, incident_id: str) -> tuple[CheckpointView, ...]:
        """Return metadata only; never expose full checkpoint payloads."""
        views: list[CheckpointView] = []
        async for snapshot in self._graph.aget_state_history(_config(incident_id)):
            values = _as_mapping(snapshot.values)
            phase = values.get("phase", "unknown")
            phase_value = phase.value if isinstance(phase, IncidentPhase) else str(phase)
            configurable = snapshot.config.get("configurable", {})
            checkpoint_id = str(configurable.get("checkpoint_id", ""))
            metadata = snapshot.metadata
            raw_created_at = snapshot.created_at
            created_at = (
                datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
                if isinstance(raw_created_at, str)
                else None
            )
            source = metadata.get("source")
            step = metadata.get("step")
            views.append(
                CheckpointView(
                    checkpoint_id=checkpoint_id,
                    phase=phase_value,
                    next_nodes=tuple(snapshot.next),
                    created_at=created_at,
                    source=source if isinstance(source, str) else None,
                    step=step if isinstance(step, int) else None,
                )
            )
        return tuple(views)

    async def replay(self, incident_id: str, checkpoint_id: str) -> RunResult:
        """Replay after a prior checkpoint; downstream nodes execute again."""
        snapshot = await self._checkpoint(incident_id, checkpoint_id)
        return await self._run(None, snapshot.config)

    async def fork(
        self, incident_id: str, checkpoint_id: str, selected_action_id: str
    ) -> RunResult:
        """Fork by changing only selection to an existing remediation candidate."""
        snapshot = await self._checkpoint(incident_id, checkpoint_id)
        values = _as_mapping(snapshot.values)
        raw_actions = values.get("candidate_actions", [])
        if not isinstance(raw_actions, list):
            raise ValueError("checkpoint has no remediation candidates")
        actions = [item for item in raw_actions if isinstance(item, RemediationAction)]
        selected = next((item for item in actions if item.id == selected_action_id), None)
        if selected is None:
            raise ValueError("selected action is not a candidate in that checkpoint")
        fork_config = await self._graph.aupdate_state(
            snapshot.config,
            IncidentState(
                phase=IncidentPhase.EVIDENCE_READY,
                preferred_action_id=selected.id,
                selected_action=None,
                approval=None,
                execution_result=None,
                verification_result=None,
            ),
            as_node="investigation",
        )
        return await self._run(None, fork_config)

    async def stream_values(
        self, incident_id: str, incident: IncidentRecord
    ) -> AsyncIterator[Mapping[str, object]]:
        """Yield v3 value snapshots while driving a new run to completion or interrupt."""
        stream = await self._graph.astream_events(
            initial_incident_state(incident_id, incident),
            config=_config(incident_id),
            version="v3",
        )
        async for value in stream.values:
            yield _as_mapping(value)
        await stream.output()
