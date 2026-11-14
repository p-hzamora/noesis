"""One immutable revision of a catalog entry."""

from datetime import datetime

from pydantic import Field

from noesis.shared_kernel.domain.value_objects import ValueObject


class CatalogRevision(ValueObject):
    """What a catalog entry says about a capability at one point in time.

    Attributes:
        number: 1-based position.
        purpose: What it is for.
        version: Version label, when it has one.
        prerequisites: What must be present to use it.
        location: Where it lives (path, URL, command), when known.
        created_at: When this revision was made.
    """

    number: int = Field(ge=1)
    purpose: str
    version: str | None = None
    prerequisites: tuple[str, ...] = ()
    location: str | None = None
    created_at: datetime
