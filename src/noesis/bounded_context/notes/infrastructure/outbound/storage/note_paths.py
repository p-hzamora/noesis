"""Checks on a vault-relative note path before anything reads it."""

from pathlib import PurePosixPath

from noesis.bounded_context.notes.domain.value_objects import NoteArea
from noesis.exceptions import NoteStorageError

NOTE_SUFFIX: str = ".md"


def checked_note_path(path: str, area: NoteArea | None) -> str:
    """`path` normalised, if it is a Markdown note inside `area` (or anywhere when None).

    Raises:
        NoteStorageError: The path is absolute, escapes with `..`, touches a hidden folder or
            file, is not Markdown, or lies outside `area`.
    """
    clean: str = path.lstrip("/")
    parts: tuple[str, ...] = PurePosixPath(clean).parts
    if (
        not clean
        or not clean.endswith(NOTE_SUFFIX)
        or any(part in {"..", "."} or part.startswith(".") for part in parts)
        or (area is not None and not clean.startswith(f"{area.value}/"))
    ):
        raise NoteStorageError(
            f"Refusing to read {path!r}: not a note inside the allowed scope.",
            {"path": path, "area": area.value if area else None},
        )
    return clean
