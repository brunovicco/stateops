"""Governed LLM Gateway implementation of the incident reasoning port."""

import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import cast

from governed_llm_gateway_client import GatewayClient
from governed_llm_gateway_client.errors import (
    GatewayClientError,
    GatewayHTTPError,
    GatewayTransportError,
)
from governed_llm_gateway_contracts import (
    DataClassification,
    Message,
    MessageRole,
    RiskLevel,
    StructuredOutputSchema,
    WorkloadRequirements,
)
from governed_llm_gateway_contracts import ExecutionStatus as GatewayExecutionStatus

from stateops.application.ports.reasoner import IncidentReasoningError
from stateops.domain.enums import ActionKind, Severity
from stateops.domain.models import (
    Evidence,
    Hypothesis,
    IncidentContext,
    IncidentRecord,
    RemediationAction,
    RootCause,
)


class GatewayReasoningError(IncidentReasoningError):
    """Raised when a governed response does not satisfy the StateOps contract."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_gateway_response",
        retryable: bool = False,
    ) -> None:
        """Retain stable Gateway metadata without preserving transport objects."""
        super().__init__(message, code=code, retryable=retryable)


_HYPOTHESES_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["id", "title", "rationale", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}

_EVIDENCE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "source": {"type": "string"},
        "summary": {"type": "string"},
        "supports": {"type": "boolean"},
    },
    "required": ["id", "source", "summary", "supports"],
    "additionalProperties": False,
}

_ROOT_CAUSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "hypothesis_id": {"type": "string"},
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["hypothesis_id", "summary", "confidence"],
    "additionalProperties": False,
}

_ACTIONS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string"},
                    "parameters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "risk": {"type": "string"},
                },
                "required": ["id", "kind", "parameters", "risk"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["actions"],
    "additionalProperties": False,
}


def _incident_payload(incident: IncidentRecord) -> dict[str, object]:
    return {
        "service": incident.service,
        "error_rate_before": incident.error_rate_before,
        "error_rate_after": incident.error_rate_after,
        "deployment": incident.deployment,
        "started_at": incident.started_at.isoformat(),
    }


def _context_payload(context: IncidentContext) -> list[dict[str, str]]:
    return [
        {"name": signal.name, "value": signal.value, "source": signal.source}
        for signal in context.signals
    ]


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GatewayReasoningError(f"gateway field {field!r} must be an object")
    return cast(Mapping[str, object], value)


def _items(value: object, *, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise GatewayReasoningError(f"gateway field {field!r} must be an array")
    return [_mapping(item, field=field) for item in value]


def _bounded_items(
    value: object, *, field: str, minimum: int, maximum: int
) -> list[Mapping[str, object]]:
    """Validate collection limits outside provider-specific JSON Schema dialects."""
    values = _items(value, field=field)
    if not minimum <= len(values) <= maximum:
        raise GatewayReasoningError(
            f"gateway field {field!r} must contain between {minimum} and {maximum} items"
        )
    return values


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2000:
        raise GatewayReasoningError(f"gateway field {field!r} must be bounded text")
    return value


def _confidence(value: object) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise GatewayReasoningError("gateway confidence must be numeric")
    result = float(value)
    if not 0 <= result <= 1:
        raise GatewayReasoningError("gateway confidence must be between zero and one")
    return result


class GovernedGatewayIncidentReasoner:
    """Use the provider-neutral Gateway client as the only production LLM boundary."""

    def __init__(
        self,
        client: GatewayClient,
        *,
        workload: str = "stateops.incident.reasoning",
        timeout_seconds: float = 30.0,
    ) -> None:
        """Configure one policy workload without naming a provider or model."""
        self._client = client
        self._workload = workload
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_env(
        cls, *, workload: str = "stateops.incident.reasoning"
    ) -> "GovernedGatewayIncidentReasoner":
        """Build from Gateway-facing environment variables only."""
        return cls(GatewayClient.from_env(), workload=workload)

    async def aclose(self) -> None:
        """Close the underlying Gateway connection pool."""
        await self._client.aclose()

    async def _generate(
        self, *, instruction: str, payload: object, schema_name: str, schema: Mapping[str, object]
    ) -> Mapping[str, object]:
        message = Message(
            role=MessageRole.USER,
            content=f"{instruction}\nINPUT_JSON={json.dumps(payload, separators=(',', ':'))}",
        )
        try:
            response = await self._client.generate(
                workload=self._workload,
                messages=(message,),
                risk_level=RiskLevel.HIGH,
                data_classification=DataClassification.PUBLIC,
                requirements=WorkloadRequirements(structured_output=True),
                structured_output=StructuredOutputSchema(name=schema_name, schema=schema),
                context_tokens_estimated=1000,
                max_output_tokens=2000,
                provider_timeout_seconds=self._timeout_seconds,
            )
        except GatewayHTTPError as exc:
            raise GatewayReasoningError(
                "gateway rejected the reasoning request",
                code=exc.code,
            ) from exc
        except GatewayTransportError as exc:
            raise GatewayReasoningError(
                "gateway transport failed",
                code="gateway_transport_error",
                retryable=True,
            ) from exc
        except GatewayClientError as exc:
            raise GatewayReasoningError(
                "gateway client failed",
                code="gateway_client_error",
            ) from exc
        if response.status is not GatewayExecutionStatus.SUCCEEDED:
            error = response.error
            raise GatewayReasoningError(
                "gateway reasoning execution failed",
                code=error.code if error is not None else "gateway_execution_failed",
                retryable=error.retryable if error is not None else False,
            )
        if response.content is None:
            raise GatewayReasoningError(
                "gateway returned no structured content",
                code="gateway_content_missing",
            )
        try:
            decoded = cast(object, json.loads(response.content))
        except json.JSONDecodeError as exc:
            raise GatewayReasoningError("gateway returned invalid JSON content") from exc
        return _mapping(decoded, field="response")

    async def generate_hypotheses(
        self, incident: IncidentRecord, context: IncidentContext
    ) -> tuple[Hypothesis, ...]:
        """Generate bounded hypotheses through the governed workload."""
        payload = await self._generate(
            instruction="Generate distinct incident root-cause hypotheses.",
            payload={"incident": _incident_payload(incident), "signals": _context_payload(context)},
            schema_name="stateops_hypotheses",
            schema=_HYPOTHESES_SCHEMA,
        )
        hypothesis_items = _bounded_items(
            payload.get("hypotheses"), field="hypotheses", minimum=1, maximum=8
        )
        hypotheses = tuple(
            Hypothesis(
                id=_text(item.get("id"), field="id"),
                title=_text(item.get("title"), field="title"),
                rationale=_text(item.get("rationale"), field="rationale"),
                confidence=_confidence(item.get("confidence")),
            )
            for item in hypothesis_items
        )
        return hypotheses

    async def investigate(
        self, incident: IncidentRecord, context: IncidentContext, hypothesis: Hypothesis
    ) -> Evidence:
        """Investigate one hypothesis through an independent governed call."""
        payload = await self._generate(
            instruction="Evaluate whether the signals support this hypothesis.",
            payload={
                "incident": _incident_payload(incident),
                "signals": _context_payload(context),
                "hypothesis": {
                    "id": hypothesis.id,
                    "title": hypothesis.title,
                    "rationale": hypothesis.rationale,
                },
            },
            schema_name="stateops_evidence",
            schema=_EVIDENCE_SCHEMA,
        )
        supports = payload.get("supports")
        if not isinstance(supports, bool):
            raise GatewayReasoningError("gateway field 'supports' must be boolean")
        return Evidence(
            id=_text(payload.get("id"), field="id"),
            hypothesis_id=hypothesis.id,
            source=_text(payload.get("source"), field="source"),
            summary=_text(payload.get("summary"), field="summary"),
            supports=supports,
        )

    async def synthesize(
        self, hypotheses: tuple[Hypothesis, ...], evidence: tuple[Evidence, ...]
    ) -> RootCause:
        """Synthesize a root cause through the governed workload."""
        payload = await self._generate(
            instruction="Select the best-supported root cause using only supplied evidence.",
            payload={
                "hypotheses": [asdict(item) for item in hypotheses],
                "evidence": [asdict(item) for item in evidence],
            },
            schema_name="stateops_root_cause",
            schema=_ROOT_CAUSE_SCHEMA,
        )
        hypothesis_id = _text(payload.get("hypothesis_id"), field="hypothesis_id")
        if hypothesis_id not in {item.id for item in hypotheses}:
            raise GatewayReasoningError("gateway selected an unknown hypothesis")
        return RootCause(
            hypothesis_id=hypothesis_id,
            summary=_text(payload.get("summary"), field="summary"),
            confidence=_confidence(payload.get("confidence")),
        )

    async def propose_remediations(
        self, incident: IncidentRecord, root_cause: RootCause
    ) -> tuple[RemediationAction, ...]:
        """Translate governed proposals into the bounded action vocabulary."""
        payload = await self._generate(
            instruction="Propose safe remediation actions using only the allowed action kinds.",
            payload={
                "incident": _incident_payload(incident),
                "root_cause": asdict(root_cause),
                "allowed_actions": [item.value for item in ActionKind],
            },
            schema_name="stateops_actions",
            schema=_ACTIONS_SCHEMA,
        )
        actions: list[RemediationAction] = []
        action_items = _bounded_items(payload.get("actions"), field="actions", minimum=1, maximum=5)
        for item in action_items:
            parameter_items = _bounded_items(
                item.get("parameters"), field="parameters", minimum=0, maximum=16
            )
            normalized = tuple(
                sorted(
                    (
                        _text(parameter.get("name"), field="parameter_name"),
                        _text(parameter.get("value"), field="parameter_value"),
                    )
                    for parameter in parameter_items
                )
            )
            if len({name for name, _ in normalized}) != len(normalized):
                raise GatewayReasoningError("gateway returned duplicate parameter names")
            try:
                kind = ActionKind(_text(item.get("kind"), field="kind"))
                risk = Severity(_text(item.get("risk"), field="risk"))
            except ValueError as exc:
                raise GatewayReasoningError("gateway returned an unsupported action") from exc
            actions.append(
                RemediationAction(
                    id=_text(item.get("id"), field="id"),
                    kind=kind,
                    parameters=normalized,
                    risk=risk,
                )
            )
        return tuple(actions)
