"""An entry with the envelope of one requested revision (the head by default)."""

from datetime import datetime

from noesis.bounded_context.knowledge.application.dtos.catalog_entry_dto import CatalogEntryDto


class CatalogEntryDetailDto(CatalogEntryDto):
    """An entry with the envelope of one requested revision (the head by default).

    `purpose`, `declared_version`, `prerequisites` and `location` are those of that revision.

    Attributes:
        number: Number of the revision shown.
        actor_kind: `user` or `agent`.
        actor_name: Who made the revision.
        actor_session: Harness session, when known.
        created_at: When the revision was made.
        source_ids: Sources the revision cites.
    """

    number: int
    actor_kind: str
    actor_name: str
    actor_session: str | None = None
    created_at: datetime
    source_ids: tuple[str, ...] = ()
