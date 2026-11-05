"""Errors raised by delivery adapters for invalid input."""

from .base import InterfaceException


class InvalidWorkBriefError(InterfaceException):
    """A work-brief file is missing, unreadable, or does not match the contract."""

    __error_code__ = "INTERFACE_001_INVALID_WORK_BRIEF"


class NotInGitRepositoryError(InterfaceException):
    """A command that stores notes for the current repository ran outside any git repository."""

    __error_code__ = "INTERFACE_002_NOT_IN_GIT_REPOSITORY"
