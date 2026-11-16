"""Propose a consolidation: a new successor and one proposed `supersedes` per original."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter

from noesis.bounded_context.knowledge.application.dtos import (
    ConsolidationDto,
    ConsolidationMemberDto,
    ConsolidationProposalDto,
    ConsolidationStepDto,
    PlannedAssertionDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionCommand,
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewStateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.application.services.consolidation_support import (
    PROGRESS_VERSION,
    ConsolidationSupport,
    MemberSnapshot,
    partial_failure,
    progress_version_of,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
    NewSourceInput,
    ProjectRef,
    SourceInput,
)
from noesis.bounded_context.knowledge.application.services.review_support import (
    Prelude,
    ReviewMutationCommand,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.entities import Consolidation, Knowledge, Project
from noesis.bounded_context.knowledge.domain.services import (
    ConsolidationEligibilityPolicy,
    DismissedPairPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    ConsolidationId,
    ConsolidationMember,
    ConsolidationProgressEnum,
    ConsolidationStateEnum,
    DismissedPair,
    Key,
    RecordId,
    Slug,
    SpaceId,
    Tag,
)
from noesis.exceptions import (
    AppException,
    ConsolidationClosedError,
    ConsolidationMembershipConflictError,
    ConsolidationNotFoundError,
    DismissedConsolidationPairError,
    EntryAlreadyExistsError,
    IneligibleConsolidationMemberError,
    InvalidConsolidationError,
    RecordNotFoundError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue

PROPOSE_CONSOLIDATION_COMMAND: str = "consolidation.propose"
_SOURCE_INPUT: TypeAdapter[SourceInput] = TypeAdapter(SourceInput)


class ProposeConsolidationCommand(ReviewMutationCommand):
    """Propose a successor for overlapping accepted Knowledge.

    Attributes:
        member_ids: The originals; two to ten distinct accepted Knowledge records.
        title: The successor's title (the caller writes it; there is no drafter).
        body: The successor's text.
        rationale: Why the originals overlap; stored on the aggregate and every assertion.
        tags: Tags of the successor.
        sources: Further sources of the successor (the originals' sources are always carried).
        reconsider_id: The `distinct` dismissal to override, when the pair was judged before.
    """

    member_ids: tuple[RecordId, ...]
    title: str
    body: str
    rationale: str
    tags: tuple[Tag, ...] = ()
    sources: tuple[SourceInput, ...] = ()
    reconsider_id: ConsolidationId | None = None


@dataclass(frozen=True, slots=True)
class _Plan:
    """What the first transaction freezes; a resume replays it instead of re-deciding."""

    members: tuple[ConsolidationMember, ...]
    project_id: RecordId | None
    project_key: str | None
    subtype: str
    title: str
    body: str
    rationale: str
    tags: tuple[str, ...]
    member_source_ids: tuple[str, ...]
    new_sources: tuple[NewSourceInput, ...]
    caller_source_ids: tuple[str, ...]
    evidence: dict[str, tuple[str, ...]]

    def to_json(self) -> dict[str, JsonValue]:
        """The plan as ledger `extra`."""
        return {
            "members": [{"id": m.record_id.value, "rev": m.at_revision} for m in self.members],
            "project_id": self.project_id.value if self.project_id else None,
            "project_key": self.project_key,
            "subtype": self.subtype,
            "title": self.title,
            "body": self.body,
            "rationale": self.rationale,
            "tags": [*self.tags],
            "member_source_ids": [*self.member_source_ids],
            "new_sources": [s.model_dump(mode="json") for s in self.new_sources],
            "caller_source_ids": [*self.caller_source_ids],
            "evidence": {key: [*value] for key, value in self.evidence.items()},
        }

    @classmethod
    def from_json(cls, data: Any) -> _Plan:
        """The plan a pending entry stored."""
        project_id: str | None = data["project_id"]
        return cls(
            members=tuple(
                ConsolidationMember(record_id=RecordId(value=m["id"]), at_revision=m["rev"])
                for m in data["members"]
            ),
            project_id=RecordId(value=project_id) if project_id else None,
            project_key=data["project_key"],
            subtype=data["subtype"],
            title=data["title"],
            body=data["body"],
            rationale=data["rationale"],
            tags=tuple(data["tags"]),
            member_source_ids=tuple(data["member_source_ids"]),
            new_sources=tuple(NewSourceInput.model_validate(s) for s in data["new_sources"]),
            caller_source_ids=tuple(data["caller_source_ids"]),
            evidence={key: tuple(value) for key, value in data["evidence"].items()},
        )

    def source_inputs(self) -> tuple[SourceInput, ...]:
        """Every source of the successor: the originals' ones, the caller's ones, then new ones."""
        existing: tuple[str, ...] = tuple(
            dict.fromkeys((*self.member_source_ids, *self.caller_source_ids))
        )
        return (
            *(ExistingSourceInput(source_id=RecordId(value=s)) for s in existing),
            *self.new_sources,
        )


@dataclass(slots=True)
class _Progress:
    """What a run has created so far, mirrored into the pending ledger entry after each step."""

    successor: str | None
    assertions: dict[str, str]
    version: int

    def adopt_successor(self, record_id: str) -> None:
        """Remember the successor a step created (or found again)."""
        self.successor = record_id

    def adopter(self, object_id: str) -> Callable[[str], None]:
        """A callback that remembers the assertion created for `object_id`."""

        def adopt(assertion_id: str) -> None:
            self.assertions[object_id] = assertion_id

        return adopt


class ProposeConsolidationHandler(IHandler[ProposeConsolidationCommand, ConsolidationProposalDto]):
    """Reserves the members, creates the proposals through C2 and C4, then materialises.

    The steps are separate transactions, so a crash leaves committed effects behind. Every
    effect has a key derived from the consolidation id, so the same command with the same
    idempotency key resumes the frozen plan and converges on the same records.
    """

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        states: IReviewStateReadRepository,
        read_repository: IConsolidationReadRepository,
    ) -> None:
        self._support: ConsolidationSupport = ConsolidationSupport(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema, states=states
        )
        self._read: IConsolidationReadRepository = read_repository
        self._capture: CaptureKnowledgeHandler = CaptureKnowledgeHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._propose: ProposeAssertionHandler = ProposeAssertionHandler(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )

    async def handle(self, action: ProposeConsolidationCommand) -> ConsolidationProposalDto:
        """Preview, open and complete, or resume the earlier identical proposal.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            InvalidRecordError: Applying without an idempotency key.
            IdempotencyKeyReusedError: The key served a different request.
            InvalidConsolidationError: Wrong member count, a repeat, blank text or a
                `--reconsider` that names no applicable dismissal.
            IneligibleConsolidationMemberError: A member cannot be consolidated.
            ConsolidationMembershipConflictError: A member belongs to another open consolidation.
            DismissedConsolidationPairError: A pair was judged distinct and not reconsidered.
            ConsolidationPartiallyAppliedError: A step failed after earlier ones committed.
        """
        support: ConsolidationSupport = self._support
        self._check_text(action)
        prelude: Prelude = await support.prelude(action, PROPOSE_CONSOLIDATION_COMMAND)
        if not action.apply:
            async with support.uow_factory() as uow:
                plan: _Plan = await self._validate(uow, action, prelude.space_id, lock=False)
                project_id: RecordId | None = plan.project_id
            return ConsolidationProposalDto(
                kind="graph_merge",
                state="planned",
                members=tuple(
                    ConsolidationMemberDto(record_id=m.record_id.value, at_revision=m.at_revision)
                    for m in plan.members
                ),
                planned_assertions=tuple(
                    PlannedAssertionDto(object_id=key, evidence_ids=value)
                    for key, value in sorted(plan.evidence.items())
                ),
                requires=support.requires(project_id).value,
                decidable_by_caller=support.may_decide(action.actor, project_id),
                dry_run=True,
                progress=ConsolidationProgressEnum.PENDING.value,
            )
        entry: LedgerEntry | None = prelude.replay
        if entry is None:
            entry = await self._open(action, prelude)
        return await self._resume(action, prelude, entry)

    @staticmethod
    def _check_text(action: ProposeConsolidationCommand) -> None:
        for field, value in (
            ("title", action.title),
            ("body", action.body),
            ("rationale", action.rationale),
        ):
            if not value.strip():
                raise InvalidConsolidationError(
                    f"A consolidation needs a non-empty {field}.",
                    {"field": field},
                    next_steps=[f"Write the {field}; there is no drafter."],
                )

    async def _validate(
        self,
        uow: IKnowledgeUnitOfWork,
        action: ProposeConsolidationCommand,
        space_id: SpaceId,
        *,
        lock: bool,
    ) -> _Plan:
        """Check eligibility, open memberships and dismissals, then freeze what the proposals need."""
        ConsolidationEligibilityPolicy.check_ids([m.value for m in action.member_ids])
        snapshot: MemberSnapshot = await self._support.snapshot_members(
            uow, action.member_ids, space_id, lock=lock
        )
        members: tuple[ConsolidationMember, ...] = ConsolidationEligibilityPolicy.check(
            snapshot.candidates
        )
        ids: list[RecordId] = [m.record_id for m in members]
        conflicts = await uow.consolidation_guard.conflicts(ids, space_id)
        if conflicts:
            raise ConsolidationMembershipConflictError(
                "A member already belongs to an open consolidation.",
                {
                    "conflicts": [
                        {"record_id": c.record_id, "consolidation_id": c.consolidation_id}
                        for c in conflicts
                    ]
                },
                next_steps=[
                    f"Run `noesis consolidation show {conflicts[0].consolidation_id}`, "
                    "or reject that consolidation first."
                ],
            )
        await self._check_dismissals(uow, action, space_id, members, ids)
        first: Knowledge = snapshot.knowledge[ids[0].value]
        project_id: RecordId | None = first.applicability.project_id
        project_key: str | None = None
        if project_id is not None:
            project: Project | None = await uow.projects.get(project_id, space_id=space_id)
            project_key = project.key.value if project else None
        evidence: dict[str, tuple[str, ...]] = {}
        for member in members:
            found = await uow.consolidation_guard.evidence_for(
                member.record_id, [member.record_id], space_id
            )
            evidence[member.record_id.value] = tuple(item.value for item in found)
        member_sources: list[str] = []
        for member in members:
            member_sources.extend(s.value for s in snapshot.source_ids[member.record_id.value])
        return _Plan(
            members=members,
            project_id=project_id,
            project_key=project_key,
            subtype=first.subtype.value,
            title=SecretRedactor.redact(action.title)[0],
            body=SecretRedactor.redact(action.body)[0],
            rationale=SecretRedactor.redact(action.rationale)[0],
            tags=tuple(sorted({tag.value for tag in action.tags})),
            member_source_ids=tuple(dict.fromkeys(member_sources)),
            new_sources=tuple(s for s in action.sources if isinstance(s, NewSourceInput)),
            caller_source_ids=tuple(
                s.source_id.value for s in action.sources if isinstance(s, ExistingSourceInput)
            ),
            evidence=evidence,
        )

    @staticmethod
    async def _check_dismissals(
        uow: IKnowledgeUnitOfWork,
        action: ProposeConsolidationCommand,
        space_id: SpaceId,
        members: tuple[ConsolidationMember, ...],
        ids: list[RecordId],
    ) -> None:
        pairs: list[DismissedPair] = await uow.consolidation_guard.dismissed_pairs(ids, space_id)
        holding: list[DismissedPair] = DismissedPairPolicy.suppressing(
            pairs, {m.record_id.value: m.at_revision for m in members}
        )
        if action.reconsider_id is not None:
            reconsidered: str = action.reconsider_id.value
            if not any(pair.consolidation_id == reconsidered for pair in holding):
                raise InvalidConsolidationError(
                    f"Consolidation {reconsidered} is not a dismissal that applies to these members.",
                    {"reconsider_id": reconsidered},
                    next_steps=["Drop --reconsider, or name the dismissal the error listed."],
                )
            holding = [pair for pair in holding if pair.consolidation_id != reconsidered]
        if holding:
            raise DismissedConsolidationPairError(
                "These members were judged distinct and neither has changed since.",
                {
                    "pairs": [
                        {
                            "consolidation_id": p.consolidation_id,
                            "first_id": p.first_id,
                            "second_id": p.second_id,
                        }
                        for p in holding
                    ]
                },
                next_steps=[f"Pass --reconsider {holding[0].consolidation_id} to override it."],
            )

    async def _open(self, action: ProposeConsolidationCommand, prelude: Prelude) -> LedgerEntry:
        """The first transaction: reserve identity and membership, freeze the plan."""
        support: ConsolidationSupport = self._support
        key: str = action.idempotency_key or ""
        try:
            async with support.uow_factory() as uow:
                plan: _Plan = await self._validate(uow, action, prelude.space_id, lock=True)
                now = support.clock.now()
                consolidation_id: ConsolidationId = ConsolidationId(
                    value=support.ids.new_record_id().value
                )
                consolidation: Consolidation = Consolidation.create(
                    id=consolidation_id,
                    space_id=prelude.space_id,
                    members=plan.members,
                    rationale=plan.rationale,
                    project_id=plan.project_id,
                    actor=action.actor,
                    now=now,
                )
                entry: LedgerEntry = LedgerEntry(
                    space_id=prelude.space_id,
                    key=key,
                    command=PROPOSE_CONSOLIDATION_COMMAND,
                    fingerprint=prelude.fingerprint,
                    extra={
                        PROGRESS_VERSION: 1,
                        "consolidation_id": consolidation_id.value,
                        "status": "pending",
                        "plan": plan.to_json(),
                        "successor_id": None,
                        "assertion_ids": {},
                    },
                    recorded_at=now,
                )
                await uow.consolidations.add(consolidation)
                await uow.ledger.record(entry)
                await uow.commit()
        except EntryAlreadyExistsError as error:
            return await support.review.winner(
                error, action, PROPOSE_CONSOLIDATION_COMMAND, prelude
            )
        return entry

    async def _resume(
        self, action: ProposeConsolidationCommand, prelude: Prelude, entry: LedgerEntry
    ) -> ConsolidationProposalDto:
        """Run every unfinished step of the frozen plan, then describe the result."""
        support: ConsolidationSupport = self._support
        extra: dict[str, JsonValue] = dict(entry.extra)
        consolidation_id: ConsolidationId = ConsolidationId(value=str(extra["consolidation_id"]))
        if extra.get("status") == "complete":
            return await self._describe(action, prelude.space_id, consolidation_id, replayed=True)
        plan: _Plan = _Plan.from_json(extra["plan"])
        stored_successor: JsonValue = extra.get("successor_id")
        raw_assertions: JsonValue = extra.get("assertion_ids")
        progress: _Progress = _Progress(
            successor=stored_successor if isinstance(stored_successor, str) else None,
            assertions=(
                {k: str(v) for k, v in raw_assertions.items()}
                if isinstance(raw_assertions, dict)
                else {}
            ),
            version=progress_version_of(entry),
        )
        steps: list[ConsolidationStepDto] = []
        retry: str = (
            f"Run the same `noesis consolidation propose` again with --idempotency-key {entry.key}."
        )

        async def remember() -> None:
            payload: dict[str, JsonValue] = {
                **extra,
                "successor_id": progress.successor,
                "assertion_ids": {**progress.assertions},
            }
            async with support.uow_factory() as uow:
                await uow.ledger.update_extra(
                    prelude.space_id,
                    entry.key,
                    expected_progress_version=progress.version,
                    extra=payload,
                )
                await uow.commit()
            progress.version += 1

        async def run[T](
            target: str,
            kind: str,
            call: Awaitable[T],
            adopt: Callable[[T], None] | None = None,
        ) -> T:
            try:
                result: T = await call
                if adopt is not None:
                    adopt(result)
                    await remember()
            except AppException as error:
                steps.append(
                    ConsolidationStepDto(
                        target=target,
                        target_type=kind,
                        outcome="failed",
                        error_code=error.error_code,
                    )
                )
                raise partial_failure(
                    consolidation_id=consolidation_id.value,
                    steps=steps,
                    progress=ConsolidationProgressEnum.PENDING.value,
                    retry=retry,
                    cause=error,
                ) from error
            steps.append(ConsolidationStepDto(target=target, target_type=kind, outcome="done"))
            return result

        async def check_members() -> None:
            async with support.uow_factory() as uow:
                aggregate: Consolidation | None = await uow.consolidations.get_by_id(
                    consolidation_id, space_id=prelude.space_id
                )
                if aggregate is None:
                    raise ConsolidationNotFoundError(
                        f"No consolidation {consolidation_id.value} in this space.",
                        {"consolidation_id": consolidation_id.value},
                    )
                if aggregate.state is ConsolidationStateEnum.DISMISSED:
                    raise ConsolidationClosedError(
                        f"Consolidation {consolidation_id.value} was dismissed; open a new one.",
                        {
                            "consolidation_id": consolidation_id.value,
                            "state": aggregate.state.value,
                        },
                    )
                snapshot = await support.snapshot_members(
                    uow, [m.record_id for m in plan.members], prelude.space_id, lock=False
                )
            for member, candidate in zip(plan.members, snapshot.candidates, strict=True):
                if (
                    candidate.effective_status is None
                    or candidate.effective_status.value != "accepted"
                    or candidate.head_revision != member.at_revision
                ):
                    raise IneligibleConsolidationMemberError(
                        f"Member {member.record_id.value} changed after the plan was frozen.",
                        {"member_id": member.record_id.value, "cause": "lifecycle_changed"},
                        next_steps=[
                            "Review the members by hand; the plan is not rewritten.",
                            f"Reject consolidation {consolidation_id.value} if it no longer applies.",
                        ],
                    )

        if progress.successor is None or len(progress.assertions) < len(plan.members):
            await check_members()
        if progress.successor is None:
            await run(
                "capture_successor",
                "knowledge",
                self._capture_successor(action, plan, consolidation_id),
                progress.adopt_successor,
            )
        successor: RecordId = RecordId(value=progress.successor or "")
        for member in plan.members:
            if member.record_id.value in progress.assertions:
                continue
            await run(
                f"supersedes:{member.record_id.value}",
                "assertion",
                self._propose_supersedes(
                    action, plan, consolidation_id, successor, member, prelude.space_id
                ),
                progress.adopter(member.record_id.value),
            )
        await run(
            "materialise",
            "consolidation",
            self._materialise(prelude, entry, extra, progress, plan),
        )
        return await self._describe(
            action, prelude.space_id, consolidation_id, replayed=prelude.replay is not None
        )

    async def _capture_successor(
        self, action: ProposeConsolidationCommand, plan: _Plan, consolidation_id: ConsolidationId
    ) -> str:
        result = await self._capture.handle(
            CaptureKnowledgeCommand(
                idempotency_key=f"{consolidation_id.value}:n",
                space_key=action.space_key,
                title=plan.title,
                body=plan.body,
                subtype=Slug(value=plan.subtype),
                actor=action.actor,
                project=ProjectRef(key=Key(value=plan.project_key)) if plan.project_key else None,
                tags=tuple(Tag(value=tag) for tag in plan.tags),
                sources=plan.source_inputs(),
            )
        )
        return result.record_id

    async def _propose_supersedes(
        self,
        action: ProposeConsolidationCommand,
        plan: _Plan,
        consolidation_id: ConsolidationId,
        successor: RecordId,
        member: ConsolidationMember,
        space_id: SpaceId,
    ) -> str:
        async with self._support.uow_factory() as uow:
            record: Knowledge | None = await uow.knowledge.get(successor, space_id=space_id)
        if record is None:
            raise RecordNotFoundError(
                f"No successor {successor.value} in this space.", {"record_id": successor.value}
            )
        result = await self._propose.handle(
            ProposeAssertionCommand(
                idempotency_key=f"{consolidation_id.value}:s:{member.record_id.value}",
                space_key=action.space_key,
                actor=action.actor,
                predicate=AssertionPredicateEnum.SUPERSEDES,
                subject_id=successor,
                object_id=member.record_id,
                evidence_ids=tuple(
                    RecordId(value=item) for item in plan.evidence.get(member.record_id.value, ())
                ),
                rationale=plan.rationale,
                project=ProjectRef(key=Key(value=plan.project_key)) if plan.project_key else None,
                sources=tuple(
                    ExistingSourceInput(source_id=source_id) for source_id in record.head.source_ids
                ),
            )
        )
        return result.id

    async def _materialise(
        self,
        prelude: Prelude,
        entry: LedgerEntry,
        extra: dict[str, JsonValue],
        progress: _Progress,
        plan: _Plan,
    ) -> None:
        support: ConsolidationSupport = self._support
        consolidation_id: ConsolidationId = ConsolidationId(value=str(extra["consolidation_id"]))
        async with support.uow_factory() as uow:
            aggregate: Consolidation | None = await uow.consolidations.get_for_update(
                consolidation_id, space_id=prelude.space_id
            )
            if aggregate is None:
                raise ConsolidationNotFoundError(
                    f"No consolidation {consolidation_id.value} in this space.",
                    {"consolidation_id": consolidation_id.value},
                )
            expected: int = aggregate.version
            changed: bool = aggregate.materialise(
                successor_id=RecordId(value=progress.successor or ""),
                assertion_ids=tuple(
                    RecordId(value=progress.assertions[m.record_id.value]) for m in plan.members
                ),
                now=support.clock.now(),
            )
            if changed:
                await uow.consolidations.save(aggregate, expected_version=expected)
            await uow.ledger.update_extra(
                prelude.space_id,
                entry.key,
                expected_progress_version=progress.version,
                extra={
                    **extra,
                    "status": "complete",
                    "successor_id": progress.successor,
                    "assertion_ids": {**progress.assertions},
                },
            )
            await uow.commit()

    async def _describe(
        self,
        action: ProposeConsolidationCommand,
        space_id: SpaceId,
        consolidation_id: ConsolidationId,
        *,
        replayed: bool,
    ) -> ConsolidationProposalDto:
        stored: ConsolidationDto | None = await self._read.get(consolidation_id, space_id)
        if stored is None:
            raise ConsolidationNotFoundError(
                f"No consolidation {consolidation_id.value} in this space.",
                {"consolidation_id": consolidation_id.value},
            )
        progress, produced = await self._support.progress_of(stored, space_id)
        project_id: RecordId | None = None
        async with self._support.uow_factory() as uow:
            aggregate: Consolidation | None = await uow.consolidations.get_by_id(
                consolidation_id, space_id=space_id
            )
            project_id = aggregate.project_id if aggregate else None
        successor_status: str | None = next(
            (p.status for p in produced if p.record_id == stored.successor_id), None
        )
        return ConsolidationProposalDto(
            consolidation_id=stored.id,
            kind=stored.kind,
            state=stored.state,
            members=stored.members,
            successor_id=stored.successor_id,
            successor_status=successor_status,
            assertions=tuple(p for p in produced if p.record_type == "assertion"),
            requires=self._support.requires(project_id).value,
            decidable_by_caller=self._support.may_decide(action.actor, project_id),
            dry_run=False,
            progress=progress.value,
            replayed=replayed,
            next_steps=(
                f"noesis consolidation show {stored.id}",
                f"noesis consolidation accept {stored.id} --idempotency-key <key> --yes",
            ),
        )
