"""`noesis doctor` output."""

from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class DoctorCheckResponse(FrozenObject):
    """One environment check of `noesis doctor`.

    Attributes:
        name: What was checked.
        ok: Whether it passed.
        detail: What was found.
        next_step: How to fix it, or what to do next.
        warning: Whether it passed but deserves attention (printed as `warn`).
    """

    name: str
    ok: bool
    detail: str
    next_step: str | None = None
    warning: bool = False


def _status(check: DoctorCheckResponse) -> str:
    """Status prefix of a doctor line."""
    if not check.ok:
        return "FAIL"
    return "warn" if check.warning else "ok "


class DoctorResponse(IRenderableResponse):
    """`noesis doctor`: all checks of one run.

    Attributes:
        ok: Whether every check passed.
        checks: The individual checks, in the order they ran.
    """

    ok: bool
    checks: tuple[DoctorCheckResponse, ...]

    def render(self) -> str:
        return "\n".join(
            f"{_status(check)} {check.name}: {check.detail}"
            + (f"\n     next: {check.next_step}" if check.next_step else "")
            for check in self.checks
        )
