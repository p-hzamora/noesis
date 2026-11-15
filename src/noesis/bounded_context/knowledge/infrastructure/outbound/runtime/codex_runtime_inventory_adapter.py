"""`IRuntimeInventoryProbe` for Codex: the skills of its configured plugins.

Reads `<codex home>/config.toml` only for the names of the `[plugins."<plugin>@<marketplace>"]`
tables (no value is copied anywhere), then looks for
`<codex home>/plugins/cache/<marketplace>/<plugin>/<version>/skills/<s>/SKILL.md`.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

from noesis.bounded_context.knowledge.application.dtos import (
    AvailabilityReasonEnum,
    InstalledArtifactDto,
    RuntimeEnum,
    RuntimeInventoryDto,
    UnreadableKindDto,
)
from noesis.bounded_context.knowledge.application.ports.runtime import IRuntimeInventoryProbe
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum
from noesis.shared_kernel.application.ports.clock import IClock

from .inventory_support import build_inventory, skills_in

_NUMBER: re.Pattern[str] = re.compile(r"\d+")


class _ConfigError(Exception):
    """The Codex home or its `config.toml` cannot be read."""


class CodexRuntimeInventoryAdapter(IRuntimeInventoryProbe):
    """What Codex has installed.

    A missing Codex home, or a `config.toml` that is unreadable or not valid TOML, reports
    `skill` as `probe_failed`. A missing `config.toml` in an existing home means no plugins.
    `agent` and `mcp_server` are never probed. When several versions of a plugin are cached,
    the highest one is listed.

    Args:
        codex_home: Codex's home folder (`CODEX_HOME`, default `~/.codex`).
        clock: Stamps the observation.
        host: Name of this machine.
    """

    def __init__(self, *, codex_home: Path, clock: IClock, host: str) -> None:
        self._codex_home: Path = codex_home
        self._clock: IClock = clock
        self._host: str = host

    @property
    def runtime(self) -> RuntimeEnum:
        """`codex`."""
        return RuntimeEnum.CODEX

    async def inventory(self) -> RuntimeInventoryDto:
        """What is installed now; never raises for an unreadable home or configuration."""
        artifacts: list[InstalledArtifactDto] = []
        unreadable: list[UnreadableKindDto] = []
        try:
            artifacts.extend(self._plugin_skills())
        except _ConfigError:
            unreadable.append(
                UnreadableKindDto(
                    kind=CatalogEntryKindEnum.SKILL, reason=AvailabilityReasonEnum.PROBE_FAILED
                )
            )
        unreadable += [
            UnreadableKindDto(kind=kind, reason=AvailabilityReasonEnum.KIND_NOT_PROBED)
            for kind in (CatalogEntryKindEnum.AGENT, CatalogEntryKindEnum.MCP_SERVER)
        ]
        return build_inventory(
            RuntimeEnum.CODEX,
            host=self._host,
            clock=self._clock,
            artifacts=artifacts,
            unreadable_kinds=unreadable,
        )

    def _plugin_skills(self) -> list[InstalledArtifactDto]:
        if not self._codex_home.is_dir():
            raise _ConfigError(f"{self._codex_home} is not a folder")
        config: Path = self._codex_home / "config.toml"
        if not config.exists():
            return []
        try:
            document: dict[str, Any] = tomllib.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise _ConfigError(str(error)) from error
        plugins: Any = document.get("plugins", {})
        if not isinstance(plugins, dict):
            raise _ConfigError("`plugins` is not a table")
        artifacts: list[InstalledArtifactDto] = []
        try:
            for key in plugins:
                plugin, separator, marketplace = str(key).rpartition("@")
                if not separator:
                    continue
                cache: Path = self._codex_home / "plugins" / "cache" / marketplace / plugin
                version: Path | None = _newest(cache)
                if version is not None:
                    artifacts.extend(
                        skills_in(version / "skills", prefix=f"{plugin}:", version=version.name)
                    )
        except OSError as error:
            raise _ConfigError(str(error)) from error
        return artifacts


def _newest(cache: Path) -> Path | None:
    """The cached version folder with the highest version (numeric parts, then name)."""
    if not cache.is_dir():
        return None
    versions: list[Path] = [path for path in cache.iterdir() if path.is_dir()]
    return max(
        versions,
        key=lambda path: ([int(part) for part in _NUMBER.findall(path.name)], path.name),
        default=None,
    )
