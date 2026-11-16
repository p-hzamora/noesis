"""Consistency boundary for a source record's imported outgoing links."""

from dataclasses import dataclass
from datetime import datetime

from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.bounded_context.knowledge.domain.value_objects.link_set_digest import LinkSetDigest
from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.exceptions import InvalidRecordError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class LinkSet(AggregateRoot["LinkSet"]):
    """Versioned set; it never changes the properties of endpoint records.

    Neo4j relationships lock both endpoints (the accepted C3b transaction-boundary deviation).
    No record change event is emitted: consumers do not yet index links.
    """

    source_record_id: RecordId
    space_id: SpaceId
    origin: str
    version: int
    digest: LinkSetDigest
    links: frozenset[RecordLink]
    updated_at: datetime

    def __post_init__(self) -> None:
        """Reject self links, duplicate target/kind pairs and invalid versions."""
        pairs: set[tuple[RecordId, str]] = {
            (link.target_record_id, link.link_type) for link in self.links
        }
        if self.version < 1 or len(pairs) != len(self.links):
            raise InvalidRecordError(
                "A link set needs a positive version and unique target/kind pairs."
            )
        if any(link.target_record_id == self.source_record_id for link in self.links):
            raise InvalidRecordError("A link set cannot link to its own source.")
        if self.digest != LinkSetDigest.of(self.links, self.origin):
            raise InvalidRecordError("The link-set digest does not match its content.")

    @classmethod
    def create(
        cls,
        *,
        source_record_id: RecordId,
        space_id: SpaceId,
        origin: str,
        version: int,
        links: frozenset[RecordLink],
        now: datetime,
    ) -> LinkSet:
        """Build a valid version and derive its digest inside Knowledge."""
        return cls(
            source_record_id=source_record_id,
            space_id=space_id,
            origin=origin,
            version=version,
            links=links,
            digest=LinkSetDigest.of(links, origin),
            created_at=now,
            updated_at=now,
        )
