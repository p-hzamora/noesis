"""What the runtime probes share: reading the file system by name only, never by content."""

from collections.abc import Iterator
from pathlib import Path

from noesis.bounded_context.knowledge.application.dtos import (
    InstalledArtifactDto,
    RuntimeEnum,
    RuntimeInventoryDto,
    UnreadableKindDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.ports.clock import IClock

SKILL_FILE: str = "SKILL.md"


def skills_in(
    folder: Path, *, prefix: str = "", version: str | None = None
) -> Iterator[InstalledArtifactDto]:
    """A `skill` per `<folder>/<name>/SKILL.md`; only the file's presence is tested.

    Raises:
        OSError: The folder exists but cannot be listed (the caller reports `probe_failed`).
    """
    if not folder.is_dir():
        return
    for child in sorted(folder.iterdir()):
        if (child / SKILL_FILE).is_file():
            yield InstalledArtifactDto(
                kind=CatalogEntryKindEnum.SKILL,
                name=f"{prefix}{child.name}",
                observed_version=version,
                install_location=str(child),
            )


def agents_in(
    folder: Path, *, prefix: str = "", version: str | None = None
) -> Iterator[InstalledArtifactDto]:
    """An `agent` per `<folder>/<name>.md`."""
    if not folder.is_dir():
        return
    for agent_file in sorted(folder.iterdir()):
        if agent_file.suffix == ".md" and agent_file.is_file():
            yield InstalledArtifactDto(
                kind=CatalogEntryKindEnum.AGENT,
                name=f"{prefix}{agent_file.stem}",
                observed_version=version,
                install_location=str(agent_file),
            )


def build_inventory(
    runtime: RuntimeEnum,
    *,
    host: str,
    clock: IClock,
    artifacts: list[InstalledArtifactDto],
    unreadable_kinds: list[UnreadableKindDto],
) -> RuntimeInventoryDto:
    """The inventory of one observation, stamped now (UTC, ISO-8601).

    An artifact found twice (same kind and name) is listed once, the first find.
    """
    unique: dict[tuple[CatalogEntryKindEnum, str], InstalledArtifactDto] = {}
    for artifact in artifacts:
        unique.setdefault((artifact.kind, artifact.name), artifact)
    return RuntimeInventoryDto(
        runtime=runtime,
        host=host,
        observed_at=clock.now().isoformat(),
        artifacts=tuple(unique.values()),
        unreadable_kinds=tuple(dict.fromkeys(unreadable_kinds)),
    )
