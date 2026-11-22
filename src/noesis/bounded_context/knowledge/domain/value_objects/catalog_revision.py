"""One immutable revision of a catalog entry."""

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from noesis.bounded_context.knowledge.domain.value_objects.actor import Actor
from noesis.bounded_context.knowledge.domain.value_objects.catalog_ref import CatalogRef
from noesis.bounded_context.knowledge.domain.value_objects.content_hash import ContentHash
from noesis.bounded_context.knowledge.domain.value_objects.enums import CatalogOriginEnum
from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.bounded_context.knowledge.domain.value_objects.tag import Tag
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.value_objects import ValueObject


def _not_blank(value: str, what: str) -> str:
    stripped: str = value.strip()
    if not stripped:
        raise InvalidRecordError(
            f"A catalog revision's {what} cannot be blank.", next_steps=[f"Provide a {what}."]
        )
    return stripped


class CatalogRevision(ValueObject):
    """What a catalog entry says about a capability at one point in time.

    Holds only runtime-neutral values the caller supplied: never an install path or a value a
    probe produced.

    Attributes:
        number: 1-based position; revisions are numbered without gaps.
        purpose: What it is for (redacted before it gets here).
        version: Declared version label, when it has one.
        prerequisites: What must be present to use it.
        location: Where its definition is version-controlled (URL, repository path or
            `plugin@marketplace`).
        actor: Who made the revision.
        source_ids: Sources it rests on; at least one.
        created_at: When this revision was made.
        capabilities: Tags naming what it supports; empty when none were stated.
        manifest_digest: Hash of the manifest file a sync read it from; None when registered by
            hand.
        origin: Whether a caller stated it (`registered`) or `catalog sync` found it
            (`discovered`).
    """

    number: int = Field(ge=1)
    purpose: str
    version: str | None = None
    prerequisites: tuple[CatalogRef, ...] = ()
    location: str
    actor: Actor
    source_ids: tuple[RecordId, ...]
    created_at: datetime
    capabilities: frozenset[Tag] = frozenset()
    manifest_digest: ContentHash | None = None
    origin: CatalogOriginEnum = CatalogOriginEnum.REGISTERED

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, value: str) -> str:
        return _not_blank(value, "purpose")

    @field_validator("location")
    @classmethod
    def _location(cls, value: str) -> str:
        return _not_blank(value, "location")

    @model_validator(mode="after")
    def _grounded(self) -> CatalogRevision:
        if not self.source_ids:
            raise InvalidRecordError(
                "A catalog revision needs at least one source.",
                next_steps=["Cite at least one source."],
            )
        return self

    def content_equals(self, other: CatalogRevision) -> bool:
        """Whether purpose, version, prerequisites and location are all the same."""
        return (
            self.purpose == other.purpose
            and self.version == other.version
            and self.prerequisites == other.prerequisites
            and self.location == other.location
        )
