"""The scan of one runtime."""

from noesis.bounded_context.knowledge.application.dtos.not_installed_dto import NotInstalledDto
from noesis.bounded_context.knowledge.application.dtos.runtime_enum import RuntimeEnum
from noesis.bounded_context.knowledge.application.dtos.uncataloged_artifact_dto import (
    UncatalogedArtifactDto,
)
from noesis.bounded_context.knowledge.application.dtos.unreadable_kind_dto import UnreadableKindDto
from noesis.bounded_context.knowledge.application.dtos.version_drift_dto import VersionDriftDto
from noesis.shared_kernel.application.dtos import BaseDto


class ScanRuntimeDto(BaseDto):
    """The scan of one runtime.

    Attributes:
        runtime: The runtime.
        host: Machine observed.
        observed_at: ISO-8601 UTC time of the observation.
        uncataloged: Installed artifacts with no entry.
        version_drift: Entries whose installed version drifted.
        not_installed: Entries with no installed match.
        unreadable_kinds: Kinds that could not be read.
    """

    runtime: RuntimeEnum
    host: str
    observed_at: str
    uncataloged: tuple[UncatalogedArtifactDto, ...] = ()
    version_drift: tuple[VersionDriftDto, ...] = ()
    not_installed: tuple[NotInstalledDto, ...] = ()
    unreadable_kinds: tuple[UnreadableKindDto, ...] = ()
