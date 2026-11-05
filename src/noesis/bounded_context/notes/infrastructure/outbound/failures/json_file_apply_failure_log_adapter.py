"""`IApplyFailureLog` keeping each failed payload and its error report as files."""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from noesis.bounded_context.notes.application.dtos import ApplyFailureRecordDto
from noesis.bounded_context.notes.application.ports.failures import IApplyFailureLog
from noesis.bounded_context.notes.domain.value_objects import NoteArea
from noesis.exceptions import NoteStorageError
from noesis.shared_kernel.infrastructure.outbound.persistence import (
    write_json_atomic,
    write_text_atomic,
)

TICKET_SUFFIX_LENGTH: int = 6


class JsonFileApplyFailureLogAdapter(IApplyFailureLog):
    """Writes `<ticket>.payload.json|txt` (the input, verbatim) and `<ticket>.json` (the report).

    The payload keeps the caller's bytes so it can be fixed and passed to `notes apply` again;
    it gets a `.json` name when it is valid JSON and `.txt` when it is not.
    """

    def __init__(self, folder: Path) -> None:
        self._folder: Path = folder

    async def record(
        self,
        *,
        raw_payload: str,
        area: NoteArea,
        commits: tuple[str, ...],
        session: str | None,
        errors: Sequence[str],
        now: datetime,
    ) -> ApplyFailureRecordDto:
        """Write the payload, then the report that names it."""
        ticket: str = f"{now:%Y%m%dT%H%M%S}-{uuid4().hex[:TICKET_SUFFIX_LENGTH]}"
        payload_file: Path = self._folder / f"{ticket}.payload.{_extension(raw_payload)}"
        record_file: Path = self._folder / f"{ticket}.json"
        try:
            write_text_atomic(payload_file, raw_payload)
            write_json_atomic(
                record_file,
                {
                    "ticket": ticket,
                    "recorded_at": now.isoformat(),
                    "area": area.value,
                    "commits": list(commits),
                    "session": session,
                    "errors": list(errors),
                    "payload_file": payload_file.name,
                },
            )
        except OSError as error:
            raise NoteStorageError(
                f"Cannot keep the failed payload under {self._folder}: {error}",
                {"folder": str(self._folder)},
            ) from error
        return ApplyFailureRecordDto(
            ticket=ticket, path=str(record_file), payload_path=str(payload_file)
        )


def _extension(raw_payload: str) -> str:
    """`json` when the payload parses as JSON, else `txt`."""
    try:
        json.loads(raw_payload)
    except json.JSONDecodeError:
        return "txt"
    return "json"
