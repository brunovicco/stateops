"""Validated HTTP transport schemas."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stateops.domain.models import IncidentRecord

_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class CreateIncidentRequest(BaseModel):
    """Bounded synthetic incident accepted by the API."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(pattern=_SAFE_ID)
    service: str = Field(min_length=1, max_length=100, pattern=_SAFE_ID)
    error_rate_before: float = Field(ge=0, le=100)
    error_rate_after: float = Field(ge=0, le=100)
    deployment: str = Field(min_length=1, max_length=128, pattern=_SAFE_ID)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_incident(self) -> "CreateIncidentRequest":
        """Reject naive timestamps and non-increasing incident error rates."""
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("started_at must include a timezone")
        if self.error_rate_after <= self.error_rate_before:
            raise ValueError("error_rate_after must be greater than error_rate_before")
        return self

    def to_domain(self) -> IncidentRecord:
        """Translate transport data into the framework-free domain value."""
        return IncidentRecord(
            service=self.service,
            error_rate_before=self.error_rate_before,
            error_rate_after=self.error_rate_after,
            deployment=self.deployment,
            started_at=self.started_at.astimezone(UTC),
        )


class ApprovalRequest(BaseModel):
    """Structured human response used with ``Command(resume=...)``."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected", "modified"]
    action_id: str = Field(pattern=_SAFE_ID)
    comment: str = Field(default="", max_length=500)
    modifications: dict[str, str] = Field(default_factory=dict)


class ForkRequest(BaseModel):
    """Controlled time-travel branch selection."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1, max_length=255)
    selected_action_id: str = Field(pattern=_SAFE_ID)
