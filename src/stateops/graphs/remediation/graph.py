"""Remediation subgraph with interrupt/resume and idempotent effects."""

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Overwrite, interrupt

from stateops.application.approvals import apply_approval, parse_approval
from stateops.application.idempotency import remediation_idempotency_key
from stateops.application.ports.clock import Clock
from stateops.application.ports.reasoner import IncidentReasoner, IncidentReasoningError
from stateops.application.ports.remediation import RemediationExecutor
from stateops.domain.enums import ActionKind, ApprovalOutcome, IncidentPhase, Severity
from stateops.domain.transitions import transition
from stateops.graphs.events import timeline_event
from stateops.graphs.failures import failed_reasoning_state
from stateops.graphs.state import IncidentState


class RemediationNodes:
    """Nodes that keep approval and side effects in separate checkpoints."""

    def __init__(
        self, reasoner: IncidentReasoner, executor: RemediationExecutor, clock: Clock
    ) -> None:
        """Capture ports outside persisted graph state."""
        self._reasoner = reasoner
        self._executor = executor
        self._clock = clock

    async def propose_actions(self, state: IncidentState) -> IncidentState:
        """Generate allowlisted candidates after evidence synthesis or replan."""
        try:
            actions = await self._reasoner.propose_remediations(
                state["incident"], state["root_cause"]
            )
        except IncidentReasoningError as exc:
            return failed_reasoning_state(
                self._clock,
                state,
                node="propose_actions",
                error=exc,
                discriminator=str(state["attempts"]),
            )
        phase = transition(state["phase"], IncidentPhase.PLANNING)
        return IncidentState(
            phase=phase,
            candidate_actions=list(actions),
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=phase,
                    event="remediation.proposed",
                    discriminator=str(state["attempts"]),
                )
            ],
        )

    def select_action(self, state: IncidentState) -> IncidentState:
        """Select deterministically; a fork can replace candidates before this node."""
        if not state["candidate_actions"]:
            raise ValueError("cannot select a remediation without candidates")
        action_rank = {
            ActionKind.ROLLBACK_DEPLOYMENT: 5,
            ActionKind.DISABLE_FEATURE_FLAG: 4,
            ActionKind.RESTART_SERVICE: 3,
            ActionKind.SCALE_SERVICE: 2,
            ActionKind.INVALIDATE_CACHE: 1,
        }
        preferred = state.get("preferred_action_id")
        selected = next(
            (item for item in state["candidate_actions"] if item.id == preferred),
            None,
        )
        if selected is None:
            selected = max(
                state["candidate_actions"],
                key=lambda item: (action_rank[ActionKind(item.kind)], item.id),
            )
        phase = transition(state["phase"], IncidentPhase.WAITING_APPROVAL)
        return IncidentState(
            selected_action=selected,
            phase=phase,
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=phase,
                    event="approval.requested",
                    discriminator=f"{selected.id}:{selected.revision}",
                )
            ],
        )

    def human_approval(self, state: IncidentState) -> Command[Literal["execute_action", "replan"]]:
        """Pause with no prior effect, then validate the untrusted resume value."""
        selected = state["selected_action"]
        if selected is None:
            raise ValueError("approval requires a selected action")
        payload = interrupt(
            {
                "incident_id": state["incident_id"],
                "phase": IncidentPhase(state["phase"]).value,
                "action": {
                    "id": selected.id,
                    "kind": ActionKind(selected.kind).value,
                    "parameters": selected.parameter_map(),
                    "risk": Severity(selected.risk).value,
                    "revision": selected.revision,
                },
                "allowed_decisions": [item.value for item in ApprovalOutcome],
            }
        )
        approval = parse_approval(payload, selected)
        if approval.outcome is ApprovalOutcome.REJECTED:
            phase = transition(state["phase"], IncidentPhase.REPLANNING)
            return Command(
                update=IncidentState(approval=approval, phase=phase),
                goto="replan",
            )
        approved_action = apply_approval(selected, approval)
        phase = transition(state["phase"], IncidentPhase.EXECUTING)
        return Command(
            update=IncidentState(
                approval=approval,
                selected_action=approved_action,
                phase=phase,
            ),
            goto="execute_action",
        )

    async def execute_action(self, state: IncidentState) -> IncidentState:
        """Run the dedicated idempotent effect after the approval checkpoint."""
        selected = state["selected_action"]
        if selected is None:
            raise ValueError("execution requires a selected action")
        key = remediation_idempotency_key(state["incident_id"], selected)
        result = await self._executor.execute(
            incident_id=state["incident_id"], action=selected, idempotency_key=key
        )
        return IncidentState(
            execution_result=result,
            attempts=state["attempts"] + 1,
            timeline=[
                timeline_event(
                    self._clock,
                    incident_id=state["incident_id"],
                    phase=IncidentPhase.EXECUTING,
                    event="remediation.executed",
                    discriminator=key,
                )
            ],
        )

    def replan(self, state: IncidentState) -> Command[Literal["propose_actions"]]:
        """Clear reducer-managed candidates explicitly before another planning cycle."""
        return Command(
            update={
                "candidate_actions": Overwrite([]),
                "preferred_action_id": None,
                "selected_action": None,
                "timeline": [
                    timeline_event(
                        self._clock,
                        incident_id=state["incident_id"],
                        phase=IncidentPhase.REPLANNING,
                        event="remediation.replanning",
                        discriminator=str(state["attempts"]),
                    )
                ],
            },
            goto="propose_actions",
        )


def build_remediation_graph(
    reasoner: IncidentReasoner,
    executor: RemediationExecutor,
    clock: Clock,
    *,
    checkpointer: Any = None,
) -> Any:
    """Compile the per-invocation human-approval subgraph."""
    nodes = RemediationNodes(reasoner, executor, clock)
    builder = StateGraph(IncidentState)
    builder.add_node("propose_actions", nodes.propose_actions)
    builder.add_node("select_action", nodes.select_action)
    builder.add_node("human_approval", nodes.human_approval)
    builder.add_node("execute_action", nodes.execute_action)
    builder.add_node("replan", nodes.replan)
    builder.add_edge(START, "propose_actions")
    builder.add_conditional_edges(
        "propose_actions",
        _after_proposal,
        {"select_action": "select_action", END: END},
    )
    builder.add_edge("select_action", "human_approval")
    builder.add_edge("execute_action", END)
    return builder.compile(checkpointer=checkpointer)


def _after_proposal(state: IncidentState) -> str:
    """Stop the subgraph when action generation failed."""
    if IncidentPhase(state["phase"]) is IncidentPhase.FAILED:
        return END
    return "select_action"
