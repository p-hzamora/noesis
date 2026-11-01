"""A computed, not yet applied, change to an agent's hook settings."""

from noesis.shared_kernel.application.dtos import BaseDto


class AgentHookPlanDto(BaseDto):
    """What installing or removing the noesis hooks would do.

    Attributes:
        settings_file: The agent settings file.
        command: The hook command to register; None when the plan removes the hooks.
        changed: Whether the file would change.
        diff: Unified diff of the change (empty when nothing changes).
        after_text: Full text the file would have after the change.
        installed_before: Event -> noesis commands registered now.
        installed_after: Event -> noesis commands registered after the change.
    """

    settings_file: str
    command: str | None
    changed: bool
    diff: str
    after_text: str
    installed_before: dict[str, list[str]]
    installed_after: dict[str, list[str]]
