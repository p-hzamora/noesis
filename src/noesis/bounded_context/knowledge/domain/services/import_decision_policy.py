"""The decision table of the vault import (`20-import.md`, "Decision table")."""

from collections.abc import Sequence

from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    GraphContent,
    IdHolderEnum,
    ImportCandidate,
    ImportDecision,
    ImportDecisionKindEnum,
    ImportOnChangeEnum,
    RecordStatusEnum,
)

_LIVE: frozenset[RecordStatusEnum] = frozenset(
    {RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED}
)


class ImportDecisionPolicy:
    """Chooses what an import does with one note given what the store already holds.

    Pure: it reads value objects and returns a value object.
    """

    def decide(
        self,
        *,
        candidates: Sequence[ImportCandidate],
        id_holder: IdHolderEnum,
        content: GraphContent,
        digest: ContentHash,
        on_change: ImportOnChangeEnum,
        can_link_successor: bool,
    ) -> ImportDecision:
        """Apply rows 1..9 in order; the first match wins.

        Args:
            candidates: Records with the note's id or citing its file locator.
            id_holder: What holds the id the note declares.
            content: The incoming title and body, redacted and stripped as they are stored.
            digest: Digest of the incoming file bytes.
            on_change: `report` or `update`.
            can_link_successor: Whether a `supersedes` proposal can follow a successor.

        Returns:
            The decision, with its target when it has one.
        """
        if id_holder == IdHolderEnum.OTHER:
            return ImportDecision(kind=ImportDecisionKindEnum.ID_CONFLICT)
        target: ImportCandidate | None = self._target(candidates)
        if target is None:
            return ImportDecision(kind=ImportDecisionKindEnum.CREATE)
        if target.head_content == content or digest in target.head_file_digests:
            return self._of(ImportDecisionKindEnum.UNCHANGED, target)
        if on_change == ImportOnChangeEnum.REPORT:
            return self._of(ImportDecisionKindEnum.CHANGED, target)
        if target.status is RecordStatusEnum.PROPOSED:
            return self._of(ImportDecisionKindEnum.REVISE, target)
        if target.status is RecordStatusEnum.ACCEPTED:
            kind: ImportDecisionKindEnum = (
                ImportDecisionKindEnum.SUCCESSOR_LINKED
                if can_link_successor
                else ImportDecisionKindEnum.SUCCESSOR_UNLINKED
            )
            return self._of(kind, target)
        return self._of(ImportDecisionKindEnum.TARGET_CLOSED, target)

    @staticmethod
    def _of(kind: ImportDecisionKindEnum, target: ImportCandidate) -> ImportDecision:
        return ImportDecision(kind=kind, target=target)

    @staticmethod
    def _target(candidates: Sequence[ImportCandidate]) -> ImportCandidate | None:
        """The newest `proposed` or `accepted` candidate, else the newest of any status (D-014)."""
        pool: list[ImportCandidate] = [c for c in candidates if c.status in _LIVE] or list(
            candidates
        )
        return max(pool, key=lambda c: (c.created_at, c.id.value), default=None)
