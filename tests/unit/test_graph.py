"""Behavior tests for durable graph execution and time travel."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from langgraph.types import Command

from stateops.adapters.incidents.synthetic_signals import SyntheticIncidentSignals
from stateops.adapters.llm.deterministic import DeterministicIncidentReasoner
from stateops.adapters.persistence.checkpointer import memory_checkpointer
from stateops.adapters.remediation.simulated_executor import SimulatedRemediationExecutor
from stateops.application.ports.reasoner import IncidentReasoningError
from stateops.application.runtime_models import RunResult
from stateops.domain.enums import IncidentPhase
from stateops.domain.models import (
    Evidence,
    ExecutionResult,
    Hypothesis,
    IncidentContext,
    IncidentRecord,
    RemediationAction,
    RootCause,
    WorkflowError,
)
from stateops.graphs.incident_graph import build_incident_graph
from stateops.graphs.remediation.graph import build_remediation_graph
from stateops.graphs.runtime import GraphIncidentRuntime
from stateops.graphs.state import IncidentState, initial_incident_state


class FakeClock:
    """Stable increasing time for graph checkpoint values."""

    def __init__(self) -> None:
        self._current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        value = self._current
        self._current += timedelta(milliseconds=1)
        return value


class FailingReasoner(DeterministicIncidentReasoner):
    """Raise a metadata-safe failure at one selected reasoning stage."""

    def __init__(self, stage: str) -> None:
        self._stage = stage

    def _raise_if_selected(self, stage: str) -> None:
        if self._stage == stage:
            raise IncidentReasoningError(
                "reasoning failed",
                code=f"{stage}_failed",
                retryable=stage == "investigate",
            )

    async def generate_hypotheses(
        self, incident: IncidentRecord, context: IncidentContext
    ) -> tuple[Hypothesis, ...]:
        self._raise_if_selected("generate")
        return await super().generate_hypotheses(incident, context)

    async def investigate(
        self, incident: IncidentRecord, context: IncidentContext, hypothesis: Hypothesis
    ) -> Evidence:
        self._raise_if_selected("investigate")
        return await super().investigate(incident, context, hypothesis)

    async def synthesize(
        self, hypotheses: tuple[Hypothesis, ...], evidence: tuple[Evidence, ...]
    ) -> RootCause:
        self._raise_if_selected("synthesize")
        return await super().synthesize(hypotheses, evidence)

    async def propose_remediations(
        self, incident: IncidentRecord, root_cause: RootCause
    ) -> tuple[RemediationAction, ...]:
        self._raise_if_selected("propose")
        return await super().propose_remediations(incident, root_cause)


def _incident() -> IncidentRecord:
    return IncidentRecord("checkout", 0.2, 18.0, "v2.31", datetime(2026, 1, 1, tzinfo=UTC))


def _runtime() -> tuple[GraphIncidentRuntime, SimulatedRemediationExecutor]:
    clock = FakeClock()
    executor = SimulatedRemediationExecutor(clock)
    graph = build_incident_graph(
        reasoner=DeterministicIncidentReasoner(),
        signals=SyntheticIncidentSignals(),
        executor=executor,
        clock=clock,
        checkpointer=memory_checkpointer(),
    )
    return GraphIncidentRuntime(graph), executor


def _approval(run: RunResult) -> dict[str, object]:
    payload = run.interrupts[0]
    assert isinstance(payload, Mapping)
    action = payload["action"]
    assert isinstance(action, Mapping)
    return {
        "decision": "approved",
        "action_id": action["id"],
        "comment": "approved in test",
    }


def test_parent_graph_fans_out_pauses_resumes_and_persists_history() -> None:
    async def scenario() -> None:
        runtime, executor = _runtime()
        paused = await runtime.start("INC-100", _incident())
        assert paused.interrupted
        assert paused.values["phase"] is IncidentPhase.WAITING_APPROVAL
        hypotheses = paused.values["hypotheses"]
        evidence = paused.values["evidence"]
        assert isinstance(hypotheses, list)
        assert isinstance(evidence, list)
        assert len(hypotheses) == 3
        assert len(evidence) == 3

        completed = await runtime.resume("INC-100", _approval(paused))
        assert not completed.interrupted
        assert completed.values["phase"] is IncidentPhase.RESOLVED
        assert executor.execution_count == 1
        assert (await runtime.state("INC-100"))["phase"] is IncidentPhase.RESOLVED

        history = await runtime.history("INC-100")
        assert history[0].phase == IncidentPhase.RESOLVED.value
        before_verification = next(item for item in history if item.next_nodes == ("verification",))
        replayed = await runtime.replay("INC-100", before_verification.checkpoint_id)
        assert replayed.values["phase"] is IncidentPhase.RESOLVED
        assert executor.execution_count == 1

    asyncio.run(scenario())


def test_value_stream_ends_with_the_persisted_interrupt_state() -> None:
    async def scenario() -> None:
        runtime, _ = _runtime()

        snapshots = [
            snapshot async for snapshot in runtime.stream_values("INC-STREAM", _incident())
        ]

        assert snapshots
        assert snapshots[-1]["phase"] is IncidentPhase.WAITING_APPROVAL
        evidence = snapshots[-1]["evidence"]
        assert isinstance(evidence, list)
        assert len(evidence) == 3
        assert snapshots[-1]["selected_action"] is not None

    asyncio.run(scenario())


def test_fork_selects_a_controlled_alternative_without_erasing_original_history() -> None:
    async def scenario() -> None:
        runtime, executor = _runtime()
        paused = await runtime.start("INC-200", _incident())
        await runtime.resume("INC-200", _approval(paused))
        original_history = await runtime.history("INC-200")
        checkpoint = next(item for item in original_history if item.next_nodes == ("verification",))

        forked = await runtime.fork("INC-200", checkpoint.checkpoint_id, "restart-secondary")
        assert forked.interrupted
        fork_payload = forked.interrupts[0]
        assert isinstance(fork_payload, Mapping)
        action = fork_payload["action"]
        assert isinstance(action, Mapping)
        assert action["id"] == "restart-secondary"
        assert len(await runtime.history("INC-200")) > len(original_history)

        after_restart = await runtime.resume("INC-200", _approval(forked))
        assert after_restart.interrupted
        assert executor.execution_count == 2
        recovered = await runtime.resume("INC-200", _approval(after_restart))
        assert recovered.values["phase"] is IncidentPhase.RESOLVED
        assert executor.execution_count == 2
        execution_result = recovered.values["execution_result"]
        assert isinstance(execution_result, ExecutionResult)
        assert execution_result.duplicate

    asyncio.run(scenario())


def test_replaying_effect_node_uses_idempotency_ledger() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        reasoner = DeterministicIncidentReasoner()
        executor = SimulatedRemediationExecutor(clock)
        graph = build_remediation_graph(
            reasoner, executor, clock, checkpointer=memory_checkpointer()
        )
        state = initial_incident_state("INC-300", _incident())
        state.update(
            IncidentState(
                phase=IncidentPhase.EVIDENCE_READY,
                root_cause=RootCause("hyp-1", "bad deployment", 0.9),
            )
        )
        config = {"configurable": {"thread_id": "INC-300"}}
        paused = await graph.ainvoke(state, config)
        interrupt_payload = paused["__interrupt__"][0].value
        await graph.ainvoke(
            Command(
                resume={
                    "decision": "approved",
                    "action_id": interrupt_payload["action"]["id"],
                    "comment": "ok",
                }
            ),
            config,
        )
        assert executor.execution_count == 1
        history = [item async for item in graph.aget_state_history(config)]
        before_effect = next(item for item in history if item.next == ("execute_action",))
        replayed = await graph.ainvoke(None, before_effect.config)
        assert executor.execution_count == 1
        assert replayed["execution_result"].duplicate

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["generate", "investigate", "synthesize", "propose"])
def test_reasoning_failures_become_terminal_serializable_state(stage: str) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        graph = build_incident_graph(
            reasoner=FailingReasoner(stage),
            signals=SyntheticIncidentSignals(),
            executor=SimulatedRemediationExecutor(clock),
            clock=clock,
            checkpointer=memory_checkpointer(),
        )
        runtime = GraphIncidentRuntime(graph)

        result = await runtime.start(f"INC-FAILED-{stage}", _incident())

        assert not result.interrupted
        assert result.values["phase"] is IncidentPhase.FAILED
        errors = result.values["errors"]
        assert isinstance(errors, list)
        assert errors
        assert all(isinstance(error, WorkflowError) for error in errors)
        assert {error.category for error in errors} == {f"{stage}_failed"}
        assert await runtime.history(f"INC-FAILED-{stage}")

    asyncio.run(scenario())
