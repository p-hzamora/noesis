"""JSON-file capture state: mapping, staging, and the per-session lock."""

import asyncio
from pathlib import Path

import pytest
from tests.support.capture_support import START, a_commit

from noesis.bounded_context.capture.domain.entities import CaptureSession
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum, SessionId
from noesis.bounded_context.capture.infrastructure.outbound.persistence import (
    JsonFileCaptureSessionRepositoryAdapter,
    JsonFileCaptureUnitOfWorkAdapter,
)
from noesis.bounded_context.capture.infrastructure.outbound.persistence.mappers import (
    CaptureSessionMapper,
)
from noesis.exceptions import (
    CaptureStateError,
)

pytestmark = pytest.mark.integration

SESSION_ID: SessionId = SessionId(value="s-1")


def _unit(folder: Path, timeout: float = 2.0) -> JsonFileCaptureUnitOfWorkAdapter:
    return JsonFileCaptureUnitOfWorkAdapter(
        JsonFileCaptureSessionRepositoryAdapter(folder, CaptureSessionMapper()),
        SESSION_ID,
        lock_timeout_seconds=timeout,
    )


async def test_sessions_round_trip_through_json(tmp_path: Path) -> None:
    session: CaptureSession = CaptureSession.create(SESSION_ID, now=START)
    session.enable(CaptureModeEnum.DRY_RUN, now=START)
    session.record_commit(a_commit(), repository_path="/work/demo", now=START)
    session.mark_handover_failed(final=False, now=START)

    async with _unit(tmp_path) as uow:
        await uow.sessions.save(session)
        await uow.commit()
    async with _unit(tmp_path) as uow:
        loaded: CaptureSession | None = await uow.sessions.get(SESSION_ID)

    assert loaded is not None
    assert (
        loaded.enabled,
        loaded.mode,
        loaded.pending,
        loaded.failed_handovers,
        loaded.repository_path,
    ) == (True, CaptureModeEnum.DRY_RUN, session.pending, 1, "/work/demo")


async def test_uncommitted_changes_are_discarded(tmp_path: Path) -> None:
    async with _unit(tmp_path) as uow:
        await uow.sessions.save(CaptureSession.create(SESSION_ID, now=START))
        assert await uow.sessions.get(SESSION_ID) is not None

    async with _unit(tmp_path) as uow:
        assert await uow.sessions.get(SESSION_ID) is None


async def test_corrupt_state_is_reported(tmp_path: Path) -> None:
    (tmp_path / "s-1.json").write_text('{"session_id": "s-1"}', encoding="utf-8")

    async with _unit(tmp_path) as uow:
        with pytest.raises(CaptureStateError):
            await uow.sessions.get(SESSION_ID)


async def test_two_units_of_the_same_session_take_turns(tmp_path: Path) -> None:
    order: list[str] = []

    async def worker(name: str) -> None:
        async with _unit(tmp_path):
            order.append(f"{name}-in")
            await asyncio.sleep(0.1)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a"), worker("b"))

    assert order in (["a-in", "a-out", "b-in", "b-out"], ["b-in", "b-out", "a-in", "a-out"])


async def test_a_lock_held_too_long_times_out(tmp_path: Path) -> None:
    async with _unit(tmp_path):
        with pytest.raises(CaptureStateError):
            async with _unit(tmp_path, timeout=0.1):
                pass
