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

from noesis.bounded_context.knowledge.application.dtos import RelatedRecordDto
from noesis.bounded_context.knowledge.application.ports.curation import ICurator
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationCandidate,
    CurationSubtypes,
    WorkBrief,
)
from noesis.exceptions import CuratorRunFailedError

from . import prompts
from .candidate_answer_schema import candidates_of_answer, response_json_schema

SYSTEM_PROMPT_RESOURCE: str = "curator_system.md"
RECURSION_GUARD: Mapping[str, str] = {"NOESIS_HOOK": "1"}
ERROR_TAIL_LENGTH: int = 300


def default_system_prompt() -> str:
    """The packaged system prompt of this adapter: the admission rule, written for `claude -p`."""
    return files(prompts).joinpath(SYSTEM_PROMPT_RESOURCE).read_text(encoding="utf-8")


def render_user_prompt(
    brief: WorkBrief, related: Sequence[RelatedRecordDto], subtypes: CurationSubtypes
) -> str:
    """The per-run message: the allowed subtypes, the brief as JSON and the related records.

    Args:
        brief: The finished work (redacted).
        related: Existing records on similar topics.
        subtypes: The subtypes the curator may use.

    Returns:
        The prompt text sent on stdin.
    """
    lines: list[str] = [
        "Subtypes (use exactly these):",
        f"- experience: {', '.join(sorted(subtypes.experience))}",
        f"- knowledge: {', '.join(sorted(subtypes.knowledge))}",
        "",
        "Work brief (JSON):",
        json.dumps(brief.model_dump(mode="json"), indent=2),
        "",
    ]
    if related:
        lines.append("Related existing records:")
        lines += [
            f"- {record.record_id} ({record.record_type} {record.subtype or '-'}, "
            f"status {record.status or '-'}, project {record.project_key or 'none'}, "
            f"revision {record.revision if record.revision is not None else '-'}): "
            f"{record.title or '(no title)'}"
            for record in related
        ]
    else:
        lines.append("Related existing records: none.")
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

    def command(self, subtypes: CurationSubtypes) -> list[str]:
        """The argument vector of one curator run (the prompt goes on stdin)."""
        arguments: list[str] = [
            self._claude_bin, "-p",
            "--output-format", "json",
            "--json-schema", response_json_schema(subtypes),
            "--system-prompt", self._system_prompt,
            "--tools", "",
            "--setting-sources", "",
            "--no-session-persistence",
            "--max-budget-usd", str(self._max_budget_usd),
        ]  # fmt: skip
        return [*arguments, "--model", self._model] if self._model else arguments

    async def judge(
        self, brief: WorkBrief, related: Sequence[RelatedRecordDto], subtypes: CurationSubtypes
    ) -> tuple[CurationCandidate, ...]:
        """Run the curator once.

        Raises:
            CuratorRunFailedError: The CLI is missing, timed out, failed, or answered without a
                usable structured output (not JSON, or no `candidates` list).
        """
        stdout: bytes = await self._run(
            render_user_prompt(brief, related, subtypes).encode("utf-8"), subtypes
        )
        try:
            envelope: object = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise CuratorRunFailedError(
                "The curator did not print JSON.", {"output": _tail(stdout)}
            ) from error
        if not isinstance(envelope, dict):
            raise CuratorRunFailedError(
                "The curator printed an unexpected JSON shape.", {"output": _tail(stdout)}
            )
        if envelope.get("is_error") or envelope.get("subtype") != "success":
            raise CuratorRunFailedError(
                f"The curator run failed: {str(envelope.get('result') or envelope.get('subtype'))[:ERROR_TAIL_LENGTH]}",
                {
                    "subtype": str(envelope.get("subtype")),
                    "api_error_status": str(envelope.get("api_error_status")),
                },
            )
        candidates: tuple[CurationCandidate, ...] | None = candidates_of_answer(
            envelope.get("structured_output")
        )
        if candidates is None:
            raise CuratorRunFailedError(
                "The curator answer has no `candidates` list.",
                {"output": _tail(stdout)},
                next_steps=["Run `noesis doctor`; check the curator settings."],
            )
        return candidates

    async def _run(self, prompt: bytes, subtypes: CurationSubtypes) -> bytes:
        """Start the CLI, feed the prompt, and return stdout of a successful exit."""
        try:
            process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
                *self.command(subtypes),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**self._environment, **RECURSION_GUARD},
            )
        except OSError as error:
            raise CuratorRunFailedError(
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
            raise CuratorRunFailedError(
                f"The curator timed out after {self._timeout_seconds:.0f}s.",
                next_steps=["Raise NOESIS_CURATOR_TIMEOUT_SECONDS or retry later."],
            ) from error
        if process.returncode != 0 and not stdout.strip():
            raise CuratorRunFailedError(
                f"The curator exited with {process.returncode}.", {"stderr": _tail(stderr)}
            )
        return stdout


def _tail(output: bytes) -> str:
    """Last part of a process output, for error metadata."""
    return output.decode("utf-8", errors="replace").strip()[-ERROR_TAIL_LENGTH:]
