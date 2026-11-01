"""Translates Claude Code hook events into Capture commands."""

from noesis.bounded_context.capture.application.handlers.commands import (
    FlushCaptureCommand,
    RecordCommitCommand,
)
from noesis.bounded_context.capture.infrastructure.inbound.claude_code.hook_payload import (
    ClaudeCodeHookPayload,
)
from noesis.utils import is_git_commit

type CaptureCommand = RecordCommitCommand | FlushCaptureCommand


def route(payload: ClaudeCodeHookPayload) -> CaptureCommand | None:
    """The capture command for this hook event, or None when the event is irrelevant.

    `PostToolUse` counts only for a Bash call that really ran `git commit` (the hook's
    `if` matcher is best-effort, so it is checked again here).
    """
    if not payload.session_id:
        return None
    match payload.hook_event_name:
        case "PostToolUse" if payload.tool_name == "Bash" and is_git_commit(payload.command):
            return RecordCommitCommand(session_id=payload.session_id, cwd=payload.cwd)
        case "Stop":
            return FlushCaptureCommand(
                session_id=payload.session_id, transcript_path=payload.transcript_path, final=False
            )
        case "SessionEnd":
            return FlushCaptureCommand(
                session_id=payload.session_id, transcript_path=payload.transcript_path, final=True
            )
        case _:
            return None
