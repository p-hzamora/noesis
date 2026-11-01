"""`IAgentHookRegistry` over Claude Code's `settings.json`."""

import difflib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from noesis.bounded_context.capture.application.dtos import AgentHookPlanDto, AgentHooksDto
from noesis.bounded_context.capture.application.ports.agent_hooks import IAgentHookRegistry
from noesis.bounded_context.capture.infrastructure.outbound.agent_hooks.claude_code_hook_settings import (
    HOOK_SPECS,
    installed_commands,
    with_noesis,
    without_noesis,
)
from noesis.exceptions import (
    AgentSettingsInvalidError,
)
from noesis.shared_kernel.domain import (
    JsonObject,
)
from noesis.shared_kernel.infrastructure.outbound.persistence import write_text_atomic

BACKUP_SUFFIX: str = ".noesis-backup-"


class ClaudeCodeSettingsAdapter(IAgentHookRegistry):
    """Edits one Claude Code settings file; a missing file reads as an empty object."""

    def __init__(self, settings_file: Path) -> None:
        self._settings_file: Path = settings_file

    def _read(self) -> tuple[JsonObject, str]:
        """The settings object and its original text (`{}` and "" when the file is missing).

        Raises:
            AgentSettingsInvalidError: The file is not valid JSON or not a JSON object.
        """
        path: Path = self._settings_file
        if not path.is_file():
            return {}, ""
        text: str = path.read_text(encoding="utf-8")
        try:
            data: object = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as error:
            raise AgentSettingsInvalidError(
                f"{path} is not valid JSON: {error}",
                {"settings_file": str(path)},
                next_steps=[f"Fix {path} by hand, then run the command again."],
            ) from error
        if not isinstance(data, dict):
            raise AgentSettingsInvalidError(
                f"{path} is not a JSON object.", {"settings_file": str(path)}
            )
        return data, text

    @staticmethod
    def _render(settings: JsonObject) -> str:
        return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"

    async def status(self) -> AgentHooksDto:
        """The registered noesis hooks and the events that still lack one."""
        current, _ = self._read()
        installed: dict[str, list[str]] = installed_commands(current)
        return AgentHooksDto(
            settings_file=str(self._settings_file),
            installed=installed,
            missing_events=[spec.event for spec in HOOK_SPECS if spec.event not in installed],
        )

    async def plan(self, command: str | None) -> AgentHookPlanDto:
        """The change that registers `command` for every hook, or removes the hooks when None."""
        current, text = self._read()
        target: JsonObject = (
            without_noesis(current) if command is None else with_noesis(current, command)
        )
        after: str = self._render(target)
        changed: bool = after != self._render(current)
        diff: str = "".join(
            difflib.unified_diff(
                text.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=f"{self._settings_file} (now)", tofile=f"{self._settings_file} (after)",
            )
        )  # fmt: skip
        return AgentHookPlanDto(
            settings_file=str(self._settings_file),
            command=command,
            changed=changed,
            diff=diff if changed else "",
            after_text=after,
            installed_before=installed_commands(current),
            installed_after=installed_commands(target),
        )

    async def apply(self, plan: AgentHookPlanDto) -> str | None:
        """Back the current file up (timestamped), then replace it atomically."""
        path: Path = self._settings_file
        backup: Path | None = None
        if path.is_file():
            backup = path.with_name(f"{path.name}{BACKUP_SUFFIX}{datetime.now(UTC):%Y%m%dT%H%M%S}")
            shutil.copy2(path, backup)
        write_text_atomic(path, plan.after_text)
        return str(backup) if backup else None
