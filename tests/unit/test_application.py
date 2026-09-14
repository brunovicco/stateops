"""Application validation and idempotency tests."""

import pytest

from stateops.application.approvals import InvalidApprovalError, apply_approval, parse_approval
from stateops.application.idempotency import remediation_idempotency_key
from stateops.domain.enums import ActionKind, ApprovalOutcome, Severity
from stateops.domain.models import RemediationAction


def _action() -> RemediationAction:
    return RemediationAction(
        id="rollback-1",
        kind=ActionKind.ROLLBACK_DEPLOYMENT,
        parameters=(("service", "checkout"), ("target_version", "v2.30")),
        risk=Severity.HIGH,
    )


def test_approval_supports_bounded_modification() -> None:
    action = _action()
    approval = parse_approval(
        {
            "decision": "modified",
            "action_id": action.id,
            "comment": "Use the known-good release",
            "modifications": {"target_version": "v2.29"},
        },
        action,
    )
    assert approval.outcome is ApprovalOutcome.MODIFIED
    modified = apply_approval(action, approval)
    assert modified.revision == 2
    assert modified.parameter_map()["target_version"] == "v2.29"
    assert remediation_idempotency_key("INC-7", modified) == "INC-7:rollback-1:2"


@pytest.mark.parametrize(
    "payload",
    [
        True,
        {"decision": "unknown", "action_id": "rollback-1"},
        {"decision": "approved", "action_id": "other"},
        {"decision": "modified", "action_id": "rollback-1"},
        {
            "decision": "modified",
            "action_id": "rollback-1",
            "modifications": {"command": "arbitrary"},
        },
        {
            "decision": "approved",
            "action_id": "rollback-1",
            "modifications": {"service": "other"},
        },
    ],
)
def test_approval_rejects_untrusted_or_overbroad_payloads(payload: object) -> None:
    with pytest.raises(InvalidApprovalError):
        parse_approval(payload, _action())


def test_unmodified_approval_keeps_action_and_invalid_ids_fail_closed() -> None:
    action = _action()
    approval = parse_approval(
        {"decision": "approved", "action_id": action.id, "comment": "ok"}, action
    )
    assert apply_approval(action, approval) is action
    with pytest.raises(ValueError, match="safe identifier"):
        remediation_idempotency_key("not safe!", action)
