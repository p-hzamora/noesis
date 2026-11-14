"""Who runs a store command: the one place that decides `agent` or `user` (D-024, A-14).

A command line cannot claim to be a person. If any harness marker is in the process environment
the actor is an agent; with none, it is the user. No option feeds this decision, so an agent
cannot pass itself off as a user. The marker variables themselves are listed once, in
`noesis.core.configurations.session_identity_settings`, and arrive here as `Environment.identity`.
"""

import getpass

from noesis.bounded_context.knowledge.domain.value_objects import Actor, ActorKindEnum
from noesis.core import SessionIdentitySettings

CLAUDE_CODE_NAME: str = "claude-code"
CODEX_NAME: str = "codex"
UNKNOWN_AGENT_NAME: str = "agent"
FALLBACK_USER_NAME: str = "user"


def _user_name() -> str:
    """The login name of the person at the terminal."""
    try:
        return getpass.getuser().strip() or FALLBACK_USER_NAME
    except OSError, KeyError, ImportError:
        return FALLBACK_USER_NAME


def _other_agent_name(ai_agent: str | None) -> str:
    """`AI_AGENT` carries `<name>_<version>_<role>`; the first part names the harness."""
    name: str = (ai_agent or "").strip().partition("_")[0].strip()
    return name or UNKNOWN_AGENT_NAME


def resolve_actor(identity: SessionIdentitySettings) -> Actor:
    """The actor of this invocation.

    Args:
        identity: The harness markers read from the process environment.

    Returns:
        An `agent` (named after the harness, with its session when it exposes one) when any
        marker is present, else the `user` named after the login, without a session.
    """
    ai_agent: str = (identity.ai_agent or "").strip()
    if identity.claudecode or identity.claude_code_session_id or ai_agent.startswith("claude-code"):
        return Actor(
            kind=ActorKindEnum.AGENT,
            name=CLAUDE_CODE_NAME,
            session=identity.claude_code_session_id,
        )
    codex_session: str | None = identity.codex_thread_id or identity.codex_session_id
    if codex_session:
        return Actor(kind=ActorKindEnum.AGENT, name=CODEX_NAME, session=codex_session)
    if identity.noesis_session_id or ai_agent:
        return Actor(
            kind=ActorKindEnum.AGENT,
            name=_other_agent_name(identity.ai_agent),
            session=identity.noesis_session_id,
        )
    return Actor(kind=ActorKindEnum.USER, name=_user_name())
