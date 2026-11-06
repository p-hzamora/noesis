"""Resolve which session a command belongs to (before any session state is opened)."""

from pathlib import Path

from noesis.bounded_context.capture.application.dtos import ResolvedIdentityDto
from noesis.bounded_context.capture.application.services.identity import SessionIdentityResolver
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class ResolveSessionIdentityQuery(FrozenObject):
    """Which session is this?

    Attributes:
        hint: An explicit session id (`--session`, or the id of a hook payload).
        cwd: Where the command runs.
        allow_fresh: Whether a new id may be chosen when nothing identifies the session.
        use_ambient: Whether the harness' own id may identify the session.
    """

    hint: str | None = None
    cwd: Path
    allow_fresh: bool = False
    use_ambient: bool = True


class ResolveSessionIdentityHandler(IHandler[ResolveSessionIdentityQuery, ResolvedIdentityDto]):
    """Delegates to the resolver, so interfaces only ever call handlers. A pure query: no writes."""

    def __init__(self, *, resolver: SessionIdentityResolver) -> None:
        self._resolver: SessionIdentityResolver = resolver

    async def handle(self, action: ResolveSessionIdentityQuery) -> ResolvedIdentityDto:
        """The identity the command runs under."""
        return await self._resolver.resolve(
            hint=action.hint,
            cwd=action.cwd,
            allow_fresh=action.allow_fresh,
            use_ambient=action.use_ambient,
        )
