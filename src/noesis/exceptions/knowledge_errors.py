"""Errors of the Knowledge context."""

from .base import ApplicationException, DomainException


class InvalidRecordIdError(DomainException):
    """A record or space id is not a ULID."""

    __error_code__ = "KNOWLEDGE_001_INVALID_RECORD_ID"


class InvalidSlugError(DomainException):
    """A subtype or tag is not lowercase letters, digits and single hyphens."""

    __error_code__ = "KNOWLEDGE_002_INVALID_SLUG"


class InvalidContentHashError(DomainException):
    """A content hash is not `sha256:` followed by 64 lowercase hex digits."""

    __error_code__ = "KNOWLEDGE_003_INVALID_CONTENT_HASH"


class InvalidKeyError(DomainException):
    """A space or project key is not a short name of letters, digits, dots, hyphens, underscores."""

    __error_code__ = "KNOWLEDGE_004_INVALID_KEY"


class KnowledgeNotRevisableError(DomainException):
    """Knowledge can be revised only while it is `proposed`."""

    __error_code__ = "KNOWLEDGE_005_KNOWLEDGE_NOT_REVISABLE"


class ExperienceWithoutSourceError(DomainException):
    """An experience needs at least one source."""

    __error_code__ = "KNOWLEDGE_006_EXPERIENCE_WITHOUT_SOURCE"


class InvalidRecordError(DomainException):
    """A record, revision or reference breaks a domain invariant."""

    __error_code__ = "KNOWLEDGE_007_INVALID_RECORD"


class RecordNotFoundError(ApplicationException):
    """No record has the requested id (or revision) in the active space."""

    __error_code__ = "KNOWLEDGE_201_RECORD_NOT_FOUND"


class RevisionConflictError(ApplicationException):
    """The expected head revision is not the record's current head."""

    __error_code__ = "KNOWLEDGE_202_REVISION_CONFLICT"


class IdempotencyKeyReusedError(ApplicationException):
    """An idempotency key was already used for a different request."""

    __error_code__ = "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"


class StoreNotInitialisedError(ApplicationException):
    """The store lacks a schema step the command requires."""

    __error_code__ = "KNOWLEDGE_204_STORE_NOT_INITIALISED"


class ReferenceNotInSpaceError(ApplicationException):
    """A referenced project, source or record does not exist in the command's space."""

    __error_code__ = "KNOWLEDGE_205_REFERENCE_NOT_IN_SPACE"


class EntryAlreadyExistsError(ApplicationException):
    """A write lost a uniqueness race; the caller re-reads and reuses the winner."""

    __error_code__ = "KNOWLEDGE_206_ENTRY_ALREADY_EXISTS"


class RecordNotRevisableError(ApplicationException):
    """The record exists but its type has no revisions (an experience is write-once)."""

    __error_code__ = "KNOWLEDGE_207_RECORD_NOT_REVISABLE"


class SpaceNotFoundError(ApplicationException):
    """No knowledge space has the requested key."""

    __error_code__ = "KNOWLEDGE_208_SPACE_NOT_FOUND"
