"""Knowledge-local link requests and results, independent of interop contracts."""

from typing import Literal

from noesis.bounded_context.knowledge.domain.value_objects import Actor, Key, RecordId, Tag
from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.bounded_context.knowledge.domain.value_objects.record_relation import RecordRelation
from noesis.shared_kernel.application.dtos import BaseDto
from noesis.utils import FrozenObject


class LinkSetRequest(FrozenObject):
    """Replace or assess the complete set for one source."""

    space_key: Key
    source_record_id: RecordId
    origin_tag: Tag
    links: tuple[RecordLink, ...]
    actor: Actor
    relations: tuple[RecordRelation, ...] = ()


class LinkSetResultDto(BaseDto):
    """A per-source outcome; store failures propagate instead."""

    outcome: Literal["created", "replaced", "unchanged", "blocked"]
    source_record_id: str
    edges: int
    block_reason: (
        Literal["record_not_found", "target_not_in_space", "idempotency_key_reused"] | None
    ) = None
    replayed: bool = False
