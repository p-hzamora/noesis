"""`noesis integrate claude-code` output."""

from abc import ABC

from pydantic import Field

from .i_renderable_response import IRenderableResponse


class IntegrationBaseResponse(IRenderableResponse, ABC):
    """Fields shared by every `noesis integrate claude-code` response.

    Attributes:
        settings_file: The settings file.
        command: The hook command noesis registers (install only).
        changed: Whether the file would change.
        applied: Whether the change was written.
        backup: Copy of the previous file, when one was written.
        diff: Unified diff of the change.
        installed: Event -> noesis commands registered after the operation.
        missing_events: Events noesis needs that have no hook yet (status only).
        warning: Advice about the registered command, when it looks wrong.
    """

    settings_file: str
    command: str | None = None
    changed: bool = False
    applied: bool = False
    backup: str | None = None
    diff: str = ""
    installed: dict[str, list[str]]
    missing_events: list[str] = Field(default_factory=list)
    warning: str | None = None

    def _installed_lines(self) -> list[str]:
        return [f"{event}: {', '.join(commands)}" for event, commands in self.installed.items()]


class IntegrationResponse(IntegrationBaseResponse):
    """`noesis integrate claude-code install|uninstall`: what changed in the settings file."""

    def render(self) -> str:
        lines: list[str] = []
        if self.diff:
            lines.append(self.diff.rstrip("\n"))
        if not self.changed:
            lines.append(f"{self.settings_file}: already up to date")
        elif self.applied:
            lines.append(
                f"wrote {self.settings_file}" + (f" (backup: {self.backup})" if self.backup else "")
            )
            lines.append("Restart Claude Code sessions so they load the hooks.")
        else:
            lines.append("Preview only. Re-run with --yes to write this change.")
        lines += self._installed_lines()
        if self.warning:
            lines.append(f"warning: {self.warning}")
        return "\n".join(lines)


class IntegrationStatusResponse(IntegrationBaseResponse):
    """`noesis integrate claude-code status`: which hooks are registered."""

    def render(self) -> str:
        missing: str = (
            "installed" if not self.missing_events else "missing " + ", ".join(self.missing_events)
        )
        return "\n".join([f"{self.settings_file}: {missing}", *self._installed_lines()])
