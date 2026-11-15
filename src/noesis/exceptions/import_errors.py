"""Errors of the vault import (`noesis import run`, `noesis import file`)."""

from .base import ApplicationException, InfrastructureException


class VaultReadFailedError(InfrastructureException):
    """The vault folder is missing or unreadable, or a note in it cannot be read.

    Metadata: `path`.
    """

    __error_code__ = "IMPORT_101_VAULT_READ_FAILED"


class FileReadFailedError(InfrastructureException):
    """`import file`: the path is missing, not a regular file, or unreadable.

    Metadata: `path`.
    """

    __error_code__ = "IMPORT_102_FILE_READ_FAILED"


class BlockingFindingsError(ApplicationException):
    """`import run --strict` found at least one blocked note, so nothing was written.

    Metadata: `blocked_reasons`, `paths`.
    """

    __error_code__ = "IMPORT_201_BLOCKING_FINDINGS"


class FileNotImportableError(ApplicationException):
    """`import file`: the file cannot become a record (blocked, not text, bad header, no body).

    Metadata: `path`, `reason`, `detail`.
    """

    __error_code__ = "IMPORT_203_FILE_NOT_IMPORTABLE"
