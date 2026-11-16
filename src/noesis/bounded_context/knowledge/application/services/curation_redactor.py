"""Redaction of everything curation keeps or sends (NFR-001): briefs, candidates, payloads."""

from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.value_objects import (
    CommitRef,
    CurationCandidate,
    WorkBrief,
)


class CurationRedactor:
    """Masks secrets in the texts of a brief and of candidates, so none reaches the submission
    key, the inbox, the curator prompt, the plan hash or a write.
    """

    @staticmethod
    def text(value: str) -> str:
        """`value` with secrets masked."""
        return SecretRedactor.redact(value)[0]

    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        """`value` with secrets masked; None stays None."""
        return None if value is None else cls.text(value)

    @classmethod
    def brief(cls, brief: WorkBrief) -> WorkBrief:
        """The brief with its goal, excerpt, commit subjects and diff stat masked."""
        return brief.model_copy(
            update={
                "goal": cls.text(brief.goal),
                "excerpt": cls.text(brief.excerpt),
                "commits": tuple(
                    CommitRef(sha=commit.sha, subject=cls.text(commit.subject))
                    for commit in brief.commits
                ),
                "diff_stat": tuple(cls.text(line) for line in brief.diff_stat),
            }
        )

    @classmethod
    def candidate(cls, candidate: CurationCandidate) -> CurationCandidate:
        """The candidate with its title, body, reason and flaw masked."""
        return candidate.model_copy(
            update={
                "title": cls.optional_text(candidate.title),
                "body": cls.optional_text(candidate.body),
                "reason": cls.optional_text(candidate.reason),
                "flaw": cls.optional_text(candidate.flaw),
            }
        )
