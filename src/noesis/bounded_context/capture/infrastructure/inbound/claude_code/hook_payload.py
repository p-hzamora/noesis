"""The subset of Claude Code's hook JSON that noesis reads, tolerant to missing fields."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ClaudeCodeHookPayload(BaseModel):
    """One hook invocation, as Claude Code sends it on stdin.

    Attributes:
        session_id: The session.
        hook_event_name: `PostToolUse`, `Stop`, `SessionEnd`, ...
        cwd: Working directory of the session.
        transcript_path: The session transcript (JSONL).
        tool_name: Tool of a tool event, e.g. `Bash`.
        tool_input: Tool arguments; `command` for Bash.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    session_id: str = ""
    hook_event_name: str = ""
    cwd: Path = Path()
    transcript_path: Path | None = None
    tool_name: str | None = None
    tool_input: dict[str, object] = Field(default_factory=dict)

    @property
    def command(self) -> str | None:
        """The Bash command of a tool event."""
        value: object = self.tool_input.get("command")
        return value if isinstance(value, str) else None
