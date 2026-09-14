"""Closed vocabularies for the incident-response domain."""

from enum import StrEnum


class IncidentPhase(StrEnum):
    """Lifecycle phases persisted in every incident checkpoint."""

    RECEIVED = "received"
    ENRICHING = "enriching"
    CLASSIFIED = "classified"
    HYPOTHESES_GENERATED = "hypotheses_generated"
    INVESTIGATING = "investigating"
    EVIDENCE_READY = "evidence_ready"
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REPLANNING = "replanning"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    FAILED = "failed"


class Severity(StrEnum):
    """Operational severity derived from incident signals."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalOutcome(StrEnum):
    """Allowed human decisions at the remediation boundary."""

    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class ActionKind(StrEnum):
    """Bounded simulated remediation operations."""

    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    DISABLE_FEATURE_FLAG = "disable_feature_flag"
    RESTART_SERVICE = "restart_service"
    SCALE_SERVICE = "scale_service"
    INVALIDATE_CACHE = "invalidate_cache"


class ExecutionStatus(StrEnum):
    """Terminal status for a remediation execution."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
