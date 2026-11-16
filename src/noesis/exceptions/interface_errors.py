"""Errors raised by delivery adapters for invalid input."""

from typing import ClassVar

from .base import InterfaceException
from .exit_code_enum import ExitCodeEnum


class InvalidWorkBriefError(InterfaceException):
    """A work-brief file is missing, unreadable, or does not match the contract."""

    __error_code__ = "INTERFACE_001_INVALID_WORK_BRIEF"


class NotInGitRepositoryError(InterfaceException):
    """A command that stores records for the current repository ran outside any git repository."""

    __error_code__ = "INTERFACE_002_NOT_IN_GIT_REPOSITORY"


class BlankSessionIdError(InterfaceException):
    """`--session` or `--parent` was given but is empty or only whitespace."""

    __error_code__ = "INTERFACE_003_BLANK_SESSION_ID"


class SelfParentSessionError(InterfaceException):
    """`--parent` names the session being switched on."""

    __error_code__ = "INTERFACE_004_SELF_PARENT_SESSION"


# INTERFACE_005 was the blank task of the retired recall command; the code stays reserved and
# must never be reused.


class UserPresenceRequiredError(InterfaceException):
    """A user-applied review transition ran without an interactive terminal on standard input."""

    __error_code__ = "INTERFACE_006_USER_PRESENCE_REQUIRED"
    __exit_code__: ClassVar[ExitCodeEnum] = ExitCodeEnum.FAILURE
