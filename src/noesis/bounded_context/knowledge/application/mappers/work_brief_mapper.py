"""Mapper from the published work-brief contract to Knowledge's own model."""

from noesis.bounded_context.knowledge.domain.value_objects import CommitRef, WorkBrief
from noesis.shared_kernel.contracts import WorkBriefContract


class WorkBriefMapper:
    """`to_domain` is the anti-corruption layer for the work brief.

    Fields are copied one by one on purpose: a new contract version must be translated here
    explicitly, never leak into the domain unnoticed.
    """

    @staticmethod
    def to_domain(contract: WorkBriefContract) -> WorkBrief:
        """The brief as Knowledge understands it (not yet redacted)."""
        return WorkBrief(
            contract_version=contract.contract_version,
            session_id=contract.session_id,
            repository=contract.repository,
            head=contract.head,
            commits=tuple(
                CommitRef(sha=commit.sha, subject=commit.subject) for commit in contract.commits
            ),
            diff_stat=contract.diff_stat,
            goal=contract.goal,
            excerpt=contract.session_excerpt,
        )
