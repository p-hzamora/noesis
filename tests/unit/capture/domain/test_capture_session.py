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
    HeadCandidate,
    NewCommitCandidateSpecification,
    OutsideDebounceSpecification,
    PendingWorkSpecification,
    SignificantChangeSpecification,
)
from noesis.bounded_context.capture.domain.value_objects import (
    CaptureModeEnum,
    DiffSize,
    SessionId,
    WorktreeHead,
)
from noesis.exceptions import (
    CaptureNotEnabledError,
    InvalidSessionIdError,
)

pytestmark = pytest.mark.unit


def _session(enabled: bool = True) -> CaptureSession:
    session = CaptureSession.create(SessionId(value="s-1"), now=START)
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


# --- repository identity, parent link, observed heads (CVG-003) ---


def test_enable_reports_whether_anything_changed_and_keeps_the_mode_when_none_is_given() -> None:
    session = CaptureSession.create(SessionId(value="s-1"), now=START)

    assert session.enable(CaptureModeEnum.DRY_RUN, now=START) is True
    assert session.enable(None, now=START) is False  # a repeat call is a no-op
    assert session.enable(CaptureModeEnum.DRY_RUN, now=START) is False
    assert session.mode is CaptureModeEnum.DRY_RUN
    assert session.enable(CaptureModeEnum.LIVE, now=START) is True


def test_enable_without_a_mode_on_a_new_session_uses_live() -> None:
    session = CaptureSession.create(SessionId(value="s-1"), now=START)

    session.enable(None, now=START)

    assert (session.enabled, session.mode) == (True, CaptureModeEnum.LIVE)


def test_a_session_remembers_its_parent() -> None:
    child = CaptureSession.create(SessionId(value="c"), now=START, parent_id="p")

    assert child.parent_id == "p"


def test_an_old_session_adopts_its_repo_id_without_losing_pending_commits() -> None:
    session = _session()
    session.record_commit(a_commit("a"), repository_path="/r", now=START)
    assert session.repo_id is None

    session.record_commit(a_commit("b"), repository_path="/r", repo_id="r-12345678", now=START)

    assert [commit.sha for commit in session.pending] == ["a", "b"]
    assert session.repo_id == "r-12345678"


def test_a_commit_of_another_repo_id_starts_a_new_batch() -> None:
    session = _session()
    session.record_commit(a_commit("a"), repository_path="/r", repo_id="r-11111111", now=START)

    session.record_commit(a_commit("b"), repository_path="/r", repo_id="r-22222222", now=START)

    assert [commit.sha for commit in session.pending] == ["b"]


def test_observed_heads_are_replaced_wholesale_so_stale_worktrees_drop_out() -> None:
    session = _session()

    assert session.observe_heads({"/r": "a", "/w": "b"}, now=START) is True
    assert session.observe_heads({"/r": "a", "/w": "b"}, now=START) is False
    session.observe_heads({"/r": "c"}, now=START)

    assert session.observed_heads == {"/r": "c"}


def _head(sha: str = "b", *, age: int = 10) -> WorktreeHead:
    return WorktreeHead(
        path="/w", sha=sha, branch="feat/x", committed_at=START - timedelta(seconds=age)
    )


def test_a_head_that_moved_recently_is_a_new_commit_candidate() -> None:
    spec = NewCommitCandidateSpecification(window_seconds=120)

    assert spec.is_satisfied_by(HeadCandidate(head=_head(), baseline_sha="a", now=START))
    assert spec.is_satisfied_by(HeadCandidate(head=_head(), baseline_sha=None, now=START))


def test_an_unmoved_head_is_not_a_candidate() -> None:
    spec = NewCommitCandidateSpecification(window_seconds=120)

    assert not spec.is_satisfied_by(HeadCandidate(head=_head("a"), baseline_sha="a", now=START))


def test_an_old_commit_is_not_a_candidate_even_without_a_baseline() -> None:
    spec = NewCommitCandidateSpecification(window_seconds=120)

    assert not spec.is_satisfied_by(
        HeadCandidate(head=_head(age=500), baseline_sha=None, now=START)
    )
