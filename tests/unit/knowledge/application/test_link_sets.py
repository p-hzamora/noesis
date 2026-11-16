"""Atomic link replacement, canonical content and version-aware ledger keys."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from tests.support.import_knowledge_support import make_fake_importer
from tests.support.knowledge_support import NOW, FakeKnowledgeUnitOfWork, make_env

from noesis.bounded_context.knowledge.application.handlers.commands.replace_link_set_handler import (
    ReplaceLinkSetHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.assess_link_set_handler import (
    AssessLinkSetHandler,
)
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.services.link_set_request import LinkSetRequest
from noesis.bounded_context.knowledge.domain.entities.link_set import LinkSet
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    Key,
    RecordId,
    SpaceId,
    Tag,
)
from noesis.bounded_context.knowledge.domain.value_objects.link_set_digest import LinkSetDigest
from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.exceptions import InvalidRecordError, SpaceNotFoundError

pytestmark = pytest.mark.unit


async def setup_links():
    env = await make_env()
    importer = make_fake_importer(env)
    source = await importer.apply(source_locator="vault://fixture/a.md", body="A")
    target = await importer.apply(source_locator="vault://fixture/b.md", body="B")
    stored: dict[str, LinkSet] = {}
    calls: list[str] = []

    class LinkUow(FakeKnowledgeUnitOfWork):
        def __init__(self):
            super().__init__(env.store)
            self.pending = None

        @property
        def link_sets(self):
            return self

        async def lock(self, source):
            calls.append("lock")

        async def get(self, source):
            calls.append("get")
            return stored.get(source.value)

        async def save(self, link_set):
            self.pending = link_set

        async def commit(self):
            await super().commit()
            if self.pending is not None:
                stored[self.pending.source_record_id.value] = self.pending

    request = LinkSetRequest(
        space_key=Key(value="default"),
        source_record_id=RecordId(value=source.record_id),
        origin_tag=Tag(value="origin:migrated"),
        actor=Actor(kind=ActorKindEnum.USER, name="tester"),
        links=(
            RecordLink(
                target_record_id=RecordId(value=target.record_id),
                link_type="links_to",
                count=1,
                anchors=("Z", "A", "Z", ""),
            ),
        ),
    )
    return env, LinkUow, request, stored, calls


async def test_create_assess_unchanged_replace_empty_and_a_b_a() -> None:
    env, factory, request, stored, calls = await setup_links()
    write = ReplaceLinkSetHandler(uow_factory=factory, clock=env.clock)
    read = AssessLinkSetHandler(uow_factory=factory, clock=env.clock)
    before = len(env.store.ledger)
    assert (await read.handle(request)).outcome == "created"
    assert calls == ["get"] and not stored and len(env.store.ledger) == before
    assert (await write.handle(request)).outcome == "created"
    assert calls[-2:] == ["lock", "get"]
    assert next(iter(stored.values())).origin == "migrated"
    assert (await write.handle(request)).outcome == "unchanged"
    assert len(env.store.ledger) == before + 1
    changed = request.model_copy(
        update={"links": (request.links[0].model_copy(update={"count": 2}),)}
    )
    assert (await read.handle(changed)).outcome == "replaced"
    assert (await write.handle(changed)).outcome == "replaced"
    assert (await write.handle(request)).outcome == "replaced"
    assert next(iter(stored.values())).version == 3
    assert len(env.store.ledger) == before + 3
    empty = request.model_copy(update={"links": ()})
    assert (await write.handle(empty)).outcome == "replaced"
    assert next(iter(stored.values())).links == frozenset()
    assert (await write.handle(empty)).outcome == "unchanged"


async def test_unchanged_never_accesses_ledger() -> None:
    env, factory, request, _, _ = await setup_links()
    await ReplaceLinkSetHandler(uow_factory=factory, clock=env.clock).handle(request)

    class NoLedger(factory):
        @property
        def ledger(self):
            raise AssertionError("unchanged must not access the ledger")

    assert (
        await ReplaceLinkSetHandler(uow_factory=NoLedger, clock=env.clock).handle(request)
    ).outcome == "unchanged"


async def test_empty_absent_and_missing_references_write_nothing() -> None:
    env, factory, request, stored, _ = await setup_links()
    handler = ReplaceLinkSetHandler(uow_factory=factory, clock=env.clock)
    assert (await handler.handle(request.model_copy(update={"links": ()}))).outcome == "unchanged"
    missing = RecordId(value="01JCKMNP000000000000009999")
    assert (
        await handler.handle(request.model_copy(update={"source_record_id": missing}))
    ).block_reason == "record_not_found"
    target = request.links[0].target_record_id.value
    env.store.knowledge[target].space_id = SpaceId(value="01JCKMNP000000000000009998")
    assert (await handler.handle(request)).block_reason == "target_not_in_space"
    assert not stored
    with pytest.raises(SpaceNotFoundError):
        await handler.handle(request.model_copy(update={"space_key": Key(value="unknown")}))


async def test_ledger_reuse_is_blocked_and_matching_entry_replays() -> None:
    env, factory, request, stored, _ = await setup_links()

    class Reused(factory):
        @property
        def ledger(self):
            ledger = AsyncMock()
            ledger.get.return_value = LedgerEntry(
                space_id=next(iter(env.store.spaces.values())).id,
                key="used",
                command="other",
                fingerprint="other",
                recorded_at=NOW,
            )
            return ledger

    assert (
        await ReplaceLinkSetHandler(uow_factory=Reused, clock=env.clock).handle(request)
    ).block_reason == "idempotency_key_reused"
    assert not stored
    write = ReplaceLinkSetHandler(uow_factory=factory, clock=env.clock)
    await write.handle(request)
    stored.clear()  # Simulate a previously recorded response under the same expected version.
    assert (await write.handle(request)).replayed


def test_aggregate_and_digest_invariants() -> None:
    source = RecordId(value="01JCKMNP000000000000000001")
    target = RecordId(value="01JCKMNP000000000000000002")
    link = RecordLink(
        target_record_id=target, link_type="links_to", count=1, anchors=("Z", "A", "Z")
    )
    embed = RecordLink(target_record_id=target, link_type="embeds", count=1)
    assert LinkSetDigest.of([link, embed], "migrated") == LinkSetDigest.of(
        [embed, link], "migrated"
    )
    assert LinkSetDigest.of([link], "other") != LinkSetDigest.of([link], "migrated")
    item = LinkSet.create(
        source_record_id=source,
        space_id=SpaceId(value="01JCKMNP000000000000009998"),
        origin="migrated",
        version=1,
        links=frozenset({link}),
        now=NOW,
    )
    assert link.anchors == ("A", "Z")
    with pytest.raises(InvalidRecordError):
        replace(item, source_record_id=target)
    with pytest.raises(InvalidRecordError):
        replace(item, version=0)
    with pytest.raises(InvalidRecordError):
        replace(item, links=frozenset({link, link.model_copy(update={"count": 2})}))
    with pytest.raises(InvalidRecordError):
        replace(item, digest=LinkSetDigest(value="wrong"))
    with pytest.raises(ValidationError):
        RecordLink(target_record_id=target, link_type="links_to", count=0)
