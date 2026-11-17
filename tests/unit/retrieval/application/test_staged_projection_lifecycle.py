"""C5b lifecycle of a staged projection: fenced writes, head churn, leases, rebuild manifest.

AC-204 (head change during embedding), AC-205 (cursor never passes a failed batch), AC-206
(lease renewal and expired-owner takeover), AC-207 (rebuild marker), AC-208 (built profile).
"""

import asyncio
import logging

import pytest
from tests.support.retrieval.retrieval_fakes import SPACE, RetrievalWorld
from tests.support.retrieval.staged_projection import STAGED_KIND, InMemoryStagedProjection

from noesis.bounded_context.retrieval.application.handlers.commands.rebuild_index_handler import (
    RebuildIndexCommand,
    RebuildIndexHandler,
)
from noesis.bounded_context.retrieval.application.handlers.commands.sync_index_handler import (
    SyncIndexCommand,
    SyncIndexHandler,
)
from noesis.bounded_context.retrieval.application.handlers.queries.get_index_status_handler import (
    GetIndexStatusHandler,
    GetIndexStatusQuery,
)
from noesis.bounded_context.retrieval.application.ports.embedding import ISemanticRuntimeProbe
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import (
    ProjectionEntryDto,
)
from noesis.bounded_context.retrieval.application.services.projection_lock import (
    LeaseHeartbeat,
    projection_lock,
)
from noesis.bounded_context.retrieval.application.services.projection_synchroniser import (
    ProjectionSynchroniser,
)
from noesis.bounded_context.retrieval.domain.enums import BuildStateEnum
from noesis.exceptions import (
    GraphStoreUnavailableError,
    IndexRebuildRequiredError,
    IndexSyncInProgressError,
)
from noesis.shared_kernel.domain import JsonValue

pytestmark = pytest.mark.unit

OWNER: str = "worker-a"


def world_with_three() -> RetrievalWorld:
    world = RetrievalWorld()
    for record_id in ("A", "B", "C"):
        world.add_knowledge(record_id)
        world.feed.add(SPACE, record_id)
    return world


def sync_handler(world: RetrievalWorld, writer: InMemoryStagedProjection) -> SyncIndexHandler:
    return SyncIndexHandler(
        writers=(writer,),
        cursors=world.cursors,
        feed=world.feed,
        states=world.states,
        indexables=world.indexables,
    )


def rebuild_handler(world: RetrievalWorld, writer: InMemoryStagedProjection) -> RebuildIndexHandler:
    return RebuildIndexHandler(
        writers=(writer,),
        cursors=world.cursors,
        feed=world.feed,
        states=world.states,
        indexables=world.indexables,
    )


async def test_rebuild_publishes_a_complete_manifest_with_the_built_profile() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors, profile={"model": "m1"})

    result = await rebuild_handler(world, writer).handle(
        RebuildIndexCommand(space_id=SPACE, owner=OWNER)
    )

    assert result.projections[0].records_indexed == 3
    manifest = await world.cursors.manifest(STAGED_KIND, SPACE)
    assert manifest is not None
    assert manifest.state is BuildStateEnum.COMPLETE
    assert manifest.profile == {"model": "m1"}
    assert await writer.entries(SPACE) == {"A": 1, "B": 1, "C": 1}
    assert world.cursors.lock_holder(STAGED_KIND, SPACE) is None


async def test_a_crashed_rebuild_leaves_the_space_rebuilding_and_sync_refuses_it() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors)
    writer.fail_on = "B"

    with pytest.raises(RuntimeError):
        await rebuild_handler(world, writer).handle(
            RebuildIndexCommand(space_id=SPACE, owner=OWNER)
        )

    manifest = await world.cursors.manifest(STAGED_KIND, SPACE)
    assert manifest is not None
    assert manifest.state is BuildStateEnum.REBUILDING
    assert manifest.profile is None
    with pytest.raises(IndexRebuildRequiredError, match="did not finish"):
        await sync_handler(world, writer).handle(SyncIndexCommand(space_id=SPACE, owner=OWNER))

    writer.fail_on = None
    await rebuild_handler(world, writer).handle(RebuildIndexCommand(space_id=SPACE, owner=OWNER))

    manifest = await world.cursors.manifest(STAGED_KIND, SPACE)
    assert manifest is not None
    assert manifest.state is BuildStateEnum.COMPLETE


async def test_a_rebuild_of_one_space_leaves_another_space_complete() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors)
    world.cursors.set_manifest(STAGED_KIND, "OTHER", BuildStateEnum.COMPLETE, {"name": "x"})
    writer.fail_on = "A"

    with pytest.raises(RuntimeError):
        await rebuild_handler(world, writer).handle(
            RebuildIndexCommand(space_id=SPACE, owner=OWNER)
        )

    other = await world.cursors.manifest(STAGED_KIND, "OTHER")
    assert other is not None
    assert other.state is BuildStateEnum.COMPLETE


async def test_a_head_that_moves_once_during_embedding_is_retried_with_the_new_head() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors)
    world.cursors.set(STAGED_KIND, SPACE, 0)
    moved: list[str] = []

    def revise_once(entry: ProjectionEntryDto) -> None:
        if entry.key.record_id == "B" and not moved:
            moved.append("B")
            world.add_knowledge("B", revision=2)

    writer.on_prepare = revise_once

    await sync_handler(world, writer).handle(SyncIndexCommand(space_id=SPACE, owner=OWNER))

    assert await writer.entries(SPACE) == {"A": 1, "B": 2, "C": 1}
    assert [e.key.revision for e in writer.prepared if e.key.record_id == "B"] == [1, 2]
    assert await world.cursors.get(STAGED_KIND, SPACE) == 3


async def test_a_head_that_keeps_moving_aborts_the_batch_without_moving_the_cursor() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors)
    world.cursors.set(STAGED_KIND, SPACE, 0)
    revision: list[int] = [1]

    def always_revise(entry: ProjectionEntryDto) -> None:
        if entry.key.record_id == "B":
            revision[0] += 1
            world.add_knowledge("B", revision=revision[0])

    writer.on_prepare = always_revise

    with pytest.raises(IndexSyncInProgressError, match="kept changing"):
        await sync_handler(world, writer).handle(SyncIndexCommand(space_id=SPACE, owner=OWNER))

    assert await world.cursors.get(STAGED_KIND, SPACE) == 0
    assert all(entry.key.revision == 1 for entry in writer.committed)  # never a relabelled vector


async def test_a_record_deleted_during_embedding_is_skipped() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors)
    world.cursors.set(STAGED_KIND, SPACE, 0)

    def forget(entry: ProjectionEntryDto) -> None:
        if entry.key.record_id == "C":
            world.states._states.pop((SPACE, "C"))  # test-only removal

    writer.on_prepare = forget

    result = await sync_handler(world, writer).handle(SyncIndexCommand(space_id=SPACE, owner=OWNER))

    assert result.projections[0].applied == 2
    assert "C" not in await writer.entries(SPACE)


async def test_a_lost_lease_rejects_the_write_and_the_cursor_stays() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors)
    world.cursors.set(STAGED_KIND, SPACE, 0)

    def steal(entry: ProjectionEntryDto) -> None:
        world.clock.advance(301)  # our lease expired during embedding
        world.cursors.hold(STAGED_KIND, SPACE, "worker-b")

    writer.on_prepare = steal

    with pytest.raises(IndexSyncInProgressError, match="lease was lost"):
        await sync_handler(world, writer).handle(SyncIndexCommand(space_id=SPACE, owner=OWNER))

    assert writer.committed == []
    assert await world.cursors.get(STAGED_KIND, SPACE) == 0


async def test_an_expired_owner_cannot_advance_after_takeover_and_release() -> None:
    world = RetrievalWorld()
    cursors = world.cursors
    assert await cursors.acquire(STAGED_KIND, SPACE, "worker-a", 300)
    world.clock.advance(301)
    assert await cursors.acquire(STAGED_KIND, SPACE, "worker-b", 300)
    await cursors.release(STAGED_KIND, SPACE, "worker-b")

    with pytest.raises(IndexSyncInProgressError):
        await cursors.advance(STAGED_KIND, SPACE, 7, owner="worker-a")
    assert not await cursors.renew(STAGED_KIND, SPACE, "worker-a", 300)


async def test_the_heartbeat_renews_and_reports_a_lost_lease() -> None:
    world = RetrievalWorld()
    assert await world.cursors.acquire(STAGED_KIND, SPACE, OWNER, 300)
    heartbeat = LeaseHeartbeat(
        world.cursors, projection=STAGED_KIND, space_id=SPACE, owner=OWNER, ttl_seconds=300
    )

    assert heartbeat.interval == 30
    assert await heartbeat.beat()
    world.cursors.fail_renewals = True
    assert not await heartbeat.beat()
    assert heartbeat.lost


async def test_a_store_failure_during_renewal_counts_as_a_lost_lease(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = RetrievalWorld()

    async def broken(*_: object) -> bool:
        raise GraphStoreUnavailableError("store down", {})

    world.cursors.renew = broken  # type: ignore[method-assign]
    heartbeat = LeaseHeartbeat(
        world.cursors, projection=STAGED_KIND, space_id=SPACE, owner=OWNER, ttl_seconds=3
    )

    with caplog.at_level(logging.WARNING):
        assert not await heartbeat.beat()
    assert heartbeat.lost
    assert "GraphStoreUnavailableError" in caplog.text
    assert "store down" not in caplog.text  # the error type only, never its message


async def test_an_unexpected_renewal_error_marks_the_lease_lost_and_propagates() -> None:
    world = RetrievalWorld()

    async def buggy(*_: object) -> bool:
        raise TypeError("a bug, not an outage")

    world.cursors.renew = buggy  # type: ignore[method-assign]
    heartbeat = LeaseHeartbeat(
        world.cursors, projection=STAGED_KIND, space_id=SPACE, owner=OWNER, ttl_seconds=3
    )

    with pytest.raises(TypeError, match="a bug"):
        await heartbeat.beat()
    assert heartbeat.lost


async def test_the_lock_surfaces_an_unexpected_renewal_error_after_releasing() -> None:
    world = RetrievalWorld()

    async def buggy(*_: object) -> bool:
        raise TypeError("a bug, not an outage")

    world.cursors.renew = buggy  # type: ignore[method-assign]

    with pytest.raises(TypeError, match="a bug"):
        async with projection_lock(
            world.cursors,
            projection=STAGED_KIND,
            space_id=SPACE,
            owner=OWNER,
            wait_seconds=0,
            ttl_seconds=1,
        ) as heartbeat:
            await asyncio.sleep(heartbeat.interval * 1.5)

    assert world.cursors.lock_holder(STAGED_KIND, SPACE) is None


async def test_the_lock_renews_in_the_background_without_blocking_the_block() -> None:
    world = RetrievalWorld()

    async with projection_lock(
        world.cursors,
        projection=STAGED_KIND,
        space_id=SPACE,
        owner=OWNER,
        wait_seconds=0,
        ttl_seconds=1,
    ) as heartbeat:
        await asyncio.sleep(heartbeat.interval * 2.5)

    assert len(world.cursors.renew_calls) >= 2
    assert world.cursors.lock_holder(STAGED_KIND, SPACE) is None


async def test_the_heartbeat_stops_after_a_lost_lease() -> None:
    world = RetrievalWorld()
    assert await world.cursors.acquire(STAGED_KIND, SPACE, OWNER, 1)
    world.cursors.fail_renewals = True
    heartbeat = LeaseHeartbeat(
        world.cursors, projection=STAGED_KIND, space_id=SPACE, owner=OWNER, ttl_seconds=1
    )

    await asyncio.wait_for(heartbeat.run(), timeout=2)

    assert heartbeat.lost


async def test_an_unfenced_index_state_upserts_directly() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors)
    synchroniser = ProjectionSynchroniser(
        cursors=world.cursors, feed=world.feed, states=world.states, indexables=world.indexables
    )
    state = (await world.states.get_states(["A"], space_id=SPACE))[0]

    assert await synchroniser.index_state(writer, state, space_id=SPACE)
    assert await writer.entries(SPACE) == {"A": 1}
    assert writer.prepared == []


class FakeProbe(ISemanticRuntimeProbe):
    async def diagnostics(self) -> dict[str, JsonValue]:
        return {"state": "configured", "mode": "resident"}


async def test_status_reports_the_built_profile_build_state_and_semantic_diagnostics() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors, profile={"model": "m1"})
    await rebuild_handler(world, writer).handle(RebuildIndexCommand(space_id=SPACE, owner=OWNER))
    writer.set_profile({"model": "m2"})
    handler = GetIndexStatusHandler(
        writers=(writer,),
        cursors=world.cursors,
        feed=world.feed,
        states=world.states,
        semantic_probe=FakeProbe(),
    )

    status = await handler.handle(GetIndexStatusQuery(space_id=SPACE))

    projection = status.projections[0]
    assert projection.profile == {"model": "m1"}
    assert projection.configured_profile == {"model": "m2"}
    assert projection.profile_matches is False
    assert projection.build_state == "complete"
    assert status.semantic == {"state": "configured", "mode": "resident"}


async def test_status_of_an_initial_rebuild_in_progress_reports_rebuilding() -> None:
    world = world_with_three()
    writer = InMemoryStagedProjection(world.cursors)
    world.cursors.set_manifest(STAGED_KIND, SPACE, BuildStateEnum.REBUILDING)
    handler = GetIndexStatusHandler(
        writers=(writer,), cursors=world.cursors, feed=world.feed, states=world.states
    )

    status = await handler.handle(GetIndexStatusQuery(space_id=SPACE))

    assert status.projections[0].build_state == "rebuilding"
    assert status.projections[0].cursor == 0
    assert status.semantic is None


async def test_status_without_writers_still_reports_semantic_diagnostics() -> None:
    world = world_with_three()
    handler = GetIndexStatusHandler(
        writers=(),
        cursors=world.cursors,
        feed=world.feed,
        states=world.states,
        semantic_probe=FakeProbe(),
    )

    status = await handler.handle(GetIndexStatusQuery(space_id=SPACE))

    assert status.semantic == {"state": "configured", "mode": "resident"}
