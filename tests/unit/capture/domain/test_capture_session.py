"""The CaptureSession aggregate and the hand-over specifications."""

from datetime import timedelta

import pytest
from tests.support.capture_support import START, a_commit

from noesis.bounded_context.capture.domain.entities import (
    CaptureSession,
    CommitRecorded,
    HandoverAbandoned,
    WorkHandedOver,
)
from noesis.bounded_context.capture.domain.specifications import (
    FlushCandidate,
    OutsideDebounceSpecification,
    PendingWorkSpecification,
    SignificantChangeSpecification,
)
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum, DiffSize, SessionId
from noesis.exceptions import (
    CaptureNotEnabledError,
    InvalidSessionIdError,
)

pytestmark = pytest.mark.unit


def _session(enabled: bool = True) -> CaptureSession:
    session: CaptureSession = CaptureSession.create(SessionId(value="s-1"), now=START)
    if enabled:
        session.enable(CaptureModeEnum.LIVE, now=START)
    return session


@pytest.mark.parametrize("value", ["", "a b", "../x", "x" * 129])
def test_session_ids_must_be_safe(value: str) -> None:
    with pytest.raises(InvalidSessionIdError):
        SessionId(value=value)


def test_commits_are_recorded_once_and_summed() -> None:
    session: CaptureSession = _session()

    assert session.record_commit(a_commit("a", files=1, lines=3), repository_path="/r", now=START)
    assert not session.record_commit(
        a_commit("a", files=1, lines=3), repository_path="/r", now=START
    )
    assert session.record_commit(a_commit("b", files=2, lines=4), repository_path="/r", now=START)

    assert session.pending_size == DiffSize(files=3, lines=7)
    assert [type(event) for event in session.collect_events()] == [CommitRecorded, CommitRecorded]


def test_a_commit_in_another_repository_starts_a_new_batch() -> None:
    session: CaptureSession = _session()
    session.record_commit(a_commit("a"), repository_path="/one", now=START)

    session.record_commit(a_commit("b"), repository_path="/two", now=START)

    assert [commit.sha for commit in session.pending] == ["b"]
    assert session.repository_path == "/two"


def test_recording_while_switched_off_is_refused() -> None:
    with pytest.raises(CaptureNotEnabledError):
        _session(enabled=False).record_commit(a_commit(), repository_path="/r", now=START)


def test_disable_keeps_pending_work() -> None:
    session: CaptureSession = _session()
    session.record_commit(a_commit(), repository_path="/r", now=START)

    session.disable(now=START)

    assert (session.enabled, len(session.pending)) == (False, 1)


def test_hand_over_clears_pending_and_moves_the_cursor() -> None:
    session: CaptureSession = _session()
    session.record_commit(a_commit(), repository_path="/r", now=START)

    session.mark_handed_over(transcript_end=42, now=START)

    assert session.pending == ()
    assert (session.cursor.offset, session.cursor.handed_over_at) == (42, START)
    assert isinstance(session.collect_events()[-1], WorkHandedOver)


def test_failed_hand_overs_retry_once_then_abandon_and_the_final_one_abandons_at_once() -> None:
    session: CaptureSession = _session()
    session.record_commit(a_commit(), repository_path="/r", now=START)

    assert session.mark_handover_failed(final=False, now=START) is False
    assert len(session.pending) == 1
    assert session.mark_handover_failed(final=False, now=START) is True
    assert (session.pending, session.failed_handovers) == ((), 0)
    assert isinstance(session.collect_events()[-1], HandoverAbandoned)

    session.record_commit(a_commit("c"), repository_path="/r", now=START)
    assert session.mark_handover_failed(final=True, now=START) is True


def test_specifications_gate_pending_debounce_and_size() -> None:
    session: CaptureSession = _session()
    pending = PendingWorkSpecification()
    debounce = OutsideDebounceSpecification(300)
    significant = SignificantChangeSpecification(min_files=3, min_lines=20)

    assert not pending.is_satisfied_by(FlushCandidate(session=session, now=START, final=False))
    session.record_commit(a_commit("a", files=1, lines=5), repository_path="/r", now=START)
    first = FlushCandidate(session=session, now=START, final=False)
    assert pending.is_satisfied_by(first)
    assert debounce.is_satisfied_by(first)  # never handed over yet
    assert not significant.is_satisfied_by(first)

    session.record_commit(a_commit("b", files=1, lines=15), repository_path="/r", now=START)
    assert significant.is_satisfied_by(
        FlushCandidate(session=session, now=START, final=False)
    )  # 20 lines summed

    session.mark_handed_over(transcript_end=1, now=START)
    soon = FlushCandidate(session=session, now=START + timedelta(seconds=10), final=False)
    assert not debounce.is_satisfied_by(soon)
    assert debounce.is_satisfied_by(FlushCandidate(session=session, now=soon.now, final=True))
    assert debounce.is_satisfied_by(
        FlushCandidate(session=session, now=START + timedelta(seconds=301), final=False)
    )
