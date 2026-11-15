"""A person must be at the terminal when the user applies a review transition (Q-002).

The actor `user` is whoever runs the command with no harness marker in the environment. An
agent shell has no terminal on standard input, so asking for one also catches an agent whose
harness marker is not recognised. Commands never prompt: they only check.
"""

import sys
from collections.abc import Callable

from noesis.bounded_context.knowledge.domain.value_objects import Actor, ActorKindEnum
from noesis.exceptions import UserPresenceRequiredError


def require_user_presence(
    actor: Actor, *, applying: bool, stdin_is_tty: Callable[[], bool] | None = None
) -> None:
    """Refuse a `user` that applies a transition without an interactive terminal on stdin.

    Args:
        actor: The resolved actor.
        applying: Whether the command writes (`--yes`); previews never need a person.
        stdin_is_tty: Answers whether standard input is a terminal; by default it asks
            `sys.stdin.isatty()` when called, so a replaced `sys.stdin` is seen.

    Raises:
        UserPresenceRequiredError: The actor is the user, the command applies, and standard
            input is not an interactive terminal.
    """
    if not applying or actor.kind is not ActorKindEnum.USER:
        return
    is_tty: bool = stdin_is_tty() if stdin_is_tty is not None else sys.stdin.isatty()
    if not is_tty:
        raise UserPresenceRequiredError(
            "Applying this review decision as the user needs an interactive terminal on "
            "standard input.",
            {"actor_kind": actor.kind.value},
            next_steps=["Run the command yourself in an interactive terminal."],
        )
