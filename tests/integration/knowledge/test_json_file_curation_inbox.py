"""The JSON file inbox on a temporary folder: atomic writes, write-once plan, lock, listing."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support.curation_support import AGENT, experience, knowledge
from tests.support.knowledge_support import MutableClock

from noesis.bounded_context.knowledge.application.dtos import RelatedLookupDto
from noesis.bounded_context.knowledge.application.ports.curation import (
    StepOutcome,
    StepOutcomeEnum,
)
from noesis.bounded_context.knowledge.domain.services import (
    CaptureKeyPolicy,
    CurationAdmissionPolicy,
    CurationProgressPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationFailureReasonEnum,
    CurationPlan,
    CurationStageEnum,
    CurationSubmission,
    SubmissionKindEnum,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.curation import (
    LOCK_WAIT_SECONDS,
    JsonFileCurationInboxAdapter,
)
from noesis.exceptions import CurationInboxFailedError

pytestmark = pytest.mark.integration

KEY = "0123456789abcdef" * 4


def submission(key: str = KEY) -> CurationSubmission:
    return CurationSubmission(
        kind=SubmissionKindEnum.APPLY,
        submission_key=key,
        project_key="acme",
        session_id="s-1",
        actor=AGENT,
        candidates=(experience(),),
    )


def plan_of(body: str = "x") -> CurationPlan:
    return CurationAdmissionPolicy().plan(
        [experience(body=body), knowledge()], project_key="acme", targets={}
    )


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(datetime(2026, 11, 14, 12, 0, tzinfo=UTC))


@pytest.fixture
def inbox(tmp_path: Path, clock: MutableClock) -> JsonFileCurationInboxAdapter:
    return JsonFileCurationInboxAdapter(tmp_path / "knowledge" / "curation", clock=clock)


async def test_a_staged_submission_is_a_ticket_derived_from_its_key_and_reused(
    inbox: JsonFileCurationInboxAdapter, tmp_path: Path
) -> None:
    first = await inbox.stage(submission())
    again = await inbox.stage(submission())

    assert first.ticket == CaptureKeyPolicy.ticket_of(KEY) == KEY[:16]
    assert again == first
    assert first.progress.stage is CurationStageEnum.STAGED and first.plan is None
    assert (tmp_path / "knowledge/curation" / f"{first.ticket}.json").is_file()
    assert await inbox.get(first.ticket) == first


async def test_an_unknown_or_unsafe_ticket_is_simply_not_found(
    inbox: JsonFileCurationInboxAdapter,
) -> None:
    assert await inbox.get("nope") is None
    assert await inbox.get("../../etc/passwd") is None
    await inbox.remove("../../etc/passwd")  # a no-op, never a deletion outside the inbox


async def test_the_plan_is_write_once_and_the_same_plan_is_a_no_op(
    inbox: JsonFileCurationInboxAdapter,
) -> None:
    ticket = (await inbox.stage(submission())).ticket
    plan = plan_of()

    await inbox.save_plan(
        ticket, plan, related_lookup=RelatedLookupDto(state="used", pending_changes=2)
    )
    await inbox.save_plan(ticket, plan)
    with pytest.raises(CurationInboxFailedError):
        await inbox.save_plan(ticket, plan_of("other"))

    kept = await inbox.get(ticket)
    assert kept is not None and kept.plan == plan
    assert kept.related_lookup == RelatedLookupDto(state="used", pending_changes=2)


async def test_advance_compares_before_it_moves(inbox: JsonFileCurationInboxAdapter) -> None:
    ticket = await inbox.stage(submission())
    planned = CurationProgressPolicy.advance(ticket.progress, CurationStageEnum.PLANNED)

    moved = await inbox.advance(ticket.ticket, ticket.progress, planned)
    with pytest.raises(CurationInboxFailedError, match="changed since"):
        await inbox.advance(ticket.ticket, ticket.progress, planned)

    assert moved.progress == planned
    stored = await inbox.get(ticket.ticket)
    assert stored is not None and stored.progress == planned


async def test_a_failed_ticket_is_listed_with_its_failure_time_oldest_first(
    inbox: JsonFileCurationInboxAdapter, clock: MutableClock
) -> None:
    older = await inbox.stage(submission("a" * 64))
    newer = await inbox.stage(submission("b" * 64))
    healthy = await inbox.stage(submission("c" * 64))
    for ticket in (newer, older):  # the newer ticket fails first
        failed = CurationProgressPolicy.fail(
            ticket.progress, CurationFailureReasonEnum.CURATOR_FAILED
        )
        await inbox.advance(ticket.ticket, ticket.progress, failed)
        clock.advance(10)

    parked = await inbox.list_parked()

    assert [t.ticket for t in parked] == [newer.ticket, older.ticket]
    assert healthy.ticket not in {t.ticket for t in parked}
    assert all(t.parked_at is not None for t in parked)


async def test_resuming_a_failed_ticket_clears_its_parked_time(
    inbox: JsonFileCurationInboxAdapter,
) -> None:
    ticket = await inbox.stage(submission())
    failed = CurationProgressPolicy.fail(ticket.progress, CurationFailureReasonEnum.STEP_FAILED)
    await inbox.advance(ticket.ticket, ticket.progress, failed)

    resumed = await inbox.advance(ticket.ticket, failed, CurationProgressPolicy.resume(failed))

    assert resumed.progress.stage is CurationStageEnum.STAGED and resumed.parked_at is None
    assert await inbox.list_parked() == ()


async def test_step_outcomes_replace_an_earlier_outcome_of_the_same_step(
    inbox: JsonFileCurationInboxAdapter,
) -> None:
    ticket = (await inbox.stage(submission())).ticket

    await inbox.record_step(
        ticket, StepOutcome(ordinal=1, step="revise", outcome=StepOutcomeEnum.WRITTEN)
    )
    await inbox.record_step(
        ticket,
        StepOutcome(
            ordinal=1, step="revise", outcome=StepOutcomeEnum.SKIPPED, reason="target_changed"
        ),
    )
    await inbox.record_step(
        ticket, StepOutcome(ordinal=2, step="knowledge", outcome=StepOutcomeEnum.WRITTEN)
    )

    stored = await inbox.get(ticket)
    assert stored is not None
    revise = stored.step(1, "revise")
    assert revise is not None and revise.outcome is StepOutcomeEnum.SKIPPED
    assert len(stored.steps) == 2


async def test_remove_deletes_the_ticket_and_its_plan(
    inbox: JsonFileCurationInboxAdapter, tmp_path: Path
) -> None:
    ticket = (await inbox.stage(submission())).ticket
    await inbox.save_plan(ticket, plan_of())

    await inbox.remove(ticket)
    await inbox.remove(ticket)  # a second removal is a no-op

    assert await inbox.get(ticket) is None
    assert not list((tmp_path / "knowledge/curation").glob(f"{ticket}*.json"))


async def test_a_rejected_payload_is_kept_outside_any_ticket(
    inbox: JsonFileCurationInboxAdapter,
) -> None:
    path = Path(await inbox.keep_rejected('{"candidates": 1}'))

    assert path.read_text() == '{"candidates": 1}' and path.parent.name == "rejected"
    assert await inbox.list_parked() == ()


async def test_a_failure_before_the_rename_leaves_the_previous_file_intact(
    inbox: JsonFileCurationInboxAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticket = await inbox.stage(submission())
    before = (tmp_path / "knowledge/curation" / f"{ticket.ticket}.json").read_text()
    planned = CurationProgressPolicy.advance(ticket.progress, CurationStageEnum.PLANNED)

    def broken(self: Path, target: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", broken)
    with pytest.raises(CurationInboxFailedError, match="disk full"):
        await inbox.advance(ticket.ticket, ticket.progress, planned)
    monkeypatch.undo()

    folder = tmp_path / "knowledge/curation"
    assert (folder / f"{ticket.ticket}.json").read_text() == before
    assert not list(folder.glob(".*.tmp"))
    stored = await inbox.get(ticket.ticket)
    assert stored is not None and stored.progress.stage is CurationStageEnum.STAGED


async def test_a_corrupt_ticket_file_is_an_inbox_failure(
    inbox: JsonFileCurationInboxAdapter, tmp_path: Path
) -> None:
    ticket = (await inbox.stage(submission())).ticket
    (tmp_path / "knowledge/curation" / f"{ticket}.json").write_text("{broken")

    with pytest.raises(CurationInboxFailedError):
        await inbox.get(ticket)


async def test_an_unwritable_folder_is_an_inbox_failure(
    tmp_path: Path, clock: MutableClock
) -> None:
    blocker = tmp_path / "state"
    blocker.write_text("a file where the folder should be")
    inbox = JsonFileCurationInboxAdapter(blocker / "knowledge" / "curation", clock=clock)

    with pytest.raises(CurationInboxFailedError):
        await inbox.stage(submission())


async def test_a_second_holder_waits_for_the_lock_then_gives_up_after_the_bound(
    tmp_path: Path, clock: MutableClock
) -> None:
    inbox = JsonFileCurationInboxAdapter(tmp_path / "inbox", clock=clock, lock_wait_seconds=0.3)
    entered: list[str] = []

    async with inbox.locked("abc123"):
        with pytest.raises(CurationInboxFailedError, match="busy") as raised:
            async with inbox.locked("abc123"):
                entered.append("second")  # pragma: no cover
        async with inbox.locked("def456"):  # another ticket is not blocked
            entered.append("other")

    async with inbox.locked("abc123"):  # released: free again
        entered.append("again")

    assert entered == ["other", "again"]
    assert raised.value.error_code == "KNOWLEDGE_142_CURATION_INBOX_FAILED"


async def test_a_waiting_holder_gets_the_lock_when_the_first_lets_go(
    tmp_path: Path, clock: MutableClock
) -> None:
    inbox = JsonFileCurationInboxAdapter(tmp_path / "inbox", clock=clock, lock_wait_seconds=5)
    order: list[str] = []

    async def first() -> None:
        async with inbox.locked("abc"):
            order.append("first in")
            await asyncio.sleep(0.2)
            order.append("first out")

    async def second() -> None:
        await asyncio.sleep(0.05)
        async with inbox.locked("abc"):
            order.append("second in")

    await asyncio.gather(first(), second())

    assert order == ["first in", "first out", "second in"]


def test_the_lock_bound_is_a_documented_ten_seconds() -> None:
    assert LOCK_WAIT_SECONDS == 10.0


async def test_the_ticket_file_never_holds_more_than_the_redacted_submission(
    inbox: JsonFileCurationInboxAdapter, tmp_path: Path
) -> None:
    ticket = (await inbox.stage(submission())).ticket

    payload = json.loads((tmp_path / "knowledge/curation" / f"{ticket}.json").read_text())

    assert set(payload) == {
        "ticket",
        "submission",
        "progress",
        "related_lookup",
        "steps",
        "created_at",
        "updated_at",
        "parked_at",
    }
