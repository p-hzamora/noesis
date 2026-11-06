"""Switch capture on for a session."""

from pathlib import Path

from noesis.bounded_context.capture.application.assemblers import CaptureSessionAssembler
from noesis.bounded_context.capture.application.dtos import (
    CaptureOutcomeDto,
    CaptureOutcomeEnum,
    CaptureStatusDto,
)
from noesis.bounded_context.capture.application.handlers.types import UnitOfWorkFactory
from noesis.bounded_context.capture.application.ports.registry import IRepoRegistry
from noesis.bounded_context.capture.application.services.journaling import CaptureJournalRecorder
from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum, RepoId, SessionId
from noesis.exceptions import CaptureSessionNotFoundError, InvalidSessionIdError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject


class EnableCaptureCommand(FrozenObject):
    """Switch capture on.

    Attributes:
        session_id: The (already resolved) session id.
        mode: `live` hands briefs to the curator; `dry-run` only records them. None keeps the
            session's mode (a new session is `live`; a new child inherits its parent's).
        repo_id: The repository the session works in.
        repository_path: Main worktree of that repository; with `repo_id` it is remembered in
            the registry.
        parent_id: The session that started this one as a sub-agent; the child gets its own
            state and inherits the parent's mode.
    """

    session_id: str
    mode: CaptureModeEnum | None = None
    repo_id: str | None = None
    repository_path: str | None = None
    parent_id: str | None = None


class EnableCaptureHandler(IHandler[EnableCaptureCommand, CaptureStatusDto]):
    """Creates the session if needed and switches it on; a repeat call changes nothing."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        clock: IClock,
        recorder: CaptureJournalRecorder,
        registry: IRepoRegistry,
    ) -> None:
        self._registry: IRepoRegistry = registry
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._recorder: CaptureJournalRecorder = recorder

    async def handle(self, action: EnableCaptureCommand) -> CaptureStatusDto:
        """Switch capture on and return the status (quietly `already_enabled` on a repeat)."""
        session_id = SessionId(value=action.session_id)
        parent_mode: CaptureModeEnum | None = None
        if action.parent_id == action.session_id:
            raise InvalidSessionIdError(
                "A session cannot be its own parent.",
                {"session_id": action.session_id},
                next_steps=["Give the sub-agent its own --session, or omit it."],
            )
        if action.parent_id is not None:  # its own unit of work, released before the child's opens
            parent_mode = await self._parent_mode(SessionId(value=action.parent_id))
        if action.repo_id is not None and action.repository_path is not None:
            await self._registry.register(
                RepoId.parse(action.repo_id), Path(action.repository_path)
            )
        async with self._uow_factory(session_id) as uow:
            existing: CaptureSession | None = await uow.sessions.get(session_id)
            session: CaptureSession = existing or CaptureSession.create(
                session_id,
                now=self._clock.now(),
                repo_id=action.repo_id,
                parent_id=action.parent_id,
            )
            now = self._clock.now()
            adopted: bool = action.repo_id is not None and session.adopt_repo(action.repo_id)
            inherited: CaptureModeEnum | None = parent_mode if existing is None else None
            changed: bool = session.enable(action.mode or inherited, now=now)
            if changed or adopted:
                await uow.sessions.save(session)
                await uow.commit()
        await self._recorder.record(
            CaptureOutcomeDto(
                session_id=session_id.value,
                outcome=CaptureOutcomeEnum.ENABLED
                if changed
                else CaptureOutcomeEnum.ALREADY_ENABLED,
                detail=_detail(session, action.parent_id),
            )
        )
        return CaptureSessionAssembler.to_dto(session, session_id)

    async def _parent_mode(self, parent_id: SessionId) -> CaptureModeEnum:
        """The parent's mode.

        Raises:
            CaptureSessionNotFoundError: The parent was never switched on.
        """
        async with self._uow_factory(parent_id) as uow:
            parent: CaptureSession | None = await uow.sessions.get(parent_id)
        if parent is None:
            raise CaptureSessionNotFoundError(
                f"No capture state exists for parent session {parent_id}.",
                {"session_id": parent_id.value},
                next_steps=["Run `noesis capture on` for the parent session first."],
            )
        return parent.mode


def _detail(session: CaptureSession, parent_id: str | None) -> str:
    mode: str = session.mode.value
    return f"{mode}, parent {parent_id}" if parent_id else mode
