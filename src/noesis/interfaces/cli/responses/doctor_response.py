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
    """

    name: str
    ok: bool
    detail: str
    next_step: str | None = None


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
            f"{'ok ' if check.ok else 'FAIL'} {check.name}: {check.detail}"
            + (f"\n     next: {check.next_step}" if check.next_step else "")
            for check in self.checks
        )
