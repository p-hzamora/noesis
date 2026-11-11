"""One place notes are read from or written to, as the manifest declares it."""

from enum import StrEnum

from noesis.utils import FrozenObject


class SourceTypeEnum(StrEnum):
    """How a source is reached."""

    OBSIDIAN = "obsidian"
    FILESYSTEM = "filesystem"
    VECTOR = "vector"


class SourceRoleEnum(StrEnum):
    """PRIMARY: read and written, exactly one. READ: recall only. INDEX: derived, rebuildable."""

    PRIMARY = "primary"
    READ = "read"
    INDEX = "index"


class SourceSpec(FrozenObject):
    """A source of notes.

    Attributes:
        name: Unique name inside the manifest.
        type: How the source is reached.
        path: Folder, relative to the manifest's source root or absolute (filesystem, obsidian).
        url: Endpoint (vector, obsidian).
        role: Primary, read or index.
    """

    name: str
    type: SourceTypeEnum
    path: str | None = None
    url: str | None = None
    role: SourceRoleEnum
