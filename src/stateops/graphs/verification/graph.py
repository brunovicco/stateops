"""Verification subgraph using typed ``Command`` update-and-route decisions."""

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Overwrite

from stateops.application.ports.clock import Clock
from stateops.application.ports.incident_signals import IncidentSignals
from stateops.domain.enums import IncidentPhase
from stateops.domain.transitions import transition
from stateops.graphs.events import timeline_event
from stateops.graphs.state import IncidentState


class VerificationNodes:
    """Nodes that measure and route recovery outcomes."""

    def __init__(self, signals: IncidentSignals, clock: Clock, *, max_attempts: int) -> None:
        """Configure a bounded remediation loop."""
        self._signals = signals
        self._clock = clock
        self._max_attempts = max_attempts

    async def observe(self, state: IncidentState) -> IncidentState:
        """Read synthetic post-action metrics."""
        selected = state["selected_action"]
        if selected is None:
            raise ValueError("verification requires a selected action")
        result = await self._signals.verify(state["incident"], selected)
        phase = transition(state["phase"], IncidentPhase.VERIFYING)
        return IncidentState(
            verification_result=result,
            phase=phase,
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=phase,
                    event="verification.observed",
                    discriminator=str(state["attempts"]),
                )
            ],
        )

    def decide(self, state: IncidentState) -> Command[Literal["resolved", "replan", "escalated"]]:
        """Update phase and route without adding a competing static edge."""
        result = state["verification_result"]
        if result is None:
            raise ValueError("verification decision requires metrics")
        if result.recovered:
            phase = transition(state["phase"], IncidentPhase.RESOLVED)
            return Command(update=IncidentState(phase=phase), goto="resolved")
        if state["attempts"] < self._max_attempts:
            phase = transition(state["phase"], IncidentPhase.REPLANNING)
            return Command(
                update={
                    "phase": phase,
                    "candidate_actions": Overwrite([]),
                    "preferred_action_id": None,
                    "selected_action": None,
                },
                goto="replan",
            )
        phase = transition(state["phase"], IncidentPhase.ESCALATED)
        return Command(update=IncidentState(phase=phase), goto="escalated")

    def terminal(self, state: IncidentState) -> IncidentState:
        """Record one metadata-only terminal decision."""
        return IncidentState(
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=IncidentPhase(state["phase"]),
                    event=f"incident.{IncidentPhase(state['phase']).value}",
                    discriminator=str(state["attempts"]),
                )
            ]
        )


def build_verification_graph(
    signals: IncidentSignals, clock: Clock, *, max_attempts: int = 3
) -> Any:
    """Compile the per-invocation verification subgraph."""
    nodes = VerificationNodes(signals, clock, max_attempts=max_attempts)
    builder = StateGraph(IncidentState)
    builder.add_node("observe_metrics", nodes.observe)
    builder.add_node("decide_recovery", nodes.decide)
    builder.add_node("resolved", nodes.terminal)
    builder.add_node("replan", nodes.terminal)
    builder.add_node("escalated", nodes.terminal)
    builder.add_edge(START, "observe_metrics")
    builder.add_edge("observe_metrics", "decide_recovery")
    builder.add_edge("resolved", END)
    builder.add_edge("replan", END)
    builder.add_edge("escalated", END)
    return builder.compile()
