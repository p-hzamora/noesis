"""Errors of the Knowledge context."""

from noesis.exceptions.base import (
    ApplicationException,
    DomainException,
    InfrastructureException,
)


class InvalidNoteSlugError(DomainException):
    """A note slug is not lowercase letters, digits, and single hyphens."""

    __error_code__ = "KNOWLEDGE_001_INVALID_NOTE_SLUG"


class InvalidNoteAreaError(DomainException):
    """A note area is not a safe relative folder inside the vault."""

    __error_code__ = "KNOWLEDGE_002_INVALID_NOTE_AREA"


class ManualNoteProtectedError(DomainException):
    """Automated curation tried to change a note a person wrote."""

    __error_code__ = "KNOWLEDGE_003_MANUAL_NOTE_PROTECTED"


class InvalidNoteLocationError(DomainException):
    """A file path does not follow the vault's note layout."""

    __error_code__ = "KNOWLEDGE_004_INVALID_NOTE_LOCATION"


class CuratorFailedError(InfrastructureException):
    """The curator run failed or answered something unusable."""

    __error_code__ = "KNOWLEDGE_101_CURATOR_FAILED"


class NoteStorageError(InfrastructureException):
    """Notes could not be read from or written to the vault."""

    __error_code__ = "KNOWLEDGE_102_NOTE_STORAGE_FAILED"


class CurationFailedError(ApplicationException):
    """Curation kept failing; the brief was parked for a manual retry."""

    __error_code__ = "KNOWLEDGE_201_CURATION_FAILED"


class ParkedCurationNotFoundError(ApplicationException):
    """No parked curation has the requested ticket."""

    __error_code__ = "KNOWLEDGE_202_PARKED_CURATION_NOT_FOUND"
