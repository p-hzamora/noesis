"""Mapping an aggregate's domain events to change-feed entries (Q-009)."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    ChangeKind,
    ChangeRecordType,
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.domain.events import (
    ExperienceRecorded,
    KnowledgeProposed,
    KnowledgeRevised,
)
from noesis.shared_kernel.domain.events import DomainEvent


def pending_changes_from(
    events: Iterable[DomainEvent[Any]],
    *,
    record_type: ChangeRecordType,
    status: str | None,
    occurred_at: datetime,
) -> list[PendingRecordChange]:
    """The feed entries of `events`, in order.

    Only Knowledge and Experience events produce a change; space, project and source events
    produce none (the feed carries no change for them).

    Args:
        events: Events collected from one aggregate.
        record_type: Type of that aggregate.
        status: The aggregate's stored status; null for types without status.
        occurred_at: Knowledge's clock time of the write, stamped on every change.
    """
    changes: list[PendingRecordChange] = []
    for event in events:
        kind: ChangeKind
        number: int | None
        match event:
            case KnowledgeProposed(revision=revision):
                kind, number = "created", revision
            case KnowledgeRevised(revision=revision):
                kind, number = "revised", revision
            case ExperienceRecorded():
                kind, number = "created", None
            case _:
                continue
        changes.append(
            PendingRecordChange(
                space_id=event.space_id,
                record_id=event.aggregate_id,
                record_type=record_type,
                change_kind=kind,
                revision=number,
                status=status,
                occurred_at=occurred_at,
            )
        )
    return changes
