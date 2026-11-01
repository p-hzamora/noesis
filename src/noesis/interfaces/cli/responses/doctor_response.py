"""`noesis doctor` output."""

from noesis.utils import FrozenObject


class DoctorCheckResponse(FrozenObject):
    """One environment check of `noesis doctor`.

    Attributes:
        name: What was checked.
        ok: Whether it passed.
        detail: What was found.
        next_step: How to fix it, or what to do next.
    """

    name: str
    ok: bool
    detail: str
    next_step: str | None = None


class DoctorResponse(FrozenObject):
    """`noesis doctor`: all checks of one run.

    Attributes:
        ok: Whether every check passed.
        checks: The individual checks, in the order they ran.
    """

    ok: bool
    checks: tuple[DoctorCheckResponse, ...]
