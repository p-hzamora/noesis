"""`IRecallAgent` that runs the Claude Code CLI headless with a JSON schema.

Isolated like the curator, and stricter: no tools (`--tools ""`), no MCP servers
(`--strict-mcp-config` with none given), no user or project settings (`--setting-sources ""`,
so no hooks or plugins), no saved session and a budget cap. The agent never touches the vault:
noesis reads the notes, masks secrets and sends their text on stdin, so what the agent can
see is exactly what was sent. `NOESIS_OBSIDIAN_MCP_TOKEN` is removed from its environment.
"""

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from importlib.resources import files

from pydantic import ValidationError

from noesis.bounded_context.notes.application.dtos import NoteContentDto, RecallBriefingDto
from noesis.bounded_context.notes.application.ports.recall import IRecallAgent
from noesis.exceptions import RecallAgentFailedError

from . import prompts
from .recall_response_schema import RESPONSE_JSON_SCHEMA, RecallBriefingModel

SYSTEM_PROMPT_RESOURCE: str = "recall_system.md"
RECURSION_GUARD: Mapping[str, str] = {"NOESIS_HOOK": "1"}
WITHHELD_VARIABLES: frozenset[str] = frozenset({"NOESIS_OBSIDIAN_MCP_TOKEN"})
ERROR_TAIL_LENGTH: int = 300
WORDS_PER_TOKEN: float = 0.75


def default_recall_system_prompt() -> str:
    """The packaged instructions of the recall agent (`prompts/recall_system.md`)."""
    return files(prompts).joinpath(SYSTEM_PROMPT_RESOURCE).read_text(encoding="utf-8")


def _escaped(text: str) -> str:
    """Note text that cannot close its own `<note>` block."""
    return text.replace("</note", "<\\/note")


def render_user_prompt(task: str, notes: Sequence[NoteContentDto], target_tokens: int) -> str:
    """The per-run message: the task, the length target and every note in full."""
    target: str = (
        f"Aim for about {target_tokens} tokens (roughly {int(target_tokens * WORDS_PER_TOKEN)} words)."
        if target_tokens
        else "No length target."
    )
    lines: list[str] = [f"Task: {task.strip()}", target, "", f"Notes ({len(notes)}):", ""]
    for note in notes:
        attributes: str = f'path="{note.path}" title="{note.title.replace(chr(34), chr(39))}"'
        attributes += f' kind="{note.kind or "note"}" origin="{note.origin}"'
        if note.updated:
            attributes += f' updated="{note.updated}"'
        lines += [f"<note {attributes}>", _escaped(note.content), "</note>", ""]
    return "\n".join(lines)


class ClaudeCliRecallAgentAdapter(IRecallAgent):
    """Runs `claude -p --output-format json --json-schema ...` and reads `structured_output`.

    `model` and `effort` go to the CLI verbatim when set, so any model and level the installed
    CLI accepts works; noesis does not keep a list of them.
    """

    def __init__(
        self,
        *,
        claude_bin: str,
        model: str,
        effort: str,
        max_budget_usd: float,
        timeout_seconds: float,
        system_prompt: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._claude_bin: str = claude_bin
        self._model: str = model
        self._effort: str = effort
        self._max_budget_usd: float = max_budget_usd
        self._timeout_seconds: float = timeout_seconds
        self._system_prompt: str = system_prompt or default_recall_system_prompt()
        self._environment: Mapping[str, str] = (
            environment if environment is not None else os.environ
        )

    def command(self) -> list[str]:
        """The argument vector of one run (the prompt goes on stdin)."""
        arguments: list[str] = [
            self._claude_bin, "-p",
            "--output-format", "json",
            "--json-schema", RESPONSE_JSON_SCHEMA,
            "--system-prompt", self._system_prompt,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
            "--max-budget-usd", str(self._max_budget_usd),
        ]  # fmt: skip
        if self._model:
            arguments += ["--model", self._model]
        if self._effort:
            arguments += ["--effort", self._effort]
        return arguments

    async def brief(
        self, task: str, notes: Sequence[NoteContentDto], *, target_tokens: int
    ) -> RecallBriefingDto:
        """Run the agent once.

        Raises:
            RecallAgentFailedError: The CLI is missing, timed out, failed, rejected the model
                or effort, or answered without a valid structured output.
        """
        stdout: bytes = await self._run(render_user_prompt(task, notes, target_tokens).encode())
        try:
            envelope: object = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise RecallAgentFailedError(
                "The recall agent did not print JSON.", {"output": _tail(stdout)}
            ) from error
        if not isinstance(envelope, dict):
            raise RecallAgentFailedError(
                "The recall agent printed an unexpected JSON shape.", {"output": _tail(stdout)}
            )
        if envelope.get("is_error") or envelope.get("subtype") != "success":
            raise RecallAgentFailedError(
                f"The recall agent run failed: {str(envelope.get('result') or envelope.get('subtype'))[:ERROR_TAIL_LENGTH]}",
                {
                    "subtype": str(envelope.get("subtype")),
                    "api_error_status": str(envelope.get("api_error_status")),
                    "model": self._model or None,
                },
            )
        try:
            answer = RecallBriefingModel.model_validate(envelope.get("structured_output"))
        except ValidationError as error:
            raise RecallAgentFailedError(
                "The recall agent answer did not match the schema.",
                {"errors": str(error)[:ERROR_TAIL_LENGTH]},
            ) from error
        return answer.to_dto(model=self._model_used(envelope))

    def _model_used(self, envelope: Mapping[str, object]) -> str | None:
        """The model the CLI reports having used, else the configured one."""
        usage: object = envelope.get("modelUsage")
        if isinstance(usage, dict) and usage:
            return ", ".join(str(name) for name in usage)
        return self._model or None

    async def _run(self, prompt: bytes) -> bytes:
        """Start the CLI, feed the prompt, and return stdout of a successful exit."""
        environment: dict[str, str] = {
            name: value
            for name, value in self._environment.items()
            if name not in WITHHELD_VARIABLES
        }
        try:
            process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
                *self.command(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**environment, **RECURSION_GUARD},
            )
        except OSError as error:
            raise RecallAgentFailedError(
                f"Cannot start the recall agent `{self._claude_bin}`: {error}",
                {"claude_bin": self._claude_bin},
                next_steps=["Install Claude Code or set NOESIS_RECALL_CLAUDE_BIN."],
            ) from error
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt), self._timeout_seconds
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise RecallAgentFailedError(
                f"The recall agent timed out after {self._timeout_seconds:.0f}s.",
                next_steps=["Raise NOESIS_RECALL_TIMEOUT_SECONDS, lower --limit, or retry later."],
            ) from error
        if process.returncode != 0 and not stdout.strip():
            raise RecallAgentFailedError(
                f"The recall agent exited with {process.returncode}.",
                {
                    "stderr": _tail(stderr),
                    "model": self._model or None,
                    "effort": self._effort or None,
                },
                next_steps=[
                    "Check NOESIS_RECALL_MODEL and NOESIS_RECALL_EFFORT (`noesis config show`)."
                ],
            )
        return stdout


def _tail(output: bytes) -> str:
    """Last part of a process output, for error metadata."""
    return output.decode("utf-8", errors="replace").strip()[-ERROR_TAIL_LENGTH:]
