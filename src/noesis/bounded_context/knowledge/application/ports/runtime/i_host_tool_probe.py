"""Looks up command-line tools on the host."""

import abc

from noesis.bounded_context.knowledge.application.dtos import (
    InstalledArtifactDto,
)


class IHostToolProbe(abc.ABC):
    """Finds executables by name; `PATH` is host-wide, so the result holds for every runtime."""

    @abc.abstractmethod
    def find(self, names: tuple[str, ...]) -> tuple[InstalledArtifactDto, ...]:
        """The requested names that were found, as `cli_tool` artifacts without a version.

        Nothing is executed, so tool versions are not observed.
        """
        ...
