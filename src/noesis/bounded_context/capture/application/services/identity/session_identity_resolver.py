"""Decides which stored session id a command runs under."""

from pathlib import Path

from noesis.bounded_context.capture.application.dtos import (
    RepositoryLocationDto,
    ResolvedIdentityDto,
)
from noesis.bounded_context.capture.application.ports.identity import ISessionIdentitySource
from noesis.bounded_context.capture.application.ports.vcs import IVcsReader
from noesis.bounded_context.capture.domain.services import SessionIdGenerator
from noesis.bounded_context.capture.domain.value_objects import RepoId, SessionId
from noesis.exceptions import SessionIdentityMissingError

OUTSIDE_REPOSITORY: RepoId = RepoId.derive("no-repo", "")
"""Stands in for the repository when the command runs outside one."""


class SessionIdentityResolver:
    """Hint, then the harness' ambient id, then (only if allowed) a fresh one.

    The id is always derived inside the repository the command runs in, so the CLI and the
    hooks of one session agree. Resolving only reads: it never stores anything.

    Blank values follow one rule. A blank *hint* is an error (it was passed on purpose, so it
    is never replaced by another source), and the CLI rejects it earlier with a usage error. A
    blank *ambient* value (an exported but empty variable) is not an identity: it counts as
    absent.
    """

    def __init__(
        self,
        *,
        identity: ISessionIdentitySource,
        vcs: IVcsReader,
        generator: SessionIdGenerator,
    ) -> None:
        self._identity: ISessionIdentitySource = identity
        self._vcs: IVcsReader = vcs
        self._generator: SessionIdGenerator = generator

    async def resolve(
        self, *, hint: str | None, cwd: Path, allow_fresh: bool, use_ambient: bool = True
    ) -> ResolvedIdentityDto:
        """The identity for a command run in `cwd`.

        Args:
            hint: An explicit `--session` or the id in a hook payload. None means "not given";
                a blank string is an error, not "not given".
            cwd: Where the command runs.
            allow_fresh: Whether a brand-new id may be chosen (only `capture on`).
            use_ambient: Whether the harness' own id may be used. A sub-agent started with
                `--parent` must not: the harness' id is its parent's.

        Raises:
            SessionIdentityMissingError: Nothing identifies the session and a fresh id is not allowed.
            InvalidSessionIdError: The hint is given but blank.
        """
        location: RepositoryLocationDto | None = await self._vcs.common_dir(cwd)
        repo: RepoId = (
            RepoId.derive(location.name, str(location.common_dir))
            if location
            else OUTSIDE_REPOSITORY
        )
        raw: str | None = hint if hint is not None else self._ambient(use_ambient)
        generated: bool = False
        if raw is None:
            if not allow_fresh:
                raise SessionIdentityMissingError(
                    "No session id given and none found in the environment.",
                    next_steps=[
                        "Pass --session <id>, or run `noesis capture on` first and pass back "
                        "the session_id it prints.",
                    ],
                )
            raw, generated = self._identity.fresh(), True
        session_id: SessionId = self._generator.derive(repo, raw)
        return ResolvedIdentityDto(
            session_id=session_id.value,
            repo_id=repo.value if location else "",
            repository_path=str(location.root) if location else "",
            generated=generated,
        )

    def _ambient(self, use_ambient: bool) -> str | None:
        """The harness' id, or None when unused, unset or blank."""
        value: str | None = self._identity.ambient() if use_ambient else None
        return value if value is not None and value.strip() else None
