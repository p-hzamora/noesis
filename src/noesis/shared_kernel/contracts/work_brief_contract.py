"""Work brief: what Capture hands to Notes about one unit of finished work.

It crosses a process boundary as JSON (`noesis notes curate --brief-file`), so it is
versioned. It deliberately carries no diff: only commit subjects, a capped diff stat, the
session goal, and an excerpt of the conversation.
"""

from typing import Literal

from noesis.utils import FrozenObject

WORK_BRIEF_CONTRACT_VERSION: Literal[1] = 1


class CommitRefContract(FrozenObject):
    """One commit of the brief.

    Attributes:
        sha: Full commit hash.
        subject: First line of the commit message.
    """

    sha: str
    subject: str


class WorkBriefContract(FrozenObject):
    """Version 1 of the work brief.

    Attributes:
        contract_version: Schema version of this payload.
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

    contract_version: Literal[1] = WORK_BRIEF_CONTRACT_VERSION
    session_id: str
    repository: str
    repository_path: str
    branch: str
    head: str
    commits: tuple[CommitRefContract, ...]
    diff_stat: tuple[str, ...] = ()
    goal: str = ""
    session_excerpt: str = ""
