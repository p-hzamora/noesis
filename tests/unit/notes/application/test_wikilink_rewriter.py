"""Wikilinks keep pointing at the same files after files move."""

import pytest

from noesis.bounded_context.notes.application.services.migration import WikilinkRewriter

pytestmark = pytest.mark.unit

FILES: list[str] = [
    "company/p/alpha/index.md",
    "company/p/alpha/decisions/use-x.md",
    "company/p/alpha/assets/logo.png",
    "repos/beta/concepts/arch.md",
    "README.md",
]
MOVES: dict[str, str] = {
    "company/p/alpha/index.md": "repos/alpha/index.md",
    "company/p/alpha/decisions/use-x.md": "repos/alpha/decisions/use-x.md",
    "company/p/alpha/assets/logo.png": "repos/alpha/assets/logo.png",
}


@pytest.fixture
def rewriter() -> WikilinkRewriter:
    return WikilinkRewriter(MOVES, FILES)


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("[[company/p/alpha/index]]", "[[repos/alpha/index]]"),
        ("[[company/p/alpha/index.md]]", "[[repos/alpha/index]]"),
        ("[[company/p/alpha/index|Alpha]]", "[[repos/alpha/index|Alpha]]"),
        (
            "[[company/p/alpha/decisions/use-x#Rationale]]",
            "[[repos/alpha/decisions/use-x#Rationale]]",
        ),
        (
            "[[company/p/alpha/decisions/use-x#Why|the why]]",
            "[[repos/alpha/decisions/use-x#Why|the why]]",
        ),
        ("| [[company/p/alpha/index\\|Alpha]] |", "| [[repos/alpha/index\\|Alpha]] |"),
        ("![[company/p/alpha/assets/logo.png]]", "![[repos/alpha/assets/logo.png]]"),
    ],
)
def test_every_link_form_to_a_moved_file_is_rewritten(
    rewriter: WikilinkRewriter, link: str, expected: str
) -> None:
    assert rewriter.rewrite(f"see {link} here") == (f"see {expected} here", 1)


@pytest.mark.parametrize(
    "link",
    [
        "[[repos/beta/concepts/arch]]",  # not moved
        "[[arch]]",
        "[[use-x]]",  # a bare name that still finds the same file
        "[[alpha/decisions/use-x]]",  # a path tail that still finds the same file
        "[[repos/alpha/index]]",  # already rewritten
        "[[nowhere]]",
        "[[#heading]]",
        "[x](company/p/alpha/index.md)",
    ],
)
def test_other_links_are_left_alone(rewriter: WikilinkRewriter, link: str) -> None:
    assert rewriter.rewrite(link) == (link, 0)


def test_a_link_that_no_longer_finds_its_file_is_made_explicit_but_ambiguous_ones_are_not_guessed() -> (
    None
):
    files = [*FILES, "repos/gamma/index.md"]
    moves = {"company/p/alpha/index.md": "repos/alpha/index.md"}
    rewriter = WikilinkRewriter(moves, files)
    assert rewriter.rewrite("[[p/alpha/index]]") == ("[[repos/alpha/index]]", 1)
    assert rewriter.rewrite("[[index]]") == ("[[index]]", 0)  # ambiguous before the move already


def test_unresolved_links_are_counted_before_and_after(rewriter: WikilinkRewriter) -> None:
    text = "[[company/p/alpha/index]] [[nowhere]] [[repos/alpha/index]]"
    assert rewriter.count_unresolved(text, after=False) == 2
    assert rewriter.count_unresolved(text, after=True) == 2
    assert rewriter.count_unresolved("[[company/p/alpha/index]]", after=True) == 1
    fixed, _ = rewriter.rewrite("[[company/p/alpha/index]]")
    assert rewriter.count_unresolved(fixed, after=True) == 0


def test_rewriting_twice_changes_nothing_more(rewriter: WikilinkRewriter) -> None:
    once, count = rewriter.rewrite(
        "[[company/p/alpha/index|A]] [[company/p/alpha/decisions/use-x#h]]"
    )
    assert count == 2
    assert rewriter.rewrite(once) == (once, 0)
