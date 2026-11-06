"""What a work brief means to Notes: its area, search text and provenance."""

import pytest

from noesis.bounded_context.notes.domain.value_objects import CommitRef, NoteArea, WorkBrief

pytestmark = pytest.mark.unit


def _brief(
    *, goal: str = "make login faster", session_id: str = "abcd1234ef", session_label: str = ""
) -> WorkBrief:
    return WorkBrief(
        session_id=session_id,
        session_label=session_label,
        repository="demo",
        repository_path="/work/demo",
        branch="main",
        head="bbb",
        commits=(
            CommitRef(sha="aaa", subject="feat: add TTL cache"),
            CommitRef(sha="bbb", subject="test: cover expiry"),
        ),
        goal=goal,
    )


def test_its_notes_belong_to_the_repository_area() -> None:
    assert _brief().area == NoteArea(value="repos/demo")


def test_search_text_is_the_goal_followed_by_the_commit_subjects() -> None:
    assert _brief().search_text() == "make login faster feat: add TTL cache test: cover expiry"


def test_search_text_without_a_goal_still_lists_the_commit_subjects() -> None:
    assert _brief(goal="").search_text() == " feat: add TTL cache test: cover expiry"


def test_provenance_is_the_commit_shas_oldest_first_and_a_short_session_id() -> None:
    brief: WorkBrief = _brief(session_id="0123456789abcdef")

    assert brief.commit_shas() == ("aaa", "bbb")
    assert brief.short_session() == "01234567"


def test_a_session_label_is_the_provenance_and_the_id_stays_opaque() -> None:
    brief: WorkBrief = _brief(session_id="demo-12345678-abcdef012345", session_label="abcdef012345")

    assert brief.short_session() == "abcdef012345"
    assert _brief(session_id="demo-12345678-abcdef012345").short_session() == "demo-123"
