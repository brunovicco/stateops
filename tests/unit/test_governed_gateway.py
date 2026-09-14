"""Governed Gateway adapter contract translation tests."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from governed_llm_gateway_client import GatewayClient
from governed_llm_gateway_client.errors import GatewayTransportError
from governed_llm_gateway_contracts import ExecutionStatus, GatewayError, StructuredOutputSchema

from stateops.adapters.llm.governed_gateway import (
    GatewayReasoningError,
    GovernedGatewayIncidentReasoner,
)
from stateops.domain.enums import ActionKind
from stateops.domain.models import IncidentContext, IncidentRecord, RootCause, Signal


class FakeGatewayClient:
    """Return queued provider-neutral response content and capture request metadata."""

    def __init__(self, responses: list[str | None]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def generate(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            status=ExecutionStatus.SUCCEEDED,
            content=self.responses.pop(0),
            error=None,
        )

    async def aclose(self) -> None:
        self.closed = True


def _incident() -> IncidentRecord:
    return IncidentRecord("checkout", 0.2, 18.0, "v2.31", datetime(2026, 1, 1, tzinfo=UTC))


def _context() -> IncidentContext:
    return IncidentContext((Signal("error", "18%", "metrics"),))


def test_gateway_reasoner_translates_all_typed_operations_without_provider_selection() -> None:
    async def scenario() -> None:
        responses: list[str | None] = [
            json.dumps(
                {
                    "hypotheses": [
                        {
                            "id": "hyp-1",
                            "title": "bad deploy",
                            "rationale": "timing",
                            "confidence": 0.9,
                        }
                    ]
                }
            ),
            json.dumps({"id": "ev-1", "source": "logs", "summary": "match", "supports": True}),
            json.dumps({"hypothesis_id": "hyp-1", "summary": "regression", "confidence": 0.95}),
            json.dumps(
                {
                    "actions": [
                        {
                            "id": "rollback-1",
                            "kind": "rollback_deployment",
                            "parameters": [{"name": "target_version", "value": "v2.30"}],
                            "risk": "high",
                        }
                    ]
                }
            ),
        ]
        fake = FakeGatewayClient(responses)
        reasoner = GovernedGatewayIncidentReasoner(cast(GatewayClient, fake))
        hypotheses = await reasoner.generate_hypotheses(_incident(), _context())
        evidence = await reasoner.investigate(_incident(), _context(), hypotheses[0])
        root = await reasoner.synthesize(hypotheses, (evidence,))
        actions = await reasoner.propose_remediations(_incident(), root)
        await reasoner.aclose()

        assert actions[0].kind is ActionKind.ROLLBACK_DEPLOYMENT
        assert root.hypothesis_id == hypotheses[0].id
        assert fake.closed
        assert all(call["workload"] == "stateops.incident.reasoning" for call in fake.calls)
        assert all("provider" not in call and "model" not in call for call in fake.calls)
        hypotheses_schema = cast(StructuredOutputSchema, fake.calls[0]["structured_output"])
        actions_schema = cast(StructuredOutputSchema, fake.calls[3]["structured_output"])
        hypotheses_properties = cast(dict[str, object], hypotheses_schema.schema["properties"])
        hypotheses_array = cast(dict[str, object], hypotheses_properties["hypotheses"])
        assert "maxItems" not in hypotheses_array
        actions_properties = cast(dict[str, object], actions_schema.schema["properties"])
        actions_array = cast(dict[str, object], actions_properties["actions"])
        assert "maxItems" not in actions_array
        action_items = actions_array["items"]
        action_properties = cast(dict[str, object], action_items)["properties"]
        parameters = cast(dict[str, object], action_properties)["parameters"]
        parameter_items = cast(dict[str, object], parameters)["items"]
        assert cast(dict[str, object], parameter_items)["additionalProperties"] is False

    asyncio.run(scenario())


def test_gateway_reasoner_preserves_failed_terminal_metadata() -> None:
    class FailedGatewayClient(FakeGatewayClient):
        async def generate(self, **kwargs: Any) -> object:
            self.calls.append(kwargs)
            return SimpleNamespace(
                status=ExecutionStatus.FAILED,
                content=None,
                error=GatewayError(
                    code="invalid_request",
                    message="provider rejected the schema",
                    retryable=False,
                ),
            )

    async def scenario() -> None:
        reasoner = GovernedGatewayIncidentReasoner(cast(GatewayClient, FailedGatewayClient([])))
        with pytest.raises(GatewayReasoningError) as raised:
            await reasoner.generate_hypotheses(_incident(), _context())

        assert raised.value.code == "invalid_request"
        assert not raised.value.retryable

    asyncio.run(scenario())


def test_gateway_reasoner_marks_transport_failures_retryable() -> None:
    class TransportFailureGatewayClient(FakeGatewayClient):
        async def generate(self, **kwargs: Any) -> object:
            self.calls.append(kwargs)
            raise GatewayTransportError("gateway unavailable")

    async def scenario() -> None:
        reasoner = GovernedGatewayIncidentReasoner(
            cast(GatewayClient, TransportFailureGatewayClient([]))
        )
        with pytest.raises(GatewayReasoningError) as raised:
            await reasoner.generate_hypotheses(_incident(), _context())

        assert raised.value.code == "gateway_transport_error"
        assert raised.value.retryable

    asyncio.run(scenario())


def test_gateway_reasoner_enforces_collection_limits_after_decoding() -> None:
    async def scenario() -> None:
        too_many = {
            "hypotheses": [
                {
                    "id": f"hyp-{index}",
                    "title": "candidate",
                    "rationale": "signal",
                    "confidence": 0.5,
                }
                for index in range(9)
            ]
        }
        reasoner = GovernedGatewayIncidentReasoner(
            cast(GatewayClient, FakeGatewayClient([json.dumps(too_many)]))
        )
        with pytest.raises(GatewayReasoningError, match="between 1 and 8"):
            await reasoner.generate_hypotheses(_incident(), _context())

    asyncio.run(scenario())


def test_gateway_reasoner_enforces_action_limits_after_decoding() -> None:
    async def scenario() -> None:
        too_many = {
            "actions": [
                {
                    "id": f"action-{index}",
                    "kind": "restart_service",
                    "parameters": [],
                    "risk": "medium",
                }
                for index in range(6)
            ]
        }
        reasoner = GovernedGatewayIncidentReasoner(
            cast(GatewayClient, FakeGatewayClient([json.dumps(too_many)]))
        )
        with pytest.raises(GatewayReasoningError, match="between 1 and 5"):
            await reasoner.propose_remediations(_incident(), RootCause("hyp-1", "regression", 0.9))

    asyncio.run(scenario())


def test_gateway_reasoner_rejects_duplicate_action_parameter_names() -> None:
    async def scenario() -> None:
        response = {
            "actions": [
                {
                    "id": "rollback-1",
                    "kind": "rollback_deployment",
                    "parameters": [
                        {"name": "target_version", "value": "v2.30"},
                        {"name": "target_version", "value": "v2.29"},
                    ],
                    "risk": "high",
                }
            ]
        }
        reasoner = GovernedGatewayIncidentReasoner(
            cast(GatewayClient, FakeGatewayClient([json.dumps(response)]))
        )
        with pytest.raises(GatewayReasoningError, match="duplicate parameter names"):
            await reasoner.propose_remediations(_incident(), RootCause("hyp-1", "regression", 0.9))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        None,
        "not-json",
        json.dumps({"hypotheses": []}),
        json.dumps({"hypotheses": [{"id": "x", "title": "x", "rationale": "x", "confidence": 9}]}),
    ],
)
def test_gateway_reasoner_fails_closed_on_invalid_structured_content(response: str | None) -> None:
    async def scenario() -> None:
        reasoner = GovernedGatewayIncidentReasoner(
            cast(GatewayClient, FakeGatewayClient([response]))
        )
        with pytest.raises(GatewayReasoningError):
            await reasoner.generate_hypotheses(_incident(), _context())

    asyncio.run(scenario())
