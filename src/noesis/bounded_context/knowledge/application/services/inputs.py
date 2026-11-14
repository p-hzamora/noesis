"""Inputs several Knowledge commands share: a project reference and a source."""

from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    Key,
    RecordId,
    SourceKindEnum,
)
from noesis.utils import FrozenObject


class ProjectRef(FrozenObject):
    """A project named by key; created on first use.

    Attributes:
        key: Project key (the git root name).
        name: Display name for a project created now; defaults to the key.
    """

    key: Key
    name: str | None = None


class ExistingSourceInput(FrozenObject):
    """A Source that already exists, cited by id.

    Attributes:
        source_id: Id of the Source; it must belong to the command's space.
    """

    source_id: RecordId


class NewSourceInput(FrozenObject):
    """A Source described by its natural key; recorded if unknown.

    Attributes:
        kind: What the source is.
        locator: Where to find it.
        digest: Content hash, when known.
    """

    kind: SourceKindEnum
    locator: str
    digest: ContentHash | None = None


type SourceInput = ExistingSourceInput | NewSourceInput
