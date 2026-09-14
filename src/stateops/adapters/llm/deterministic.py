"""Credential-free deterministic reasoner for tests and local workflow demos."""

import hashlib

from stateops.domain.enums import ActionKind, Severity
from stateops.domain.models import (
    Evidence,
    Hypothesis,
    IncidentContext,
    IncidentRecord,
    RemediationAction,
    RootCause,
)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


class DeterministicIncidentReasoner:
    """Exercise graph semantics without pretending deterministic rules are an LLM."""

    async def generate_hypotheses(
        self, incident: IncidentRecord, context: IncidentContext
    ) -> tuple[Hypothesis, ...]:
        """Return a variable list whose identities do not depend on execution order."""
        del context
        candidates = (
            ("bad-deployment", f"Deployment {incident.deployment} introduced a regression", 0.91),
            ("database-pressure", "Database pool saturation increased request failures", 0.55),
            ("dependency-latency", "A downstream dependency breached its latency SLO", 0.42),
        )
        return tuple(
            Hypothesis(
                id=_stable_id("hyp", f"{incident.service}:{slug}"),
                title=slug.replace("-", " "),
                rationale=rationale,
                confidence=confidence,
            )
            for slug, rationale, confidence in candidates
        )

    async def investigate(
        self, incident: IncidentRecord, context: IncidentContext, hypothesis: Hypothesis
    ) -> Evidence:
        """Correlate each hypothesis with deterministic synthetic signals."""
        del context
        deployment_related = "deployment" in hypothesis.title
        summary = (
            f"Errors began immediately after {incident.deployment}"
            if deployment_related
            else f"No strong signal supports {hypothesis.title}"
        )
        return Evidence(
            id=_stable_id("ev", f"{incident.service}:{hypothesis.id}"),
            hypothesis_id=hypothesis.id,
            source="synthetic-correlation",
            summary=summary,
            supports=deployment_related,
        )

    async def synthesize(
        self, hypotheses: tuple[Hypothesis, ...], evidence: tuple[Evidence, ...]
    ) -> RootCause:
        """Select the highest-confidence supported hypothesis."""
        supported = {item.hypothesis_id for item in evidence if item.supports}
        candidates = [item for item in hypotheses if item.id in supported] or list(hypotheses)
        selected = max(candidates, key=lambda item: (item.confidence, item.id))
        return RootCause(
            hypothesis_id=selected.id,
            summary=selected.rationale,
            confidence=selected.confidence,
        )

    async def propose_remediations(
        self, incident: IncidentRecord, root_cause: RootCause
    ) -> tuple[RemediationAction, ...]:
        """Return bounded safe actions with rollback as the preferred choice."""
        del root_cause
        return (
            RemediationAction(
                id="rollback-primary",
                kind=ActionKind.ROLLBACK_DEPLOYMENT,
                parameters=(("service", incident.service), ("target_version", "previous")),
                risk=Severity.HIGH,
            ),
            RemediationAction(
                id="restart-secondary",
                kind=ActionKind.RESTART_SERVICE,
                parameters=(("service", incident.service),),
                risk=Severity.MEDIUM,
            ),
        )
