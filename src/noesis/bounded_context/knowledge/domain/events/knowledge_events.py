"""Domain events of the Knowledge context; internal to it in C2 (no outbox, D-008).

Every event names its aggregate in `aggregate_id`; the fields below add what happened.
"""

from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    ExperienceSubtypeEnum,
    Key,
    OwnershipEnum,
    SourceKindEnum,
)
from noesis.shared_kernel.domain.events import DomainEvent


class KnowledgeSpaceCreated(DomainEvent[object]):
    """A knowledge space came into existence."""

    key: Key


class ProjectRegistered(DomainEvent[object]):
    """A project was registered in a space."""

    space_id: str
    key: Key


class SourceRecorded(DomainEvent[object]):
    """A source was recorded for the first time."""

    space_id: str
    kind: SourceKindEnum


class KnowledgeProposed(DomainEvent[object]):
    """Knowledge was created as a proposal, at revision 1."""

    space_id: str
    ownership: OwnershipEnum
    revision: int


class KnowledgeRevised(DomainEvent[object]):
    """Proposed knowledge received a new revision."""

    space_id: str
    revision: int


class ExperienceRecorded(DomainEvent[object]):
    """An experience was recorded."""

    space_id: str
    subtype: ExperienceSubtypeEnum


class AssertionProposed(DomainEvent[object]):
    """An assertion was created as a proposal."""

    space_id: str


class CatalogEntryRegistered(DomainEvent[object]):
    """A catalog entry was registered."""

    space_id: str
    kind: CatalogEntryKindEnum


class CatalogEntryRevised(DomainEvent[object]):
    """A catalog entry received a new revision."""

    space_id: str
    revision: int
