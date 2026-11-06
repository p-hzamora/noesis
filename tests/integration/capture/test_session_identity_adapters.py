"""The identity chain: first source wins, a fresh id is random, blanks do not count."""

import pytest

from noesis.bounded_context.capture.infrastructure.outbound.identity import (
    AmbientSessionSource,
    ChainSessionIdentitySourceAdapter,
    CodexSessionIdentitySourceAdapter,
    StaticSessionIdentitySourceAdapter,
)

pytestmark = pytest.mark.integration


class _Source(AmbientSessionSource):
    def __init__(self, value: str | None) -> None:
        self._value: str | None = value

    def read(self) -> str | None:
        return self._value


def test_the_first_source_that_knows_an_id_wins() -> None:
    chain = ChainSessionIdentitySourceAdapter([_Source(None), _Source("harness"), _Source("later")])

    assert chain.ambient() == "harness"


def test_with_no_source_the_ambient_identity_is_unknown() -> None:
    assert ChainSessionIdentitySourceAdapter([]).ambient() is None
    assert ChainSessionIdentitySourceAdapter([_Source(None)]).ambient() is None


def test_fresh_ids_are_random_and_never_repeat() -> None:
    chain = ChainSessionIdentitySourceAdapter([])

    assert chain.fresh() != chain.fresh()
    assert len(chain.fresh()) == 32


@pytest.mark.parametrize(
    ("value", "expected"),
    [("abc", "abc"), ("  abc ", "abc"), ("", None), ("  ", None), (None, None)],
)
def test_the_static_source_returns_its_value_unless_blank(
    value: str | None, expected: str | None
) -> None:
    assert StaticSessionIdentitySourceAdapter(value).read() == expected


# --- Codex ---


@pytest.mark.parametrize(
    ("thread_id", "session_id", "expected"),
    [
        ("thread-1", "session-1", "thread-1"),  # the thread id comes first
        (None, "session-1", "session-1"),
        ("", "session-1", "session-1"),
        ("  ", None, None),
        (None, None, None),
    ],
)
def test_codex_reads_the_thread_id_then_the_session_id(
    thread_id: str | None, session_id: str | None, expected: str | None
) -> None:
    assert CodexSessionIdentitySourceAdapter(thread_id, session_id).read() == expected


def test_codex_comes_before_the_user_variable_in_the_chain() -> None:
    codex = CodexSessionIdentitySourceAdapter("codex-thread", None)
    chain = ChainSessionIdentitySourceAdapter([codex, StaticSessionIdentitySourceAdapter("mine")])

    assert chain.ambient() == "codex-thread"
    assert (
        ChainSessionIdentitySourceAdapter(
            [
                CodexSessionIdentitySourceAdapter(None, None),
                StaticSessionIdentitySourceAdapter("mine"),
            ]
        ).ambient()
        == "mine"
    )
