"""Note slugs, areas and locations."""

import pytest

from noesis.bounded_context.notes.domain.value_objects import (
    NoteArea,
    NoteKindEnum,
    NoteLocation,
    NoteOriginEnum,
    NoteSlug,
)
from noesis.exceptions import (
    InvalidNoteAreaError,
    InvalidNoteLocationError,
    InvalidNoteSlugError,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", ["Use TTL", "a--b", "-a", "a_b", "", "x" * 81])
def test_invalid_slugs_are_rejected(value: str) -> None:
    with pytest.raises(InvalidNoteSlugError):
        NoteSlug(value=value)


def test_slugs_derive_from_titles() -> None:
    assert NoteSlug.from_title("Use a TTL cache, not Redis!").value == "use-a-ttl-cache-not-redis"
    assert NoteSlug.from_title("¿?").value == "note"


@pytest.mark.parametrize("value", ["/abs", "../up", "repos/../x", "repos//x", "repos/x/auto", ""])
def test_unsafe_or_reserved_areas_are_rejected(value: str) -> None:
    with pytest.raises(InvalidNoteAreaError):
        NoteArea(value=value)


def test_repository_areas_know_their_repository() -> None:
    assert NoteArea.for_repository("noesis").repository == "noesis"
    assert NoteArea(value="learning/python").repository is None


@pytest.mark.parametrize(
    ("origin", "path"),
    [
        (NoteOriginEnum.AUTO, "repos/demo/auto/gotchas/stale-token.md"),
        (NoteOriginEnum.MANUAL, "repos/demo/gotchas/stale-token.md"),
    ],
)
def test_locations_render_and_parse_back(origin: NoteOriginEnum, path: str) -> None:
    location = NoteLocation(
        area=NoteArea.for_repository("demo"),
        origin=origin,
        kind=NoteKindEnum.GOTCHA,
        slug=NoteSlug(value="stale-token"),
    )

    assert location.relative_path == path
    assert NoteLocation.parse(path) == location
    assert (
        location.with_origin(NoteOriginEnum.MANUAL).relative_path
        == "repos/demo/gotchas/stale-token.md"
    )


@pytest.mark.parametrize(
    "path", ["repos/demo/index.md", "repos/demo/notes/x.md", "decisions/x.md", "a/decisions/x.txt"]
)
def test_paths_outside_the_note_layout_are_not_locations(path: str) -> None:
    with pytest.raises(InvalidNoteLocationError):
        NoteLocation.parse(path)


def test_each_kind_has_a_folder_and_required_sections() -> None:
    assert [kind.folder for kind in NoteKindEnum] == ["decisions", "gotchas", "runs", "glossary"]
    assert NoteKindEnum.from_folder("glossary") is NoteKindEnum.GLOSSARY
    assert NoteKindEnum.from_folder("notes") is None
    assert NoteKindEnum.GOTCHA.required_sections == ("Symptom", "Cause", "Fix or workaround")
