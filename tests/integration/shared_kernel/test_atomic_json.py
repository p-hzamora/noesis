"""Atomic JSON persistence helpers."""

from pathlib import Path

import pytest

from noesis.shared_kernel.infrastructure.outbound.persistence import (
    read_json_object,
    write_json_atomic,
)

pytestmark = pytest.mark.integration


def test_written_objects_read_back_and_leave_no_temporary_file(tmp_path: Path) -> None:
    target: Path = tmp_path / "nested" / "state.json"

    write_json_atomic(target, {"offset": 3, "items": ["a"]})

    assert read_json_object(target) == {"offset": 3, "items": ["a"]}
    assert [path.name for path in target.parent.iterdir()] == ["state.json"]


@pytest.mark.parametrize("content", [None, "not json", "[1, 2]"])
def test_missing_malformed_or_non_object_files_read_as_none(
    tmp_path: Path, content: str | None
) -> None:
    target: Path = tmp_path / "state.json"
    if content is not None:
        target.write_text(content, encoding="utf-8")

    assert read_json_object(target) is None
