"""Knowledge value objects."""

from noesis.bounded_context.knowledge.domain.value_objects.curation_decision import (
    CurationActionEnum,
    CurationDecision,
    NoteDraft,
)
from noesis.bounded_context.knowledge.domain.value_objects.note_area import NoteArea
from noesis.bounded_context.knowledge.domain.value_objects.note_kind_enum import NoteKindEnum
from noesis.bounded_context.knowledge.domain.value_objects.note_location import NoteLocation
from noesis.bounded_context.knowledge.domain.value_objects.note_origin_enum import NoteOriginEnum
from noesis.bounded_context.knowledge.domain.value_objects.note_section import NoteSection
from noesis.bounded_context.knowledge.domain.value_objects.note_slug import NoteSlug

__all__ = [
    "CurationActionEnum",
    "CurationDecision",
    "NoteArea",
    "NoteDraft",
    "NoteKindEnum",
    "NoteLocation",
    "NoteOriginEnum",
    "NoteSection",
    "NoteSlug",
]
