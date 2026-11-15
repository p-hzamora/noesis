"""An `available` entry whose declared and installed versions differ."""

from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class VersionDriftDto(BaseDto):
    """An `available` entry whose declared and installed versions differ.

    Attributes:
        entry_id: The entry.
        kind: Entry kind.
        name: Entry name.
        declared_version: Version the catalog declares.
        observed_version: Version installed.
    """

    entry_id: str
    kind: CatalogEntryKindEnum
    name: str
    declared_version: str
    observed_version: str
