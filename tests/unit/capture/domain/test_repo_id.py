"""RepoId: folder name plus a digest of where the repository lives."""

import pytest
from pydantic import ValidationError

from noesis.bounded_context.capture.domain.value_objects import RepoId

pytestmark = pytest.mark.unit


def test_the_id_is_the_name_and_an_eight_hex_digest() -> None:
    repo = RepoId.derive("billing", "/work/billing/.git")

    assert repo.value.startswith("billing-")
    assert len(repo.digest) == 8
    assert str(repo) == repo.value


def test_same_name_in_two_places_gives_two_ids() -> None:
    assert RepoId.derive("api", "/a/api/.git") != RepoId.derive("api", "/b/api/.git")


def test_the_same_place_always_gives_the_same_id() -> None:
    assert RepoId.derive("api", "/a/api/.git") == RepoId.derive("api", "/a/api/.git")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("my repo!", "my-repo"),
        ("../../etc", "etc"),
        ("", "repo"),
        ("***", "repo"),
        ("x" * 90, "x" * 40),
    ],
)
def test_the_name_is_sanitized_and_capped(name: str, expected: str) -> None:
    assert RepoId.derive(name, "/p/.git").name == expected


def test_it_is_immutable_and_validates_what_it_is_given() -> None:
    repo = RepoId.derive("api", "/p/.git")

    with pytest.raises(ValidationError):
        repo.name = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RepoId(name="a/b", digest="0" * 8)


def test_a_printed_value_parses_back_to_the_same_id() -> None:
    repo = RepoId.derive("my-repo", "/p/.git")

    assert RepoId.parse(repo.value) == repo
