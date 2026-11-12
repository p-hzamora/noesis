"""Errors of the Notes context."""

from .base import ApplicationException, DomainException, InfrastructureException


class InvalidNoteSlugError(DomainException):
    """A note slug is not lowercase letters, digits, and single hyphens."""

    __error_code__ = "NOTES_001_INVALID_NOTE_SLUG"


class InvalidNoteScopeError(DomainException):
    """A note scope is not `repo:<name>` or `topic:<name>` with a safe name."""

    __error_code__ = "NOTES_002_INVALID_NOTE_SCOPE"


class ManualNoteProtectedError(DomainException):
    """Automated curation tried to change a note a person wrote."""

    __error_code__ = "NOTES_003_MANUAL_NOTE_PROTECTED"


class InvalidNotePathError(DomainException):
    """A note path is not a safe relative Markdown path inside the vault."""

    __error_code__ = "NOTES_004_INVALID_NOTE_PATH"


class InvalidNoteIdError(DomainException):
    """A note id is not a ULID."""

    __error_code__ = "NOTES_005_INVALID_NOTE_ID"


class InvalidNoteKindError(DomainException):
    """A note kind name is not lowercase words joined by hyphens."""

    __error_code__ = "NOTES_006_INVALID_NOTE_KIND"


class InvalidNoteSourceRefError(DomainException):
    """A note source reference is not `<type>:<id>`."""

    __error_code__ = "NOTES_007_INVALID_NOTE_SOURCE_REF"


class CuratorFailedError(InfrastructureException):
    """The curator run failed or answered something unusable."""

    __error_code__ = "NOTES_101_CURATOR_FAILED"


class RecallAgentFailedError(InfrastructureException):
    """The recall agent could not produce a briefing: missing, failed, timed out or unusable."""

    __error_code__ = "NOTES_103_RECALL_AGENT_FAILED"


class NoteStorageError(InfrastructureException):
    """Notes could not be read from or written to the vault."""

    __error_code__ = "NOTES_102_NOTE_STORAGE_FAILED"


class CurationFailedError(ApplicationException):
    """Curation or storage kept failing; the brief was parked for a manual retry."""

    __error_code__ = "NOTES_201_CURATION_FAILED"


class ParkedCurationNotFoundError(ApplicationException):
    """No parked curation has the requested ticket."""

    __error_code__ = "NOTES_202_PARKED_CURATION_NOT_FOUND"


class ApplyFailedError(ApplicationException):
    """An apply was rejected or could not be stored; the payload was kept for a second try."""

    __error_code__ = "NOTES_203_APPLY_FAILED"


class NoRecallTermsError(ApplicationException):
    """A recall task has no keywords left once short words and stopwords are removed."""

    __error_code__ = "NOTES_204_NO_RECALL_TERMS"


class InvalidManifestError(ApplicationException):
    """A `noesis.yaml` manifest (or the merge of it with the default) breaks a rule."""

    __error_code__ = "NOTES_205_INVALID_MANIFEST"


class UnknownNoteKindError(ApplicationException):
    """A note kind is not in the manifest's kind catalog."""

    __error_code__ = "NOTES_206_UNKNOWN_NOTE_KIND"


class InvalidMigrationPlanError(ApplicationException):
    """A vault migration plan is malformed, or does not fit the vault it is applied to."""

    __error_code__ = "NOTES_207_INVALID_MIGRATION_PLAN"


class MigrationConflictError(ApplicationException):
    """A migration target already exists with different content; nothing was written."""

    __error_code__ = "NOTES_208_MIGRATION_CONFLICT"


class MigrationVerificationError(InfrastructureException):
    """A written migration target does not match its source; no source file was deleted."""

    __error_code__ = "NOTES_104_MIGRATION_VERIFICATION_FAILED"
