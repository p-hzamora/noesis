"""`IRuntimeInventoryProbe` for Claude Code: user, plugin and project skills and agents.

Reads, by name only: `<config>/skills/<name>/SKILL.md`, the plugin registry
`<config>/plugins/installed_plugins.json` (plugin names, install paths and versions), each
install's `skills/<s>/SKILL.md` and `agents/<a>.md`, and `<project>/.claude/skills|agents`.
Nothing is executed and no file content other than the registry is read.
"""

import json
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

from .inventory_support import agents_in, build_inventory, skills_in

REGISTRY: Path = Path("plugins") / "installed_plugins.json"


class _RegistryError(Exception):
    """The plugin registry cannot be read or does not have the expected shape."""


class ClaudeCodeRuntimeInventoryAdapter(IRuntimeInventoryProbe):
    """What Claude Code has installed for this user and project.

    A missing config folder, or a registry that is unreadable or malformed, reports `skill` and
    `agent` as `probe_failed` (plugin artifacts cannot be enumerated). A missing registry file
    in an existing config folder means no plugins are installed. `mcp_server` is never probed.

    Args:
        config_dir: Claude Code's configuration folder.
        project_root: The project the command runs in.
        clock: Stamps the observation.
        host: Name of this machine.
    """

    def __init__(self, *, config_dir: Path, project_root: Path, clock: IClock, host: str) -> None:
        self._config_dir: Path = config_dir
        self._project_root: Path = project_root
        self._clock: IClock = clock
        self._host: str = host

    @property
    def runtime(self) -> RuntimeEnum:
        """`claude-code`."""
        return RuntimeEnum.CLAUDE_CODE

    async def inventory(self) -> RuntimeInventoryDto:
        """What is installed now; never raises for an unreadable folder or registry."""
        artifacts: list[InstalledArtifactDto] = []
        unreadable: list[UnreadableKindDto] = []
        try:
            artifacts.extend(skills_in(self._config_dir / "skills"))
            artifacts.extend(self._plugin_artifacts())
        except _RegistryError, OSError:
            unreadable += [
                UnreadableKindDto(kind=kind, reason=AvailabilityReasonEnum.PROBE_FAILED)
                for kind in (CatalogEntryKindEnum.SKILL, CatalogEntryKindEnum.AGENT)
            ]
        claude_folder: Path = self._project_root / ".claude"
        try:
            artifacts.extend(skills_in(claude_folder / "skills"))
            artifacts.extend(agents_in(claude_folder / "agents"))
        except OSError:
            unreadable += [
                UnreadableKindDto(kind=kind, reason=AvailabilityReasonEnum.PROBE_FAILED)
                for kind in (CatalogEntryKindEnum.SKILL, CatalogEntryKindEnum.AGENT)
            ]
        unreadable.append(
            UnreadableKindDto(
                kind=CatalogEntryKindEnum.MCP_SERVER, reason=AvailabilityReasonEnum.KIND_NOT_PROBED
            )
        )
        return build_inventory(
            RuntimeEnum.CLAUDE_CODE,
            host=self._host,
            clock=self._clock,
            artifacts=artifacts,
            unreadable_kinds=unreadable,
        )

    def _plugin_artifacts(self) -> list[InstalledArtifactDto]:
        if not self._config_dir.is_dir():
            raise _RegistryError(f"{self._config_dir} is not a folder")
        registry: Path = self._config_dir / REGISTRY
        if not registry.exists():
            return []
        try:
            document: Any = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise _RegistryError(str(error)) from error
        plugins: Any = document.get("plugins") if isinstance(document, dict) else None
        if not isinstance(plugins, dict):
            raise _RegistryError("the registry has no `plugins` object")
        artifacts: list[InstalledArtifactDto] = []
        for key, installs in plugins.items():
            plugin: str = str(key).rsplit("@", 1)[0]
            if not isinstance(installs, list):
                raise _RegistryError(f"plugin {key!r} has no list of installs")
            for install in installs:
                if not isinstance(install, dict) or not isinstance(install.get("installPath"), str):
                    raise _RegistryError(f"plugin {key!r} has an install without installPath")
                version: Any = install.get("version")
                root: Path = Path(install["installPath"])
                observed: str | None = version if isinstance(version, str) else None
                artifacts.extend(skills_in(root / "skills", prefix=f"{plugin}:", version=observed))
                artifacts.extend(agents_in(root / "agents", prefix=f"{plugin}:", version=observed))
        return artifacts
