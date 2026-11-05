"""Check whether the checkout noesis runs from is behind its origin."""

from pathlib import Path

from noesis.diagnostics.application.dtos import UpdateCheckDto
from noesis.diagnostics.application.enums import UpdateVerdictEnum
from noesis.diagnostics.application.policies import UpdateAssessment, assess_update
from noesis.diagnostics.application.ports.updates import CheckoutSnapshot, ICheckoutInspector
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

SHORT_SHA_LENGTH: int = 7


class CheckForUpdateQuery(FrozenObject):
    """What to inspect.

    Attributes:
        package_dir: Folder of the installed `noesis` package.
    """

    package_dir: Path


class CheckForUpdateHandler(IHandler[CheckForUpdateQuery, UpdateCheckDto]):
    """Reads the checkout through the inspector and states the verdict."""

    def __init__(self, *, inspector: ICheckoutInspector) -> None:
        self._inspector: ICheckoutInspector = inspector

    async def handle(self, action: CheckForUpdateQuery) -> UpdateCheckDto:
        """The verdict, its reason and, when the checkout is outdated, how to update it."""
        snapshot: CheckoutSnapshot = await self._inspector.inspect(action.package_dir)
        assessment: UpdateAssessment = assess_update(snapshot)
        return UpdateCheckDto(
            verdict=assessment.verdict,
            reason=assessment.reason,
            checkout=str(snapshot.checkout) if snapshot.checkout else None,
            branch=snapshot.branch,
            remote_url=snapshot.remote_url,
            remote_branch=snapshot.remote_branch,
            local_sha=_short(snapshot.local_sha),
            remote_sha=_short(snapshot.remote_sha),
            dirty=snapshot.dirty,
            next_steps=_next_steps(assessment.verdict, snapshot.checkout),
        )


def _short(sha: str | None) -> str | None:
    return sha[:SHORT_SHA_LENGTH] if sha else None


def _next_steps(verdict: UpdateVerdictEnum, checkout: Path | None) -> tuple[str, ...]:
    if checkout is None or verdict not in (UpdateVerdictEnum.BEHIND, UpdateVerdictEnum.DIVERGED):
        return ()
    return (f"git -C {checkout} pull", f"uv tool install --reinstall {checkout}")
