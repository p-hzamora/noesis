"""What the runtime probes share: listing artifacts and reading only their manifest frontmatter.

A manifest's body is never read into memory beyond the first 16 KiB and never stored; the whole
file is only hashed.
"""

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from noesis.bounded_context.knowledge.application.dtos import (
    InstalledArtifactDto,
    RuntimeEnum,
    RuntimeInventoryDto,
    UnreadableKindDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.ports.clock import IClock

SKILL_FILE: str = "SKILL.md"
MAX_FRONTMATTER_BYTES: int = 16 * 1024
_CHUNK_BYTES: int = 64 * 1024
_FENCE: re.Pattern[str] = re.compile(r"^---[ \t]*$")


@dataclass(frozen=True, slots=True)
class ManifestFacts:
    """What a manifest file tells a probe.

    Attributes:
        description: Frontmatter `description`, whitespace-collapsed; None when missing, not
            text, malformed or in a frontmatter block that does not close within 16 KiB.
        digest: `sha256:<hex>` of the whole file; None when the file cannot be read.
        requires: Raw `metadata.noesis.requires` values that are text.
    """

    description: str | None = None
    digest: str | None = None
    requires: tuple[str, ...] = ()


def read_manifest(path: Path) -> ManifestFacts:
    """The description, whole-file digest and declared requirements of one manifest.

    Reads the first 16 KiB for the frontmatter and streams the rest only into the hash. Never
    raises: an unreadable file yields no facts, a malformed frontmatter yields only the digest.
    """
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            head: bytes = stream.read(MAX_FRONTMATTER_BYTES)
            hasher.update(head)
            while chunk := stream.read(_CHUNK_BYTES):
                hasher.update(chunk)
    except OSError:
        return ManifestFacts()
    digest: str = f"sha256:{hasher.hexdigest()}"
    metadata: dict[str, Any] | None = _frontmatter(head.decode("utf-8", errors="replace"))
    if metadata is None:
        return ManifestFacts(digest=digest)
    return ManifestFacts(
        description=_description(metadata.get("description")),
        digest=digest,
        requires=_requires(metadata.get("metadata")),
    )


def _frontmatter(text: str) -> dict[str, Any] | None:
    lines: list[str] = text.splitlines()
    if not lines or not _FENCE.match(lines[0].lstrip("\ufeff")):
        return None
    for index in range(1, len(lines)):
        if _FENCE.match(lines[index]):
            try:
                loaded: Any = yaml.safe_load("\n".join(lines[1:index]))
            except yaml.YAMLError:
                return None
            return loaded if isinstance(loaded, dict) else None
    return None


def _description(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    collapsed: str = " ".join(value.split())
    return collapsed or None


def _requires(metadata: Any) -> tuple[str, ...]:
    noesis: Any = metadata.get("noesis") if isinstance(metadata, dict) else None
    requires: Any = noesis.get("requires") if isinstance(noesis, dict) else None
    if not isinstance(requires, list):
        return ()
    return tuple(item.strip() for item in requires if isinstance(item, str) and item.strip())


def skills_in(
    folder: Path, *, prefix: str = "", version: str | None = None
) -> Iterator[InstalledArtifactDto]:
    """A `skill` per `<folder>/<name>/SKILL.md`, with the facts of its manifest.

    Raises:
        OSError: The folder exists but cannot be listed (the caller reports `probe_failed`).
    """
    if not folder.is_dir():
        return
    for child in sorted(folder.iterdir()):
        manifest: Path = child / SKILL_FILE
        if manifest.is_file():
            facts: ManifestFacts = read_manifest(manifest)
            yield InstalledArtifactDto(
                kind=CatalogEntryKindEnum.SKILL,
                name=f"{prefix}{child.name}",
                observed_version=version,
                install_location=str(child),
                description=facts.description,
                manifest_digest=facts.digest,
                declared_requires=facts.requires,
            )


def agents_in(
    folder: Path, *, prefix: str = "", version: str | None = None
) -> Iterator[InstalledArtifactDto]:
    """An `agent` per `<folder>/<name>.md`, with the facts of its manifest."""
    if not folder.is_dir():
        return
    for agent_file in sorted(folder.iterdir()):
        if agent_file.suffix == ".md" and agent_file.is_file():
            facts: ManifestFacts = read_manifest(agent_file)
            yield InstalledArtifactDto(
                kind=CatalogEntryKindEnum.AGENT,
                name=f"{prefix}{agent_file.stem}",
                observed_version=version,
                install_location=str(agent_file),
                description=facts.description,
                manifest_digest=facts.digest,
                declared_requires=facts.requires,
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
