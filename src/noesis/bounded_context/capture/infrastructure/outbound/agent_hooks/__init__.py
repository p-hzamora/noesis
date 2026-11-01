"""Agent hook registries."""

from noesis.bounded_context.capture.infrastructure.outbound.agent_hooks.claude_code_hook_settings import (
    HOOK_SPECS,
    HOOK_SUBCOMMAND,
    HookSpec,
    installed_commands,
    is_noesis_handler,
    with_noesis,
    without_noesis,
)
from noesis.bounded_context.capture.infrastructure.outbound.agent_hooks.claude_code_settings_adapter import (
    ClaudeCodeSettingsAdapter,
)

__all__ = [
    "ClaudeCodeSettingsAdapter",
    "HOOK_SPECS",
    "HOOK_SUBCOMMAND",
    "HookSpec",
    "installed_commands",
    "is_noesis_handler",
    "with_noesis",
    "without_noesis",
]
