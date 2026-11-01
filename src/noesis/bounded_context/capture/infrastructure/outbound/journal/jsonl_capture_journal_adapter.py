"""`ICaptureJournal` as one JSON-lines file per session."""

import json
from pathlib import Path

from pydantic import ValidationError

from noesis.bounded_context.capture.application.dtos import CaptureRunDto
from noesis.bounded_context.capture.application.ports.journal import ICaptureJournal
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.bounded_context.capture.infrastructure.outbound.publishing import (
    BriefFiles,
)
from noesis.shared_kernel.domain import (
    JsonObject,
)
from noesis.shared_kernel.infrastructure.outbound.persistence import read_json_object


class JsonlCaptureJournalAdapter(ICaptureJournal):
    """Entries in `<folder>/<session>.jsonl`; reading attaches each brief's curation result."""

    def __init__(self, folder: Path) -> None:
        self._folder: Path = folder

    def _file(self, session_id: SessionId) -> Path:
        return self._folder / f"{session_id.value}.jsonl"

    async def append(self, session_id: SessionId, entry: CaptureRunDto) -> None:
        """Append one line (append-only, never rewritten)."""
        path: Path = self._file(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json(exclude={"result"}) + "\n")

    async def read(self, session_id: SessionId) -> list[CaptureRunDto]:
        """Every readable entry, oldest first."""
        path: Path = self._file(session_id)
        if not path.is_file():
            return []
        runs: list[CaptureRunDto] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                run: CaptureRunDto = CaptureRunDto.model_validate(json.loads(line))
            except json.JSONDecodeError, ValidationError:
                continue
            result: JsonObject | None = (
                read_json_object(BriefFiles.result_of(Path(run.reference)))
                if run.reference
                else None
            )
            runs.append(run.model_copy(update={"result": result}) if result else run)
        return runs
