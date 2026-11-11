"""A briefing is checked against the notes that were read, then written as Markdown."""

import pytest
from tests.support.notes_support import a_content

from noesis.bounded_context.notes.application.dtos import (
    BriefingItemDto,
    NoteContentDto,
    RecallBriefingDto,
)
from noesis.bounded_context.notes.application.services.recall import BriefingGrounder

pytestmark = pytest.mark.unit

A = "repos/demo/decisions/a.md"
B = "repos/demo/gotchas/b.md"


def _note(path: str, title: str) -> NoteContentDto:
    return a_content(path, title=title)


NOTES = (_note(A, "Note A"), _note(B, "Note B"))


def _item(text: str, *sources: str) -> BriefingItemDto:
    return BriefingItemDto(text=text, sources=sources)


def test_citations_to_notes_that_were_not_read_are_removed() -> None:
    draft = RecallBriefingDto(
        summary="s",
        constraints=(_item("keep it private", A, "repos/demo/invented.md", "/" + B),),
    )

    checked = BriefingGrounder.ground(draft, NOTES)

    assert checked.constraints == (_item("keep it private", A, B),)
    assert checked.unsupported == ()


@pytest.mark.parametrize("field", ["constraints", "decisions", "gotchas", "context"])
def test_a_grounded_item_without_a_valid_citation_is_set_aside_not_kept(field: str) -> None:
    draft = RecallBriefingDto(
        summary="s", **{field: (_item("made up", "repos/demo/invented.md"), _item("no sources"))}
    )

    checked = BriefingGrounder.ground(draft, NOTES)

    assert getattr(checked, field) == ()
    assert [item.text for item in checked.unsupported] == ["made up", "no sources"]


def test_inferences_and_open_questions_may_have_no_citation() -> None:
    draft = RecallBriefingDto(
        summary="s",
        inferences=(_item("probably x", "repos/demo/invented.md"),),
        open_questions=(_item("who decides?"),),
        not_covered=("deployment",),
    )

    checked = BriefingGrounder.ground(draft, NOTES)

    assert checked.inferences == (_item("probably x"),)
    assert checked.open_questions == (_item("who decides?"),)
    assert checked.unsupported == ()
    assert checked.not_covered == ("deployment",)


def test_markdown_separates_grounded_claims_from_inferences_and_lists_the_notes_read() -> None:
    draft = RecallBriefingDto(
        summary="Mind privacy.",
        constraints=(_item("never log candidate data", A),),
        gotchas=(_item("untracking keeps history", B, A),),
        inferences=(_item("export needs a gate too", A),),
        not_covered=("deployment",),
    )

    markdown = BriefingGrounder.markdown(
        "continue the CV work", BriefingGrounder.ground(draft, NOTES), NOTES
    )

    assert markdown.startswith("# Recall briefing: continue the CV work\n\nMind privacy.")
    assert f"- never log candidate data [`{A}`]" in markdown
    assert f"- untracking keeps history [`{B}`, `{A}`]" in markdown
    assert "## Inferences (the agent's reasoning; the notes do not state these)" in markdown
    assert "## Decisions\n\n_None stated in the notes._" in markdown
    assert "## Not covered by the notes\n\n- deployment" in markdown
    assert (
        f"## Notes read\n\n- `{A}`: Note A (2026-11-01)\n- `{B}`: Note B (2026-11-01)" in markdown
    )
