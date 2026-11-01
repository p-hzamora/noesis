"""Adding and removing noesis hooks in a Claude Code settings object."""

import pytest

from noesis.bounded_context.capture.infrastructure.outbound.agent_hooks import (
    installed_commands,
    is_noesis_handler,
    with_noesis,
    without_noesis,
)
from noesis.shared_kernel.domain import (
    JsonObject,
)

pytestmark = pytest.mark.unit

COMMAND: str = "/home/u/.local/bin/noesis hook claude-code"
FOREIGN: JsonObject = {
    "model": "opus",
    "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "other-tool"}]}],
        "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt"}]}],
    },
}


def test_install_adds_one_handler_per_event_and_keeps_foreign_hooks() -> None:
    settings: JsonObject = with_noesis(FOREIGN, COMMAND)

    assert settings["model"] == "opus"
    assert installed_commands(settings) == {
        "Stop": [COMMAND],
        "PostToolUse": [COMMAND],
        "SessionEnd": [COMMAND],
    }
    post_tool_use = settings["hooks"]["PostToolUse"]  # type: ignore[index]
    assert post_tool_use[0] == FOREIGN["hooks"]["PostToolUse"][0]  # type: ignore[index]
    assert post_tool_use[1] == {
        "matcher": "Bash",
        "hooks": [
            {"type": "command", "command": COMMAND, "if": "Bash(git commit*)", "async": True}
        ],
    }
    assert settings["hooks"]["SessionEnd"] == [{"hooks": [{"type": "command", "command": COMMAND}]}]  # type: ignore[index]


def test_install_is_idempotent_and_replaces_an_older_command() -> None:
    once: JsonObject = with_noesis(FOREIGN, "old/noesis hook claude-code")

    twice: JsonObject = with_noesis(with_noesis(once, COMMAND), COMMAND)

    assert twice == with_noesis(FOREIGN, COMMAND)


def test_uninstall_restores_the_original_settings() -> None:
    assert without_noesis(with_noesis(FOREIGN, COMMAND)) == FOREIGN
    assert without_noesis(with_noesis({}, COMMAND)) == {}
    assert without_noesis({"hooks": "unexpected"}) == {"hooks": "unexpected"}


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        ({"type": "command", "command": COMMAND}, True),
        ({"type": "command", "command": "python -m noesis hook claude-code"}, True),
        ({"type": "command", "command": "noesis capture status"}, False),
        ({"type": "command", "command": "other hook claude-code"}, False),
        ("not a dict", False),
    ],
)
def test_only_noesis_hook_handlers_are_recognised(handler: object, expected: bool) -> None:
    assert is_noesis_handler(handler) is expected  # type: ignore[arg-type]
