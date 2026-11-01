"""`ITranscriptReader` for Claude Code's JSONL session transcripts."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from noesis.bounded_context.capture.application.dtos import TranscriptSnapshotDto
from noesis.bounded_context.capture.application.ports.transcript import ITranscriptReader
from noesis.utils import is_git_commit

WORK_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
GOAL_CHARS: int = 300
EXCERPT_CHARS: int = 4000
EXCERPT_ITEM_CHARS: int = 600
SKILL_PREFIX: str = "Base directory for this skill"
NOT_RECORDED: str = "Not recorded"


@dataclass(frozen=True, slots=True, kw_only=True)
class _Block:
    """One content block of a transcript line."""

    role: str | None
    kind: str | None
    text: str | None = None
    tool_name: str | None = None
    command: str | None = None

    @property
    def is_prose(self) -> bool:
        """Text a person or the assistant wrote, not a command wrapper or skill expansion."""
        return (
            self.kind == "text"
            and self.text is not None
            and bool(self.text.strip())
            and not self.text.lstrip().startswith(("<", SKILL_PREFIX))
        )


def _blocks(raw: bytes) -> Iterator[_Block]:
    """Every content block of every parsable line."""
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            entry: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        message: object = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(message, dict):
            continue
        role: object = message.get("role")
        content: object = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict):
                tool_input: object = block.get("input")
                yield _Block(
                    role=role if isinstance(role, str) else None,
                    kind=block.get("type"),
                    text=block.get("text"),
                    tool_name=block.get("name"),
                    command=tool_input.get("command") if isinstance(tool_input, dict) else None,
                )


def _has_real_work(raw: bytes) -> bool:
    """The assistant edited a file or ran a git commit."""
    return any(
        block.role == "assistant"
        and block.kind == "tool_use"
        and (
            block.tool_name in WORK_TOOLS
            or (block.tool_name == "Bash" and is_git_commit(block.command))
        )
        for block in _blocks(raw)
    )


def _goal(raw: bytes) -> str:
    """First real user prompt."""
    for block in _blocks(raw):
        if block.role == "user" and block.is_prose and block.text:
            return " ".join(block.text.split())[:GOAL_CHARS]
    return NOT_RECORDED


def _excerpt(raw: bytes) -> str:
    """User prompts and assistant prose (no tool output), newest kept within the cap."""
    items: list[str] = [
        f"{'U' if block.role == 'user' else 'A'}: {' '.join(block.text.split())[:EXCERPT_ITEM_CHARS]}"
        for block in _blocks(raw)
        if block.role in ("user", "assistant") and block.is_prose and block.text
    ]
    kept: list[str] = []
    size: int = 0
    for item in reversed(items):
        if size + len(item) > EXCERPT_CHARS:
            break
        kept.append(item)
        size += len(item)
    return "\n".join(reversed(kept))


class ClaudeCodeTranscriptReaderAdapter(ITranscriptReader):
    """Reads `~/.claude/projects/.../<session>.jsonl` files."""

    async def read(self, path: Path | None, *, since_offset: int) -> TranscriptSnapshotDto | None:
        """Snapshot; an offset past the end (compaction rewrote the file) rescans everything."""
        if path is None:
            return None
        try:
            raw: bytes = path.read_bytes()
        except OSError:
            return None
        start: int = since_offset if 0 <= since_offset <= len(raw) else 0
        fresh: bytes = raw[start:]
        return TranscriptSnapshotDto(
            end_offset=len(raw),
            has_real_work=_has_real_work(fresh),
            goal=_goal(raw),
            excerpt=_excerpt(fresh),
        )
