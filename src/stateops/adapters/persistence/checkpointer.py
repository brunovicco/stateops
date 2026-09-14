"""Redis checkpointer lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.checkpoint.redis.jsonplus_redis import JsonPlusRedisSerializer
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_CHECKPOINT_TYPES = (
    ("stateops.domain.enums", "ActionKind"),
    ("stateops.domain.enums", "ApprovalOutcome"),
    ("stateops.domain.enums", "ExecutionStatus"),
    ("stateops.domain.enums", "IncidentPhase"),
    ("stateops.domain.enums", "Severity"),
    ("stateops.domain.models", "ApprovalDecision"),
    ("stateops.domain.models", "Evidence"),
    ("stateops.domain.models", "ExecutionResult"),
    ("stateops.domain.models", "Hypothesis"),
    ("stateops.domain.models", "IncidentContext"),
    ("stateops.domain.models", "IncidentRecord"),
    ("stateops.domain.models", "RemediationAction"),
    ("stateops.domain.models", "RootCause"),
    ("stateops.domain.models", "Signal"),
    ("stateops.domain.models", "TimelineEvent"),
    ("stateops.domain.models", "VerificationResult"),
    ("stateops.domain.models", "WorkflowError"),
)
_CHECKPOINT_JSON_TYPES = tuple((*module.split("."), name) for module, name in _CHECKPOINT_TYPES)


class StateOpsRedisSerializer(JsonPlusRedisSerializer):
    """Redis serializer that blocks non-allowlisted dataclass constructors."""

    def _constructor_class(self, obj: dict[str, Any]) -> type[Any]:
        identity = obj.get("id")
        if not isinstance(identity, list) or tuple(identity) not in _CHECKPOINT_JSON_TYPES:
            raise ValueError("checkpoint constructor is not allowlisted")
        return super()._constructor_class(obj)


def checkpoint_serializer() -> JsonPlusSerializer:
    """Create the restricted serializer used by in-memory tests."""
    return JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES)


def redis_checkpoint_serializer() -> StateOpsRedisSerializer:
    """Create the Redis JSON serializer with exact constructor allowlists."""
    return StateOpsRedisSerializer(
        allowed_json_modules=_CHECKPOINT_JSON_TYPES,
        allowed_msgpack_modules=_CHECKPOINT_TYPES,
    )


def memory_checkpointer() -> InMemorySaver:
    """Create an isolated checkpointer for deterministic tests only."""
    return InMemorySaver(serde=checkpoint_serializer())


@asynccontextmanager
async def redis_checkpointer(redis_url: str) -> AsyncIterator[AsyncRedisSaver]:
    """Open and initialize the production async Redis checkpointer."""
    saver = AsyncRedisSaver(redis_url)
    saver.serde = redis_checkpoint_serializer()
    async with saver:
        yield saver
