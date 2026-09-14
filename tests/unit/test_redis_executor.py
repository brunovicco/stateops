"""Redis remediation ledger unit tests."""

from datetime import UTC, datetime

import pytest

from stateops.adapters.remediation.redis_executor import RedisSimulatedRemediationExecutor
from stateops.domain.enums import ActionKind, Severity
from stateops.domain.models import RemediationAction


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.closed = False
        self.reachable = True

    async def ping(self) -> bool:
        return self.reachable

    async def set(self, name: str, value: str, *, nx: bool = False) -> bool | None:
        if nx and name in self.values:
            return None
        self.values[name] = value
        return True

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def aclose(self) -> None:
        self.closed = True


def _action() -> RemediationAction:
    return RemediationAction(
        id="rollback-primary",
        kind=ActionKind.ROLLBACK_DEPLOYMENT,
        parameters=(("service", "checkout"),),
        risk=Severity.HIGH,
        revision=1,
    )


@pytest.mark.anyio
async def test_redis_executor_claims_once_and_returns_duplicate_evidence() -> None:
    client = FakeRedis()
    executor = RedisSimulatedRemediationExecutor("redis://unused", FixedClock(), client=client)
    await executor.setup()

    first = await executor.execute(
        incident_id="INC-1", action=_action(), idempotency_key="INC-1:rollback-primary:1"
    )
    duplicate = await executor.execute(
        incident_id="INC-1", action=_action(), idempotency_key="INC-1:rollback-primary:1"
    )

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert duplicate.action_id == first.action_id
    assert duplicate.started_at == first.started_at
    assert len(client.values) == 1
    await executor.aclose()
    assert client.closed is True


@pytest.mark.anyio
async def test_redis_executor_fails_closed_for_missing_or_invalid_committed_value() -> None:
    client = FakeRedis()
    executor = RedisSimulatedRemediationExecutor("redis://unused", FixedClock(), client=client)
    key = "stateops:remediation:INC-1:rollback-primary:1"
    client.values[key] = "not-json"

    with pytest.raises(RuntimeError, match="invalid remediation ledger value"):
        await executor.execute(
            incident_id="INC-1", action=_action(), idempotency_key="INC-1:rollback-primary:1"
        )

    client.values.pop(key)

    async def disappearing_get(name: str) -> None:
        del name
        return None

    client.get = disappearing_get  # type: ignore[method-assign]
    client.values[key] = "claimed-by-another-writer"
    with pytest.raises(RuntimeError, match="idempotency conflict result disappeared"):
        await executor.execute(
            incident_id="INC-1", action=_action(), idempotency_key="INC-1:rollback-primary:1"
        )
