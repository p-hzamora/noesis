"""Errors of the Knowledge context."""

from .base import ApplicationException, DomainException, InfrastructureException


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


class InvalidAssertionError(DomainException):
    """An assertion breaks a creation invariant or the kind matrix; the metadata names the field."""

    __error_code__ = "KNOWLEDGE_020_INVALID_ASSERTION"


class InvalidStatusTransitionError(DomainException):
    """The requested review transition is not allowed from the record's current status."""

    __error_code__ = "KNOWLEDGE_021_INVALID_STATUS_TRANSITION"


class ReviewNotAuthorisedError(DomainException):
    """The actor may not take this review decision on this scope."""

    __error_code__ = "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"


class EvidenceRequiredError(DomainException):
    """An agent cannot accept an assertion that has no evidence."""

    __error_code__ = "KNOWLEDGE_023_EVIDENCE_REQUIRED"


class InvalidCatalogNameError(DomainException):
    """A catalog entry name breaks the name grammar (ASCII letters, digits, `.`, `_`, `-`, `:`)."""

    __error_code__ = "KNOWLEDGE_061_INVALID_CATALOG_NAME"


class InvalidCatalogPrerequisiteError(DomainException):
    """A catalog prerequisite is malformed, or an entry lists itself."""

    __error_code__ = "KNOWLEDGE_062_INVALID_CATALOG_PREREQUISITE"


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


class StatusConflictError(ApplicationException):
    """A concurrent review decision on the same record won."""

    __error_code__ = "KNOWLEDGE_220_STATUS_CONFLICT"


class DuplicateAssertionError(ApplicationException):
    """A live (proposed or accepted) assertion already states the same thing."""

    __error_code__ = "KNOWLEDGE_221_DUPLICATE_ASSERTION"


class ReferenceNotAcceptableError(ApplicationException):
    """An endpoint of an assertion is retracted, superseded or not yet accepted."""

    __error_code__ = "KNOWLEDGE_222_REFERENCE_NOT_ACCEPTABLE"


class ExpectedRevisionRequiredError(ApplicationException):
    """Accepting knowledge needs the head revision the reviewer judged."""

    __error_code__ = "KNOWLEDGE_223_EXPECTED_REVISION_REQUIRED"


class RecordNotReviewableError(ApplicationException):
    """The record's type has no review status."""

    __error_code__ = "KNOWLEDGE_224_RECORD_NOT_REVIEWABLE"


class CatalogEntryNotFoundError(ApplicationException):
    """No catalog entry matches the reference (or revision) in the active space."""

    __error_code__ = "KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND"


class CatalogEntryAlreadyExistsError(ApplicationException):
    """A catalog entry with the same kind and name already exists in the space."""

    __error_code__ = "KNOWLEDGE_262_CATALOG_ENTRY_ALREADY_EXISTS"


class InvalidCurationTransitionError(DomainException):
    """A curation ticket was moved to a stage its progress does not allow."""

    __error_code__ = "KNOWLEDGE_040_INVALID_CURATION_TRANSITION"


class CuratorRunFailedError(InfrastructureException):
    """The curator is missing, timed out, failed, or answered something unusable."""

    __error_code__ = "KNOWLEDGE_141_CURATOR_FAILED"


class CurationInboxFailedError(InfrastructureException):
    """The curation inbox cannot be read, written or locked."""

    __error_code__ = "KNOWLEDGE_142_CURATION_INBOX_FAILED"


class CurationParkedError(ApplicationException):
    """A curation failed and its ticket is parked; the metadata names the ticket and the cause."""

    __error_code__ = "KNOWLEDGE_241_CURATION_FAILED"


class ParkedCurationTicketNotFoundError(ApplicationException):
    """No curation ticket has the requested id."""

    __error_code__ = "KNOWLEDGE_242_PARKED_CURATION_NOT_FOUND"


class CurationRejectedError(ApplicationException):
    """An apply payload has flawed entries; nothing was staged or written."""

    __error_code__ = "KNOWLEDGE_243_CURATION_REJECTED"


class BriefAlreadyIngestedError(ApplicationException):
    """The submission's plan is registered in the store but its local plan is not available."""

    __error_code__ = "KNOWLEDGE_244_BRIEF_ALREADY_INGESTED"


class RelatedLookupUnavailableError(ApplicationException):
    """The related-record lookup is required and cannot answer."""

    __error_code__ = "KNOWLEDGE_245_RELATED_LOOKUP_UNAVAILABLE"
