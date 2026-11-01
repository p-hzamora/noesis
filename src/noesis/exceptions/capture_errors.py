"""Errors of the Capture context."""

from noesis.exceptions.base import ApplicationException, DomainException, InfrastructureException


class InvalidSessionIdError(DomainException):
    """An agent session id is empty or contains unsafe characters."""

    __error_code__ = "CAPTURE_001_INVALID_SESSION_ID"


class CaptureNotEnabledError(DomainException):
    """Work was recorded for a session that is not switched on."""

    __error_code__ = "CAPTURE_002_CAPTURE_NOT_ENABLED"


class CaptureStateError(InfrastructureException):
    """Capture state could not be read, written, or locked."""

    __error_code__ = "CAPTURE_101_STATE_FAILED"


class CaptureSessionNotFoundError(ApplicationException):
    """No capture state exists for the session."""

    __error_code__ = "CAPTURE_201_SESSION_NOT_FOUND"
