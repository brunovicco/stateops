"""Parent StateOps graph composition."""

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from stateops.application.ports.clock import Clock
from stateops.application.ports.incident_signals import IncidentSignals
from stateops.application.ports.reasoner import IncidentReasoner
from stateops.application.ports.remediation import RemediationExecutor
from stateops.domain.enums import IncidentPhase, Severity
from stateops.domain.transitions import transition
from stateops.graphs.events import timeline_event
from stateops.graphs.investigation.graph import build_investigation_graph
from stateops.graphs.remediation.graph import build_remediation_graph
from stateops.graphs.state import IncidentState
from stateops.graphs.verification.graph import build_verification_graph


class IncidentNodes:
    """Parent lifecycle nodes outside specialized subgraphs."""

    def __init__(self, signals: IncidentSignals, clock: Clock) -> None:
        """Capture the external signal port and clock."""
        self._signals = signals
        self._clock = clock

    async def enrich(self, state: IncidentState) -> IncidentState:
        """Load operational context and enter enrichment."""
        phase = transition(state["phase"], IncidentPhase.ENRICHING)
        context = await self._signals.enrich(state["incident"])
        return IncidentState(
            context=context,
            phase=phase,
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=phase,
                    event="incident.enriched",
                )
            ],
        )

    def classify(self, state: IncidentState) -> IncidentState:
        """Classify severity deterministically from the normalized error rate."""
        error_rate = state["incident"].error_rate_after
        if error_rate >= 15:
            severity = Severity.CRITICAL
        elif error_rate >= 5:
            severity = Severity.HIGH
        elif error_rate >= 1:
            severity = Severity.MEDIUM
        else:
            severity = Severity.LOW
        phase = transition(state["phase"], IncidentPhase.CLASSIFIED)
        return IncidentState(
            severity=severity,
            phase=phase,
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=phase,
                    event="incident.classified",
                )
            ],
        )


def _after_verification(state: IncidentState) -> Literal["remediation"] | str:
    if IncidentPhase(state["phase"]) is IncidentPhase.REPLANNING:
        return "remediation"
    return END


def _after_investigation(state: IncidentState) -> Literal["remediation"] | str:
    """Stop the parent graph when the investigation failed."""
    if IncidentPhase(state["phase"]) is IncidentPhase.FAILED:
        return END
    return "remediation"


def _after_remediation(state: IncidentState) -> Literal["verification"] | str:
    """Stop the parent graph when remediation planning failed."""
    if IncidentPhase(state["phase"]) is IncidentPhase.FAILED:
        return END
    return "verification"


def build_incident_graph(
    *,
    reasoner: IncidentReasoner,
    signals: IncidentSignals,
    executor: RemediationExecutor,
    clock: Clock,
    checkpointer: Any,
    max_attempts: int = 3,
) -> Any:
    """Compile the durable parent graph with per-invocation subgraphs."""
    nodes = IncidentNodes(signals, clock)
    builder = StateGraph(IncidentState)
    builder.add_node("enrich", nodes.enrich)
    builder.add_node("classify", nodes.classify)
    builder.add_node("investigation", build_investigation_graph(reasoner, clock))
    builder.add_node("remediation", build_remediation_graph(reasoner, executor, clock))
    builder.add_node(
        "verification",
        build_verification_graph(signals, clock, max_attempts=max_attempts),
    )
    builder.add_edge(START, "enrich")
    builder.add_edge("enrich", "classify")
    builder.add_edge("classify", "investigation")
    builder.add_conditional_edges(
        "investigation",
        _after_investigation,
        {"remediation": "remediation", END: END},
    )
    builder.add_conditional_edges(
        "remediation",
        _after_remediation,
        {"verification": "verification", END: END},
    )
    builder.add_conditional_edges(
        "verification",
        _after_verification,
        {"remediation": "remediation", END: END},
    )
    return builder.compile(checkpointer=checkpointer)
