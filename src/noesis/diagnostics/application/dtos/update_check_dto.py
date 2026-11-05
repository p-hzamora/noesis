"""Result of an update check."""

from noesis.diagnostics.application.enums import UpdateVerdictEnum
from noesis.shared_kernel.application.dtos import BaseDto


class UpdateCheckDto(BaseDto):
    """How the checkout noesis runs from compares with its origin.

    Attributes:
        verdict: The comparison result.
        reason: One sentence saying why.
        checkout: Root of the checkout, or None when there is none.
        branch: Current branch.
        remote_url: URL of `origin`.
        remote_branch: Origin's default branch.
        local_sha: Short (7 characters) hash of the local commit.
        remote_sha: Short (7 characters) hash of origin's commit.
        dirty: Whether the working tree has uncommitted changes.
        next_steps: Commands that bring the checkout and the installed tool up to date.
    """

    verdict: UpdateVerdictEnum
    reason: str
    checkout: str | None = None
    branch: str | None = None
    remote_url: str | None = None
    remote_branch: str | None = None
    local_sha: str | None = None
    remote_sha: str | None = None
    dirty: bool = False
    next_steps: tuple[str, ...] = ()
