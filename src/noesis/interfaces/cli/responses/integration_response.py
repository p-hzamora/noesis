"""`noesis integrate claude-code` output."""

from pydantic import Field

from noesis.utils import FrozenObject


class IntegrationResponse(FrozenObject):
    """`noesis integrate claude-code install|uninstall|status`.

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
