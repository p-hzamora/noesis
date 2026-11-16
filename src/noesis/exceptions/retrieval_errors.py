"""Errors of the Retrieval context.

Codes in use: 101 (infrastructure) and 201 to 203 (application). Codes 102..109 and 204..209
are reserved for later chunks (C5b, C8, C9) and must not be reused.
"""

from .base import ApplicationException, InfrastructureException


class SemanticIndexUnavailableError(InfrastructureException):
    """The semantic index is required by the request but is absent or cannot answer."""

    __error_code__ = "RETRIEVAL_101_SEMANTIC_INDEX_UNAVAILABLE"


class IndexNotInitialisedError(ApplicationException):
    """A projection has no cursor yet: it was never built for the space."""

    __error_code__ = "RETRIEVAL_201_INDEX_NOT_INITIALISED"


class IndexRebuildRequiredError(ApplicationException):
    """A cursor is ahead of the head or meets a gap, or a projection's profile changed."""

    __error_code__ = "RETRIEVAL_202_INDEX_REBUILD_REQUIRED"


class IndexSyncInProgressError(ApplicationException):
    """Another sync or rebuild holds the projection's lock and did not finish in time."""

    __error_code__ = "RETRIEVAL_203_INDEX_SYNC_IN_PROGRESS"
