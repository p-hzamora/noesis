"""Something found installed."""

from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.dtos import BaseDto


class InstalledArtifactDto(BaseDto):
    """Something found installed.

    Attributes:
        kind: Entry kind it matches.
        name: Name; plugin artifacts are qualified `<plugin>:<name>`.
        observed_version: Installed version, when the runtime records one.
        install_location: Where it was found; in memory and output only, never stored.
    """

    kind: CatalogEntryKindEnum
    name: str
    observed_version: str | None = None
    install_location: str | None = None
