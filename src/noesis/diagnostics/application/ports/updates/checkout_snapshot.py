"""What was observed about the checkout noesis runs from."""

from pathlib import Path

from noesis.utils import FrozenObject


class CheckoutSnapshot(FrozenObject):
    """Facts about a checkout and its origin; every fact the inspector could not read is None.

    Attributes:
        checkout: Root of the git checkout the package lives in, or None when it is not one.
        branch: Current branch (`HEAD` when detached).
        remote_url: URL of the `origin` remote, or None when there is none.
        local_sha: Full commit hash of HEAD.
        remote_branch: Origin's default branch.
        remote_sha: Full commit hash origin's default branch points to.
        dirty: Whether the working tree has uncommitted changes.
        remote_contains_local: Whether the origin commit includes the local one, or None when
            the histories could not be compared.
        local_contains_remote: Whether the local commit includes the origin one, or None when
            the histories could not be compared.
    """

    checkout: Path | None = None
    branch: str | None = None
    remote_url: str | None = None
    local_sha: str | None = None
    remote_branch: str | None = None
    remote_sha: str | None = None
    dirty: bool = False
    remote_contains_local: bool | None = None
    local_contains_remote: bool | None = None
