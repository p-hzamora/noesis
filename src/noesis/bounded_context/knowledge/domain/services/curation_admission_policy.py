"""What a candidate becomes: the admission table of curation (rows 1 to 12)."""

from collections.abc import Mapping, Sequence

from noesis.bounded_context.knowledge.domain.value_objects.curation_candidate import (
    DEFAULT_CURATION_SUBTYPES,
    CandidateKindEnum,
    CurationCandidate,
    CurationSubtypes,
)
from noesis.bounded_context.knowledge.domain.value_objects.curation_plan import (
    FIRST_ORDINAL,
    CurationPlan,
    PlanEntry,
)
from noesis.bounded_context.knowledge.domain.value_objects.curation_target import (
    MIGRATED_TAG,
    CurationTarget,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    RecordStatusEnum,
    RecordTypeEnum,
)
from noesis.bounded_context.knowledge.domain.value_objects.planned_write import (
    PlannedWrite,
    ProposeKnowledge,
    ProposeSuccessor,
    RecordExperience,
    ReviseProposal,
    Skip,
)

MIGRATED_TARGET_KEPT: str = "migrated_target_kept"
ASSERTIONS_UNAVAILABLE: str = "assertions unavailable: target not linked"


class CurationAdmissionPolicy:
    """Candidate plus optional target gives one planned write. Rows run in order; the first wins.

    | # | Condition | Planned write |
    | - | --- | --- |
    | 1 | the curator answered a skip | Skip `curator: <reason>` |
    | 2 | malformed entry, duplicate key, bad evidence key, target or evidence without reason | Skip `malformed: <detail>` |
    | 3 | subtype not allowed | Skip `unknown_subtype` |
    | 4 | experience | RecordExperience |
    | 5 | knowledge, no target | ProposeKnowledge |
    | 6 | target not found in the space | Skip `target_not_found` |
    | 7 | target is not Knowledge | Skip `target_not_knowledge` |
    | 8 | target is space-wide (Q-009, interim) | Skip `target_space_wide` |
    | 9 | target of another project | Skip `target_other_project` |
    | 10 | target `proposed`, same project | ReviseProposal; Q-018: a target tagged `origin:migrated` is kept, ProposeKnowledge |
    | 11 | target `superseded` or `retracted` (Q-010, default) | Skip `target_not_revisable` |
    | 12 | target `accepted`, same project | ProposeSuccessor; without assertions, ProposeKnowledge naming the target |

    No row yields an accept: capture never accepts (Q-002). Only the Q-018 exception of row 10
    reads the tag `origin:migrated`.

    Args:
        subtypes: The subtypes a candidate may carry (Q-003).
        assertions_available: Whether C4's `supports` and `supersedes` assertions can be proposed.
    """

    def __init__(
        self,
        *,
        subtypes: CurationSubtypes = DEFAULT_CURATION_SUBTYPES,
        assertions_available: bool = True,
    ) -> None:
        self._subtypes: CurationSubtypes = subtypes
        self._assertions_available: bool = assertions_available

    @staticmethod
    def flaws(candidates: Sequence[CurationCandidate]) -> dict[int, str]:
        """Index -> what is wrong with the entry: its own defect, a key used twice, or an
        evidence key that names no experience candidate of the list. Skips are held to the same
        standard here (the strict apply payload rejects them); `plan` lets row 1 come first.
        """
        experience_keys: set[str] = {
            candidate.key
            for candidate in candidates
            if candidate.kind is CandidateKindEnum.EXPERIENCE and candidate.key
        }
        found: dict[int, str] = {}
        seen: set[str] = set()
        for index, candidate in enumerate(candidates):
            detail: str | None = candidate.entry_flaw()
            if detail is None and candidate.key in seen:
                detail = f"key {candidate.key!r} is used twice"
            if detail is None:
                detail = next(
                    (
                        f"evidence key {key!r} names no experience candidate"
                        for key in candidate.evidence_keys
                        if key not in experience_keys
                    ),
                    None,
                )
            if candidate.key:
                seen.add(candidate.key)
            if detail is not None:
                found[index] = detail
        return found

    def plan(
        self,
        candidates: Sequence[CurationCandidate],
        *,
        project_key: str,
        targets: Mapping[str, CurationTarget],
    ) -> CurationPlan:
        """The plan of `candidates`, in their order; ordinals start at 1 and never shift.

        Args:
            candidates: The candidates, already redacted.
            project_key: The brief's project; every proposal is scoped to it.
            targets: The existing records the candidates name, by id; an id that is absent was
                not found in the active space.
        """
        flawed: dict[int, str] = self.flaws(candidates)
        writes: list[PlannedWrite] = []
        for index, candidate in enumerate(candidates):
            target: CurationTarget | None = (
                targets.get(candidate.target_record_id) if candidate.target_record_id else None
            )
            writes.append(
                self.decide(
                    candidate, project_key=project_key, target=target, flaw=flawed.get(index)
                )
            )
        ordinals: dict[str, int] = {
            candidate.key: FIRST_ORDINAL + index
            for index, candidate in enumerate(candidates)
            if candidate.key and isinstance(writes[index], RecordExperience)
        }
        entries: list[PlanEntry] = []
        for index, (candidate, write) in enumerate(zip(candidates, writes, strict=True)):
            if self._assertions_available and not isinstance(write, RecordExperience | Skip):
                evidence: tuple[int, ...] = tuple(
                    dict.fromkeys(
                        ordinals[key] for key in candidate.evidence_keys if key in ordinals
                    )
                )
                write = write.model_copy(update={"evidence_ordinals": evidence})
            entries.append(
                PlanEntry(ordinal=FIRST_ORDINAL + index, candidate=candidate, write=write)
            )
        return CurationPlan(entries=tuple(entries))

    def decide(
        self,
        candidate: CurationCandidate,
        *,
        project_key: str,
        target: CurationTarget | None,
        flaw: str | None = None,
    ) -> PlannedWrite:
        """The planned write of one candidate (rows 1 to 12).

        Args:
            candidate: The candidate.
            project_key: The brief's project.
            target: The record the candidate names, or None when it names none or it was not found.
            flaw: The plan-level defect of the entry (`flaws`), or None.
        """
        if candidate.kind is CandidateKindEnum.SKIP and candidate.flaw is None:
            return Skip(reason=f"curator: {candidate.reason or 'no reason given'}")
        detail: str | None = flaw if flaw is not None else candidate.entry_flaw()
        if detail is not None or candidate.kind is None:
            return Skip(reason=f"malformed: {detail or 'missing kind'}")
        if (candidate.subtype or "") not in self._subtypes.allowed_for(candidate.kind):
            return Skip(reason="unknown_subtype")
        if candidate.kind is CandidateKindEnum.EXPERIENCE:
            return RecordExperience()
        if not candidate.target_record_id:
            return ProposeKnowledge()
        return self._decide_target(candidate.target_record_id, project_key, target)

    def _decide_target(
        self, target_record_id: str, project_key: str, target: CurationTarget | None
    ) -> PlannedWrite:
        """Rows 6 to 12: a knowledge candidate that names a target."""
        if target is None:
            return Skip(reason="target_not_found")
        if target.record_type != RecordTypeEnum.KNOWLEDGE.value:
            return Skip(reason="target_not_knowledge")
        if target.project_key is None:
            return Skip(reason="target_space_wide")
        if target.project_key != project_key:
            return Skip(reason="target_other_project")
        match target.status:
            case RecordStatusEnum.PROPOSED.value:
                if MIGRATED_TAG in target.tags:
                    return ProposeKnowledge(
                        target_record_id=target_record_id, reason=MIGRATED_TARGET_KEPT
                    )
                return ReviseProposal(
                    target_record_id=target_record_id,
                    expected_revision=target.head_revision or 1,
                )
            case RecordStatusEnum.ACCEPTED.value:
                if self._assertions_available:
                    return ProposeSuccessor(target_record_id=target_record_id)
                return ProposeKnowledge(
                    target_record_id=target_record_id, reason=ASSERTIONS_UNAVAILABLE
                )
            case _:
                return Skip(reason="target_not_revisable")
