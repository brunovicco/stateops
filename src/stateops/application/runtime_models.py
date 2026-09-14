"""Technology-neutral views returned by the workflow runtime."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RunResult:
    """One graph run that either completed or paused for input."""

    values: Mapping[str, object]
    interrupted: bool
    interrupts: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class CheckpointView:
    """Sanitized checkpoint metadata safe for application consumers."""

    checkpoint_id: str
    phase: str
    next_nodes: tuple[str, ...]
    created_at: datetime | None
    source: str | None
    step: int | None
