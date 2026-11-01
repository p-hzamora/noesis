"""Which noesis hooks an agent's settings register."""

from noesis.shared_kernel.application.dtos import BaseDto


class AgentHooksDto(BaseDto):
    """What `noesis integrate claude-code status` shows.

    Attributes:
        settings_file: The agent settings file that was inspected.
        installed: Event name -> noesis commands registered for it.
        missing_events: Events noesis needs but that have no noesis hook yet.
    """

    settings_file: str
    installed: dict[str, list[str]]
    missing_events: list[str]
