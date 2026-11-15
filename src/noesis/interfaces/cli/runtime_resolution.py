"""Which runtimes `catalog check` and `catalog scan` look at (D-008): the caller decides.

Explicit `--runtime` values win; else the runtime of the session that runs the command (from
the markers in the process environment); else every supported runtime, Claude Code first.
"""

import typer

from noesis.bounded_context.knowledge.application.dtos import RuntimeEnum
from noesis.core import SessionIdentitySettings

AI_AGENT_CLAUDE_PREFIX: str = "claude-code"


def parse_runtimes(given: list[str]) -> tuple[RuntimeEnum, ...]:
    """The `--runtime` values as given, without repeats.

    Raises:
        typer.BadParameter: A value is not a supported runtime.
    """
    runtimes: list[RuntimeEnum] = []
    for value in given:
        try:
            runtimes.append(RuntimeEnum(value))
        except ValueError:
            allowed: str = ", ".join(runtime.value for runtime in RuntimeEnum)
            raise typer.BadParameter(
                f"Unknown runtime {value!r}; use one of: {allowed}.", param_hint="--runtime"
            ) from None
    return tuple(dict.fromkeys(runtimes))


def resolve_runtimes(
    given: list[str], identity: SessionIdentitySettings
) -> tuple[RuntimeEnum, ...]:
    """The runtimes to probe, in the order the result blocks should come back.

    Args:
        given: `--runtime` values.
        identity: The harness markers read from the process environment.

    Returns:
        The given runtimes; else Codex when a Codex marker is set; else Claude Code when one of
        its markers is set; else both, `claude-code` first.

    Raises:
        typer.BadParameter: A given value is not a supported runtime.
    """
    if given:
        return parse_runtimes(given)
    if identity.codex_thread_id or identity.codex_session_id:
        return (RuntimeEnum.CODEX,)
    ai_agent: str = (identity.ai_agent or "").strip()
    if (
        identity.claudecode
        or identity.claude_code_session_id
        or ai_agent.startswith(AI_AGENT_CLAUDE_PREFIX)
    ):
        return (RuntimeEnum.CLAUDE_CODE,)
    return (RuntimeEnum.CLAUDE_CODE, RuntimeEnum.CODEX)
