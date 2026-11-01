"""Errors raised by delivery adapters for invalid input."""

from noesis.exceptions.base import InterfaceException


class InvalidWorkBriefError(InterfaceException):
    """A work-brief file is missing, unreadable, or does not match the contract."""

    __error_code__ = "INTERFACE_001_INVALID_WORK_BRIEF"
