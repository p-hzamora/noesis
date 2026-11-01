"""Root of every exception noesis raises on purpose.

Each concrete error declares a stable `__error_code__` (`CTX_NNN_NAME`) that callers can
branch on, an `__exit_code__` (the CLI analog of an HTTP status), and optional `next_steps`
telling a person or an agent how to recover. Interfaces render these; nothing else does.
"""

import re
from collections.abc import Sequence
from typing import ClassVar

from noesis.exceptions.exit_code_enum import ExitCodeEnum
from noesis.shared_kernel.domain import (
    JsonValue,
)


class AppException(Exception):  # noqa: N818 - house style: bases end in Exception, concrete errors in Error
    """Base for every deliberate noesis error.

    Attributes:
        message: Human-readable explanation (plain English).
        metadata: Structured context for logs and JSON output.
        next_steps: Concrete actions that fix the problem.
    """

    __error_code__: ClassVar[str] = "APP_000_UNEXPECTED"
    __exit_code__: ClassVar[ExitCodeEnum] = ExitCodeEnum.FAILURE

    def __init__(
        self,
        message: str,
        metadata: dict[str, JsonValue] | None = None,
        *,
        next_steps: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.metadata: dict[str, JsonValue] = dict(metadata or {})
        self.next_steps: tuple[str, ...] = tuple(next_steps)

    @classmethod
    def error_title(cls) -> str:
        """Readable title derived from the class name (`VaultNotConfiguredError` -> `Vault not configured`)."""
        words: list[str] = re.findall(r"[A-Z][a-z0-9]*", cls.__name__.removesuffix("Error"))
        return " ".join(words).capitalize() if words else cls.__name__

    @property
    def error_code(self) -> str:
        """Stable code to branch on."""
        return self.__error_code__

    @property
    def exit_code(self) -> ExitCodeEnum:
        """Exit code a CLI should end with."""
        return self.__exit_code__


class CoreException(AppException):
    """Configuration or environment problems detected before any use case runs."""

    __error_code__ = "CORE_000_UNEXPECTED"


class DomainException(AppException):
    """A business rule was violated."""

    __error_code__ = "DOMAIN_000_UNEXPECTED"


class ApplicationException(AppException):
    """A use case could not complete (missing resource, invalid state transition)."""

    __error_code__ = "APPLICATION_000_UNEXPECTED"


class InfrastructureException(AppException):
    """An external system failed: files, git, a subprocess, the curator."""

    __error_code__ = "INFRASTRUCTURE_000_UNEXPECTED"


class InterfaceException(AppException):
    """Invalid input reached an interface (bad arguments, malformed hook payload)."""

    __error_code__ = "INTERFACE_000_UNEXPECTED"
    __exit_code__ = ExitCodeEnum.USAGE
