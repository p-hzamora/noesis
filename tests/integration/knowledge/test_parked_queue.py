"""File-based parked-curation queue."""

from pathlib import Path

import pytest
from tests.support.knowledge_support import NOW, a_brief

from noesis.bounded_context.knowledge.infrastructure.outbound.queue import (
    JsonFileParkedCurationQueueAdapter,
)

pytestmark = pytest.mark.integration


async def test_parked_briefs_round_trip_and_are_discarded(tmp_path: Path) -> None:
    queue = JsonFileParkedCurationQueueAdapter(tmp_path / "parked")
    assert await queue.list_parked() == []

    ticket: str = await queue.park(a_brief(), error="MCP 401", now=NOW)
    (tmp_path / "parked/garbage.json").write_text("{}", encoding="utf-8")

    assert ticket.startswith("20261030T120000-")
    assert [(p.ticket, p.repository, p.error) for p in await queue.list_parked()] == [
        (ticket, "demo", "MCP 401")
    ]
    assert await queue.get(ticket) == a_brief()
    assert await queue.get("missing") is None
    await queue.discard(ticket)
    assert await queue.get(ticket) is None
