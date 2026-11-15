"""An installed artifact with no entry of the same kind and name."""

from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class UncatalogedArtifactDto(BaseDto):
    """An installed artifact with no entry of the same kind and name.

    Attributes:
        kind: Artifact kind.
        name: Artifact name.
        observed_version: Installed version, when known.
    """

    kind: CatalogEntryKindEnum
    name: str
    observed_version: str | None = None
