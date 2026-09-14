"""Deterministic remediation idempotency keys."""

import re

from stateops.domain.models import RemediationAction

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def remediation_idempotency_key(incident_id: str, action: RemediationAction) -> str:
    """Build a bounded stable key from incident, action, and revision."""
    if _SAFE_ID.fullmatch(incident_id) is None or _SAFE_ID.fullmatch(action.id) is None:
        raise ValueError("incident and action identifiers must use the safe identifier format")
    return f"{incident_id}:{action.id}:{action.revision}"
