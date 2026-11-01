"""`IParkedCurationQueue` storing one JSON file per parked brief."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from noesis.bounded_context.knowledge.application.dtos import ParkedCurationDto
from noesis.bounded_context.knowledge.application.ports.queue import IParkedCurationQueue
from noesis.shared_kernel.contracts import WorkBriefContract
from noesis.shared_kernel.domain import (
    JsonObject,
)
from noesis.shared_kernel.infrastructure.outbound.persistence import (
    read_json_object,
    write_json_atomic,
)

TICKET_SUFFIX_LENGTH: int = 6


class JsonFileParkedCurationQueueAdapter(IParkedCurationQueue):
    """Parked briefs live in `<state dir>/knowledge/parked/<ticket>.json`."""

    def __init__(self, folder: Path) -> None:
        self._folder: Path = folder

    def _file(self, ticket: str) -> Path:
        return self._folder / f"{Path(ticket).name}.json"

    async def park(self, brief: WorkBriefContract, *, error: str, now: datetime) -> str:
        """Store the brief; the ticket sorts by time (`YYYYmmddTHHMMSS-xxxxxx`)."""
        ticket: str = f"{now:%Y%m%dT%H%M%S}-{uuid4().hex[:TICKET_SUFFIX_LENGTH]}"
        write_json_atomic(
            self._file(ticket),
            {
                "ticket": ticket,
                "parked_at": now.isoformat(),
                "error": error,
                "brief": brief.model_dump(mode="json"),
            },
        )
        return ticket

    def _entries(self) -> list[tuple[JsonObject, WorkBriefContract]]:
        entries: list[tuple[JsonObject, WorkBriefContract]] = []
        for path in sorted(self._folder.glob("*.json")) if self._folder.is_dir() else []:
            data: JsonObject | None = read_json_object(path)
            raw_brief: object = data.get("brief") if data else None
            if data is None or not isinstance(raw_brief, dict):
                continue
            try:
                entries.append((data, WorkBriefContract.model_validate(raw_brief)))
            except ValidationError:
                continue  # an unreadable entry must not hide the others
        return entries

    async def list_parked(self) -> list[ParkedCurationDto]:
        """Every parked brief, oldest first."""
        return [
            ParkedCurationDto(
                ticket=str(data.get("ticket", "")),
                repository=brief.repository,
                head=brief.head,
                parked_at=str(data.get("parked_at", "")),
                error=str(data.get("error", "")),
            )
            for data, brief in self._entries()
        ]

    async def get(self, ticket: str) -> WorkBriefContract | None:
        """The brief behind `ticket`, or None."""
        data: JsonObject | None = read_json_object(self._file(ticket))
        raw_brief: object = data.get("brief") if data else None
        if not isinstance(raw_brief, dict):
            return None
        try:
            return WorkBriefContract.model_validate(raw_brief)
        except ValidationError:
            return None

    async def discard(self, ticket: str) -> None:
        """Remove the entry (no error if it is already gone)."""
        self._file(ticket).unlink(missing_ok=True)
