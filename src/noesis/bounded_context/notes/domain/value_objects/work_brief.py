"""The finished work Notes curates, in Notes's own terms.

Capture publishes it as `WorkBriefContract`; Notes translates that contract into this
value object at its edge, so the rules about what a brief means here live with Notes
and the shared contract stays plain, versioned data.
"""

from noesis.shared_kernel.domain.value_objects import ValueObject

from .note_area import NoteArea

SHORT_SESSION_LENGTH: int = 8


class CommitRef(ValueObject):
    """One commit of the brief.

    Attributes:
        sha: Full commit hash.
        subject: First line of the commit message.
    """

    sha: str
    subject: str


class WorkBrief(ValueObject):
    """One unit of finished work, ready to be curated.

    Attributes:
        session_id: Agent session the work came from.
        repository: Repository directory name.
        repository_path: Absolute repository root.
        branch: Branch at hand-over time.
        head: Newest commit of the brief.
        commits: The commits, oldest first.
        diff_stat: Capped `git show --stat` lines (names and counts only).
        goal: The session's first real prompt.
        session_excerpt: User prompts and assistant prose since the last hand-over.
    """

    session_id: str
    repository: str
    repository_path: str
    branch: str
    head: str
    commits: tuple[CommitRef, ...]
    diff_stat: tuple[str, ...] = ()
    goal: str = ""
    session_excerpt: str = ""

    @property
    def area(self) -> NoteArea:
        """The vault area its notes belong to: the repository's."""
        return NoteArea.for_repository(self.repository)

    def search_text(self) -> str:
        """Text that finds the notes the curator should know about: goal and commit subjects."""
        return " ".join([self.goal, *(commit.subject for commit in self.commits)])

    def commit_shas(self) -> tuple[str, ...]:
        """The commit hashes, oldest first, recorded as the provenance of its notes."""
        return tuple(commit.sha for commit in self.commits)

    def short_session(self) -> str:
        """The abbreviated session id recorded as the provenance of its notes."""
        return self.session_id[:SHORT_SESSION_LENGTH]
