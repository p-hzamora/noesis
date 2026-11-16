"""One piece of knowledge or experience a curator or a caller proposes to keep."""

from enum import StrEnum

from noesis.shared_kernel.domain.value_objects import ValueObject


class CandidateKindEnum(StrEnum):
    """What a candidate says: an experience, knowledge, or that nothing is worth keeping."""

    EXPERIENCE = "experience"
    KNOWLEDGE = "knowledge"
    SKIP = "skip"


class CurationSubtypes(ValueObject):
    """The subtypes a candidate may carry, per record type (Q-003).

    Attributes:
        knowledge: Allowed Knowledge subtypes.
        experience: Allowed Experience subtypes.
    """

    knowledge: frozenset[str]
    experience: frozenset[str]

    def allowed_for(self, kind: CandidateKindEnum) -> frozenset[str]:
        """The subtypes of `kind`; empty for a skip."""
        match kind:
            case CandidateKindEnum.KNOWLEDGE:
                return self.knowledge
            case CandidateKindEnum.EXPERIENCE:
                return self.experience
            case CandidateKindEnum.SKIP:
                return frozenset()


DEFAULT_CURATION_SUBTYPES: CurationSubtypes = CurationSubtypes(
    knowledge=frozenset({"concept", "convention", "howto", "decision", "glossary"}),
    experience=frozenset({"observation", "outcome", "failure"}),
)
"""Q-003: Knowledge `concept, convention, howto, decision, glossary`; Experience: C2's three."""


class CurationCandidate(ValueObject):
    """A candidate as read from a curator answer or an apply payload.

    Every field may be missing: a flawed entry keeps its position in the plan and is skipped by
    the admission policy instead of shifting the ordinals of the entries after it.

    Attributes:
        kind: What it says; None when missing or unknown.
        key: Local key, unique in a plan.
        subtype: Subtype slug.
        title: Title (required for knowledge; kept in the plan for an experience, Q-013).
        body: Text.
        target_record_id: Existing knowledge this candidate refines or replaces.
        evidence_keys: Keys of the experience candidates that support it.
        reason: Why it is kept or skipped; becomes the rationale of an assertion.
        flaw: A defect found while reading the entry, when it could not be read as written.
    """

    kind: CandidateKindEnum | None = None
    key: str | None = None
    subtype: str | None = None
    title: str | None = None
    body: str | None = None
    target_record_id: str | None = None
    evidence_keys: tuple[str, ...] = ()
    reason: str | None = None
    flaw: str | None = None

    def entry_flaw(self) -> str | None:
        """What is wrong with this entry on its own, or None.

        The plan-level checks (a key used twice, an evidence key naming nothing) are
        `CurationAdmissionPolicy.flaws`.
        """
        if self.flaw:
            return self.flaw
        if self.kind is None:
            return "missing kind"
        if not _present(self.key):
            return "missing key"
        if self.kind is CandidateKindEnum.SKIP:
            return None if _present(self.reason) else "a skip needs a reason"
        if not _present(self.subtype):
            return "missing subtype"
        if not _present(self.body):
            return "missing body"
        if self.kind is CandidateKindEnum.KNOWLEDGE:
            if not _present(self.title):
                return "knowledge needs a title"
        elif self.target_record_id or self.evidence_keys:
            return "only knowledge may name a target or evidence"
        if (self.target_record_id or self.evidence_keys) and not _present(self.reason):
            return "a target or evidence needs a reason"
        return None


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())
