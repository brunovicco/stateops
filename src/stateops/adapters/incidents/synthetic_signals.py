"""Deterministic operational signals for a safe local demonstration."""

from stateops.domain.enums import ActionKind
from stateops.domain.models import (
    IncidentContext,
    IncidentRecord,
    RemediationAction,
    Signal,
    VerificationResult,
)


class SyntheticIncidentSignals:
    """Model realistic incident data without contacting production systems."""

    async def enrich(self, incident: IncidentRecord) -> IncidentContext:
        """Derive deterministic metrics, logs, and deployment history."""
        return IncidentContext(
            signals=(
                Signal(
                    name="error_rate",
                    value=f"{incident.error_rate_after:.2f}%",
                    source="synthetic-prometheus",
                ),
                Signal(
                    name="recent_deployment",
                    value=incident.deployment,
                    source="synthetic-deploy-api",
                ),
                Signal(
                    name="dominant_error",
                    value="checkout validation failed",
                    source="synthetic-logs",
                ),
            )
        )

    async def verify(
        self, incident: IncidentRecord, action: RemediationAction
    ) -> VerificationResult:
        """Report recovery for rollback/flag actions and bounded failure otherwise."""
        recovered = action.kind in {
            ActionKind.ROLLBACK_DEPLOYMENT,
            ActionKind.DISABLE_FEATURE_FLAG,
        }
        return VerificationResult(
            recovered=recovered,
            error_rate_before=incident.error_rate_after,
            error_rate_after=0.4 if recovered else 14.2,
            latency_before_ms=1400,
            latency_after_ms=210 if recovered else 980,
        )
