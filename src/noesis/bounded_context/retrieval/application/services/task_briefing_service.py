"""Task briefing pipeline shared by recall and unified search: admit, hydrate, digest, ground."""

from noesis.exceptions import RecordNotFoundError
from noesis.shared_kernel.contracts.knowledge import (
    CatalogAvailabilityRequestContract,
    GraphNeighbourContract,
    RecordBodyMissingError,
    RecordReviewStateContract,
)

from ...domain.policies.briefing_policy import BriefingPolicy
from ..dtos.briefing_dtos import (
    BriefingDraftDto,
    BriefingItemDto,
    CitationDto,
    EvidenceDto,
    RecallRequestDto,
    RecallResultDto,
    RecommendedToolDto,
)
from ..ports.briefing import (
    IBriefingModel,
    IBriefingRedactor,
    ICatalogAvailability,
    IRecommendationReader,
    IReviewReader,
)
from ..ports.record_source.i_indexable_record_reader import IIndexableRecordReader
from .record_searcher import RecordSearcher

NO_PROJECT_WARNING: str = "no project resolved; searched space-wide records only"


class TaskBriefingService:
    """Orchestrate evidence, review, recommendations and optional synthesis in that order."""

    def __init__(
        self,
        searcher: RecordSearcher,
        bodies: IIndexableRecordReader,
        *,
        reviews: IReviewReader | None,
        recommendations: IRecommendationReader | None,
        catalog: ICatalogAvailability | None,
        model: IBriefingModel,
        redactor: IBriefingRedactor,
        max_evidence_chars: int = 24000,
    ) -> None:
        self._searcher = searcher
        self._bodies = bodies
        self._reviews = reviews
        self._recommendations = recommendations
        self._catalog = catalog
        self._model = model
        self._redactor = redactor
        self._budget = max_evidence_chars

    async def brief(
        self, request: RecallRequestDto, *, max_evidence_chars: int | None = None
    ) -> RecallResultDto:
        """Gather evidence; typed store errors always propagate before synthesis.

        Args:
            request: The scoped briefing request.
            max_evidence_chars: Evidence budget for this call; the configured one when None.
        """
        search = request.search.model_copy(
            update={
                "include_stale": False,
                "require_semantic": False,
                "statuses": (),
                "all_projects": False,
            }
        )
        result = await self._searcher.search(search)
        space = search.space_id
        project = search.project_key if result.project_id is not None else None
        warnings: list[str] = list(result.warnings)
        if result.project_id is None:
            warnings.append(NO_PROJECT_WARNING)
        if self._reviews is None:
            warnings.append("review capability unavailable; Knowledge is unreviewed")
        if self._catalog is None:
            warnings.append("catalog capability unavailable")
        states = await self._states([hit.record_id for hit in result.hits], space)
        records: list[EvidenceDto] = []
        for hit in result.hits:
            state = states.get(hit.record_id)
            if self._reviews is not None and (state is None or not _admitted(state, project)):
                continue
            records.append(
                EvidenceDto(
                    id=hit.record_id,
                    type=hit.record_type,
                    title=self._redactor.redact(hit.title or "")[0] or None,
                    revision=state.head_revision if state else hit.revision,
                    authority=state.authority if state else "unreviewed",
                    status=(state.effective_status or state.status) if state else hit.status,
                    superseded_by=tuple(state.superseded_by_record_ids) if state else (),
                    migrated=bool(state and "origin:migrated" in state.tags),
                    discovery=tuple(self._mask_path(path) for path in hit.discovery),
                    warnings=tuple(self._redactor.redact(item)[0] for item in hit.warnings),
                )
            )
        records.sort(key=lambda record: BriefingPolicy.rank(record.type, record.authority))
        migrated = any(record.migrated and record.status == "proposed" for record in records)
        hidden: set[str] = set()
        remaining = self._budget if max_evidence_chars is None else max_evidence_chars
        for index, record in enumerate(records):
            try:
                body = await self._bodies.get(record.id, record.revision, space_id=space)
            except RecordBodyMissingError, RecordNotFoundError:
                records[index] = record.model_copy(update={"omitted_reason": "body_missing"})
                continue
            if body.status == "retracted" or body.project_id not in (None, result.project_id):
                hidden.add(record.id)
                continue
            if body.revision != record.revision or body.head_revision != record.revision:
                records[index] = record.model_copy(update={"omitted_reason": "revision_changed"})
                continue
            title = self._redactor.redact(body.title or "")[0]
            text = self._redactor.redact(body.body)[0]
            size = len(title) + len(text)
            if size > remaining:
                records[index] = record.model_copy(
                    update={"title": title or None, "omitted_reason": "budget"}
                )
                continue
            remaining -= size
            records[index] = record.model_copy(
                update={"title": title or None, "body": text, "read": True}
            )
        records = [record for record in records if record.id not in hidden]
        evidence = [record for record in records if record.read]
        tools: tuple[RecommendedToolDto, ...] = ()
        tools_state = "not_available" if self._catalog is None else "not_verified"
        draft = BriefingDraftDto()
        unsupported: tuple[BriefingItemDto, ...] = ()
        synthesis = "no_evidence"
        if evidence:
            tools, tools_state = await self._tools(request, evidence, project, warnings)
            # A second state/head change invalidates evidence; never retry indefinitely.
            checked = await self._states([record.id for record in records if record.read], space)
            for index, record in enumerate(records):
                if (
                    record.read
                    and self._reviews is not None
                    and (
                        checked.get(record.id) is None or not _admitted(checked[record.id], project)
                    )
                ):
                    hidden.add(record.id)
                if (
                    record.read
                    and self._reviews is not None
                    and checked.get(record.id) != states.get(record.id)
                ):
                    records[index] = record.model_copy(
                        update={"body": None, "read": False, "omitted_reason": "review_changed"}
                    )
            records = [record for record in records if record.id not in hidden]
            rechecked = [record for record in records if record.read]
            if len(rechecked) != len(evidence):
                evidence = rechecked
                if evidence:
                    tools, tools_state = await self._tools(request, evidence, project, [])
                else:
                    tools, tools_state = (
                        (),
                        "not_available" if self._catalog is None else "not_verified",
                    )
        if evidence:
            if request.no_synthesis:
                draft = _digest(evidence)
                synthesis = "digest"
            else:
                draft, unsupported = _ground(
                    await self._model.synthesize(self._redactor.redact(search.text)[0], evidence),
                    evidence,
                )
                synthesis = "briefing"
        return RecallResultDto(
            synthesis=synthesis,
            search=result,
            records=tuple(records),
            constraints=draft.constraints,
            decisions=draft.decisions,
            context=draft.context,
            unconfirmed=draft.unconfirmed,
            unsupported=unsupported,
            tools=tools,
            tools_state=tools_state,
            capabilities={
                "review": "available" if self._reviews else "not_available",
                "catalog": "available" if self._catalog else "not_available",
            },
            warnings=tuple(warnings),
            next_steps=("noesis review accept --tag origin:migrated --all --yes",)
            if migrated
            else (),
        )

    def _mask_path(self, path: GraphNeighbourContract) -> GraphNeighbourContract:
        """Discovery ids and labels are output too; mask them like title and body."""

        def mask(text: str) -> str:
            return self._redactor.redact(text)[0]

        return path.model_copy(
            update={
                "record_id": mask(path.record_id),
                "seed_id": mask(path.seed_id),
                "original_target_id": None
                if path.original_target_id is None
                else mask(path.original_target_id),
                "origin": None if path.origin is None else mask(path.origin),
                "anchors": tuple(mask(item) for item in path.anchors),
                "supersession_path": tuple(mask(item) for item in path.supersession_path),
                "warnings": tuple(mask(item) for item in path.warnings),
            }
        )

    async def _states(self, ids: list[str], space: str) -> dict[str, RecordReviewStateContract]:
        if self._reviews is None or not ids:
            return {}
        return {
            state.record_id: state for state in await self._reviews.get_states(ids, space_id=space)
        }

    async def _tools(
        self,
        request: RecallRequestDto,
        evidence: list[EvidenceDto],
        project: str | None,
        warnings: list[str],
    ) -> tuple[tuple[RecommendedToolDto, ...], str]:
        if self._catalog is None or self._recommendations is None:
            return (), "not_available"
        by_id = {record.id: record for record in evidence}
        assertions = await self._recommendations.by_subjects(
            list(by_id), space_id=request.search.space_id
        )
        valid = []
        for assertion in assertions:
            record = by_id.get(assertion.subject_id)
            if (
                record is None
                or assertion.project_key not in (None, project)
                or assertion.status not in {"proposed", "accepted"}
                or assertion.predicate != "recommends"
                or assertion.object_type != "catalog_entry"
            ):
                continue
            if (
                assertion.subject_at_revision is not None
                and assertion.subject_at_revision != record.revision
            ):
                warnings.append(f"stale endorsement omitted: {assertion.assertion_id}")
                continue
            valid.append(assertion)
        ids = tuple(dict.fromkeys(assertion.object_id for assertion in valid))
        if not ids:
            return (), "not_verified"
        availability = await self._catalog.check(
            CatalogAvailabilityRequestContract(
                space_id=request.search.space_id, entry_ids=ids, runtimes=request.runtimes
            )
        )
        if availability.outcome == "not_checked":
            warnings.append(f"tools not verified: {availability.reason_code}")
            return (), "not_verified"
        tools = []
        for catalog_id in ids:
            endorsements = tuple(
                assertion for assertion in valid if assertion.object_id == catalog_id
            )
            observations = tuple(
                runtime.model_copy(
                    update={
                        "entries": tuple(
                            entry for entry in runtime.entries if entry.entry_id == catalog_id
                        )
                    }
                )
                for runtime in availability.runtimes
            )
            tools.append(
                RecommendedToolDto(
                    catalog_id=catalog_id,
                    assertion_ids=tuple(item.assertion_id for item in endorsements),
                    endorsements=endorsements,
                    endorsement="accepted"
                    if any(item.status == "accepted" for item in endorsements)
                    else "proposed",
                    runtimes=observations,
                    usable=any(
                        entry.status == "available"
                        for runtime in observations
                        for entry in runtime.entries
                    ),
                )
            )
        return tuple(tools), "checked"


def _admitted(state: RecordReviewStateContract, project: str | None) -> bool:
    return (
        state.authority != "retracted"
        and state.status != "retracted"
        and state.project_key in (None, project)
    )


def _digest(evidence: list[EvidenceDto]) -> BriefingDraftDto:
    sections: dict[str, list[BriefingItemDto]] = {
        name: [] for name in ("constraints", "decisions", "context", "unconfirmed")
    }
    for record in evidence:
        section = BriefingPolicy.digest_section(record.type, record.authority)
        sections[section].append(
            BriefingItemDto(
                text=record.body or "",
                citations=(CitationDto(record_id=record.id, revision=record.revision),),
            )
        )
    return BriefingDraftDto.model_validate(sections)


def _ground(
    draft: BriefingDraftDto, evidence: list[EvidenceDto]
) -> tuple[BriefingDraftDto, tuple[BriefingItemDto, ...]]:
    records = {
        (record.id, record.revision): record.type == "knowledge"
        and record.authority == "authoritative"
        for record in evidence
    }
    sections: dict[str, list[BriefingItemDto]] = {
        name: [] for name in ("constraints", "decisions", "context", "unconfirmed")
    }
    unsupported: list[BriefingItemDto] = []
    for name in sections:
        for item in getattr(draft, name):
            keys = [(citation.record_id, citation.revision) for citation in item.citations]
            destination = BriefingPolicy.admit(name, keys, records)
            if destination == "unsupported":
                unsupported.append(item)
                continue
            sections[destination].append(item)
    return BriefingDraftDto.model_validate(sections), tuple(unsupported)
