"""Errors raised by delivery adapters for invalid input."""

from .base import InterfaceException


class InvalidWorkBriefError(InterfaceException):
    """A work-brief file is missing, unreadable, or does not match the contract."""

    __error_code__ = "INTERFACE_001_INVALID_WORK_BRIEF"


class NotInGitRepositoryError(InterfaceException):
    """A command that stores notes for the current repository ran outside any git repository."""

    __error_code__ = "INTERFACE_002_NOT_IN_GIT_REPOSITORY"


class BlankSessionIdError(InterfaceException):
    """`--session` or `--parent` was given but is empty or only whitespace."""

    __error_code__ = "INTERFACE_003_BLANK_SESSION_ID"


class SelfParentSessionError(InterfaceException):
    """`--parent` names the session being switched on."""

    __error_code__ = "INTERFACE_004_SELF_PARENT_SESSION"


class EmptyRecallTaskError(InterfaceException):
    """`notes recall` got an empty or blank task."""

    __error_code__ = "INTERFACE_005_EMPTY_RECALL_TASK"
