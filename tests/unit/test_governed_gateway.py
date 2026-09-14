"""Governed Gateway adapter contract translation tests."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from governed_llm_gateway_client import GatewayClient

from stateops.adapters.llm.governed_gateway import (
    GatewayReasoningError,
    GovernedGatewayIncidentReasoner,
)
from stateops.domain.enums import ActionKind
from stateops.domain.models import IncidentContext, IncidentRecord, Signal


class FakeGatewayClient:
    """Return queued provider-neutral response content and capture request metadata."""

    def __init__(self, responses: list[str | None]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def generate(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.responses.pop(0))

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
                            "parameters": {"target_version": "v2.30"},
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
