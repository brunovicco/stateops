"""Durable Redis idempotency ledger for simulated remediations."""

import json
from datetime import datetime
from typing import Protocol, cast

from redis.asyncio import Redis

from stateops.application.ports.clock import Clock
from stateops.domain.enums import ActionKind, ExecutionStatus
from stateops.domain.models import ExecutionResult, RemediationAction

_KEY_PREFIX = "stateops:remediation:"


class AsyncRedisClient(Protocol):
    """Small Redis surface required by the remediation ledger."""

    async def ping(self) -> bool:
        """Confirm the backing Redis service is reachable."""

    async def set(self, name: str, value: str, *, nx: bool = False) -> bool | None:
        """Set a value, optionally only when the key does not exist."""

    async def get(self, name: str) -> bytes | str | None:
        """Read a previously stored value."""

    async def aclose(self) -> None:
        """Close the client and its connection pool."""


def _encode(result: ExecutionResult) -> str:
    return json.dumps(
        {
            "action_id": result.action_id,
            "idempotency_key": result.idempotency_key,
            "started_at": result.started_at.isoformat(),
            "completed_at": result.completed_at.isoformat(),
            "status": result.status.value,
            "synthetic_effect": result.synthetic_effect,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode(payload: bytes | str, *, duplicate: bool) -> ExecutionResult:
    try:
        text = payload.decode() if isinstance(payload, bytes) else payload
        value = json.loads(text)
        if not isinstance(value, dict):
            raise TypeError("ledger value must be an object")
        return ExecutionResult(
            action_id=str(value["action_id"]),
            idempotency_key=str(value["idempotency_key"]),
            started_at=datetime.fromisoformat(str(value["started_at"])),
            completed_at=datetime.fromisoformat(str(value["completed_at"])),
            status=ExecutionStatus(str(value["status"])),
            synthetic_effect=str(value["synthetic_effect"]),
            duplicate=duplicate,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid remediation ledger value") from exc


class RedisSimulatedRemediationExecutor:
    """Persist synthetic effect evidence behind an atomic Redis claim."""

    def __init__(
        self,
        redis_url: str,
        clock: Clock,
        *,
        client: AsyncRedisClient | None = None,
    ) -> None:
        """Capture Redis and time capabilities."""
        self._clock = clock
        self._client = client or cast(
            AsyncRedisClient,
            Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            ),
        )

    async def setup(self) -> None:
        """Fail startup when the Redis ledger cannot be reached."""
        await self._client.ping()

    async def aclose(self) -> None:
        """Release the Redis connection pool."""
        await self._client.aclose()

    async def execute(
        self, *, incident_id: str, action: RemediationAction, idempotency_key: str
    ) -> ExecutionResult:
        """Claim the effect once atomically, or return its committed evidence."""
        del incident_id
        result = ExecutionResult(
            action_id=action.id,
            idempotency_key=idempotency_key,
            started_at=self._clock.now(),
            completed_at=self._clock.now(),
            status=ExecutionStatus.SUCCEEDED,
            synthetic_effect=f"simulated:{ActionKind(action.kind).value}",
        )
        key = f"{_KEY_PREFIX}{idempotency_key}"
        inserted = await self._client.set(key, _encode(result), nx=True)
        if inserted:
            return result
        existing = await self._client.get(key)
        if existing is None:
            raise RuntimeError("idempotency conflict result disappeared")
        return _decode(existing, duplicate=True)
