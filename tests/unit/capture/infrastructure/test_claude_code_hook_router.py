"""Claude Code hook JSON translated into Capture commands."""

from pathlib import Path

import pytest

from noesis.bounded_context.capture.application.handlers.commands import (
    FlushCaptureCommand,
    RecordCommitCommand,
)
from noesis.bounded_context.capture.infrastructure.inbound.claude_code import (
    ClaudeCodeHookPayload,
    route,
)

pytestmark = pytest.mark.unit


def _payload(**fields: object) -> ClaudeCodeHookPayload:
    return ClaudeCodeHookPayload.model_validate({"session_id": "s1", "cwd": "/repo", **fields})


def test_a_bash_git_commit_becomes_record_commit() -> None:
    command = route(
        _payload(
            hook_event_name="PostToolUse",
            tool_name="Bash",
            tool_input={"command": "git commit -m x"},
        )
    )

    assert command == RecordCommitCommand(session_id="s1", cwd=Path("/repo"))


@pytest.mark.parametrize(
    "fields",
    [
        {"hook_event_name": "PostToolUse", "tool_name": "Edit"},
        {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
        {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": 3}},
        {"hook_event_name": "Unknown"},
        {"hook_event_name": "Stop", "session_id": ""},
    ],
)
def test_irrelevant_events_route_to_nothing(fields: dict[str, object]) -> None:
    assert route(_payload(**fields)) is None


@pytest.mark.parametrize(("event", "final"), [("Stop", False), ("SessionEnd", True)])
def test_turn_and_session_end_become_flush(event: str, final: bool) -> None:
    command = route(_payload(hook_event_name=event, transcript_path="/t.jsonl"))

    assert command == FlushCaptureCommand(
        session_id="s1", transcript_path=Path("/t.jsonl"), final=final
    )


def test_unknown_fields_are_ignored_and_missing_ones_default() -> None:
    payload: ClaudeCodeHookPayload = ClaudeCodeHookPayload.model_validate({"extra": 1})

    assert (payload.session_id, payload.command, payload.transcript_path) == ("", None, None)
