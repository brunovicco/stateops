"""Map-reduce investigation subgraph built with dynamic ``Send`` fan-out."""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from stateops.application.ports.clock import Clock
from stateops.application.ports.reasoner import IncidentReasoner, IncidentReasoningError
from stateops.domain.enums import IncidentPhase
from stateops.domain.models import Hypothesis
from stateops.domain.transitions import transition
from stateops.graphs.events import timeline_event
from stateops.graphs.failures import (
    failed_reasoning_state,
    failed_state_from_branch_errors,
    reasoning_error,
)
from stateops.graphs.state import IncidentState


class InvestigationTaskState(TypedDict):
    """Isolated input for one dynamically created investigation branch."""

    incident_id: str
    incident: object
    context: object
    hypothesis: Hypothesis


class InvestigationNodes:
    """Nodes for variable fan-out and deterministic evidence reduction."""

    def __init__(self, reasoner: IncidentReasoner, clock: Clock) -> None:
        """Capture application capabilities outside checkpointed state."""
        self._reasoner = reasoner
        self._clock = clock

    async def generate_hypotheses(self, state: IncidentState) -> IncidentState:
        """Generate hypotheses, then persist them before fan-out."""
        try:
            hypotheses = await self._reasoner.generate_hypotheses(
                state["incident"], state["context"]
            )
        except IncidentReasoningError as exc:
            return failed_reasoning_state(
                self._clock,
                state,
                node="generate_hypotheses",
                error=exc,
            )
        phase = transition(state["phase"], IncidentPhase.HYPOTHESES_GENERATED)
        return IncidentState(
            phase=phase,
            hypotheses=list(hypotheses),
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=phase,
                    event="hypotheses.generated",
                )
            ],
        )

    def mark_investigating(self, state: IncidentState) -> IncidentState:
        """Enter the parallel phase in a sequential super-step."""
        phase = transition(state["phase"], IncidentPhase.INVESTIGATING)
        return IncidentState(
            phase=phase,
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=phase,
                    event="investigation.started",
                )
            ],
        )

    def fan_out(self, state: IncidentState) -> list[Send]:
        """Create one branch per hypothesis; topology is not fixed at compile time."""
        return [
            Send(
                "investigate_hypothesis",
                {
                    "incident_id": state["incident_id"],
                    "incident": state["incident"],
                    "context": state["context"],
                    "hypothesis": hypothesis,
                },
            )
            for hypothesis in state["hypotheses"]
        ]

    async def investigate_hypothesis(self, state: InvestigationTaskState) -> IncidentState:
        """Collect one branch's evidence without writing scalar shared channels."""
        from typing import cast

        from stateops.domain.models import IncidentContext, IncidentRecord

        incident = cast(IncidentRecord, state["incident"])
        context = cast(IncidentContext, state["context"])
        hypothesis = state["hypothesis"]
        try:
            evidence = await self._reasoner.investigate(incident, context, hypothesis)
        except IncidentReasoningError as exc:
            return IncidentState(
                errors=[
                    reasoning_error(
                        incident_id=state["incident_id"],
                        node="investigate_hypothesis",
                        error=exc,
                        discriminator=hypothesis.id,
                    )
                ],
                timeline=[
                    timeline_event(
                        self._clock,
                        incident_id=state["incident_id"],
                        phase=IncidentPhase.INVESTIGATING,
                        event="reasoning.failed",
                        discriminator=f"investigate_hypothesis:{hypothesis.id}:{exc.code}",
                    )
                ],
            )
        return IncidentState(
            evidence=[evidence],
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=IncidentPhase.INVESTIGATING,
                    event="investigation.branch.completed",
                    discriminator=hypothesis.id,
                )
            ],
        )

    async def synthesize(self, state: IncidentState) -> IncidentState:
        """Reduce accumulated evidence into one probable root cause."""
        if state["errors"]:
            return failed_state_from_branch_errors(self._clock, state)
        try:
            root_cause = await self._reasoner.synthesize(
                tuple(state["hypotheses"]), tuple(state["evidence"])
            )
        except IncidentReasoningError as exc:
            return failed_reasoning_state(
                self._clock,
                state,
                node="synthesize_evidence",
                error=exc,
            )
        phase = transition(state["phase"], IncidentPhase.EVIDENCE_READY)
        return IncidentState(
            root_cause=root_cause,
            phase=phase,
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=phase,
                    event="evidence.synthesized",
                )
            ],
        )


def build_investigation_graph(reasoner: IncidentReasoner, clock: Clock) -> Any:
    """Compile a per-invocation subgraph that inherits its parent's checkpointer."""
    nodes = InvestigationNodes(reasoner, clock)
    builder = StateGraph(IncidentState)
    builder.add_node("generate_hypotheses", nodes.generate_hypotheses)
    builder.add_node("mark_investigating", nodes.mark_investigating)
    builder.add_node("investigate_hypothesis", nodes.investigate_hypothesis)
    builder.add_node("synthesize_evidence", nodes.synthesize)
    builder.add_edge(START, "generate_hypotheses")
    builder.add_conditional_edges(
        "generate_hypotheses",
        _after_hypotheses,
        {"mark_investigating": "mark_investigating", END: END},
    )
    builder.add_conditional_edges("mark_investigating", nodes.fan_out)
    builder.add_edge("investigate_hypothesis", "synthesize_evidence")
    builder.add_edge("synthesize_evidence", END)
    return builder.compile()


def _after_hypotheses(state: IncidentState) -> str:
    """Stop the subgraph when hypothesis generation failed."""
    if IncidentPhase(state["phase"]) is IncidentPhase.FAILED:
        return END
    return "mark_investigating"
