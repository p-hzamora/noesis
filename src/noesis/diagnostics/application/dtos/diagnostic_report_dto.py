"""Result of a diagnostics run."""

from noesis.shared_kernel.application.dtos import BaseDto


class DiagnosticCheckDto(BaseDto):
    """One environment check.

    Attributes:
        name: What was checked.
        ok: Whether it passed.
        detail: What was found.
        next_step: How to fix it, or what to do next.
        warning: Whether it passed but deserves attention (never fails the run).
    """

    name: str
    ok: bool
    detail: str
    next_step: str | None = None
    warning: bool = False


class DiagnosticReportDto(BaseDto):
    """All checks of one `doctor` run.

    Attributes:
        ok: Whether every check passed.
        checks: The individual checks, in the order they ran.
    """

    ok: bool
    checks: tuple[DiagnosticCheckDto, ...]
