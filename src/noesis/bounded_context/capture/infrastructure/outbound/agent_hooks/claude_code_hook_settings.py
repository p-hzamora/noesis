"""Pure functions that add, remove and inspect noesis hooks in a Claude Code settings object.

Only handlers whose command runs `noesis … hook claude-code` are ever touched; every other
hook, matcher and setting is preserved exactly. Installing twice gives the same result.
"""

import copy
from dataclasses import dataclass

from noesis.shared_kernel.domain import (
    JsonObject,
    JsonValue,
)

HOOK_SUBCOMMAND: str = "hook claude-code"
PROGRAM_MARKER: str = "noesis"


@dataclass(frozen=True, slots=True, kw_only=True)
class HookSpec:
    """One hook noesis registers.

    Attributes:
        event: Claude Code event name.
        matcher: Tool matcher for tool events.
        condition: Permission-rule filter (`if`), evaluated by Claude Code on tool events only.
        run_async: Whether Claude Code runs it in the background.
    """

    event: str
    matcher: str | None
    condition: str | None
    run_async: bool


HOOK_SPECS: tuple[HookSpec, ...] = (
    HookSpec(event="PostToolUse", matcher="Bash", condition="Bash(git commit*)", run_async=True),
    HookSpec(event="Stop", matcher=None, condition=None, run_async=True),
    HookSpec(
        event="SessionEnd", matcher=None, condition=None, run_async=False
    ),  # must finish before exit
)


def is_noesis_handler(handler: JsonValue) -> bool:
    """Whether a hook handler entry runs `noesis … hook claude-code`."""
    if not isinstance(handler, dict):
        return False
    command: JsonValue = handler.get("command")
    return isinstance(command, str) and PROGRAM_MARKER in command and HOOK_SUBCOMMAND in command


def without_noesis(settings: JsonObject) -> JsonObject:
    """A copy of `settings` with every noesis handler removed and emptied containers dropped."""
    result: JsonObject = copy.deepcopy(settings)
    hooks: JsonValue = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    for event in list(hooks):
        groups: JsonValue = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups: list[JsonValue] = []
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                handlers: list[JsonValue] = [h for h in group["hooks"] if not is_noesis_handler(h)]  # type: ignore[union-attr]
                if not handlers:
                    continue
                group = {**group, "hooks": handlers}
            kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        del result["hooks"]
    return result


def with_noesis(settings: JsonObject, command: str) -> JsonObject:
    """A copy of `settings` with exactly one noesis handler per `HOOK_SPECS` entry."""
    result: JsonObject = without_noesis(settings)
    hooks: JsonValue = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = result["hooks"] = {}
    for spec in HOOK_SPECS:
        handler: JsonObject = {"type": "command", "command": command}
        if spec.condition:
            handler["if"] = spec.condition
        if spec.run_async:
            handler["async"] = True
        group: JsonObject = {"hooks": [handler]}
        if spec.matcher:
            group = {"matcher": spec.matcher, **group}
        groups: JsonValue = hooks.setdefault(spec.event, [])
        if isinstance(groups, list):
            groups.append(group)
    return result


def installed_commands(settings: JsonObject) -> dict[str, list[str]]:
    """Event name -> noesis commands registered for it."""
    found: dict[str, list[str]] = {}
    hooks: JsonValue = settings.get("hooks")
    for event, groups in hooks.items() if isinstance(hooks, dict) else []:
        for group in groups if isinstance(groups, list) else []:
            handlers: JsonValue = group.get("hooks") if isinstance(group, dict) else None
            for handler in handlers if isinstance(handlers, list) else []:
                if is_noesis_handler(handler) and isinstance(handler, dict):
                    found.setdefault(event, []).append(str(handler.get("command")))
    return found
