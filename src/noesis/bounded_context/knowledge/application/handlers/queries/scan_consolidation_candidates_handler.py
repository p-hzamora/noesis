"""Scan for accepted Knowledge that may overlap; read-only, bounded and deterministic."""

from noesis.bounded_context.knowledge.application.dtos import (
    CandidateSnapshotDto,
    CandidateSnapshotPageDto,
    ConsolidationScanDto,
    OpenMembershipDto,
    ScanCandidateDto,
    ScanGroupDto,
)
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.review_support import require_space_id
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CONSOLIDATION_STEP,
    CORE_STEP,
    REVIEW_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.services import (
    DismissedPairPolicy,
    ReviewAuthorityPolicy,
)
from noesis.bounded_context.knowledge.domain.services.consolidation_policies import (
    MIGRATED_REVIEW_STEP,
    ineligible,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    MIGRATED_TAG,
    Applicability,
    DismissedPair,
    Key,
    MemberCandidate,
    RecordId,
    RecordStatusEnum,
    SpaceId,
)
from noesis.exceptions import (
    AppException,
    InvalidConsolidationError,
    RecordNotFoundError,
    SimilarityUnavailableError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.contracts.ports.knowledge import ISimilarRecordFinder
from noesis.shared_kernel.contracts.retrieval import SimilarRecordHitItem, SimilarRecordsContract
from noesis.utils import FrozenObject

DEFAULT_HITS: int = 5
DEFAULT_ANCHORS: int = 20
MAX_HITS: int = 50
MAX_ANCHORS: int = 100
SEMANTIC_SEVERITY: tuple[str, ...] = ("unavailable", "absent", "lagging", "ready")
"""Worst first: the scan reports the least available semantic state it met."""


class ScanConsolidationCandidatesQuery(FrozenObject):
    """Choose anchors by exactly one of a record, a project or the space-wide records.

    Attributes:
        space_key: Key of the active space.
        record_id: One anchor.
        project: Anchors are this project's accepted Knowledge.
        space_wide: Anchors are the space-wide accepted Knowledge.
        hits: Most similar records fetched per anchor, 1..50.
        anchors: Most anchors per page, 1..100.
        cursor: The previous page's `next_cursor`.
        include_dismissed: Label, rather than hide, pairs a `distinct` dismissal judged.
    """

    space_key: Key
    record_id: RecordId | None = None
    project: Key | None = None
    space_wide: bool = False
    hits: int = DEFAULT_HITS
    anchors: int = DEFAULT_ANCHORS
    cursor: str | None = None
    include_dismissed: bool = False


class ScanConsolidationCandidatesHandler(
    IHandler[ScanConsolidationCandidatesQuery, ConsolidationScanDto]
):
    """Anchors, then similar hits, then eligibility, open memberships and dismissals."""

    def __init__(
        self,
        *,
        read_repository: IConsolidationReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
        finder: ISimilarRecordFinder,
    ) -> None:
        self._read: IConsolidationReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema
        self._finder: ISimilarRecordFinder = finder

    async def handle(self, action: ScanConsolidationCandidatesQuery) -> ConsolidationScanDto:
        """Scan; nothing is written and a missing semantic index is a normal answer.

        Raises:
            InvalidConsolidationError: Not exactly one anchor selector, or a bound exceeded.
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            RecordNotFoundError: The anchor is not a record of the space.
            IneligibleConsolidationMemberError: The anchor is not accepted, current Knowledge.
            SimilarityUnavailableError: The similarity lookup failed (store errors pass as is).
        """
        self._check(action)
        await require_steps(self._schema, CORE_STEP, REVIEW_STEP, CONSOLIDATION_STEP)
        space_id: SpaceId = await require_space_id(self._records, action.space_key)
        anchors: list[CandidateSnapshotDto]
        next_cursor: str | None = None
        if action.record_id is not None:
            anchors = [await self._explicit_anchor(action.record_id, space_id)]
        else:
            page: CandidateSnapshotPageDto = await self._read.recent_accepted(
                space_id, project=action.project, limit=action.anchors, cursor=action.cursor
            )
            anchors, next_cursor = list(page.items), page.next_cursor
        groups: list[ScanGroupDto] = []
        states: list[str] = []
        suppressed: int = 0
        migrated: set[str] = set()
        for anchor in anchors:
            contract: SimilarRecordsContract = await self._similar(anchor, space_id, action.hits)
            states.append(contract.semantic_state)
            group, hidden, excluded = await self._group(anchor, contract, space_id, action)
            suppressed += hidden
            migrated |= excluded
            if group.candidates:
                groups.append(group)
        excluded_total: int = (
            len(migrated)
            if action.record_id is not None
            else await self._read.count_unaccepted_migrated(space_id, project=action.project)
        )
        return ConsolidationScanDto(
            groups=tuple(groups),
            semantic_state=_worst(states),
            suppressed_count=suppressed,
            excluded_unaccepted_migrated=excluded_total,
            next_cursor=next_cursor,
            next_steps=(
                (
                    "Proposed migrated records are not eligible until reviewed: the user runs "
                    f"`{MIGRATED_REVIEW_STEP}` in a terminal.",
                )
                if excluded_total > 0
                else ()
            ),
        )

    @staticmethod
    def _check(action: ScanConsolidationCandidatesQuery) -> None:
        chosen: int = sum(
            (action.record_id is not None, action.project is not None, action.space_wide)
        )
        if chosen != 1:
            raise InvalidConsolidationError(
                "Choose exactly one of a record, a project or the space-wide records to scan.",
                next_steps=["Pass one of --record, --project or --global."],
            )
        if not 1 <= action.hits <= MAX_HITS or not 1 <= action.anchors <= MAX_ANCHORS:
            raise InvalidConsolidationError(
                f"Hits are 1..{MAX_HITS} and anchors are 1..{MAX_ANCHORS}.",
                {"hits": action.hits, "anchors": action.anchors},
            )

    async def _explicit_anchor(
        self, record_id: RecordId, space_id: SpaceId
    ) -> CandidateSnapshotDto:
        found: list[CandidateSnapshotDto] = await self._read.describe([record_id], space_id)
        if not found:
            raise RecordNotFoundError(
                f"No record {record_id.value} in this space.",
                {"record_id": record_id.value},
                next_steps=["Check the id and the active space."],
            )
        anchor: CandidateSnapshotDto = found[0]
        candidate = MemberCandidate(
            record_id=record_id,
            is_knowledge=anchor.record_type == "knowledge",
            effective_status=(
                RecordStatusEnum(anchor.effective_status) if anchor.effective_status else None
            ),
            tags=anchor.tags,
        )
        if not candidate.is_knowledge:
            raise ineligible(
                candidate, "not_knowledge", f"{record_id.value} is not a Knowledge record."
            )
        if candidate.effective_status is not RecordStatusEnum.ACCEPTED:
            status: str = anchor.effective_status or "unknown"
            raise ineligible(
                candidate,
                "not_accepted" if status == "proposed" else status,
                f"Knowledge {record_id.value} is {status}; only accepted, current Knowledge "
                "can be an anchor.",
            )
        return anchor

    async def _similar(
        self, anchor: CandidateSnapshotDto, space_id: SpaceId, hits: int
    ) -> SimilarRecordsContract:
        try:
            return await self._finder.find_similar(
                anchor.record_id, space_id=space_id.value, limit=hits
            )
        except AppException as error:
            if error.error_code.startswith("INTEGRATION"):
                raise
            raise SimilarityUnavailableError(
                "The similarity lookup is unavailable; scan again later or propose by explicit ids.",
                {"original_code": error.error_code, "anchor_id": anchor.record_id},
                next_steps=["Run `noesis index status`, or use `noesis consolidation propose`."],
            ) from error

    async def _group(
        self,
        anchor: CandidateSnapshotDto,
        contract: SimilarRecordsContract,
        space_id: SpaceId,
        action: ScanConsolidationCandidatesQuery,
    ) -> tuple[ScanGroupDto, int, set[str]]:
        hits: list[SimilarRecordHitItem] = [
            hit for hit in contract.hits if hit.record_id != anchor.record_id
        ]
        snapshots: dict[str, CandidateSnapshotDto] = {
            s.record_id: s
            for s in await self._read.describe(
                [RecordId(value=h.record_id) for h in hits], space_id
            )
        }
        eligible: list[tuple[SimilarRecordHitItem, CandidateSnapshotDto]] = []
        migrated: set[str] = set()
        for hit in hits:
            snapshot: CandidateSnapshotDto | None = snapshots.get(hit.record_id)
            if snapshot is None or snapshot.record_type != "knowledge":
                continue
            if snapshot.subtype != anchor.subtype or snapshot.project_id != anchor.project_id:
                continue
            if snapshot.effective_status != RecordStatusEnum.ACCEPTED.value:
                if snapshot.stored_status == "proposed" and MIGRATED_TAG in snapshot.tags:
                    migrated.add(snapshot.record_id)
                continue
            eligible.append((hit, snapshot))
        ids: list[RecordId] = [
            RecordId(value=anchor.record_id),
            *(RecordId(value=s.record_id) for _, s in eligible),
        ]
        held: dict[str, str] = {
            m.record_id: m.consolidation_id for m in await self._read.conflicts(ids, space_id)
        }
        pairs: list[DismissedPair] = DismissedPairPolicy.suppressing(
            await self._read.dismissed_pairs(ids, space_id),
            {
                anchor.record_id: anchor.head_revision or 0,
                **{s.record_id: s.head_revision or 0 for _, s in eligible},
            },
        )
        judged: dict[str, str] = {}
        for pair in pairs:
            if anchor.record_id in (pair.first_id, pair.second_id):
                other: str = pair.second_id if pair.first_id == anchor.record_id else pair.first_id
                judged.setdefault(other, pair.consolidation_id)
        candidates: list[ScanCandidateDto] = []
        hidden: int = 0
        for hit, snapshot in eligible:
            if snapshot.record_id in held:
                continue
            dismissed_in: str | None = judged.get(snapshot.record_id)
            if dismissed_in is not None and not action.include_dismissed:
                hidden += 1
                continue
            candidates.append(
                ScanCandidateDto(
                    record_id=snapshot.record_id,
                    title=snapshot.title,
                    revision=snapshot.head_revision,
                    rank=hit.rank,
                    found_by=hit.found_by,
                    dismissed_in=dismissed_in,
                )
            )
        project_id: RecordId | None = (
            RecordId(value=anchor.project_id) if anchor.project_id else None
        )
        return (
            ScanGroupDto(
                anchor_id=anchor.record_id,
                anchor_title=anchor.title,
                anchor_revision=anchor.head_revision,
                candidates=tuple(candidates),
                conflicts=tuple(
                    OpenMembershipDto(record_id=record_id, consolidation_id=consolidation_id)
                    for record_id, consolidation_id in sorted(held.items())
                ),
                requires=ReviewAuthorityPolicy.requires(
                    [Applicability(project_id=project_id)]
                ).value,
            ),
            hidden,
            migrated,
        )


def _worst(states: list[str]) -> str:
    """The least available state seen; `absent` when nothing was asked."""
    for state in SEMANTIC_SEVERITY:
        if state in states:
            return state
    return "absent"
