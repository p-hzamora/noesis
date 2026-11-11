"""Search and list queries."""

import pytest
from pydantic import ValidationError
from tests.support.notes_support import (
    NOW,
    InMemoryNoteReadRepository,
    InMemoryParkedQueue,
    a_brief,
    a_summary,
)

from noesis.bounded_context.notes.application.dtos import NoteSummaryDto
from noesis.bounded_context.notes.application.handlers.queries import (
    ListNotesHandler,
    ListNotesQuery,
    ListParkedCurationsHandler,
    ListParkedCurationsQuery,
    SearchNotesHandler,
    SearchNotesQuery,
)
from noesis.bounded_context.notes.domain.value_objects import NoteOriginEnum

pytestmark = pytest.mark.unit

NOTES: list[NoteSummaryDto] = [
    a_summary(
        f"repos/demo/{origin}/decisions/{i}.md",
        title=str(i),
        origin=origin,
        updated=None,
        snippet="",
    )
    for i, origin in enumerate(["auto", "manual", "auto"])
]


async def test_search_limits_results() -> None:
    handler = SearchNotesHandler(read_repository=InMemoryNoteReadRepository(NOTES))

    result = await handler.handle(SearchNotesQuery(text="cache", area="repos/demo", limit=2))

    assert len(result.notes) == 2


def test_search_needs_text_and_a_sane_limit() -> None:
    with pytest.raises(ValidationError):
        SearchNotesQuery(text="")
    with pytest.raises(ValidationError):
        SearchNotesQuery(text="x", limit=0)


async def test_list_filters_by_origin() -> None:
    handler = ListNotesHandler(read_repository=InMemoryNoteReadRepository(NOTES))

    result = await handler.handle(ListNotesQuery(origin=NoteOriginEnum.MANUAL))

    assert [note.origin for note in result.notes] == ["manual"]


async def test_parked_curations_are_listed() -> None:
    queue = InMemoryParkedQueue()
    await queue.park(a_brief(), error="down", now=NOW)

    result = await ListParkedCurationsHandler(queue=queue).handle(ListParkedCurationsQuery())

    assert [(item.ticket, item.error) for item in result.parked] == [("ticket-1", "down")]
