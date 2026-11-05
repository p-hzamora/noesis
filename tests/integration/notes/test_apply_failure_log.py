"""File-based log of failed apply payloads."""

import json
from pathlib import Path

import pytest
from tests.support.notes_support import NOW

from noesis.bounded_context.notes.domain.value_objects import NoteArea
from noesis.bounded_context.notes.infrastructure.outbound.failures import (
    JsonFileApplyFailureLogAdapter,
)
from noesis.exceptions import NoteStorageError

pytestmark = pytest.mark.integration

AREA = NoteArea.for_repository("demo")


async def test_a_json_payload_is_kept_verbatim_with_its_report(tmp_path: Path) -> None:
    log = JsonFileApplyFailureLogAdapter(tmp_path / "apply-failed")
    raw = '{"decisions": [ {"action": "create"} ]}\n'

    record = await log.record(
        raw_payload=raw,
        area=AREA,
        commits=("abc",),
        session="abcd1234",
        errors=["entry 0: missing kind or title"],
        now=NOW,
    )

    assert record.ticket.startswith("20261030T120000-")
    assert Path(record.payload_path).name == f"{record.ticket}.payload.json"
    assert Path(record.payload_path).read_text() == raw
    report = json.loads(Path(record.path).read_text())
    assert report["errors"] == ["entry 0: missing kind or title"]
    assert report["area"] == "repos/demo"
    assert report["commits"] == ["abc"]
    assert report["session"] == "abcd1234"
    assert report["payload_file"] == Path(record.payload_path).name


async def test_a_payload_that_is_not_json_is_kept_as_text(tmp_path: Path) -> None:
    log = JsonFileApplyFailureLogAdapter(tmp_path)

    record = await log.record(
        raw_payload="{oops", area=AREA, commits=(), session=None, errors=["x"], now=NOW
    )

    assert record.payload_path.endswith(".payload.txt")
    assert Path(record.payload_path).read_text() == "{oops"


async def test_every_failure_gets_its_own_ticket(tmp_path: Path) -> None:
    log = JsonFileApplyFailureLogAdapter(tmp_path)

    first = await log.record(
        raw_payload="1", area=AREA, commits=(), session=None, errors=[], now=NOW
    )
    second = await log.record(
        raw_payload="2", area=AREA, commits=(), session=None, errors=[], now=NOW
    )

    assert first.ticket != second.ticket
    assert Path(first.payload_path).read_text() == "1"


async def test_an_unwritable_folder_is_a_storage_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    log = JsonFileApplyFailureLogAdapter(blocker / "apply-failed")

    with pytest.raises(NoteStorageError):
        await log.record(raw_payload="x", area=AREA, commits=(), session=None, errors=[], now=NOW)
