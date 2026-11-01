"""Outcome of installing or removing the noesis hooks."""

from noesis.shared_kernel.application.dtos import BaseDto


class AgentHookChangeDto(BaseDto):
    """What `noesis integrate claude-code install|uninstall` reports.

    Attributes:
        settings_file: The agent settings file.
        command: The hook command registered (install only).
        changed: Whether the file would change.
        applied: Whether the change was written.
        backup: Copy of the previous file, when one was written.
        diff: Unified diff of the change (empty when nothing changes).
        installed: Event -> noesis commands registered after the operation.
    """

    settings_file: str
    command: str | None
    changed: bool
    applied: bool
    backup: str | None
    diff: str
    installed: dict[str, list[str]]
