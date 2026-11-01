"""`ICurator` that runs the Claude Code CLI headless with a JSON schema.

The run is isolated on purpose: no tools (`--tools ""`), no user or project settings
(`--setting-sources ""`, so no hooks and no plugins), no saved session, and a budget cap.
`NOESIS_HOOK=1` is also exported so that, should any hook still fire, noesis ignores it.
"""

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from importlib.resources import files

from pydantic import ValidationError

from noesis.bounded_context.knowledge.application.dtos import NoteSummaryDto
from noesis.bounded_context.knowledge.application.ports.curation import ICurator
from noesis.bounded_context.knowledge.domain.value_objects import CurationDecision, WorkBrief
from noesis.exceptions import (
    CuratorFailedError,
)

from . import prompts
from .curator_response_schema import RESPONSE_JSON_SCHEMA, CuratorResponseModel

SYSTEM_PROMPT_RESOURCE: str = "curator_system.md"
RECURSION_GUARD: Mapping[str, str] = {"NOESIS_HOOK": "1"}
ERROR_TAIL_LENGTH: int = 300


def default_system_prompt() -> str:
    """The packaged system prompt of this adapter: the admission rule, written for `claude -p`."""
    return files(prompts).joinpath(SYSTEM_PROMPT_RESOURCE).read_text(encoding="utf-8")


def render_user_prompt(brief: WorkBrief, related: Sequence[NoteSummaryDto]) -> str:
    """The per-run message: the brief as JSON plus the related notes.

    Args:
        brief: The finished work.
        related: Existing notes on similar topics.

    Returns:
        The prompt text sent on stdin.
    """
    lines: list[str] = [
        "Work brief (JSON):",
        json.dumps(brief.model_dump(mode="json"), indent=2),
        "",
    ]
    if related:
        lines.append("Related existing notes:")
        lines += [
            f"- {note.path} ({note.origin} {note.kind or 'note'}): {note.title} -- {note.snippet}"
            for note in related
        ]
    else:
        lines.append("Related existing notes: none.")
    return "\n".join(lines)


class ClaudeCliCuratorAdapter(ICurator):
    """Runs `claude -p --output-format json --json-schema ...` and reads `structured_output`."""

    def __init__(
        self,
        *,
        claude_bin: str,
        model: str,
        max_budget_usd: float,
        timeout_seconds: float,
        system_prompt: str,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._claude_bin: str = claude_bin
        self._model: str = model
        self._max_budget_usd: float = max_budget_usd
        self._timeout_seconds: float = timeout_seconds
        self._system_prompt: str = system_prompt
        self._environment: Mapping[str, str] = (
            environment if environment is not None else os.environ
        )

    def command(self) -> list[str]:
        """The argument vector of one curator run (the prompt goes on stdin)."""
        arguments: list[str] = [
            self._claude_bin, "-p",
            "--output-format", "json",
            "--json-schema", RESPONSE_JSON_SCHEMA,
            "--system-prompt", self._system_prompt,
            "--tools", "",
            "--setting-sources", "",
            "--no-session-persistence",
            "--max-budget-usd", str(self._max_budget_usd),
        ]  # fmt: skip
        return [*arguments, "--model", self._model] if self._model else arguments

    async def curate(
        self, brief: WorkBrief, related: Sequence[NoteSummaryDto]
    ) -> tuple[CurationDecision, ...]:
        """Run the curator once.

        Raises:
            CuratorFailedError: The CLI is missing, timed out, failed, or answered without a valid
                structured output.
        """
        stdout: bytes = await self._run(render_user_prompt(brief, related).encode("utf-8"))
        try:
            envelope: object = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise CuratorFailedError(
                "The curator did not print JSON.", {"output": _tail(stdout)}
            ) from error
        if not isinstance(envelope, dict):
            raise CuratorFailedError(
                "The curator printed an unexpected JSON shape.", {"output": _tail(stdout)}
            )
        if envelope.get("is_error") or envelope.get("subtype") != "success":
            raise CuratorFailedError(
                f"The curator run failed: {str(envelope.get('result') or envelope.get('subtype'))[:ERROR_TAIL_LENGTH]}",
                {
                    "subtype": str(envelope.get("subtype")),
                    "api_error_status": str(envelope.get("api_error_status")),
                },
            )
        try:
            response: CuratorResponseModel = CuratorResponseModel.model_validate(
                envelope.get("structured_output")
            )
        except ValidationError as error:
            raise CuratorFailedError(
                "The curator answer did not match the schema.",
                {"errors": str(error)[:ERROR_TAIL_LENGTH]},
            ) from error
        return response.to_decisions()

    async def _run(self, prompt: bytes) -> bytes:
        """Start the CLI, feed the prompt, and return stdout of a successful exit."""
        try:
            process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
                *self.command(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**self._environment, **RECURSION_GUARD},
            )
        except OSError as error:
            raise CuratorFailedError(
                f"Cannot start the curator `{self._claude_bin}`: {error}",
                {"claude_bin": self._claude_bin},
                next_steps=[
                    "Install Claude Code or set NOESIS_CURATOR_CLAUDE_BIN (`noesis doctor`)."
                ],
            ) from error
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt), self._timeout_seconds
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise CuratorFailedError(
                f"The curator timed out after {self._timeout_seconds:.0f}s.",
                next_steps=["Raise NOESIS_CURATOR_TIMEOUT_SECONDS or retry later."],
            ) from error
        if process.returncode != 0 and not stdout.strip():
            raise CuratorFailedError(
                f"The curator exited with {process.returncode}.", {"stderr": _tail(stderr)}
            )
        return stdout


def _tail(output: bytes) -> str:
    """Last part of a process output, for error metadata."""
    return output.decode("utf-8", errors="replace").strip()[-ERROR_TAIL_LENGTH:]
