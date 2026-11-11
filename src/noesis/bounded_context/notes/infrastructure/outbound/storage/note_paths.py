"""Checks on a source-relative note path before anything reads it."""

from pathlib import PurePosixPath

from noesis.exceptions import NoteStorageError

NOTE_SUFFIX: str = ".md"


def checked_note_path(path: str) -> str:
    """`path` normalised, if it is a visible Markdown file path.

    Raises:
        NoteStorageError: The path is absolute, escapes with `..`, touches a hidden folder or
            file, or is not Markdown.
    """
    clean: str = path.lstrip("/")
    parts: tuple[str, ...] = PurePosixPath(clean).parts
    if (
        not clean
        or not clean.endswith(NOTE_SUFFIX)
        or any(part in {"..", "."} or part.startswith(".") for part in parts)
    ):
        raise NoteStorageError(
            f"Refusing to read {path!r}: not a note inside the source.", {"path": path}
        )
    return clean
