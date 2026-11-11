"""Recall with synthesis: multi-keyword search, bounded full reads, grounded briefing, honest failures."""

import pytest
from tests.support.notes_support import (
    DefaultManifestProvider,
    FixedClock,
    InMemoryNoteReadRepository,
    ScriptedRecallAgent,
    a_summary,
)

from noesis.bounded_context.notes.application.dtos import (
    BriefingItemDto,
    NoteSummaryDto,
    RecallBriefingDto,
)
from noesis.bounded_context.notes.application.handlers.queries import (
    RecallNotesHandler,
    RecallNotesQuery,
)
from noesis.exceptions import NoteStorageError, RecallAgentFailedError

pytestmark = pytest.mark.unit

PRIVACY = "repos/cv/decisions/privacy.md"
GROUNDING = "repos/cv/decisions/grounding.md"
GOTCHA = "repos/cv/gotchas/history.md"
TASK = "Continue the cv-generator project while preserving candidate privacy"


def _note(path: str, title: str, snippet: str, *, kind: str = "decision") -> NoteSummaryDto:
    return a_summary(
        path, title=title, kind=kind, origin="manual", updated="2026-11-01", snippet=snippet
    )


NOTES = (
    _note(PRIVACY, "Candidate privacy", "candidate data stays local"),
    _note(GROUNDING, "Evidence grounding", "every claim cites evidence"),
    _note(GOTCHA, "History keeps files", "untracking keeps candidate history", kind="gotcha"),
)
ANSWER = RecallBriefingDto(
    summary="Keep candidate data local.",
    constraints=(BriefingItemDto(text="no cloud upload", sources=(PRIVACY,)),),
    gotchas=(BriefingItemDto(text="history keeps files", sources=(GOTCHA, "repos/cv/made-up.md")),),
    decisions=(BriefingItemDto(text="uncited claim", sources=("repos/cv/made-up.md",)),),
    not_covered=("hosting",),
    model="claude-haiku-5-5",
)


def _handler(
    answer: RecallBriefingDto | str = ANSWER,
    *,
    notes: tuple[NoteSummaryDto, ...] = NOTES,
    max_input_chars: int = 60_000,
    **repository_options: object,
) -> tuple[RecallNotesHandler, InMemoryNoteReadRepository, ScriptedRecallAgent]:
    repository = InMemoryNoteReadRepository(notes, match_all=False, **repository_options)  # type: ignore[arg-type]
    agent = ScriptedRecallAgent(answer)
    handler = RecallNotesHandler(
        read_repository=repository,
        manifest=DefaultManifestProvider(),
        clock=FixedClock(),
        agent=agent,
        max_input_chars=max_input_chars,
    )
    return handler, repository, agent


async def test_notes_found_by_different_keywords_are_all_candidates() -> None:
    handler, repository, _ = _handler()

    digest = await handler.handle(RecallNotesQuery(task=TASK, scope="repo:cv"))

    # the combined sentence would match nothing; each keyword finds its own notes
    assert "candidate" in repository.queries and "privacy" in repository.queries
    assert set(repository.read_paths) == {PRIVACY, GOTCHA}  # GROUNDING matches no keyword
    assert digest.considered == 2


async def test_the_agent_gets_the_full_text_of_the_notes_read_and_the_task() -> None:
    handler, _, agent = _handler(bodies={PRIVACY: "FULL BODY of privacy " * 5})

    await handler.handle(RecallNotesQuery(task=TASK, budget_tokens=700))

    task, notes, target = agent.calls[0]
    assert task == TASK
    assert target == 700
    assert next(note for note in notes if note.path == PRIVACY).content.startswith("FULL BODY")


async def test_the_briefing_is_checked_against_the_notes_read() -> None:
    handler, _, _ = _handler()

    digest = await handler.handle(RecallNotesQuery(task=TASK))

    assert digest.synthesis == "briefing"
    briefing = digest.briefing
    assert briefing is not None
    assert briefing.gotchas[0].sources == (GOTCHA,)  # the invented path is gone
    assert [item.text for item in briefing.unsupported] == ["uncited claim"]
    assert briefing.model == "claude-haiku-5-5"
    assert "# Recall briefing: " in briefing.markdown
    assert any("set aside" in warning for warning in digest.warnings)
    assert {entry.path for entry in digest.entries} == {PRIVACY, GOTCHA}


async def test_only_the_top_limit_notes_are_read() -> None:
    handler, repository, _ = _handler(
        notes=tuple(_note(f"repos/cv/n{i}.md", f"project note {i}", "project") for i in range(8))
    )

    digest = await handler.handle(RecallNotesQuery(task="project notes", limit=2))

    assert len(repository.read_paths) == 2
    assert (digest.considered, digest.omitted) == (6, 4)  # each query fetches 3 x limit


async def test_no_evidence_means_no_agent_call_and_an_explicit_status() -> None:
    handler, repository, agent = _handler(notes=())

    digest = await handler.handle(RecallNotesQuery(task=TASK))

    assert (digest.synthesis, digest.briefing, digest.entries) == ("no_evidence", None, ())
    assert agent.calls == []
    assert repository.read_paths == []


async def test_no_evidence_in_a_scope_warns_which_scope_was_searched() -> None:
    handler, _, _ = _handler(notes=())

    digest = await handler.handle(RecallNotesQuery(task=TASK, scope="repo:noesis"))

    assert len(digest.warnings) == 1
    assert "repo:noesis" in digest.warnings[0]


async def test_no_evidence_without_a_scope_has_no_scope_warning() -> None:
    handler, _, _ = _handler(notes=())

    digest = await handler.handle(RecallNotesQuery(task=TASK))

    assert digest.warnings == ()


async def test_without_synthesis_no_note_is_read_and_no_agent_runs() -> None:
    handler, repository, agent = _handler()

    digest = await handler.handle(RecallNotesQuery(task=TASK, synthesize=False))

    assert (digest.synthesis, digest.briefing) == ("digest", None)
    assert agent.calls == [] and repository.read_paths == []
    assert digest.entries


async def test_secrets_are_masked_before_the_agent_sees_the_notes() -> None:
    handler, _, agent = _handler(bodies={PRIVACY: "token=sk-ant-api03-abcdefghijklmnopqrstuv\nok"})

    digest = await handler.handle(RecallNotesQuery(task=TASK))

    sent = next(note for note in agent.calls[0][1] if note.path == PRIVACY).content
    assert "sk-ant" not in sent and "[REDACTED]" in sent
    assert any("Masked 1 possible secrets" in warning for warning in digest.warnings)


async def test_long_notes_are_cut_to_their_share_of_the_input_limit_and_say_so() -> None:
    handler, _, agent = _handler(
        max_input_chars=2_000, bodies={PRIVACY: "a" * 5_000, GOTCHA: "b" * 10}
    )

    digest = await handler.handle(RecallNotesQuery(task=TASK))

    notes = {note.path: note.content for note in agent.calls[0][1]}
    assert len(notes[PRIVACY]) < 1_200 and "note cut here" in notes[PRIVACY]
    assert notes[GOTCHA] == "b" * 10
    assert any(PRIVACY in warning and "Cut" in warning for warning in digest.warnings)


async def test_an_unreadable_note_is_reported_and_the_rest_still_brief() -> None:
    handler, _, agent = _handler(unreadable=[PRIVACY])

    digest = await handler.handle(RecallNotesQuery(task=TASK))

    assert [note.path for note in agent.calls[0][1]] == [GOTCHA]
    assert any(PRIVACY in warning and "Could not read" in warning for warning in digest.warnings)
    assert digest.synthesis == "briefing"


async def test_when_no_note_can_be_read_it_fails_instead_of_briefing_from_nothing() -> None:
    handler, _, agent = _handler(unreadable=[PRIVACY, GOTCHA])

    with pytest.raises(NoteStorageError) as raised:
        await handler.handle(RecallNotesQuery(task=TASK))

    assert agent.calls == []
    assert raised.value.metadata["candidates"] == [PRIVACY, GOTCHA]


async def test_an_agent_failure_propagates_with_the_candidates_and_a_way_out() -> None:
    handler, _, _ = _handler("claude is not installed")

    with pytest.raises(RecallAgentFailedError) as raised:
        await handler.handle(RecallNotesQuery(task=TASK))

    assert raised.value.metadata["candidates"] == [PRIVACY, GOTCHA]
    assert any("--no-synthesis" in step for step in raised.value.next_steps)


async def test_synthesis_without_an_agent_is_an_error_not_a_silent_digest() -> None:
    repository = InMemoryNoteReadRepository(NOTES, match_all=False)
    handler = RecallNotesHandler(
        read_repository=repository, manifest=DefaultManifestProvider(), clock=FixedClock()
    )

    with pytest.raises(RecallAgentFailedError):
        await handler.handle(RecallNotesQuery(task=TASK))


async def test_a_rare_keyword_outweighs_a_generic_one_in_the_merge() -> None:
    generic = tuple(_note(f"repos/cv/g{i}.md", f"working {i}", "working") for i in range(6))
    rare = _note("repos/cv/rare.md", "Evidence grounding", "grounding")
    handler, repository, _ = _handler(notes=(*generic, rare))

    await handler.handle(RecallNotesQuery(task="working grounding", limit=1))

    assert repository.read_paths == ["repos/cv/rare.md"]
