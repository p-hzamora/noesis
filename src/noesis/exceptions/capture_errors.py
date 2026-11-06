"""Errors of the Capture context."""

from .base import ApplicationException, DomainException, InfrastructureException
from .exit_code_enum import ExitCodeEnum


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


class SessionIdentityMissingError(ApplicationException):
    """No session id was given and the harness exposes none.

    A missing `--session` is something the caller fixes on the command line, so it ends as a
    usage error (exit 2) like the other flag errors, while keeping its capture code.
    """

    __error_code__ = "CAPTURE_202_SESSION_ID_MISSING"
    __exit_code__ = ExitCodeEnum.USAGE
