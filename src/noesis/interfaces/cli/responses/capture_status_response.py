"""`noesis capture on|off|status` output."""

from .i_renderable_response import IRenderableResponse


class CaptureStatusResponse(IRenderableResponse):
    """`noesis capture on|off|status`: the state of one capture session.

    Attributes:
        session_id: The session.
        enabled: Whether capture is on.
        mode: `live` or `dry-run`.
        repository_path: Repository of the pending commits.
        pending_commits: Commits waiting for a hand-over.
        pending_files: Files they touch.
        pending_lines: Lines they change.
        last_handover_at: Time of the last hand-over (ISO), if any.
        failed_handovers: Consecutive hand-overs that could not start.
        repo_id: The repository the session works in, when known.
        parent_id: The session that started this one as a sub-agent, if any.
        env_file: The `.env` file this invocation read; hooks must read the same one.
        state_dir: Folder holding the capture flag and journal.
        vault_dir: Vault the curator writes to, or None when unset.
        generated: Whether this call chose the session id itself because none was given or
            found (only `capture on` can); no hook can match such an id.
    """

    session_id: str
    enabled: bool
    mode: str
    repository_path: str | None
    pending_commits: int
    pending_files: int
    pending_lines: int
    last_handover_at: str | None
    failed_handovers: int
    repo_id: str | None = None
    parent_id: str | None = None
    env_file: str | None = None
    state_dir: str | None = None
    vault_dir: str | None = None
    generated: bool = False

    def render(self) -> str:
        state: str = f"on ({self.mode})" if self.enabled else "off"
        pending: str = (
            f"{self.pending_commits} commit(s), {self.pending_files} file(s), "
            f"{self.pending_lines} line(s)"
            if self.pending_commits
            else "none"
        )
        parent: str = f"parent: {self.parent_id}\n" if self.parent_id else ""
        return (
            f"session {self.session_id}: {state}\n"
            f"{parent}"
            f"pending: {pending}\n"
            f"last hand-over: {self.last_handover_at or 'never'}\n"
            f"env file: {self.env_file}\n"
            f"state dir: {self.state_dir}\n"
            f"vault: {self.vault_dir or 'not set'}"
        )
