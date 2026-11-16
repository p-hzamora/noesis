"""The finished work Knowledge curates, in Knowledge's own terms.

Capture publishes it as `WorkBriefContract`; the curation module translates that contract into
this value object at its edge, so what a brief means here lives with Knowledge.
"""

import hashlib
import json

from noesis.shared_kernel.domain.value_objects import ValueObject


def canonical_json(payload: object) -> str:
    """Stable JSON: sorted keys, no whitespace, non-ASCII kept."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    """Hex SHA-256 of `text` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CommitRef(ValueObject):
    """One commit of a brief.

    Attributes:
        sha: Full commit hash.
        subject: First line of the commit message.
    """

    sha: str
    subject: str


class WorkBrief(ValueObject):
    """One unit of finished work, ready to be curated.

    Attributes:
        contract_version: Version of the published contract it was read from.
        session_id: Agent session the work came from.
        repository: Project key: the repository directory name.
        head: Newest commit of the brief.
        commits: The commits, oldest first.
        diff_stat: Capped `git show --stat` lines (names and counts only).
        goal: The session's first real prompt.
        excerpt: User prompts and assistant prose since the last hand-over.
    """

    contract_version: int = 1
    session_id: str
    repository: str
    head: str
    commits: tuple[CommitRef, ...]
    diff_stat: tuple[str, ...] = ()
    goal: str = ""
    excerpt: str = ""

    def submission_key(self) -> str:
        """Identity of this work: SHA-256 of the canonical JSON of the version, session,
        repository, head and the ordered commit hashes.

        The excerpt and the goal are left out, so publishing the same work again gives the same key.
        """
        return sha256_hex(
            canonical_json(
                {
                    "contract_version": self.contract_version,
                    "session_id": self.session_id,
                    "repository": self.repository,
                    "head": self.head,
                    "commits": [commit.sha for commit in self.commits],
                }
            )
        )

    def search_text(self) -> str:
        """Text that finds the records the curator should know about: goal and commit subjects."""
        return " ".join([self.goal, *(commit.subject for commit in self.commits)])

    def commit_shas(self) -> tuple[str, ...]:
        """The commit hashes, oldest first."""
        return tuple(commit.sha for commit in self.commits)
