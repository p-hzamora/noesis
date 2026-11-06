"""SessionIdGenerator: idempotent, repo-salted, injection-safe."""

import pytest

from noesis.bounded_context.capture.domain.services import SessionIdGenerator
from noesis.bounded_context.capture.domain.value_objects import RepoId, SessionId
from noesis.exceptions import InvalidSessionIdError

pytestmark = pytest.mark.unit

REPO = RepoId.derive("billing", "/work/billing/.git")
OTHER = RepoId.derive("billing", "/elsewhere/billing/.git")


def test_a_raw_id_becomes_the_repo_id_plus_twelve_hex() -> None:
    derived = SessionIdGenerator().derive(REPO, "0a1b2c3d-claude-session")

    assert derived.value.startswith(f"{REPO.value}-")
    assert len(derived.value.rsplit("-", 1)[1]) == 12


def test_derivation_is_deterministic() -> None:
    generator = SessionIdGenerator()

    assert generator.derive(REPO, "abc") == generator.derive(REPO, "abc")


def test_a_derived_id_passes_through_unchanged() -> None:
    generator = SessionIdGenerator()
    derived = generator.derive(REPO, "abc")

    assert generator.derive(REPO, derived.value) == derived


def test_the_same_raw_id_differs_between_repositories() -> None:
    generator = SessionIdGenerator()

    assert generator.derive(REPO, "abc") != generator.derive(OTHER, "abc")


def test_an_id_derived_for_another_repo_is_hashed_again_not_trusted() -> None:
    generator = SessionIdGenerator()
    foreign = generator.derive(OTHER, "abc")

    assert generator.derive(REPO, foreign.value) != foreign


@pytest.mark.parametrize(
    "raw", ["../../etc/passwd", "a b; rm -rf /", "x" * 500, "$(whoami)", "ü", "a\nb", "a/b"]
)
def test_hostile_input_is_hashed_into_a_safe_id(raw: str) -> None:
    derived = SessionIdGenerator().derive(REPO, raw)

    assert "/" not in derived.value
    assert derived.value.startswith(REPO.value)


@pytest.mark.parametrize("raw", ["", "   "])
def test_a_blank_id_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidSessionIdError):
        SessionIdGenerator().derive(REPO, raw)


def test_the_label_is_the_digest_of_a_derived_id_else_the_short_form() -> None:
    generator = SessionIdGenerator()
    derived = generator.derive(REPO, "abc")

    assert generator.label(derived) == derived.value.rsplit("-", 1)[1]
    assert generator.label(SessionId(value="plain-session-id")) == "plain-se"
