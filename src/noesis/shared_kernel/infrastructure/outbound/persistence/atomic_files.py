"""Atomic file writes: readers never see a half-written file."""

import json
from pathlib import Path

from noesis.shared_kernel.domain import (
    JsonObject,
)


def write_text_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` through a temporary file and an atomic rename.

    Args:
        path: Destination file; missing parent folders are created.
        text: UTF-8 content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json_atomic(path: Path, data: JsonObject) -> None:
    """Write `data` to `path` as indented JSON, atomically.

    Args:
        path: Destination file; missing parent folders are created.
        data: JSON object to store.
    """
    write_text_atomic(path, json.dumps(data, indent=2, sort_keys=True))


def read_json_object(path: Path) -> JsonObject | None:
    """Return the JSON object stored at `path`.

    Args:
        path: File to read.

    Returns:
        The object, or None when the file is missing, unreadable, or not a JSON object.
    """
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
