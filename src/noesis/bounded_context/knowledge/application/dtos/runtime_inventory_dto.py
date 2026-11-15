"""What one runtime has installed, as of one observation."""

from noesis.bounded_context.knowledge.application.dtos.installed_artifact_dto import (
    InstalledArtifactDto,
)
from noesis.bounded_context.knowledge.application.dtos.runtime_enum import RuntimeEnum
from noesis.bounded_context.knowledge.application.dtos.unreadable_kind_dto import UnreadableKindDto
from noesis.shared_kernel.application.dtos import BaseDto


class RuntimeInventoryDto(BaseDto):
    """What one runtime has installed, as of one observation.

    Attributes:
        runtime: The runtime.
        host: Name of the machine.
        observed_at: ISO-8601 UTC time of the observation.
        artifacts: What was found.
        unreadable_kinds: Kinds that could not be read, with the reason.
    """

    runtime: RuntimeEnum
    host: str
    observed_at: str
    artifacts: tuple[InstalledArtifactDto, ...] = ()
    unreadable_kinds: tuple[UnreadableKindDto, ...] = ()
