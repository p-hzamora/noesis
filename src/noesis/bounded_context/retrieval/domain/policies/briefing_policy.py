"""Authority and citation admission are independent of models, delivery and storage."""

from collections.abc import Mapping, Sequence

type EvidenceKey = tuple[str, int | None]


class BriefingPolicy:
    """Only read, authoritative Knowledge can support constraints or decisions."""

    @staticmethod
    def rank(record_type: str, authority: str) -> int:
        """Stable rank tier; callers preserve search order within a tier."""
        if record_type == "knowledge" and authority == "authoritative":
            return 0
        if record_type == "experience":
            return 1
        return 3 if authority == "superseded" else 2

    @staticmethod
    def digest_section(record_type: str, authority: str) -> str:
        """An experience provides context; unreviewed guidance stays unconfirmed."""
        if record_type == "experience":
            return "context"
        return "constraints" if authority == "authoritative" else "unconfirmed"

    @staticmethod
    def admit(
        section: str, citations: Sequence[EvidenceKey], evidence: Mapping[EvidenceKey, bool]
    ) -> str:
        """Return the permissible section; evidence values mark authoritative Knowledge."""
        if not citations or any(key not in evidence for key in citations):
            return "unsupported"
        if section in {"constraints", "decisions"} and not all(evidence[key] for key in citations):
            return "unconfirmed"
        return section
