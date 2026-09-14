"""Opt-in durable restart proof against a real Redis instance."""

import asyncio
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from stateops.adapters.clock import SystemClock
from stateops.adapters.incidents.synthetic_signals import SyntheticIncidentSignals
from stateops.adapters.llm.deterministic import DeterministicIncidentReasoner
from stateops.adapters.persistence.checkpointer import redis_checkpointer
from stateops.adapters.remediation.redis_executor import RedisSimulatedRemediationExecutor
from stateops.application.idempotency import remediation_idempotency_key
from stateops.domain.enums import IncidentPhase
from stateops.domain.models import IncidentRecord, RemediationAction
from stateops.graphs.incident_graph import build_incident_graph
from stateops.graphs.runtime import GraphIncidentRuntime

_REDIS_URL = os.environ.get("STATEOPS_TEST_REDIS_URL")


@pytest.mark.integration
@pytest.mark.skipif(_REDIS_URL is None, reason="STATEOPS_TEST_REDIS_URL is not configured")
def test_waiting_incident_and_effect_ledger_survive_runtime_reconstruction() -> None:
    async def scenario(redis_url: str) -> None:
        incident_id = f"IT-{uuid4()}"
        incident = IncidentRecord("checkout", 0.2, 18.0, "v2.31", datetime(2026, 1, 1, tzinfo=UTC))
        clock = SystemClock()
        signals = SyntheticIncidentSignals()
        reasoner = DeterministicIncidentReasoner()

        first_executor = RedisSimulatedRemediationExecutor(redis_url, clock)
        try:
            await first_executor.setup()
            async with redis_checkpointer(redis_url) as first_saver:
                first = GraphIncidentRuntime(
                    build_incident_graph(
                        reasoner=reasoner,
                        signals=signals,
                        executor=first_executor,
                        clock=clock,
                        checkpointer=first_saver,
                    )
                )
                paused = await first.start(incident_id, incident)
                assert paused.values["phase"] == IncidentPhase.WAITING_APPROVAL
                interrupt_payload = paused.interrupts[0]
                assert isinstance(interrupt_payload, Mapping)
                action = interrupt_payload["action"]
                assert isinstance(action, Mapping)
                action_id = action["id"]
        finally:
            await first_executor.aclose()

        second_executor = RedisSimulatedRemediationExecutor(redis_url, clock)
        try:
            await second_executor.setup()
            async with redis_checkpointer(redis_url) as second_saver:
                resumed_runtime = GraphIncidentRuntime(
                    build_incident_graph(
                        reasoner=reasoner,
                        signals=signals,
                        executor=second_executor,
                        clock=clock,
                        checkpointer=second_saver,
                    )
                )
                recovered_state = await resumed_runtime.state(incident_id)
                assert recovered_state["phase"] == IncidentPhase.WAITING_APPROVAL
                completed = await resumed_runtime.resume(
                    incident_id,
                    {"decision": "approved", "action_id": action_id, "comment": "restart proof"},
                )
                assert completed.values["phase"] == IncidentPhase.RESOLVED
                selected_action = completed.values["selected_action"]
                assert isinstance(selected_action, RemediationAction)
                duplicate = await second_executor.execute(
                    incident_id=incident_id,
                    action=selected_action,
                    idempotency_key=remediation_idempotency_key(incident_id, selected_action),
                )
                assert duplicate.duplicate is True
        finally:
            await second_executor.aclose()

    assert _REDIS_URL is not None
    asyncio.run(scenario(_REDIS_URL))
