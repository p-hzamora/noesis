"""The record fields a note's header maps to."""

from noesis.bounded_context.interop.domain.value_objects.header_source import HeaderSource
from noesis.shared_kernel.domain.value_objects import ValueObject


class NoteMapping(ValueObject):
    """Header-derived fields of one note.

    Attributes:
        record_id: The note's declared ULID, or None.
        title: Mapped title.
        subtype: Subtype as written (Knowledge validates it).
        project_key: Project key as written, or None for space-wide.
        tags: Valid tags, lowercased, sorted and de-duplicated (without the origin tag).
        header_sources: Extra Sources, in header order, de-duplicated.
        sources_skipped: Header source entries that did not map.
        warnings: Warnings, `dropped_tag:<value>` included.
    """

    record_id: str | None = None
    title: str
    subtype: str
    project_key: str | None = None
    tags: tuple[str, ...] = ()
    header_sources: tuple[HeaderSource, ...] = ()
    sources_skipped: int = 0
    warnings: tuple[str, ...] = ()
