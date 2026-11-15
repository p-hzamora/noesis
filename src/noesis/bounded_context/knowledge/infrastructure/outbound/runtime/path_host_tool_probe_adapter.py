"""`IHostToolProbe` over `shutil.which` on the process `PATH`."""

import shutil

from noesis.bounded_context.knowledge.application.dtos import (
    InstalledArtifactDto,
)
from noesis.bounded_context.knowledge.application.ports.runtime import IHostToolProbe
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum


class PathHostToolProbeAdapter(IHostToolProbe):
    """Looks names up on `PATH`; executes nothing, so versions are not observed.

    Args:
        path: The `PATH` to search; None uses the process `PATH`.
    """

    def __init__(self, *, path: str | None = None) -> None:
        self._path: str | None = path

    def find(self, names: tuple[str, ...]) -> tuple[InstalledArtifactDto, ...]:
        """The requested names that resolve to an executable, in the order asked."""
        found: list[InstalledArtifactDto] = []
        for name in dict.fromkeys(names):
            location: str | None = shutil.which(name, path=self._path)
            if location is not None:
                found.append(
                    InstalledArtifactDto(
                        kind=CatalogEntryKindEnum.CLI_TOOL, name=name, install_location=location
                    )
                )
        return tuple(found)
