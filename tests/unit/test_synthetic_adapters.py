"""Credential-free adapter behavior tests."""

import asyncio
from datetime import UTC, datetime, timedelta

from stateops.adapters.incidents.synthetic_signals import SyntheticIncidentSignals
from stateops.adapters.llm.deterministic import DeterministicIncidentReasoner
from stateops.adapters.remediation.simulated_executor import SimulatedRemediationExecutor
from stateops.application.idempotency import remediation_idempotency_key
from stateops.domain.enums import ActionKind, Severity
from stateops.domain.models import IncidentRecord, RemediationAction


class FakeClock:
    """Deterministic monotonic clock for effect evidence."""

    def __init__(self) -> None:
        self._current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


def _incident() -> IncidentRecord:
    return IncidentRecord("checkout", 0.2, 18.0, "v2.31", datetime(2026, 1, 1, tzinfo=UTC))


def test_deterministic_reasoner_and_signals_form_a_complete_reasoning_cycle() -> None:
    async def scenario() -> None:
        incident = _incident()
        signals = SyntheticIncidentSignals()
        reasoner = DeterministicIncidentReasoner()
        context = await signals.enrich(incident)
        hypotheses = await reasoner.generate_hypotheses(incident, context)
        evidence = tuple(
            [await reasoner.investigate(incident, context, hypothesis) for hypothesis in hypotheses]
        )
        root_cause = await reasoner.synthesize(hypotheses, evidence)
        actions = await reasoner.propose_remediations(incident, root_cause)
        assert len(hypotheses) == len(evidence) == 3
        assert root_cause.confidence == 0.91
        assert actions[0].kind is ActionKind.ROLLBACK_DEPLOYMENT
        assert (await signals.verify(incident, actions[0])).recovered
        assert not (
            await signals.verify(
                incident,
                RemediationAction("restart", ActionKind.RESTART_SERVICE, (), Severity.MEDIUM),
            )
        ).recovered

    asyncio.run(scenario())


def test_simulated_executor_deduplicates_effects() -> None:
    async def scenario() -> None:
        action = RemediationAction("rollback", ActionKind.ROLLBACK_DEPLOYMENT, (), Severity.HIGH)
        executor = SimulatedRemediationExecutor(FakeClock())
        key = remediation_idempotency_key("INC-1", action)
        first = await executor.execute(incident_id="INC-1", action=action, idempotency_key=key)
        duplicate = await executor.execute(incident_id="INC-1", action=action, idempotency_key=key)
        assert not first.duplicate
        assert duplicate.duplicate
        assert duplicate.completed_at == first.completed_at
        assert executor.execution_count == 1

    asyncio.run(scenario())
