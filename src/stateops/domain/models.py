"""Framework-free immutable values stored in the StateOps graph state."""

from dataclasses import dataclass
from datetime import datetime

from stateops.domain.enums import (
    ActionKind,
    ApprovalOutcome,
    ExecutionStatus,
    IncidentPhase,
    Severity,
)


def _stored_datetime(value: object) -> datetime:
    """Normalize a datetime restored by either binary or JSON persistence."""
    restored = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(restored, datetime):
        raise TypeError("stored datetime must be a datetime or ISO-8601 string")
    if restored.tzinfo is None or restored.utcoffset() is None:
        raise ValueError("stored datetime must include a timezone")
    return restored


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    """Normalized incident input."""

    service: str
    error_rate_before: float
    error_rate_after: float
    deployment: str
    started_at: datetime

    def __post_init__(self) -> None:
        """Restore timestamp invariants after JSON checkpoint deserialization."""
        object.__setattr__(self, "started_at", _stored_datetime(self.started_at))


@dataclass(frozen=True, slots=True)
class Signal:
    """One bounded observation used during reasoning."""

    name: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class IncidentContext:
    """Enriched operational context."""

    signals: tuple[Signal, ...]

    def __post_init__(self) -> None:
        """Restore the immutable collection representation after JSON storage."""
        object.__setattr__(self, "signals", tuple(self.signals))


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """A possible cause generated before parallel investigation."""

    id: str
    title: str
    rationale: str
    confidence: float


@dataclass(frozen=True, slots=True)
class Evidence:
    """Evidence collected for one hypothesis."""

    id: str
    hypothesis_id: str
    source: str
    summary: str
    supports: bool


@dataclass(frozen=True, slots=True)
class RootCause:
    """Synthesized most probable root cause."""

    hypothesis_id: str
    summary: str
    confidence: float


@dataclass(frozen=True, slots=True)
class RemediationAction:
    """Allowlisted action with normalized string parameters."""

    id: str
    kind: ActionKind
    parameters: tuple[tuple[str, str], ...]
    risk: Severity
    revision: int = 1

    def __post_init__(self) -> None:
        """Restore enum and tuple invariants after JSON checkpoint deserialization."""
        object.__setattr__(self, "kind", ActionKind(self.kind))
        object.__setattr__(
            self,
            "parameters",
            tuple((str(name), str(value)) for name, value in self.parameters),
        )
        object.__setattr__(self, "risk", Severity(self.risk))

    def parameter_map(self) -> dict[str, str]:
        """Return a new mutable representation for transport boundaries."""
        return dict(self.parameters)


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Validated human decision returned from an interrupt."""

    outcome: ApprovalOutcome
    action_id: str
    comment: str
    modifications: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Restore enum and tuple invariants after JSON checkpoint deserialization."""
        object.__setattr__(self, "outcome", ApprovalOutcome(self.outcome))
        object.__setattr__(
            self,
            "modifications",
            tuple((str(name), str(value)) for name, value in self.modifications),
        )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Structured evidence for one idempotent simulated side effect."""

    action_id: str
    idempotency_key: str
    started_at: datetime
    completed_at: datetime
    status: ExecutionStatus
    synthetic_effect: str
    duplicate: bool = False

    def __post_init__(self) -> None:
        """Restore timestamp and enum invariants after JSON checkpoint deserialization."""
        object.__setattr__(self, "started_at", _stored_datetime(self.started_at))
        object.__setattr__(self, "completed_at", _stored_datetime(self.completed_at))
        object.__setattr__(self, "status", ExecutionStatus(self.status))


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Synthetic post-remediation metrics and decision."""

    recovered: bool
    error_rate_before: float
    error_rate_after: float
    latency_before_ms: int
    latency_after_ms: int


@dataclass(frozen=True, slots=True)
class WorkflowError:
    """Metadata-safe workflow failure."""

    id: str
    category: str
    node: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """Metadata-only lifecycle event."""

    id: str
    event: str
    phase: IncidentPhase
    occurred_at: datetime

    def __post_init__(self) -> None:
        """Restore timestamp and phase invariants after JSON checkpoint deserialization."""
        object.__setattr__(self, "phase", IncidentPhase(self.phase))
        object.__setattr__(self, "occurred_at", _stored_datetime(self.occurred_at))
