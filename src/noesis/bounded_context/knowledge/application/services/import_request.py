"""The validated request both import handlers take, and its prepared (redacted) form."""

from dataclasses import dataclass

from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ContentHash,
    GraphContent,
    ImportOnChangeEnum,
    Key,
    RecordId,
    Slug,
    SourceKindEnum,
    SpaceId,
    Tag,
)
from noesis.utils import FrozenObject


class ImportHeaderSource(FrozenObject):
    """An extra Source a note's header cites.

    Attributes:
        kind: Source kind other than `file_version`.
        locator: Where to find it.
    """

    kind: SourceKindEnum
    locator: str


class ImportRequest(FrozenObject):
    """One note or file to import, with every field a C2 value object.

    Attributes:
        space_key: Key of the active space.
        record_id: The id the note declares; None to mint one.
        origin_tag: `origin:migrated` or `origin:imported`; added to the record's tags.
        title: Title, not redacted.
        body: Text, not redacted.
        subtype: Subtype of a record created now.
        project_key: Project of a record created now; None means space-wide.
        tags: Tags of a record created now, without the origin tag.
        source_locator: Locator of the `file_version` Source.
        source_digest: Digest of the file bytes.
        header_sources: Extra Sources, in header order.
        actor: Who runs the import.
        on_change: Whether a changed note is reported or applied.
    """

    space_key: Key
    record_id: RecordId | None = None
    origin_tag: Tag
    title: str
    body: str
    subtype: Slug
    project_key: Key | None = None
    tags: tuple[Tag, ...] = ()
    source_locator: str
    source_digest: ContentHash
    header_sources: tuple[ImportHeaderSource, ...] = ()
    actor: Actor
    on_change: ImportOnChangeEnum


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedImport:
    """A request after validation, redaction and space resolution.

    Attributes:
        space_id: The active space.
        request: The request with title, body and locators redacted and stripped as stored.
        content: The incoming title and text as they will be stored.
    """

    space_id: SpaceId
    request: ImportRequest
    content: GraphContent
