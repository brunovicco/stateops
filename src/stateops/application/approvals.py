"""Validation for untrusted human approval payloads."""

from collections.abc import Mapping

from stateops.domain.enums import ApprovalOutcome
from stateops.domain.models import ApprovalDecision, RemediationAction


class InvalidApprovalError(ValueError):
    """Raised when a resume payload exceeds the approval contract."""


def parse_approval(payload: object, action: RemediationAction) -> ApprovalDecision:
    """Parse a JSON-like approval and constrain modifications to existing parameters."""
    if not isinstance(payload, Mapping):
        raise InvalidApprovalError("approval payload must be an object")
    decision = payload.get("decision")
    action_id = payload.get("action_id")
    comment = payload.get("comment", "")
    if not isinstance(decision, str):
        raise InvalidApprovalError("decision must be a string")
    try:
        outcome = ApprovalOutcome(decision)
    except ValueError as exc:
        raise InvalidApprovalError("decision must be approved, rejected, or modified") from exc
    if action_id != action.id:
        raise InvalidApprovalError("approval action_id does not match the selected action")
    if not isinstance(comment, str) or len(comment) > 500:
        raise InvalidApprovalError("comment must be a string no longer than 500 characters")

    raw_modifications = payload.get("modifications", {})
    if not isinstance(raw_modifications, Mapping):
        raise InvalidApprovalError("modifications must be an object")
    allowed_parameters = action.parameter_map()
    modifications: list[tuple[str, str]] = []
    for key, value in raw_modifications.items():
        if not isinstance(key, str) or key not in allowed_parameters:
            raise InvalidApprovalError("modification targets an unsupported parameter")
        if not isinstance(value, str) or not value or len(value) > 200:
            raise InvalidApprovalError("modified parameters must be bounded non-empty strings")
        modifications.append((key, value))
    if outcome is ApprovalOutcome.MODIFIED and not modifications:
        raise InvalidApprovalError("modified approval requires at least one modification")
    if outcome is not ApprovalOutcome.MODIFIED and modifications:
        raise InvalidApprovalError("only modified approvals may include modifications")
    return ApprovalDecision(
        outcome=outcome,
        action_id=action.id,
        comment=comment,
        modifications=tuple(sorted(modifications)),
    )


def apply_approval(action: RemediationAction, approval: ApprovalDecision) -> RemediationAction:
    """Apply an approved bounded modification without changing action identity."""
    if approval.outcome is not ApprovalOutcome.MODIFIED:
        return action
    parameters = action.parameter_map()
    parameters.update(dict(approval.modifications))
    return RemediationAction(
        id=action.id,
        kind=action.kind,
        parameters=tuple(sorted(parameters.items())),
        risk=action.risk,
        revision=action.revision + 1,
    )
