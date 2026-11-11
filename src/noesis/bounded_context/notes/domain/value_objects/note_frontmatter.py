"""The `noesis:` frontmatter block: a note's identity and provenance."""

from datetime import date

from noesis.shared_kernel.domain.value_objects import ValueObject

from .note_id import NoteId
from .note_kind import NoteKind
from .note_origin_enum import NoteOriginEnum
from .note_scope import NoteScope
from .note_source_ref import NoteSourceRef


class NoteFrontmatter(ValueObject):
    """What every noesis note declares about itself.

    Attributes:
        id: Stable id, kept across moves and renames.
        scope: Repository or topic the note belongs to.
        kind: What the note records.
        origin: `auto` (noesis wrote it) or `manual` (a person did).
        sources: Where the knowledge came from.
        updated: Last update date.
    """

    id: NoteId
    scope: NoteScope
    kind: NoteKind
    origin: NoteOriginEnum
    sources: tuple[NoteSourceRef, ...] = ()
    updated: date
