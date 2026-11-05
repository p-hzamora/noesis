"""Mapper from the published work-brief contract to Notes's own model."""

from noesis.bounded_context.notes.domain.value_objects import CommitRef, WorkBrief
from noesis.shared_kernel.contracts import WorkBriefContract


class WorkBriefMapper:
    """`to_domain` is Notes's anti-corruption layer for the work brief.

    Fields are copied one by one on purpose: a new contract version must be translated here
    explicitly, never leak into the domain unnoticed.
    """

    @staticmethod
    def to_domain(contract: WorkBriefContract) -> WorkBrief:
        """The brief as Notes understands it."""
        return WorkBrief(
            session_id=contract.session_id,
            repository=contract.repository,
            repository_path=contract.repository_path,
            branch=contract.branch,
            head=contract.head,
            commits=tuple(
                CommitRef(sha=commit.sha, subject=commit.subject) for commit in contract.commits
            ),
            diff_stat=contract.diff_stat,
            goal=contract.goal,
            session_excerpt=contract.session_excerpt,
        )
