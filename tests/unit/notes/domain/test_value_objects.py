"""Note slugs (scopes, ids and paths are covered in test_note_identity)."""

import pytest

from noesis.bounded_context.notes.domain.value_objects import NoteKind, NoteSlug
from noesis.exceptions import InvalidNoteKindError, InvalidNoteSlugError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", ["Use TTL", "a--b", "-a", "a_b", "", "x" * 81])
def test_invalid_slugs_are_rejected(value: str) -> None:
    with pytest.raises(InvalidNoteSlugError):
        NoteSlug(value=value)


def test_slugs_derive_from_titles() -> None:
    assert NoteSlug.from_title("Use a TTL cache, not Redis!").value == "use-a-ttl-cache-not-redis"
    assert NoteSlug.from_title("¿?").value == "note"


@pytest.mark.parametrize("value", ["Decision", "a b", "", "-x", "x" * 41])
def test_a_kind_name_must_be_hyphenated_lowercase_words(value: str) -> None:
    with pytest.raises(InvalidNoteKindError):
        NoteKind(value=value)
