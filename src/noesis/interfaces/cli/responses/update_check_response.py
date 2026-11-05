"""`noesis update check` output."""

from .i_renderable_response import IRenderableResponse


class UpdateCheckResponse(IRenderableResponse):
    """`noesis update check`: how the installed checkout compares with its origin.

    Attributes:
        verdict: `up_to_date`, `behind`, `ahead`, `diverged` or `unknown`.
        reason: One sentence saying why.
        checkout: Root of the checkout, or None when there is none.
        branch: Current branch.
        remote_url: URL of `origin`.
        remote_branch: Origin's default branch.
        local_sha: Short hash of the local commit.
        remote_sha: Short hash of origin's commit.
        dirty: Whether the working tree has uncommitted changes.
        next_steps: Commands that bring the checkout and the installed tool up to date.
    """

    verdict: str
    reason: str
    checkout: str | None = None
    branch: str | None = None
    remote_url: str | None = None
    remote_branch: str | None = None
    local_sha: str | None = None
    remote_sha: str | None = None
    dirty: bool = False
    next_steps: tuple[str, ...] = ()

    def render(self) -> str:
        lines: list[str] = [f"{self.verdict}: {self.reason}"]
        if self.checkout:
            lines.append(f"  checkout: {self.checkout} ({self.branch or 'unknown branch'})")
        if self.local_sha or self.remote_sha:
            lines.append(
                f"  local {self.local_sha or '?'}, origin/{self.remote_branch or '?'} "
                f"{self.remote_sha or '?'}"
            )
        if self.dirty:
            lines.append("  the working tree has uncommitted changes")
        lines += [f"  next: {step}" for step in self.next_steps]
        return "\n".join(lines)
