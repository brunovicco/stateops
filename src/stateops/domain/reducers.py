"""Deterministic reducers for concurrently written graph channels."""

from collections.abc import Callable

from stateops.domain.models import (
    Evidence,
    Hypothesis,
    RemediationAction,
    TimelineEvent,
    WorkflowError,
)


def _merge_by_key[T](
    left: list[T], right: list[T], *, key: Callable[[T], tuple[object, ...]]
) -> list[T]:
    merged = {key(item): item for item in left}
    merged.update({key(item): item for item in right})
    return [merged[item_key] for item_key in sorted(merged, key=repr)]


def merge_hypotheses(left: list[Hypothesis], right: list[Hypothesis]) -> list[Hypothesis]:
    """Merge hypotheses by stable identity independently of branch completion order."""
    return _merge_by_key(left, right, key=lambda item: (item.id,))


def merge_evidence(left: list[Evidence], right: list[Evidence]) -> list[Evidence]:
    """Merge parallel evidence by stable identity."""
    return _merge_by_key(left, right, key=lambda item: (item.id,))


def merge_actions(
    left: list[RemediationAction], right: list[RemediationAction]
) -> list[RemediationAction]:
    """Merge remediation candidates by action identity and revision."""
    return _merge_by_key(left, right, key=lambda item: (item.id, item.revision))


def merge_errors(left: list[WorkflowError], right: list[WorkflowError]) -> list[WorkflowError]:
    """Merge metadata-safe errors by stable identity."""
    return _merge_by_key(left, right, key=lambda item: (item.id,))


def merge_timeline(left: list[TimelineEvent], right: list[TimelineEvent]) -> list[TimelineEvent]:
    """Deduplicate events and sort by timestamp then stable identity."""
    merged = {item.id: item for item in (*left, *right)}
    return sorted(merged.values(), key=lambda item: (item.occurred_at, item.id))
