"""The session identity a command will run under."""

from noesis.shared_kernel.application.dtos import BaseDto


class ResolvedIdentityDto(BaseDto):
    """Who the session is, and which repository it belongs to.

    Attributes:
        session_id: The stored session id (`<repo id>-<12 hex>`).
        repo_id: The repository id, or empty outside a repository.
        repository_path: Main worktree of the repository, or empty outside one.
        generated: Whether noesis chose the id because nobody provided one.
    """

    session_id: str
    repo_id: str = ""
    repository_path: str = ""
    generated: bool = False
