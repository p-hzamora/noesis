"""Identity value objects of a note: id, scope, kind, source reference and path."""

import pytest

from noesis.bounded_context.notes.domain.value_objects import (
    NoteId,
    NoteKind,
    NotePath,
    NoteScope,
    NoteScopeTypeEnum,
    NoteSourceRef,
)
from noesis.exceptions import (
    InvalidNoteIdError,
    InvalidNoteKindError,
    InvalidNotePathError,
    InvalidNoteScopeError,
    InvalidNoteSourceRefError,
)

pytestmark = pytest.mark.unit

ULID: str = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_note_id_accepts_a_ulid() -> None:
    assert NoteId(value=ULID).value == ULID


@pytest.mark.parametrize(
    "bad", ["", "abc", ULID.lower(), ULID[:-1], f"{ULID}0", "I" * 26, "8" * 26]
)
def test_note_id_rejects_anything_else(bad: str) -> None:
    with pytest.raises(InvalidNoteIdError):
        NoteId(value=bad)


def test_scope_parses_repo_and_topic() -> None:
    repo = NoteScope.parse("repo:noesis")
    topic = NoteScope.parse("topic:rust-ownership")
    assert (repo.type, repo.name) == (NoteScopeTypeEnum.REPO, "noesis")
    assert (topic.type, topic.name) == (NoteScopeTypeEnum.TOPIC, "rust-ownership")
    assert str(repo) == "repo:noesis"
    assert NoteScope.for_repository("noesis") == repo


@pytest.mark.parametrize(
    "bad", ["personal", "repo:", "repo", "team:x", "repo:a/b", "repo:..", "topic:", "repo:.hidden"]
)
def test_scope_rejects_personal_and_unsafe_names(bad: str) -> None:
    with pytest.raises(InvalidNoteScopeError):
        NoteScope.parse(bad)


def test_kind_is_shape_only() -> None:
    assert NoteKind(value="howto").value == "howto"
    assert NoteKind(value="my-new-kind").value == "my-new-kind"  # membership is the catalog's job


@pytest.mark.parametrize("bad", ["", "Decision", "two words", "1abc", "a/b"])
def test_kind_rejects_bad_shape(bad: str) -> None:
    with pytest.raises(InvalidNoteKindError):
        NoteKind(value=bad)


def test_source_ref_is_kind_colon_id() -> None:
    assert NoteSourceRef(value="commit:8e6d3b5f").value == "commit:8e6d3b5f"
    with pytest.raises(InvalidNoteSourceRefError):
        NoteSourceRef(value="no-colon")


def test_note_path_is_a_safe_relative_markdown_path() -> None:
    assert NotePath(value="any/where/note.md").value == "any/where/note.md"
    for bad in ["/abs/note.md", "../x.md", "a/../x.md", "note.txt", ".hidden/x.md", ""]:
        with pytest.raises(InvalidNotePathError):
            NotePath(value=bad)
