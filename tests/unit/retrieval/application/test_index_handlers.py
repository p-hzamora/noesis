"""Index sync, rebuild and status over the in-memory `probe` projection (FR-006, FR-013, FR-024)."""

from pathlib import Path

import pytest
from pydantic import SecretStr
from tests.support.retrieval.probe_projection import InMemoryProbeProjection
from tests.support.retrieval.retrieval_fakes import (
    SPACE,
    FakeRecordStateReader,
    RetrievalWorld,
    make_state,
)

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
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_writer import IIndexWriter
from noesis.core import load_environment
from noesis.exceptions import (
    IndexNotInitialisedError,
    IndexRebuildRequiredError,
    IndexSyncInProgressError,
    InvalidConfigurationError,
)
from noesis.interfaces.cli.bootstrap import retrieval_handlers_builder
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient, Neo4jConnectionSettings

pytestmark = pytest.mark.unit

OWNER: str = "sync-1"


class OtherProbe(InMemoryProbeProjection):
    """A second projection kind, to prove `--projection` and per-kind cursors."""

    @property
    def kind(self) -> str:
        return "other"


def seed_world() -> RetrievalWorld:
    """K created, E created, K revised to head 2, K accepted: four changes, head 4."""
    world = RetrievalWorld()
    world.add_knowledge("K", revision=2, status="accepted")
    world.add_experience("E")
    world.feed.add(SPACE, "K")
    world.feed.add(SPACE, "E", record_type="experience", revision=None, status=None)
    world.feed.add(SPACE, "K", change_kind="revised", revision=2)
    world.feed.add(SPACE, "K", change_kind="status_changed", revision=2, status="accepted")
    return world


def sync_handler(world: RetrievalWorld, *writers: IIndexWriter) -> SyncIndexHandler:
    return SyncIndexHandler(
        writers=tuple(writers),
        cursors=world.cursors,
        feed=world.feed,
        states=world.states,
        indexables=world.indexables,
    )


def rebuild_handler(world: RetrievalWorld, *writers: IIndexWriter) -> RebuildIndexHandler:
    return RebuildIndexHandler(
        writers=tuple(writers),
        cursors=world.cursors,
        feed=world.feed,
        states=world.states,
        indexables=world.indexables,
    )


def status_handler(world: RetrievalWorld, *writers: IIndexWriter) -> GetIndexStatusHandler:
    return GetIndexStatusHandler(
        writers=tuple(writers), cursors=world.cursors, feed=world.feed, states=world.states
    )


def sync_command(wait_seconds: int = 0) -> SyncIndexCommand:
    return SyncIndexCommand(space_id=SPACE, wait_seconds=wait_seconds, owner=OWNER)


async def test_sync_applies_every_change_and_indexes_each_record_at_its_head_revision() -> None:
    world = seed_world()
    probe = InMemoryProbeProjection()
    world.cursors.set("probe", SPACE, 0)

    result = await sync_handler(world, probe).handle(sync_command())

    assert result.head_sequence == 4
    (projection,) = result.projections
    assert (projection.kind, projection.applied, projection.skipped, projection.cursor) == (
        "probe",
        4,
        0,
        4,
    )
    assert await probe.entries(SPACE) == {"K": 2, "E": None}
    assert probe.status_of(SPACE, "K") == "accepted"
    assert len(probe.upserts) == 2  # applied once per distinct record id in the batch
    assert await world.cursors.get("probe", SPACE) == 4
    assert sorted(world.indexables.gets, key=str) == [("E", None), ("K", 2)]


async def test_sync_skips_other_record_types_and_ids_not_found_in_the_space() -> None:
    world = RetrievalWorld()
    world.add_knowledge("K")
    world.states.add(SPACE, make_state("A1", record_type="assertion", subtype=None))
    world.feed.add(SPACE, "K")
    world.feed.add(SPACE, "A1", record_type="assertion", revision=None)
    world.feed.add(SPACE, "GHOST")
    probe = InMemoryProbeProjection()
    world.cursors.set("probe", SPACE, 0)

    result = await sync_handler(world, probe).handle(sync_command())

    (projection,) = result.projections
    assert (projection.applied, projection.skipped, projection.cursor) == (1, 2, 3)
    assert await probe.entries(SPACE) == {"K": 1}


async def test_sync_pulls_in_batches_until_the_head() -> None:
    world = RetrievalWorld()
    world.add_knowledge("K")
    for _ in range(250):
        world.feed.add(SPACE, "K")
    probe = InMemoryProbeProjection()
    world.cursors.set("probe", SPACE, 0)

    result = await sync_handler(world, probe).handle(sync_command())

    assert result.projections[0].applied == 250
    assert result.projections[0].cursor == 250
    assert await world.cursors.get("probe", SPACE) == 250


async def test_sync_is_idempotent_when_rerun() -> None:
    world = seed_world()
    probe = InMemoryProbeProjection()
    world.cursors.set("probe", SPACE, 0)
    await sync_handler(world, probe).handle(sync_command())
    before = await probe.entries(SPACE)

    again = await sync_handler(world, probe).handle(sync_command())

    assert again.projections[0].applied == 0
    assert await probe.entries(SPACE) == before


async def test_sync_takes_the_lock_and_releases_it_afterwards() -> None:
    world = seed_world()
    world.cursors.set("probe", SPACE, 0)

    await sync_handler(world, InMemoryProbeProjection()).handle(sync_command())

    assert world.cursors.acquire_calls == [("probe", SPACE, OWNER)]
    assert world.cursors.release_calls == [("probe", SPACE, OWNER)]
    assert world.cursors.lock_holder("probe", SPACE) is None


async def test_sync_without_a_cursor_needs_a_rebuild_first() -> None:
    world = seed_world()

    with pytest.raises(IndexNotInitialisedError):
        await sync_handler(world, InMemoryProbeProjection()).handle(sync_command())

    assert world.cursors.lock_holder("probe", SPACE) is None


async def test_sync_when_another_owner_holds_the_lock_fails_without_writing() -> None:
    world = seed_world()
    probe = InMemoryProbeProjection()
    world.cursors.set("probe", SPACE, 0)
    world.cursors.hold("probe", SPACE, "someone-else")

    with pytest.raises(IndexSyncInProgressError):
        await sync_handler(world, probe).handle(sync_command(wait_seconds=0))

    assert probe.upserts == []
    assert world.cursors.advance_calls == []
    assert world.cursors.lock_holder("probe", SPACE) == "someone-else"


async def test_sync_after_the_lock_expired_succeeds() -> None:
    world = seed_world()
    world.cursors.set("probe", SPACE, 0)
    world.cursors.hold("probe", SPACE, "crashed", ttl_seconds=1)
    world.clock.advance(2)

    result = await sync_handler(world, InMemoryProbeProjection()).handle(sync_command())

    assert result.projections[0].cursor == 4


async def test_sync_over_a_gap_in_the_feed_requires_a_rebuild() -> None:
    world = seed_world()
    world.feed.drop(SPACE, 2)
    probe = InMemoryProbeProjection()
    world.cursors.set("probe", SPACE, 0)

    with pytest.raises(IndexRebuildRequiredError):
        await sync_handler(world, probe).handle(sync_command())

    assert await world.cursors.get("probe", SPACE) == 0
    assert world.cursors.lock_holder("probe", SPACE) is None  # released on failure too


async def test_sync_with_a_cursor_ahead_of_the_head_requires_a_rebuild() -> None:
    world = seed_world()
    world.cursors.set("probe", SPACE, 9)

    with pytest.raises(IndexRebuildRequiredError):
        await sync_handler(world, InMemoryProbeProjection()).handle(sync_command())


async def test_ac031_sync_with_no_projection_reports_the_head_and_does_nothing() -> None:
    world = seed_world()

    result = await sync_handler(world).handle(sync_command())

    assert result.projections == ()
    assert result.head_sequence == 4
    assert any("no index projection registered; nothing to sync" in w for w in result.warnings)
    assert world.cursors.acquire_calls == []
    assert world.cursors.advance_calls == []


async def test_ac031_rebuild_with_no_projection_reports_the_head_and_does_nothing() -> None:
    world = seed_world()

    result = await rebuild_handler(world).handle(
        RebuildIndexCommand(space_id=SPACE, projection=None, owner=OWNER)
    )

    assert result.projections == ()
    assert result.head_sequence == 4
    assert any("no index projection registered; nothing to rebuild" in w for w in result.warnings)
    assert world.cursors.acquire_calls == []
    assert world.cursors.advance_calls == []


async def test_ac031_status_with_no_projection_reports_the_head_and_a_warning() -> None:
    world = seed_world()

    result = await status_handler(world).handle(GetIndexStatusQuery(space_id=SPACE, verify=True))

    assert result.projections == ()
    assert result.head_sequence == 4
    assert any("no index projection registered" in w for w in result.warnings)
    assert world.cursors.acquire_calls == []


async def test_rebuild_clears_scans_heads_and_sets_the_cursor_to_the_captured_head() -> None:
    world = seed_world()
    world.states.add(SPACE, make_state("P1", record_type="project", subtype=None, status=None))
    probe = InMemoryProbeProjection()
    probe.plant(SPACE, "STALE", 3)

    result = await rebuild_handler(world, probe).handle(
        RebuildIndexCommand(space_id=SPACE, projection=None, owner=OWNER)
    )

    (projection,) = result.projections
    assert projection.kind == "probe"
    assert projection.records_indexed == 2
    assert projection.duration_seconds >= 0
    assert probe.clears == [SPACE]
    assert await probe.entries(SPACE) == {"K": 2, "E": None}
    assert await world.cursors.get("probe", SPACE) == 4
    assert ("probe", SPACE, 4) in world.cursors.advance_calls
    assert world.cursors.lock_holder("probe", SPACE) is None


async def test_ac010_a_change_made_during_the_scan_is_picked_up_by_the_closing_sync() -> None:
    world = seed_world()
    probe = InMemoryProbeProjection()

    class CapturingDuringScan(FakeRecordStateReader):
        """The first scan page triggers a capture of N after the head was read."""

        def __init__(self, inner: FakeRecordStateReader) -> None:
            super().__init__()
            self.inner = inner
            self.fired = False

        async def get_states(self, record_ids, *, space_id):  # type: ignore[no-untyped-def]
            return await self.inner.get_states(record_ids, space_id=space_id)

        async def scan_states(self, space_id, *, after_id, limit):  # type: ignore[no-untyped-def]
            page = await self.inner.scan_states(space_id, after_id=after_id, limit=limit)
            if not self.fired:
                self.fired = True
                world.add_knowledge("N")
                world.feed.add(space_id, "N")
            return page

    states = CapturingDuringScan(world.states)
    handler = RebuildIndexHandler(
        writers=(probe,),
        cursors=world.cursors,
        feed=world.feed,
        states=states,
        indexables=world.indexables,
    )

    await handler.handle(RebuildIndexCommand(space_id=SPACE, projection=None, owner=OWNER))

    assert await probe.entries(SPACE) == {"E": None, "K": 2, "N": 1}
    assert await world.cursors.get("probe", SPACE) == 5
    assert ("probe", SPACE, 4) in world.cursors.advance_calls  # the captured head, set first


async def test_rebuild_of_one_projection_leaves_the_others_alone() -> None:
    world = seed_world()
    probe, other = InMemoryProbeProjection(), OtherProbe()

    result = await rebuild_handler(world, probe, other).handle(
        RebuildIndexCommand(space_id=SPACE, projection="other", owner=OWNER)
    )

    assert [p.kind for p in result.projections] == ["other"]
    assert other.clears == [SPACE]
    assert probe.clears == [] and probe.upserts == []
    assert await world.cursors.get("probe", SPACE) is None


async def test_rebuild_when_another_owner_holds_the_lock_fails_before_clearing() -> None:
    world = seed_world()
    probe = InMemoryProbeProjection()
    world.cursors.hold("probe", SPACE, "someone-else")

    with pytest.raises(IndexSyncInProgressError):
        await rebuild_handler(world, probe).handle(
            RebuildIndexCommand(space_id=SPACE, projection=None, owner=OWNER)
        )

    assert probe.clears == []


async def synced(world: RetrievalWorld, probe: InMemoryProbeProjection) -> None:
    world.cursors.set("probe", SPACE, 0)
    await sync_handler(world, probe).handle(sync_command())


async def test_status_reports_cursor_lag_and_profile() -> None:
    world = seed_world()
    world.cursors.set("probe", SPACE, 1)

    result = await status_handler(world, InMemoryProbeProjection()).handle(
        GetIndexStatusQuery(space_id=SPACE, verify=False)
    )

    (projection,) = result.projections
    assert result.head_sequence == 4
    assert (projection.kind, projection.cursor, projection.lag) == ("probe", 1, 3)
    assert projection.profile == {"name": "probe", "version": 1}
    assert projection.divergences == ()


async def test_status_without_a_cursor_needs_a_rebuild_first() -> None:
    world = seed_world()

    with pytest.raises(IndexNotInitialisedError):
        await status_handler(world, InMemoryProbeProjection()).handle(
            GetIndexStatusQuery(space_id=SPACE, verify=False)
        )


async def test_status_verify_of_a_consistent_projection_finds_nothing() -> None:
    world = seed_world()
    world.states.add(SPACE, make_state("P1", record_type="project", subtype=None, status=None))
    probe = InMemoryProbeProjection()
    await synced(world, probe)

    result = await status_handler(world, probe).handle(
        GetIndexStatusQuery(space_id=SPACE, verify=True)
    )

    assert result.projections[0].lag == 0
    assert result.projections[0].divergences == ()


async def test_status_verify_reports_missing_wrong_revision_and_extra_entries() -> None:
    world = seed_world()
    world.add_knowledge("M", revision=3)
    world.add_knowledge("W", revision=2)
    probe = InMemoryProbeProjection()
    await synced(world, probe)
    probe.drop(SPACE, "K")  # missing
    probe.plant(SPACE, "M", 1)  # at an old revision
    probe.plant(SPACE, "EXTRA", 1)  # not a record of the space

    result = await status_handler(world, probe).handle(
        GetIndexStatusQuery(space_id=SPACE, verify=True)
    )

    found = {
        d.record_id: (d.expected_revision, d.found_revision)
        for d in result.projections[0].divergences
    }
    assert found == {
        "K": (2, None),
        "M": (3, 1),
        "W": (2, None),
        "EXTRA": (None, 1),
    }


def test_duplicate_projection_kind_is_a_typed_configuration_error_at_start_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registered = retrieval_handlers_builder.RegisteredProjections(
        writers=(InMemoryProbeProjection(), InMemoryProbeProjection()), candidate_sources=()
    )
    monkeypatch.setattr(
        retrieval_handlers_builder, "registered_projections", lambda client, environment: registered
    )
    client = Neo4jClient(
        Neo4jConnectionSettings(
            uri="bolt://127.0.0.1:1", user="neo4j", password=SecretStr("not-used")
        )
    )

    with pytest.raises(InvalidConfigurationError):
        retrieval_handlers_builder.build_retrieval(
            client,
            load_environment(tmp_path / "missing.env"),  # type: ignore[operator]
        )


async def test_unknown_feed_kinds_cross_batches_without_body_reads_and_restart_is_noop() -> None:
    world = RetrievalWorld()
    world.add_knowledge("K")
    world.feed.add(SPACE, "K")
    for _ in range(101):
        world.feed.add(SPACE, "unread", change_kind="future_kind")
    world.feed.add(SPACE, "K", change_kind="revised")
    world.feed.add(SPACE, "unread", change_kind="trailing_future")
    world.cursors.set("probe", SPACE, 0)
    probe = InMemoryProbeProjection()
    handler = sync_handler(world, probe)
    result = await handler.handle(sync_command())
    (projection,) = result.projections
    assert (
        projection.cursor,
        projection.applied,
        projection.skipped,
        projection.unknown_changes,
    ) == (104, 2, 102, 102)
    assert all(record_id == "K" for record_id, _ in world.indexables.gets)
    before = len(probe.upserts)
    assert (await handler.handle(sync_command())).projections[0].applied == 0
    assert len(probe.upserts) == before


async def test_unknown_feed_kinds_do_not_hide_a_genuine_gap() -> None:
    world = RetrievalWorld()
    for _ in range(3):
        world.feed.add(SPACE, "unread", change_kind="future")
    world.feed.drop(SPACE, 2)
    world.cursors.set("probe", SPACE, 0)
    with pytest.raises(IndexRebuildRequiredError):
        await sync_handler(world, InMemoryProbeProjection()).handle(sync_command())
    assert await world.cursors.get("probe", SPACE) == 0
